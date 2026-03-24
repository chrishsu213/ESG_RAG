"""
modules/parser_pdf_vision.py — Gemini Vision PDF 解析器
將 PDF 每頁轉為圖片，送入 Gemini Vision 進行高品質 Markdown 轉換。
支援混合模式：純文字頁走 PyMuPDF（免費），圖表/掃描頁走 Vision（付費）。
"""
from __future__ import annotations

import io
import time
import concurrent.futures
from typing import Callable, Optional

import fitz  # PyMuPDF
from google import genai
from google.genai import types




class VisionPdfParser:
    """
    使用 Gemini Vision 解析 PDF，自動判斷每頁是否需要 Vision 輔助。

    Parameters
    ----------
    mode : str
        "auto"       - 自動判斷：文字少的頁面用 Vision，文字多的走 PyMuPDF（推薦）
        "vision"     - 所有頁面都用 Vision（品質最高，採並發處理）
        "vision_pdf" - 整份 PDF 上傳模式（已棄用，建議改用 vision）
        "text"       - 所有頁面都走 PyMuPDF（免費，與舊版相同）
    text_threshold : int
        auto 模式下，少於此字數的頁面會切換為 Vision 模式。
    on_progress : Callable | None
        進度回呼 (current_page, total_pages, mode_used)。
    max_workers : int
        vision 模式的並發執行緒數（建議 5~8，避免撞 GCP Rate Limit）。
    """

    _VISION_MODEL = "gemini-2.5-flash"  # Vertex AI GA 2.5
    _MAX_RETRIES = 5
    _RETRY_DELAY = 15.0  # 指數退避基數（秒）
    _BATCH_PAGE_LIMIT = 15  # 整份 PDF 上傳時，每批最多頁數

    _VISION_PROMPT = """你是一位專業的文件數位化專家。請將此圖片（PDF單頁）的內容完美轉換為 Markdown 格式。

**核心規則（嚴格遵守）**：
1. 【文字】保持原有段落與換行結構。
2. 【表格】只要畫面上看起來是表格（有欄列對齊的數據），絕對要使用 Markdown Table `| 欄位 | 欄位 |` 完美重現，不可用文字簡化。
3. 【資訊圖表】如果是圓餅圖、散佈圖等無法轉為表格的視覺圖表，請用「📊 [圖表標題]：[核心數據與結論描述]」來總結。
4. 【無效頁面】如果是封面、目錄，或是只有大圖沒有實質數據的過場頁，請直接輸出 'EMPTY_PAGE'。

**標題與排版**：
- 畫面中最大的字體、且獨立成行 → 強制標記為 `# 標題`
- 次大字體、章節編號（如 1.1、壹、） → 標記為 `## 標題` 或 `### 標題`
- **絕對禁止**使用 `**加粗**` 來代替任何獨立成行的標題，必須用 `#` 語法
- `#` 號與標題文字之間必須有一個空格（正確：`## 標題`，錯誤：`##標題`）
- 排除頁首頁尾的導覽列與頁碼文字。
- 多欄排版請「由左至右、由上至下」依序讀取。

不要有任何開場白，直接輸出 Markdown。"""

    _WHOLE_PDF_PROMPT = """你是一位專業的文件數位化專家。請將此 PDF 文件的所有內容轉換為結構化的 Markdown 格式。

⚠️ **頁碼標記（最高優先，絕對必須）**：
每一個 PDF 頁面的內容開頭，無論該頁是文字頁、圖表頁或跳過的目錄頁，**一定要**輸出該頁的頁碼標記，格式如下：
```
<!-- PAGE:1 -->
```
其中數字為該頁在原始 PDF 中的實際頁碼（從 1 開始）。
絕對不能省略此標記。若某頁被跳過（如封面、目錄），仍須輸出 `<!-- PAGE:N -->` 後才能跳過該頁內容。

**頁面類型判斷**（每種頁面用不同方式處理）：
- 「資訊圖表頁」（散佈的 KPI 數據、圓餅圖、統計指標等）→ 整理為「**標籤**：數值」格式，按區塊順序排列
- 「文字內容頁」→ 保持原有段落結構
- 「目錄頁/封面頁」→ 輸出頁碼標記後跳過，不要輸出其他內容

**閱讀順序**：
- 多欄排版：先完整讀完左欄（上到下），再讀右欄（上到下）
- 不要交錯混合不同欄的內容

**必須排除**：
- 頁面頂部/底部的導覽列（如 Overview、治理、減碳、增綠、自然、共融、附錄 等標籤列）
- 每頁重複出現的公司名稱或報告標題
- 頁碼數字本身（但頁碼標記 `<!-- PAGE:N -->` 必須保留）

**標題層級判定規則（嚴格遵守）**：
請根據原始 PDF 的視覺排版與字體大小來決定 Markdown 標題層級：
1. 若該行文字字體最大、且獨立成行 → 強制標記為 `# 標題`
2. 若該行包含段落編號（如「壹、」「一、」「1.1」「第一章」）且字體加粗獨立成行 → 強制標記為 `## 標題` 或 `### 標題`
3. **絕對禁止**使用 `**加粗**` 來代替任何獨立成行的標題，必須用 `#` 語法
4. `#` 號與標題文字之間必須有一個空格（正確：`## 標題`，錯誤：`##標題`）

**其他規則**：
1. 表格轉為 Markdown 表格
2. 圖表數據用文字描述：「📊 [圖表標題]：[數據描述]」
3. 保留數字和專有名詞的準確性
4. 不要添加原文沒有的內容
5. 保持原文語言輸出，不要翻譯原文內容

直接輸出 Markdown 內容，不要添加額外說明。"""

    def __init__(
        self,
        mode: str = "auto",
        text_threshold: int = 100,
        on_progress: Optional[Callable] = None,
        api_key: Optional[str] = None,
        max_workers: int = 6,
    ) -> None:
        from config import get_genai_client
        self._client = get_genai_client(api_key)
        self._mode = mode
        self._text_threshold = text_threshold
        self._on_progress = on_progress
        self._max_workers = max_workers

        # 統計
        self.stats = {"total_pages": 0, "vision_pages": 0, "text_pages": 0, "skipped_pages": 0}

    def parse(self, file_path: str) -> str:
        """
        解析 PDF 檔案，回傳完整的 Markdown 字串。
        vision 模式採用並發處理，大幅縮短等待時間。
        """
        # 整份 PDF 上傳模式（已棄用，保留向下相容）
        if self._mode == "vision_pdf":
            import warnings
            warnings.warn(
                "vision_pdf 模式已棄用，請改用 mode='vision' 以獲得並發解析與更穩定的頁碼標記",
                DeprecationWarning, stacklevel=2,
            )
            return self._parse_whole_pdf(file_path)

        doc = fitz.open(file_path)
        total_pages = len(doc)
        self.stats["total_pages"] = total_pages

        # ── vision 模式：並發處理所有頁面 ────────────────────────────────
        if self._mode == "vision":
            return self._parse_vision_concurrent(doc, file_path, total_pages)

        # ── auto / text 模式：同步逐頁處理 ───────────────────────────────
        pages_md: list[str] = []
        for page_num, page in enumerate(doc, start=1):
            if self._on_progress:
                self._on_progress(page_num, total_pages, "分析中")

            text_content = page.get_text("text").strip()
            text_len = len(text_content)

            if self._mode == "text":
                use_vision = False
            else:  # auto
                use_vision = text_len < self._text_threshold

            if use_vision:
                if self._on_progress:
                    self._on_progress(page_num, total_pages, "Vision 解讀")
                page_md = self._vision_parse_page(page, page_num)
                if page_md:
                    self.stats["vision_pages"] += 1
                    pages_md.append(page_md.rstrip() + "\n")  # 統一尾部格式
                else:
                    self.stats["skipped_pages"] += 1
            else:
                if self._on_progress:
                    self._on_progress(page_num, total_pages, "文字提取")
                page_md = self._text_parse_page(page)
                if page_md.strip():
                    self.stats["text_pages"] += 1
                    pages_md.append(page_md.rstrip() + "\n")  # 統一尾部格式
                else:
                    self.stats["skipped_pages"] += 1

        doc.close()
        return "\n\n---\n\n".join(pages_md)

    def _parse_vision_concurrent(self, doc: fitz.Document, file_path: str, total_pages: int) -> str:
        """
        企業級並發視覺解析引擎。
        Step 1：主執行緒預先將所有頁面 render 為 PNG bytes（fitz 非 thread-safe，必須在主緒完成）。
        Step 2：ThreadPoolExecutor 並發送出所有 API 請求。
        Step 3：用 index 陣列保證頁序，過濾空頁後拼接 Markdown。
        """
        if self._on_progress:
            self._on_progress(0, total_pages, f"預先渲染所有頁面...")

        # Step 1: 主執行緒渲染（確保 fitz 操作的執行緒安全）
        mat = fitz.Matrix(2.0, 2.0)  # 2x 放大以提高辨識率
        page_images: list[tuple[int, bytes]] = []
        for page_num in range(total_pages):
            page = doc.load_page(page_num)
            pix = page.get_pixmap(matrix=mat)
            page_images.append((page_num + 1, pix.tobytes("png")))
        doc.close()

        # Step 2: 並發 API 請求
        results_md: list[str] = [""] * total_pages
        completed = 0

        if self._on_progress:
            self._on_progress(0, total_pages, f"啟動 {self._max_workers} 股並發解析...")

        with concurrent.futures.ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            future_to_page = {
                executor.submit(self._call_gemini_vision, img_bytes, p_num): p_num
                for p_num, img_bytes in page_images
            }

            for future in concurrent.futures.as_completed(future_to_page):
                p_num = future_to_page[future]
                try:
                    md_text = future.result()
                except Exception as e:
                    print(f"[VISION] 第 {p_num} 頁意外失敗：{e}")
                    md_text = ""

                results_md[p_num - 1] = md_text
                completed += 1

                if md_text.strip():
                    self.stats["vision_pages"] += 1
                else:
                    self.stats["skipped_pages"] += 1

                if self._on_progress:
                    self._on_progress(completed, total_pages, f"Vision 解析 ({completed}/{total_pages})")

        # Step 3: 過濾空頁並組合最終 Markdown
        final_pages = [md for md in results_md if md.strip()]
        return "\n\n---\n\n".join(final_pages)

    def _call_gemini_vision(self, img_bytes: bytes, page_num: int) -> str:
        """
        單頁 Vision API 呼叫，含指數退避重試。
        此方法在 ThreadPoolExecutor 中並發執行，必須是 thread-safe。
        """
        import time as _time
        last_error = None

        for attempt in range(1, self._MAX_RETRIES + 1):
            try:
                response = self._client.models.generate_content(
                    model=self._VISION_MODEL,
                    contents=[
                        types.Content(role="user", parts=[
                            types.Part.from_bytes(data=img_bytes, mime_type="image/png"),
                            types.Part(text=self._VISION_PROMPT),
                        ])
                    ],
                )
                result_text = response.text.strip()

                # 過濾無效頁面
                if "EMPTY_PAGE" in result_text:
                    return ""

                # 強制注入頁碼錨點
                return f"<!-- PAGE:{page_num} -->\n{result_text}"

            except Exception as e:
                last_error = e
                # 指數退避（15, 30, 60, 60, 60），最長 60 秒
                delay = min(self._RETRY_DELAY * (2 ** (attempt - 1)), 60)
                _time.sleep(delay)

        print(f"[VISION] 第 {page_num} 頁徹底失敗（{self._MAX_RETRIES} 次重試）：{last_error}")
        return ""  # 失敗回傳空字串，防止整本書崩潰

    def _parse_whole_pdf(self, file_path: str) -> str:
        """整份 PDF 上傳給 Gemini。超過 30 頁自動分批處理。（已棄用，保留向下相容）"""
        doc = fitz.open(file_path)
        total_pages = len(doc)
        self.stats["total_pages"] = total_pages

        if total_pages <= 30:
            doc.close()
            if self._on_progress:
                self._on_progress(1, 1, f"上傳整份 PDF（{total_pages} 頁）至 Gemini...")
            with open(file_path, "rb") as f:
                pdf_bytes = f.read()
            result = self._send_pdf_to_gemini(pdf_bytes, 1, total_pages)
            self.stats["vision_pages"] = total_pages
            return result
        else:
            all_results: list[str] = []
            batch_count = (total_pages + self._BATCH_PAGE_LIMIT - 1) // self._BATCH_PAGE_LIMIT

            for batch_idx in range(batch_count):
                start_page = batch_idx * self._BATCH_PAGE_LIMIT
                end_page = min(start_page + self._BATCH_PAGE_LIMIT, total_pages)

                if self._on_progress:
                    self._on_progress(
                        batch_idx + 1, batch_count,
                        f"分批處理中：第 {start_page+1}-{end_page} 頁（共 {total_pages} 頁）"
                    )

                sub_doc = fitz.open()
                sub_doc.insert_pdf(doc, from_page=start_page, to_page=end_page - 1)
                pdf_bytes = sub_doc.tobytes()
                sub_doc.close()

                batch_result = self._send_pdf_to_gemini(pdf_bytes, start_page + 1, end_page)
                if batch_result:
                    all_results.append(batch_result)
                    self.stats["vision_pages"] += (end_page - start_page)

            doc.close()

            if self._on_progress:
                self._on_progress(batch_count, batch_count, f"全部完成！共 {total_pages} 頁")

            return "\n\n---\n\n".join(all_results)

    def _send_pdf_to_gemini(self, pdf_bytes: bytes, page_start: int, page_end: int) -> str:
        """將 PDF bytes 送給 Gemini 解析，帶重試機制。"""
        import time as _time

        prompt = self._WHOLE_PDF_PROMPT
        if page_start > 1:
            prompt += f"\n\n注意：這是原始文件的第 {page_start} 至 {page_end} 頁，請在 PAGE 標記中使用這些實際頁碼。"

        last_error = None
        for attempt in range(1, self._MAX_RETRIES + 1):
            try:
                response = self._client.models.generate_content(
                    model=self._VISION_MODEL,
                    contents=[
                        types.Content(
                            role="user",
                            parts=[
                                types.Part.from_bytes(
                                    data=pdf_bytes,
                                    mime_type="application/pdf",
                                ),
                                types.Part(text=prompt),
                            ],
                        )
                    ],
                )
                return response.text.strip()

            except Exception as e:
                last_error = e
                if self._on_progress:
                    self._on_progress(0, 0, f"重試中... ({e})")
                delay = min(self._RETRY_DELAY * (2 ** (attempt - 1)), 120)  # 指數退避，最長 120s
                _time.sleep(delay)

        raise RuntimeError(f"PDF 第 {page_start}-{page_end} 頁解析失敗：{last_error}")

    def _vision_parse_page(self, page: fitz.Page, page_num: int) -> str:
        """用 Gemini Vision 解讀單頁 PDF（auto 模式使用）。"""
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("png")
        return self._call_gemini_vision(img_bytes, page_num)

    def _text_parse_page(self, page: fitz.Page) -> str:
        """用 PyMuPDF 純文字模式解析單頁（與原有 parser_pdf.py 邏輯類似）。"""
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        lines: list[str] = [f"<!-- PAGE:{page.number + 1} -->"]

        for block in blocks:
            if block["type"] != 0:
                continue

            for line in block.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue

                text = "".join(s["text"] for s in spans).strip()
                if not text:
                    continue

                max_font_size = max(s["size"] for s in spans)
                is_bold = any("bold" in s.get("font", "").lower() for s in spans)

                heading = self._detect_heading(text, max_font_size, is_bold)
                if heading:
                    lines.append(f"\n{'#' * heading} {text}\n")
                else:
                    lines.append(text)

        # 表格提取
        try:
            tables = page.find_tables()
            if tables and len(tables.tables) > 0:
                for table in tables:
                    rows = table.extract()
                    if not rows:
                        continue
                    clean_rows = [
                        [str(c).strip() if c else "" for c in row]
                        for row in rows
                    ]
                    header = clean_rows[0]
                    sep = ["-" * max(len(h), 3) for h in header]
                    md = ["| " + " | ".join(header) + " |",
                          "| " + " | ".join(sep) + " |"]
                    for row in clean_rows[1:]:
                        while len(row) < len(header):
                            row.append("")
                        md.append("| " + " | ".join(row[:len(header)]) + " |")
                    lines.append("\n" + "\n".join(md))
        except Exception:
            pass

        return "\n".join(lines)

    @staticmethod
    def _detect_heading(text: str, font_size: float, is_bold: bool) -> int | None:
        if len(text) > 200:
            return None
        if font_size >= 20:
            return 1
        if font_size >= 16:
            return 2
        if font_size >= 13 and is_bold:
            return 3
        return None
