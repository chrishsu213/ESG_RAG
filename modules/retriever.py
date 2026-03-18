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
from supabase import Client

from config import EMBEDDING_MODEL, EMBEDDING_DIMENSION

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
    - rerank()        → 用 Gemini 對結果精排
    """

    _RERANK_MODEL = "gemini-2.0-flash"  # Vertex AI GA
    _EXPAND_MODEL = "gemini-2.0-flash-lite"   # 極快、極便宜，用於查詢展開

    def __init__(
        self,
        supabase_client: Client,
        api_key: Optional[str] = None,
    ) -> None:
        from config import get_genai_client
        self._client = supabase_client
        self._genai = get_genai_client(api_key)
        self._model = EMBEDDING_MODEL

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
        result = self._client.rpc("match_chunks", params).execute()
        return self._apply_time_weight(result.data or [])

    # ── 混合搜尋 ───────────────────────────────────────
    @traceable(name="hybrid_search")
    def hybrid_search(
        self,
        query: str,
        top_k: int = 5,
        threshold: float = 0.3,
        language: Optional[str] = None,
        fiscal_year: Optional[str] = None,
        group: Optional[str] = None,
        company: Optional[str] = None,
        expand_query: bool = True,
    ) -> list[dict[str, Any]]:
        """向量 + 全文混合搜尋（使用 match_chunks_hybrid RPC）。"""
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
            return self._client.rpc("match_chunks_hybrid", params).execute().data or []

        logger = logging.getLogger(__name__)
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

        return self._apply_time_weight(all_results)

    # ── Re-ranking ─────────────────────────────────────
    @traceable(name="rerank")
    def rerank(
        self,
        query: str,
        results: list[dict[str, Any]],
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """
        用 Gemini 對搜尋結果精排。
        讓 AI 評分每個結果與問題的相關性，重新排序。
        """
        if not results:
            return results

        # 組合 prompt
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
                    response_mime_type="application/json",  # 強制 JSON 輸出
                ),
            )
            # 解析 JSON 陣列
            ranking = json.loads(response.text.strip())

            # 根據排序重組結果
            reranked = []
            for idx in ranking:
                if isinstance(idx, int) and 1 <= idx <= len(results):
                    reranked.append(results[idx - 1])
            # 加入未被排到的結果
            for r in results:
                if r not in reranked:
                    reranked.append(r)

            return reranked[:top_k]
        except Exception as e:
            print(f"[RERANK] Re-ranking 失敗，返回原始排序：{e}")
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
            print(f"[RETRIEVER] 查詢展開 JSON 解析失敗：{e}")
        except Exception as e:
            print(f"[RETRIEVER] 查詢展開失敗，使用原始查詢：{e}")
        return []

    # ── 時間加權排序 ───────────────────────────────────
    @staticmethod
    def _apply_time_weight(
        results: list[dict[str, Any]],
        time_weight: float = 0.1,
    ) -> list[dict[str, Any]]:
        """根據 fiscal_year 對搜尋結果做軟排序加權。

        公式：adjusted_score = similarity * (1 - time_weight) + year_score * time_weight
        year_score = 0~1，當年度為 1.0，每差一年遞減 0.15。
        """
        if not results:
            return results

        current_year = datetime.now().year

        for r in results:
            fy = r.get("fiscal_year")
            year_score = 0.7  # 未填年度給予中性偏高權重，避免懲罰未標記的新文件
            if fy:
                # 嘗試從 fiscal_year 提取數字年份（支援民國年 3 位數 + 西元年 4 位數）
                match = re.search(r"(\d{3,4})", str(fy))
                if match:
                    doc_year = int(match.group(1))
                    if doc_year < 1911:  # 民國年轉換（如 113 → 2024）
                        doc_year += 1911
                    years_diff = max(0, current_year - doc_year)
                    year_score = max(0, 1.0 - years_diff * 0.15)

            sim = r.get("similarity", 0) or 0
            r["adjusted_score"] = sim * (1 - time_weight) + year_score * time_weight

        results.sort(key=lambda x: x.get("adjusted_score", 0), reverse=True)
        return results
