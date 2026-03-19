"""
modules/retriever.py — 語義搜尋 / 混合搜尋 / Re-ranking 模組
封裝 Supabase RPC 呼叫，提供多種搜尋模式。
"""
from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Optional

from tenacity import retry, stop_after_attempt, wait_exponential

from google import genai
from google.genai import types
from google.cloud import discoveryengine_v1 as discoveryengine
from supabase import Client

from config import EMBEDDING_MODEL, EMBEDDING_DIMENSION, GCP_PROJECT, RagConfig

logger = logging.getLogger(__name__)
try:
    from langsmith import traceable
except ImportError:
    def traceable(*args, **kwargs):
        """langsmith 未安裝時的 no-op decorator。"""
        def decorator(fn):
            return fn
        return decorator if not args or not callable(args[0]) else args[0]


class SemanticRetriever:
    """
    多模式搜尋器：
    - search()        → 純向量搜尋
    - hybrid_search() → 向量 + 全文混合搜尋 (RRF)
    - rerank()        → 用 Vertex AI Ranking API 對結果精排
    """

    _EXPAND_MODEL = "gemini-2.5-flash-lite"  # 極快、極便宜，用於查詢展開
    _RERANK_MODEL = "gemini-2.5-flash"       # Ranking API fallback 用

    def __init__(
        self,
        supabase_client: Client,
        api_key: Optional[str] = None,
        rag_config: Optional[RagConfig] = None,
    ) -> None:
        from config import get_genai_client
        self._client = supabase_client
        self._genai = get_genai_client(api_key)
        self._model = EMBEDDING_MODEL
        self._rag_config = rag_config or RagConfig(supabase_client)

    @traceable(name="embed_query")
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5), reraise=True)
    def _embed_query(self, query: str) -> list[float]:
        """將查詢文字轉為向量（帶重試，防止並行 Rate Limit）。"""
        result = self._genai.models.embed_content(
            model=self._model,
            contents=[query],
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_QUERY",
                output_dimensionality=EMBEDDING_DIMENSION,
            ),
        )
        return result.embeddings[0].values

    # ── 純向量搜尋 ─────────────────────────────────────
    @traceable(name="vector_search")
    def search(
        self,
        query: str,
        top_k: int = 5,
        threshold: float = 0.5,
        language: Optional[str] = None,
        fiscal_year: Optional[str] = None,
        group: Optional[str] = None,
        company: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """純向量語義搜尋（使用 match_chunks RPC）。"""
        query_embedding = self._embed_query(query)
        # 確保 embedding 是純 list[float]（防止 numpy/proto 型別問題）
        query_embedding = [float(v) for v in query_embedding]
        params = {
            "query_embedding": query_embedding,
            "match_count": top_k,
            "match_threshold": threshold,
        }
        if language:
            params["filter_language"] = language
        if fiscal_year:
            params["filter_fiscal_year"] = fiscal_year
        if group:
            params["filter_group"] = group
        if company:
            params["filter_company"] = company
        try:
            result = self._client.rpc("match_chunks", params).execute()
        except Exception as e:
            logger.error(f"[Retriever] match_chunks RPC 失敗：{type(e).__name__}: {e}")
            raise
        return self._apply_time_weight(result.data or [])

    # ── 混合搜尋 ───────────────────────────────────────
    @traceable(name="hybrid_search")
    def hybrid_search(
        self,
        query: str,
        top_k: int = 5,
        threshold: Optional[float] = None,
        language: Optional[str] = None,
        fiscal_year: Optional[str] = None,
        group: Optional[str] = None,
        company: Optional[str] = None,
        expand_query: bool = True,
    ) -> list[dict[str, Any]]:
        """向量 + 全文混合搜尋（使用 match_chunks_hybrid RPC）。"""
        # 動態讀取 threshold（None 時從 rag_config 取）
        if threshold is None:
            threshold = self._rag_config.get("hybrid_threshold", float)
        # 建立查詢清單（原始 + 展開）
        queries = [query]
        if expand_query:
            expanded = self._expand_query(query)
            queries.extend(expanded)

        all_results = []
        seen_ids = set()

        def _fetch_single(q: str) -> list[dict]:
            """單一查詢的檢索遏輯（用於平行執行）。"""
            q_embedding = self._embed_query(q)
            q_embedding = [float(v) for v in q_embedding]
            params = {
                "query_embedding": q_embedding,
                "query_text": q,
                "match_count": top_k,
                "match_threshold": threshold,
            }
            if language:
                params["filter_language"] = language
            if fiscal_year:
                params["filter_fiscal_year"] = fiscal_year
            if group:
                params["filter_group"] = group
            if company:
                params["filter_company"] = company
            try:
                return self._client.rpc("match_chunks_hybrid", params).execute().data or []
            except Exception as e:
                logger.error(f"[Retriever] match_chunks_hybrid RPC 失敗：{type(e).__name__}: {e}")
                raise

        try:
            # 平行發射多個檢索請求
            with ThreadPoolExecutor(max_workers=len(queries)) as executor:
                future_to_q = {executor.submit(_fetch_single, q): q for q in queries}
                for future in as_completed(future_to_q):
                    try:
                        for r in future.result():
                            rid = r.get("id")
                            if rid and rid not in seen_ids:
                                seen_ids.add(rid)
                                all_results.append(r)
                    except Exception as e:
                        # RPC 不存在的錯誤必須往外拋，觸發降級機制
                        if "match_chunks_hybrid" in str(e):
                            raise
                        # 其他錯誤（API 超時、Rate Limit）做隔離
                        failed_q = future_to_q[future]
                        logger.warning(f"[RETRIEVER] 子查詢 '{failed_q}' 檢索失敗，略過：{e}")
        except Exception as e:
            if "match_chunks_hybrid" in str(e):
                logger.info("[RETRIEVER] hybrid RPC 尚未建立，退回純向量搜尋")
                return self.search(query, top_k=top_k, threshold=threshold, language=language, fiscal_year=fiscal_year, group=group, company=company)
            raise

        return all_results

    # ── Re-ranking ─────────────────────────────────────
    @traceable(name="rerank")
    def rerank(
        self,
        query: str,
        results: list[dict[str, Any]],
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """
        用 Vertex AI Ranking API 對搜尋結果精排。
        若 Ranking API 失敗，退回 Gemini prompt-based rerank。
        """
        if not results:
            return results

        try:
            reranked = self._rerank_via_ranking_api(query, results, top_k)
            for r in reranked:
                r["_rerank_method"] = "ranking_api"
                # 用 Ranking API 分數取代原始 similarity，供時間加權使用
                if "rerank_score" in r:
                    r["similarity"] = r["rerank_score"]
            return self._apply_time_weight(reranked)
        except Exception as e:
            logger.warning(f"[RERANK] Ranking API 失敗，退回 Gemini rerank：{e}")
            reranked = self._rerank_via_gemini(query, results, top_k)
            for r in reranked:
                r["_rerank_method"] = "gemini_fallback"
            return self._apply_time_weight(reranked)

    def _rerank_via_ranking_api(
        self,
        query: str,
        results: list[dict[str, Any]],
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """使用 Vertex AI Ranking API (Discovery Engine) 精排。"""
        # 懶初始化 RankServiceClient
        if not hasattr(self, '_rank_client'):
            self._rank_client = discoveryengine.RankServiceClient()

        # 將搜尋結果轉換為 RankingRecord
        records = []
        for i, r in enumerate(results):
            records.append(discoveryengine.RankingRecord(
                id=str(i),
                title=r.get("file_name", "") or "",
                content=(r.get("text_content", "") or "")[:1024],
            ))

        ranking_config = (
            f"projects/{GCP_PROJECT}/locations/global"
            f"/rankingConfigs/default_ranking_config"
        )

        request = discoveryengine.RankRequest(
            ranking_config=ranking_config,
            model="semantic-ranker-default@latest",
            top_n=top_k,
            query=query,
            records=records,
        )

        response = self._rank_client.rank(request=request)

        # 根據 Ranking API 回傳的順序重組結果
        reranked = []
        for rec in response.records:
            idx = int(rec.id)
            if 0 <= idx < len(results):
                r = results[idx].copy()
                r["rerank_score"] = rec.score
                reranked.append(r)

        logger.info(f"[RERANK] Ranking API 完成：{len(reranked)} 筆結果")
        return reranked[:top_k]

    def _rerank_via_gemini(
        self,
        query: str,
        results: list[dict[str, Any]],
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Fallback：用 Gemini 對搜尋結果精排。"""
        docs_text = ""
        for i, r in enumerate(results):
            snippet = r["text_content"][:500]
            docs_text += f"\n[文件{i+1}] {snippet}\n"

        prompt = f"""你是一位資訊檢索專家。以下是使用者的問題和多個候選文件片段。
請根據每個文件與問題的相關性，輸出排序後的文件編號（最相關的排在前面）。
只輸出 JSON 陣列，例如 [3, 1, 5, 2, 4]。不要輸出其他文字。

使用者問題：{query}

候選文件：
{docs_text}

請輸出排序後的文件編號 JSON 陣列："""

        try:
            response = self._genai.models.generate_content(
                model=self._RERANK_MODEL,
                contents=[prompt],
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    response_mime_type="application/json",
                ),
            )
            ranking = json.loads(response.text.strip())
            reranked = []
            for idx in ranking:
                if isinstance(idx, int) and 1 <= idx <= len(results):
                    reranked.append(results[idx - 1])
            for r in results:
                if r not in reranked:
                    reranked.append(r)
            return reranked[:top_k]
        except Exception as e:
            logger.warning(f"[RERANK] Gemini rerank 也失敗，返回原始排序：{e}")
            return results[:top_k]

    # ── 查詢展開 ───────────────────────────────────────
    @traceable(name="expand_query")
    def _expand_query(self, query: str) -> list[str]:
        """用 Gemini Flash 將使用者查詢展開為 2 個替代查詢。
        
        若展開失敗（如 API 異常），回傳空列表，不影響原始搜尋。
        """
        if len(query) > 100:  # 查詢已經夠長，不需展開
            return []

        prompt = f"""你是 ESG 與財務資訊檢索專家。使用者輸入了一個搜尋查詢，請將它改寫為 2 個更精確的替代查詢，用於搜尋企業永續報告、財務報告等知識庫。

規則：
1. 保持與原始查詢相同的意圖，不要偏離主題
2. 補充可能的專業術語、全名、同義詞
3. 只輸出 JSON 陣列，例如 ["查詢1", "查詢2"]

原始查詢：{query}

輸出 JSON 陣列："""

        try:
            response = self._genai.models.generate_content(
                model=self._EXPAND_MODEL,
                contents=[prompt],
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    response_mime_type="application/json",
                ),
            )
            raw_text = response.text.strip()
            # 防禦性解析：清理可能的 Markdown code block 標記
            json_match = re.search(r'\[.*\]', raw_text, re.DOTALL)
            clean_text = json_match.group(0) if json_match else raw_text
            expanded = json.loads(clean_text)
            if isinstance(expanded, list):
                return [str(q).strip() for q in expanded[:2] if q and str(q).strip()]
        except json.JSONDecodeError as e:
            logger.debug(f"[RETRIEVER] 查詢展開 JSON 解析失敗：{e}")
        except Exception as e:
            logger.debug(f"[RETRIEVER] 查詢展開失敗，使用原始查詢：{e}")
        return []

    # ── 多因子加權排序 ──────────────────────────────────
    # 來源類型權重對照表
    _SOURCE_WEIGHTS: dict[str, float] = {
        "永續報告書": 1.0,     # 最權威，ESG 核心文件
        "網頁":     0.9,       # 最即時，通常是最新消息
        "年度報告": 0.75,      # 有 ESG 章節但非主文件
    }
    _DEFAULT_SOURCE_WEIGHT = 0.6  # 其他 / 未分類

    def _apply_time_weight(
        self,
        results: list[dict[str, Any]],
        sim_weight: Optional[float] = None,
        time_weight: Optional[float] = None,
        source_weight: Optional[float] = None,
    ) -> list[dict[str, Any]]:
        """多因子加權排序。動態從 rag_config 讀取權重。

        公式：adjusted_score = similarity × sim_weight
                              + year_score × time_weight
                              + source_score × source_weight

        year_score   = 0~1，當年度為 1.0，每差一年遞減 0.15。
        source_score = 依 category 對照 _SOURCE_WEIGHTS。
        """
        if not results:
            return results

        # 以「結果集中最新的年份」為基準（而非當前年）
        # 確保最新報告永遠得 1.0 分，舊報告依差距遞減
        def _extract_year(r: dict) -> int | None:
            fy = r.get("fiscal_year")
            if not fy:
                return None
            match = re.search(r"(\d{3,4})", str(fy))
            if match:
                y = int(match.group(1))
                return y + 1911 if y < 1911 else y
            return None

        known_years = [y for r in results if (y := _extract_year(r)) is not None]
        # 最新年不超過今年，防止資料錯誤
        current_year = datetime.now().year
        anchor_year = min(max(known_years), current_year) if known_years else current_year

        for r in results:
            # ── 年份分數（以 anchor_year 為満分基準）──
            doc_year = _extract_year(r)
            year_score = 0.85  # 未填年度：假設接近最新，給予高分
            if doc_year is not None:
                years_diff = max(0, anchor_year - doc_year)
                year_score = max(0.0, 1.0 - years_diff * 0.25)  # 每差1年 -0.25

            # ── 來源類型分數 ──
            cat = r.get("category", "") or ""
            src_type = r.get("source_type", "") or ""
            if src_type == "web":
                src_score = SemanticRetriever._SOURCE_WEIGHTS.get("網頁", 0.9)
            else:
                src_score = SemanticRetriever._SOURCE_WEIGHTS.get(
                    cat, SemanticRetriever._DEFAULT_SOURCE_WEIGHT
                )

            # ── 加權合成 ──
            # 動態讀取權重（防禦老舊 cached 物件沒有 _rag_config）
            _cfg = getattr(self, '_rag_config', None)
            if _cfg is not None and sim_weight is None:
                sw = _cfg.get("sim_weight", float)
            else:
                sw = sim_weight if sim_weight is not None else 0.60
            if _cfg is not None and time_weight is None:
                tw = _cfg.get("year_weight", float)
            else:
                tw = time_weight if time_weight is not None else 0.25
            if _cfg is not None and source_weight is None:
                srcw = _cfg.get("source_weight", float)
            else:
                srcw = source_weight if source_weight is not None else 0.15
            # 最終 None 安全 fallback
            sw   = sw   if isinstance(sw,   float) else 0.60
            tw   = tw   if isinstance(tw,   float) else 0.25
            srcw = srcw if isinstance(srcw, float) else 0.15

            sim = r.get("similarity", 0) or 0
            r["adjusted_score"] = (
                sim * sw
                + year_score * tw
                + src_score * srcw
            )

        results.sort(key=lambda x: x.get("adjusted_score", 0), reverse=True)
        return results
