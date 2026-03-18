"""
modules/cleaner.py — 模組 2d：通用 Markdown 清洗器
過濾無意義的頁首、頁尾、頁碼、目錄頁，正規化空白行。
"""
from __future__ import annotations

import re
from config import HEADER_FOOTER_PATTERNS


class MarkdownCleaner:
    """對 raw Markdown 字串執行清洗規則。"""

    # 目錄條目模式：標題 + 點線/空格 + 頁碼
    _TOC_LINE_PATTERNS = [
        re.compile(r"^.{2,60}[.\s·…]{3,}\s*\d{1,4}\s*$"),   # 章節名稱 ...... 42
        re.compile(r"^.{2,60}\s{3,}\d{1,4}\s*$"),            # 章節名稱         42
        re.compile(r"^[.\s·…]{5,}$"),                        # 純點線行
    ]

    # 目錄區段標題關鍵字
    # 目錄區段標題關鍵字
    _TOC_SECTION_KEYWORDS = ["目錄", "目 錄", "Table of Contents", "CONTENTS", "contents"]

    # 導覽列模式（永續報告書常見的頂部/底部標籤列）
    _NAV_BAR_RE = re.compile(
        r"^(Overview|治理|減碳|增綠|自然|共融|附錄)"
        r"(\s+(Overview|治理|減碳|增綠|自然|共融|附錄))+\s*$"
    )

    # 亂碼偵測：一行中有過多替換字元
    _GARBLED_RE = re.compile(r"[\ufffd]{2,}")

    def __init__(self) -> None:
        self._patterns = [re.compile(p, re.MULTILINE) for p in HEADER_FOOTER_PATTERNS]

    def clean(self, raw_md: str) -> str:
        """
        清洗主流程：

        1. 移除整段目錄區段（由「目錄」標題起始的區段）
        2. 移除符合頁首/頁尾/頁碼 pattern 的行
        3. 移除目錄條目行（標題 + 點線 + 頁碼）
        4. 正規化連續空行（最多保留一行空行）
        5. 移除行尾多餘空白

        Returns
        -------
        str
            清洗後的 Markdown 字串。
        """
        # 先移除整段目錄區段
        raw_md = self._remove_toc_sections(raw_md)

        lines = raw_md.splitlines()
        cleaned: list[str] = []

        for line in lines:
            stripped = line.strip()

            # 過濾符合任一頁首/頁尾 pattern 的行
            if stripped and any(p.match(stripped) for p in self._patterns):
                continue

            # 過濾導覽列
            if stripped and self._NAV_BAR_RE.match(stripped):
                continue

            # 過濾亂碼行（包含連續替換字元）
            if stripped and self._GARBLED_RE.search(stripped):
                continue

            # 過濾目錄條目行
            if stripped and any(p.match(stripped) for p in self._TOC_LINE_PATTERNS):
                continue

            cleaned.append(line.rstrip())

        text = "\n".join(cleaned)

        # ── Heading 正規化（攔截 Gemini 的不確定性輸出）────
        # 修復 1：獨立成行的加粗文字帶編號 → 轉為 ## 標題
        # 匹配如：**1.0 溫室氣體盤查**、**壹、公司治理**、**第一章 概述**
        text = re.sub(
            r"^\*\*\s*((?:[\d]+[\.\-][\d]*\s*|[壹貳參肆伍陸柒捌玖拾]、|[一二三四五六七八九十]+、|第[一二三四五六七八九十\d]+[章節篇])\s*.+?)\*\*\s*$",
            r"## \1",
            text,
            flags=re.MULTILINE,
        )
        # 修復 1b：獨立成行的純加粗短句（無編號但長度 < 40）→ 轉為 ### 標題
        text = re.sub(
            r"^\*\*([^*\n]{3,40})\*\*\s*$",
            r"### \1",
            text,
            flags=re.MULTILINE,
        )

        # 修復 2：##字 → ## 字（標題與文字之間補空格）
        text = re.sub(
            r"^(#{1,6})([^\s#])",
            r"\1 \2",
            text,
            flags=re.MULTILINE,
        )

        # 正規化多餘空行（最多保留一個空行）
        text = re.sub(r"\n{3,}", "\n\n", text)

        # 移除開頭 / 結尾的空白
        text = text.strip()

        return text

    def _remove_toc_sections(self, text: str) -> str:
        """
        移除以「目錄」為標題的整段區段。
        從「# 目錄」或「## 目錄」開始，到下一個同級或更高級標題結束。
        """
        lines = text.splitlines()
        result: list[str] = []
        in_toc = False
        toc_heading_level = 0

        for line in lines:
            stripped = line.strip()

            # 檢查是否是標題行
            heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)

            if heading_match:
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()

                if in_toc:
                    # 遇到同級或更高級的標題 → 結束目錄區段
                    if level <= toc_heading_level:
                        in_toc = False
                        result.append(line)
                    # 否則仍在目錄區段內，跳過
                    continue

                # 檢查是否是目錄標題
                if any(kw in title for kw in self._TOC_SECTION_KEYWORDS):
                    in_toc = True
                    toc_heading_level = level
                    continue

            if in_toc:
                continue

            result.append(line)

        return "\n".join(result)
