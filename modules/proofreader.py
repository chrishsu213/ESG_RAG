"""
modules/proofreader.py — AI 校對模組
使用 Gemini 對清洗後的 Markdown 進行自動校對與修正。
"""
from __future__ import annotations

import time
from typing import Optional

from google import genai
from google.genai import types

from config import GEMINI_API_KEY


class AiProofreader:
    """
    使用 Gemini 對 Markdown 文本進行智能校對。

    功能：
    - 修正亂碼/編碼錯誤
    - 修復不正確的段落斷行
    - 刪除重複的段落
    - 修復 Markdown 表格格式
    - 移除殘餘的頁首頁尾內容
    - 修正明顯的 OCR 識別錯誤
    """

    _MODEL = "gemini-flash-lite-latest"
    _MAX_RETRIES = 3
    _RETRY_DELAY = 2.0

    # 每次處理的最大字元數（避免超過 token 上限）
    _CHUNK_SIZE = 8000

    _PROOFREAD_PROMPT = """你是一位專業的文件校對員。以下是從 PDF 提取出的 Markdown 文本，可能包含以下問題：

1. 亂碼或編碼錯誤
2. 不正確的段落斷行（同一段落被拆成多行）
3. 重複的段落
4. 表格格式錯誤
5. 殘餘的頁首/頁尾/頁碼（如「台泥企業團」、「第 X 頁」反覆出現）
6. OCR 識別錯誤（如「0」和「O」混淆）

請修正上述問題並輸出修正後的 Markdown。

規則：
- 只修正格式和錯誤，不要改變原文的實質內容
- 不要添加原文沒有的資訊
- 保持原有的標題層級結構
- 輸出繁體中文
- 直接輸出修正後的內容，不要添加任何說明

原始文本：
"""

    def __init__(self, api_key: Optional[str] = None) -> None:
        key = api_key or GEMINI_API_KEY
        if not key:
            raise ValueError("需要 GEMINI_API_KEY 才能使用 AI 校對功能")
        self._client = genai.Client(api_key=key)

    def proofread(
        self,
        markdown_text: str,
        on_progress: Optional[callable] = None,
    ) -> str:
        """
        對 Markdown 文本進行 AI 校對。

        如果文本太長，會自動分段處理。

        Parameters
        ----------
        markdown_text : str
            待校對的 Markdown 文本。
        on_progress : callable | None
            進度回呼 (current_chunk, total_chunks)。

        Returns
        -------
        str
            校對後的 Markdown 文本。
        """
        # 如果文本夠短，一次處理
        if len(markdown_text) <= self._CHUNK_SIZE:
            return self._proofread_chunk(markdown_text)

        # 分段處理
        chunks = self._split_by_sections(markdown_text)
        total = len(chunks)
        proofread_chunks: list[str] = []

        for i, chunk in enumerate(chunks, 1):
            if on_progress:
                on_progress(i, total)

            result = self._proofread_chunk(chunk)
            proofread_chunks.append(result)

        return "\n\n".join(proofread_chunks)

    def _proofread_chunk(self, text: str) -> str:
        """對單段文本進行校對。"""
        last_error = None

        for attempt in range(1, self._MAX_RETRIES + 1):
            try:
                response = self._client.models.generate_content(
                    model=self._MODEL,
                    contents=[self._PROOFREAD_PROMPT + text],
                    config=types.GenerateContentConfig(
                        temperature=0.1,  # 低溫度以確保忠實校對
                    ),
                )
                return response.text.strip()

            except Exception as e:
                last_error = e
                if attempt < self._MAX_RETRIES:
                    time.sleep(self._RETRY_DELAY * attempt)

        # 校對失敗，回傳原文
        print(f"[PROOFREAD] AI 校對失敗：{last_error}，回傳原文")
        return text

    def _split_by_sections(self, text: str) -> list[str]:
        """
        按照 Markdown 標題（# ## ###）將文本分段，
        確保每段不超過 _CHUNK_SIZE 字元。
        """
        lines = text.split("\n")
        chunks: list[str] = []
        current_chunk: list[str] = []
        current_size = 0

        for line in lines:
            line_len = len(line) + 1  # +1 for newline

            # 遇到標題且當前 chunk 已有內容且快要超限
            if (
                line.startswith("#")
                and current_chunk
                and current_size + line_len > self._CHUNK_SIZE
            ):
                chunks.append("\n".join(current_chunk))
                current_chunk = []
                current_size = 0

            current_chunk.append(line)
            current_size += line_len

            # 即使沒遇到標題，但超限了也要切
            if current_size > self._CHUNK_SIZE and len(current_chunk) > 1:
                chunks.append("\n".join(current_chunk))
                current_chunk = []
                current_size = 0

        if current_chunk:
            chunks.append("\n".join(current_chunk))

        return chunks
