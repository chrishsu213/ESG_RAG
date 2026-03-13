"""
modules/parser_docx.py — 模組 2b：Word (.docx) → Markdown
使用 python-docx 提取內容，保留 Heading 樣式與表格。
"""
from __future__ import annotations

from docx import Document
from docx.table import Table as DocxTable
from docx.oxml.ns import qn


class DocxParser:
    """將 .docx 檔案解析為 Markdown 格式字串。"""

    # Heading 樣式名稱 → Markdown 層級
    _HEADING_MAP = {
        "Heading 1": 1,
        "Heading 2": 2,
        "Heading 3": 3,
        "Heading 4": 4,
        "Heading 5": 5,
        "Heading 6": 6,
        "Title": 1,
        "Subtitle": 2,
    }

    def parse(self, file_path: str) -> str:
        """
        讀取 docx，依序遍歷段落與表格產生 Markdown。

        Returns
        -------
        str
            整份文件的 Markdown 字串。
        """
        doc = Document(file_path)
        md_parts: list[str] = []

        # 依文件 body 中的元素順序走訪（段落 + 表格交錯）
        for element in doc.element.body:
            tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag

            if tag == "p":
                paragraph = self._element_to_paragraph(element, doc)
                if paragraph is not None:
                    md_parts.append(paragraph)

            elif tag == "tbl":
                table = self._element_to_table(element, doc)
                if table:
                    md_parts.append(table)

        return "\n\n".join(md_parts)

    # ── 段落處理 ─────────────────────────────────────
    def _element_to_paragraph(self, element, doc: Document) -> str | None:
        """將 XML <w:p> 元素轉為 Markdown 行。"""
        # 找到對應的 Paragraph 物件
        from docx.text.paragraph import Paragraph

        para = Paragraph(element, doc.element.body)
        text = para.text.strip()
        if not text:
            return None

        # 判斷 Heading
        style_name = para.style.name if para.style else ""
        level = self._HEADING_MAP.get(style_name)

        if level:
            return f"{'#' * level} {text}"

        # 處理粗體 / 斜體 (整段 run 級別)
        runs_md: list[str] = []
        for run in para.runs:
            t = run.text
            if not t:
                continue
            if run.bold:
                t = f"**{t}**"
            if run.italic:
                t = f"*{t}*"
            runs_md.append(t)

        return "".join(runs_md) if runs_md else text

    # ── 表格處理 ─────────────────────────────────────
    @staticmethod
    def _element_to_table(element, doc: Document) -> str:
        """將 XML <w:tbl> 元素轉為 Markdown 表格。"""
        table = DocxTable(element, doc.element.body)
        rows = table.rows
        if not rows:
            return ""

        md_rows: list[list[str]] = []
        for row in rows:
            cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
            md_rows.append(cells)

        if not md_rows:
            return ""

        # 確定欄數
        col_count = max(len(r) for r in md_rows)
        for r in md_rows:
            while len(r) < col_count:
                r.append("")

        header = md_rows[0]
        sep = ["-" * max(len(h), 3) for h in header]
        lines = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join(sep) + " |",
        ]
        for r in md_rows[1:]:
            lines.append("| " + " | ".join(r) + " |")

        return "\n".join(lines)
