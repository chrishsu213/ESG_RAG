"""
modules/parser_audio.py — 錄音檔解析模組
使用 Gemini Audio API 將錄音檔轉錄為帶講者標記的 Markdown。
支援專有名詞字典自動替換。

流程：
    1. 上傳錄音檔 → Gemini 轉錄
    2. 套用專有名詞字典替換
    3. 回傳草稿 Markdown（使用者可編輯後再入庫）
"""
from __future__ import annotations

import re
import time
from typing import Callable, Optional

from google import genai
from google.genai import types





class AudioParser:
    """
    錄音檔轉錄器：
    - 支援 mp3, wav, m4a, ogg, flac
    - 自動辨識講者
    - 套用專有名詞字典
    """

    _MODEL = "gemini-2.5-flash"  # Vertex AI GA 2.5
    _MAX_RETRIES = 3
    _RETRY_DELAY = 3.0

    _SUPPORTED_MIME = {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
        ".webm": "audio/webm",
    }

    _TRANSCRIPTION_PROMPT = """你是一位專業的會議記錄轉錄員。請將此錄音檔轉錄為結構化的 Markdown 格式。

**轉錄規則**：

1. **講者辨識**：盡可能區分不同的講者，使用以下格式：
   - 如果能辨識講者身份，使用 `**[講者名稱]**：`
   - 如果無法確定，使用 `**[講者 A]**：`、`**[講者 B]**：` 等

2. **時間標記**：每隔合理的段落加上時間標記，格式為 `[HH:MM:SS]`

3. **內容格式**：
   - 保持原始語句的完整性，不要過度精簡
   - 專業術語保持原樣
   - 數字和數據要精確記錄
   - 明顯的口誤或重複可以適度清理

4. **段落結構**：
   - 議題切換時用 `---` 分隔
   - 如果有明顯的議程項目，使用 `## 議題名稱` 標記

5. **特殊標記**：
   - 聽不清楚的部分用 `[聽不清楚]` 標記
   - 背景雜音導致無法辨識的用 `[雜音]` 標記
   - 不確定的內容用 `[?]` 標記

**輸出範例**：

## 開場

[00:00:15] **[主持人]**：各位好，今天的會議主要討論...

[00:01:30] **[講者 A]**：關於碳排放目標，我們目前的進度是...

---

## 碳排放議題

[00:05:20] **[講者 B]**：根據最新的 SBT 報告...
"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> None:
        from config import get_genai_client
        self._client = get_genai_client(api_key)
        self._on_progress = on_progress

    def parse(
        self,
        file_path: str,
        terms_dict: Optional[dict[str, str]] = None,
    ) -> dict:
        """
        轉錄錄音檔。

        Parameters
        ----------
        file_path : str
            錄音檔路徑。
        terms_dict : dict | None
            專有名詞字典 {原始詞: 完整名稱}。

        Returns
        -------
        dict
            - raw_transcript: str (原始轉錄)
            - corrected_transcript: str (套用字典後的轉錄)
            - terms_applied: list[str] (被替換的詞彙)
        """
        import os

        ext = os.path.splitext(file_path)[1].lower()
        mime_type = self._SUPPORTED_MIME.get(ext)
        if not mime_type:
            raise ValueError(
                f"不支援的音檔格式：{ext}。"
                f"支援：{', '.join(self._SUPPORTED_MIME.keys())}"
            )

        if self._on_progress:
            self._on_progress("讀取音檔中...")

        with open(file_path, "rb") as f:
            audio_bytes = f.read()

        file_size_mb = len(audio_bytes) / (1024 * 1024)
        if self._on_progress:
            self._on_progress(f"音檔大小：{file_size_mb:.1f} MB，開始轉錄...")

        # 呼叫 Gemini
        raw_transcript = self._transcribe(audio_bytes, mime_type)

        # 套用專有名詞字典
        corrected = raw_transcript
        terms_applied = []
        if terms_dict:
            corrected, terms_applied = self._apply_terms_dict(
                raw_transcript, terms_dict
            )

        return {
            "raw_transcript": raw_transcript,
            "corrected_transcript": corrected,
            "terms_applied": terms_applied,
        }

    def _transcribe(self, audio_bytes: bytes, mime_type: str) -> str:
        """呼叫 Gemini Audio API 轉錄。"""
        last_error = None
        for attempt in range(1, self._MAX_RETRIES + 1):
            try:
                if self._on_progress:
                    self._on_progress(
                        f"Gemini 轉錄中（第 {attempt} 次嘗試）..."
                    )

                response = self._client.models.generate_content(
                    model=self._MODEL,
                    contents=[
                        types.Content(
                            role="user",
                            parts=[
                                types.Part.from_bytes(
                                    data=audio_bytes,
                                    mime_type=mime_type,
                                ),
                                types.Part(text=self._TRANSCRIPTION_PROMPT),
                            ],
                        )
                    ],
                )

                result = response.text.strip()

                if self._on_progress:
                    self._on_progress("轉錄完成！")

                return result

            except Exception as e:
                last_error = e
                if self._on_progress:
                    self._on_progress(f"轉錄失敗，重試中... ({e})")
                time.sleep(self._RETRY_DELAY * attempt)

        raise RuntimeError(f"錄音檔轉錄失敗（已重試 {self._MAX_RETRIES} 次）：{last_error}")

    @staticmethod
    def _apply_terms_dict(
        text: str, terms_dict: dict[str, str]
    ) -> tuple[str, list[str]]:
        """
        套用專有名詞字典。
        按照詞彙長度由長到短排序，避免短詞覆蓋長詞。
        """
        applied = []

        # 長詞優先
        sorted_terms = sorted(terms_dict.keys(), key=len, reverse=True)

        for term in sorted_terms:
            full_name = terms_dict[term]
            # 只替換獨立出現的詞（前後不是中文字或英文字母）
            pattern = re.compile(
                rf"(?<![a-zA-Z\u4e00-\u9fff]){re.escape(term)}(?![a-zA-Z\u4e00-\u9fff])",
                re.IGNORECASE,
            )
            if pattern.search(text):
                text = pattern.sub(full_name, text)
                applied.append(term)

        return text, applied

    @staticmethod
    def get_supported_formats() -> list[str]:
        """回傳支援的音檔格式列表。"""
        return list(AudioParser._SUPPORTED_MIME.keys())
