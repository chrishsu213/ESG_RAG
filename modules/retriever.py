"""
modules/retriever.py — 語義搜尋 / 混合搜尋 / Re-ranking 模組
封裝 Supabase RPC 呼叫，提供多種搜尋模式。
"""
from __future__ import annotations

import json
from typing import Any, Optional

from google import genai
from google.genai import types
from supabase import Client

from config import GEMINI_API_KEY, EMBEDDING_MODEL, EMBEDDING_DIMENSION


class SemanticRetriever:
    """
    多模式搜尋器：
    - search()        → 純向量搜尋
    - hybrid_search() → 向量 + 全文混合搜尋 (RRF)
    - rerank()        → 用 Gemini 對結果精排
    """

    _RERANK_MODEL = "gemini-3-flash-preview"

    def __init__(
        self,
        supabase_client: Client,
        api_key: Optional[str] = None,
    ) -> None:
        key = api_key or GEMINI_API_KEY
        if not key:
            raise ValueError("未提供 GEMINI_API_KEY")
        self._client = supabase_client
        self._genai = genai.Client(api_key=key)
        self._model = EMBEDDING_MODEL

    def _embed_query(self, query: str) -> list[float]:
        """將查詢文字轉為向量。"""
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
    def search(
        self,
        query: str,
        top_k: int = 5,
        threshold: float = 0.5,
        language: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """純向量語義搜尋（使用 match_chunks RPC）。
        language: 若指定（如 'en'），只搜該語言的文件。
        """
        query_embedding = self._embed_query(query)
        params = {
            "query_embedding": query_embedding,
            "match_count": top_k,
            "match_threshold": threshold,
        }
        if language:
            params["filter_language"] = language
        result = self._client.rpc("match_chunks", params).execute()
        return result.data or []

    # ── 混合搜尋 ───────────────────────────────────────
    def hybrid_search(
        self,
        query: str,
        top_k: int = 5,
        threshold: float = 0.3,
        language: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """向量 + 全文混合搜尋（使用 match_chunks_hybrid RPC）。
        language: 若指定（如 'en'），只搜該語言的文件。
        如果 hybrid RPC 尚未建立，自動退回純向量搜尋。
        """
        query_embedding = self._embed_query(query)
        params = {
            "query_embedding": query_embedding,
            "query_text": query,
            "match_count": top_k,
            "match_threshold": threshold,
        }
        if language:
            params["filter_language"] = language
        try:
            result = self._client.rpc("match_chunks_hybrid", params).execute()
            return result.data or []
        except Exception as e:
            if "match_chunks_hybrid" in str(e):
                print("[RETRIEVER] hybrid RPC 尚未建立，退回純向量搜尋")
                return self.search(query, top_k=top_k, threshold=threshold, language=language)
            raise

    # ── Re-ranking ─────────────────────────────────────
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
