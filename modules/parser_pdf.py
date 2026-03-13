"""
modules/parser_pdf.py — 模組 2a：PDF → Markdown
使用 PyMuPDF (fitz) 提取 PDF 文字內容，盡量保留標題層級與表格結構。
支援多欄排版偵測，確保文字按正確閱讀順序輸出。
"""
from __future__ import annotations

import re
import fitz  # PyMuPDF


class PdfParser:
    """將 PDF 檔案解析為 Markdown 格式字串。"""

    def parse(self, file_path: str) -> str:
        """
        讀取 PDF，逐頁提取文字並轉換為 Markdown。

        Returns
        -------
        str
            整份文件的 Markdown 字串。
        """
        doc = fitz.open(file_path)
        pages_md: list[str] = []

        for page_num, page in enumerate(doc, start=1):
            blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE, sort=True)["blocks"]
            
            # 只保留文字區塊（sort=True 已依座標排序）
            text_blocks = [b for b in blocks if b["type"] == 0]
            
            page_lines: list[str] = []

            # 插入頁碼標記（供 Chunker 追蹤來源頁數）
            page_lines.append(f"<!-- PAGE:{page_num} -->")

            for block in text_blocks:
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    if not spans:
                        continue

                    text = "".join(s["text"] for s in spans).strip()
                    if not text:
                        continue

                    # ── 標題偵測 (依字體大小啟發式判斷) ──
                    max_font_size = max(s["size"] for s in spans)
                    is_bold = any(
                        "bold" in s.get("font", "").lower() for s in spans
                    )

                    heading_level = self._detect_heading_level(
                        text, max_font_size, is_bold
                    )
                    if heading_level:
                        page_lines.append(f"\n{'#' * heading_level} {text}\n")
                    else:
                        page_lines.append(text)

            # 將該頁所有文字段落合併
            page_text = "\n".join(page_lines)

            # 同時嘗試提取表格 (PyMuPDF >= 1.23.0)
            tables_md = self._extract_tables(page)
            if tables_md:
                page_text += "\n\n" + tables_md

            pages_md.append(page_text)

        doc.close()
        return "\n\n".join(pages_md)

    # ── 私有方法 ─────────────────────────────────────
    @staticmethod
    def _sort_blocks_reading_order(blocks: list[dict], page_width: float) -> list[dict]:
        """
        將文字區塊按照人眼閱讀順序排列。
        
        策略：
        1. 依 X 座標分群，偵測是否為多欄排版
        2. 同一欄內按 Y 座標（上到下）排序
        3. 欄之間按 X 座標（左到右）排序
        """
        if not blocks:
            return blocks

        # 取得每個區塊的左上角座標
        positioned = []
        for b in blocks:
            x0 = b["bbox"][0]  # 左邊界
            y0 = b["bbox"][1]  # 上邊界
            positioned.append((x0, y0, b))

        # 偵測欄數：根據 X 座標分群
        mid_x = page_width / 2
        left_col = []
        right_col = []
        full_width = []

        for x0, y0, b in positioned:
            block_width = b["bbox"][2] - b["bbox"][0]
            
            # 如果區塊寬度超過頁面 60%，視為全幅（標題、跨欄文字）
            if block_width > page_width * 0.6:
                full_width.append((y0, x0, b))
            elif x0 + block_width / 2 < mid_x:
                left_col.append((y0, x0, b))
            else:
                right_col.append((y0, x0, b))

        # 各欄按 Y 排序（上到下）
        full_width.sort(key=lambda t: t[0])
        left_col.sort(key=lambda t: t[0])
        right_col.sort(key=lambda t: t[0])

        # 如果沒有明顯的多欄（其中一邊幾乎沒有），直接按 Y 排序
        if len(left_col) <= 1 or len(right_col) <= 1:
            all_blocks = full_width + left_col + right_col
            all_blocks.sort(key=lambda t: (t[0], t[1]))
            return [b for _, _, b in all_blocks]

        # 多欄排版：全幅 → 左欄 → 右欄（依 Y 座標穿插）
        result = []
        
        # 把全幅元素作為分隔點，在全幅元素之間穿插左右欄
        if full_width:
            fw_iter = iter(full_width)
            current_fw = next(fw_iter, None)
            
            li, ri = 0, 0
            while li < len(left_col) or ri < len(right_col) or current_fw:
                # 先輸出 Y 座標在目前位置之前的全幅元素
                while current_fw and (
                    (li < len(left_col) and current_fw[0] <= left_col[li][0]) or
                    (li >= len(left_col) and ri >= len(right_col))
                ):
                    result.append(current_fw[2])
                    current_fw = next(fw_iter, None)
                
                # 輸出左欄（到下一個全幅元素的 Y 或結束）
                boundary_y = current_fw[0] if current_fw else float('inf')
                while li < len(left_col) and left_col[li][0] < boundary_y:
                    result.append(left_col[li][2])
                    li += 1
                
                # 輸出右欄（同範圍）
                while ri < len(right_col) and right_col[ri][0] < boundary_y:
                    result.append(right_col[ri][2])
                    ri += 1
                
                # 輸出當前全幅元素
                if current_fw and (li >= len(left_col) or current_fw[0] <= left_col[li][0] if li < len(left_col) else True):
                    result.append(current_fw[2])
                    current_fw = next(fw_iter, None)
        else:
            # 沒有全幅，直接左欄 → 右欄
            result = [b for _, _, b in left_col] + [b for _, _, b in right_col]

        return result

    # ── 私有方法 ─────────────────────────────────────
    @staticmethod
    def _detect_heading_level(
        text: str, font_size: float, is_bold: bool
    ) -> int | None:
        """
        依字體大小啟發式判斷標題層級。
        回傳 1-3 或 None（非標題）。
        """
        if len(text) > 200:  # 太長的文本不是標題
            return None
        if font_size >= 20:
            return 1
        if font_size >= 16:
            return 2
        if font_size >= 13 and is_bold:
            return 3
        return None

    @staticmethod
    def _extract_tables(page: fitz.Page) -> str:
        """嘗試用 PyMuPDF 內建 find_tables 提取表格並轉為 Markdown。"""
        try:
            tables = page.find_tables()
        except Exception:
            return ""

        if not tables or len(tables.tables) == 0:
            return ""

        md_parts: list[str] = []
        for table in tables:
            rows = table.extract()
            if not rows:
                continue

            # 清理 None 值
            clean_rows = [
                [str(cell).strip() if cell else "" for cell in row]
                for row in rows
            ]

            # 第一列當表頭
            header = clean_rows[0]
            separator = ["-" * max(len(h), 3) for h in header]
            md_table_lines = [
                "| " + " | ".join(header) + " |",
                "| " + " | ".join(separator) + " |",
            ]
            for row in clean_rows[1:]:
                # 確保列數對齊
                while len(row) < len(header):
                    row.append("")
                md_table_lines.append("| " + " | ".join(row[: len(header)]) + " |")

            md_parts.append("\n".join(md_table_lines))

        return "\n\n".join(md_parts)
