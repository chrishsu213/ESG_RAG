"""
modules/embedder.py — Gemini Embedding 模組
使用 Google text-embedding-004 模型產生 768 維向量。
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log

from config import EMBEDDING_MODEL, EMBEDDING_DIMENSION

# Phase 2: 可選的 dataclass 設定（完全向下相容）
try:
    from config_modules import EmbedderConfig
except ImportError:
    EmbedderConfig = None  # type: ignore

logger = logging.getLogger(__name__)


class GeminiEmbedder:
    """封裝 Google Gemini Embedding API，支援單筆與批次嵌入。

    可傳入 EmbedderConfig 覆寫預設參數：
        embedder = GeminiEmbedder(cfg=EmbedderConfig(dimension=1024))
    """

    _MAX_BATCH_SIZE = 100       # API 單次上限

    def __init__(self, api_key: Optional[str] = None, cfg=None) -> None:
        from config import get_genai_client
        self._client = get_genai_client(api_key)
        if cfg is not None:
            self._model = cfg.model
        else:
            self._model = EMBEDDING_MODEL

    # ── 單筆嵌入 ──────────────────────────────────────
    def embed_text(self, text: str) -> list[float]:
        """產生單段文字的 768 維向量嵌入。"""
        result = self._call_with_retry([text])
        return result[0]

    # ── 批次嵌入 ──────────────────────────────────────
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批次產生多段文字的向量嵌入。"""
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
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=10),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _call_with_retry(self, texts: list[str]) -> list[list[float]]:
        """呼叫 Gemini Embedding API，自動重試（指數退避）。"""
        result = self._client.models.embed_content(
            model=self._model,
            contents=texts,
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_DOCUMENT",
                output_dimensionality=EMBEDDING_DIMENSION,
            ),
        )
        return [e.values for e in result.embeddings]
