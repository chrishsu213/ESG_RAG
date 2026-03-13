"""
modules/embedder.py — Gemini Embedding 模組
使用 Google text-embedding-004 模型產生 768 維向量。
"""
from __future__ import annotations

import time
from typing import Optional

from google import genai
from google.genai import types

from config import GEMINI_API_KEY, EMBEDDING_MODEL, EMBEDDING_DIMENSION


class GeminiEmbedder:
    """封裝 Google Gemini Embedding API，支援單筆與批次嵌入。"""

    _MAX_BATCH_SIZE = 100       # API 單次上限
    _MAX_RETRIES = 3
    _RETRY_DELAY_SEC = 2.0

    def __init__(self, api_key: Optional[str] = None) -> None:
        key = api_key or GEMINI_API_KEY
        if not key:
            raise ValueError(
                "未提供 GEMINI_API_KEY，請在 .env 中設定或傳入 api_key 參數"
            )
        self._client = genai.Client(api_key=key)
        self._model = EMBEDDING_MODEL

    # ── 單筆嵌入 ──────────────────────────────────────
    def embed_text(self, text: str) -> list[float]:
        """
        產生單段文字的向量嵌入。

        Parameters
        ----------
        text : str
            輸入文字。

        Returns
        -------
        list[float]
            768 維向量。
        """
        result = self._call_with_retry([text])
        return result[0]

    # ── 批次嵌入 ──────────────────────────────────────
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        批次產生多段文字的向量嵌入。

        Parameters
        ----------
        texts : list[str]
            輸入文字列表。

        Returns
        -------
        list[list[float]]
            每段文字對應的 768 維向量。
        """
        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), self._MAX_BATCH_SIZE):
            batch = texts[i : i + self._MAX_BATCH_SIZE]
            # 過濾空白文字，API 不接受空 Part
            batch = [t if t and t.strip() else " " for t in batch]
            embeddings = self._call_with_retry(batch)
            all_embeddings.extend(embeddings)
            # 批次間稍微延遲避免 rate-limit
            if i + self._MAX_BATCH_SIZE < len(texts):
                time.sleep(0.5)

        return all_embeddings

    # ── 內部：帶重試的 API 呼叫 ────────────────────────
    def _call_with_retry(self, texts: list[str]) -> list[list[float]]:
        """呼叫 Gemini Embedding API，自動重試最多 _MAX_RETRIES 次。"""
        last_error: Exception | None = None

        for attempt in range(1, self._MAX_RETRIES + 1):
            try:
                result = self._client.models.embed_content(
                    model=self._model,
                    contents=texts,
                    config=types.EmbedContentConfig(
                        task_type="RETRIEVAL_DOCUMENT",
                        output_dimensionality=EMBEDDING_DIMENSION,
                    ),
                )
                return [e.values for e in result.embeddings]
            except Exception as e:
                last_error = e
                if attempt < self._MAX_RETRIES:
                    wait = self._RETRY_DELAY_SEC * attempt
                    print(
                        f"[EMBED] 第 {attempt} 次嵌入失敗 ({e})，"
                        f"{wait:.1f}s 後重試…"
                    )
                    time.sleep(wait)

        raise RuntimeError(
            f"Embedding API 呼叫失敗（已重試 {self._MAX_RETRIES} 次）：{last_error}"
        )
