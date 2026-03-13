"""
modules/parser_url.py — 模組 2c：URL → Markdown
使用 requests + BeautifulSoup 擷取網頁主體內容。
"""
from __future__ import annotations

import re
import requests
from bs4 import BeautifulSoup, Tag


class UrlParser:
    """將網頁 URL 解析為 Markdown 格式字串。"""

    _HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}

    def parse(self, url: str) -> str:
        """下載網頁並提取可讀內容為 Markdown。"""
        result = self.parse_with_meta(url)
        return result["content"]

    def parse_with_meta(self, url: str) -> dict:
        """
        下載網頁並提取可讀內容、標題、語言。

        Returns
        -------
        dict
            - content: str (Markdown)
            - title: str (頁面標題)
            - language: str (語言代碼，如 "zh-TW", "en")
        """
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        try:
            resp = requests.get(url, timeout=30, headers={
                "User-Agent": "Mozilla/5.0 (compatible; RAGBot/1.0)"
            })
            resp.raise_for_status()
        except requests.exceptions.SSLError:
            print(f"[Warning] SSL 憑證驗證失敗，嘗試以 verify=False 繞過: {url}")
            resp = requests.get(url, timeout=30, verify=False, headers={
                "User-Agent": "Mozilla/5.0 (compatible; RAGBot/1.0)"
            })
            resp.raise_for_status()
            
        resp.encoding = resp.apparent_encoding

        soup = BeautifulSoup(resp.text, "html.parser")

        # 提取標題
        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        if not title:
            h1 = soup.find("h1")
            if h1:
                title = h1.get_text(strip=True)

        # 提取語言
        language = "zh-TW"
        html_tag = soup.find("html")
        if html_tag and html_tag.get("lang"):
            lang = html_tag["lang"].strip().lower()
            if lang.startswith("en"):
                language = "en"
            elif lang.startswith("ja"):
                language = "ja"
            elif lang.startswith("zh"):
                language = "zh-TW" if "tw" in lang or "hant" in lang else "zh-CN"
            else:
                language = lang

        # 移除不需要的元素
        for tag in soup.find_all(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
            tag.decompose()

        # 優先取 <article> 或 <main>，否則取 <body>
        main_content = soup.find("article") or soup.find("main") or soup.find("body")
        content = self._element_to_md(main_content) if main_content else ""

        return {
            "content": content,
            "title": title,
            "language": language,
        }

    # ── 遞迴轉換 ────────────────────────────────────
    def _element_to_md(self, element: Tag) -> str:
        parts: list[str] = []

        for child in element.children:
            if isinstance(child, str):
                text = child.strip()
                if text:
                    parts.append(text)
                continue

            if not isinstance(child, Tag):
                continue

            tag_name = child.name

            # 標題
            if tag_name in self._HEADING_TAGS:
                level = self._HEADING_TAGS[tag_name]
                text = child.get_text(strip=True)
                if text:
                    parts.append(f"\n{'#' * level} {text}\n")
                continue

            # 段落
            if tag_name == "p":
                text = child.get_text(strip=True)
                if text:
                    parts.append(text + "\n")
                continue

            # 列表
            if tag_name in ("ul", "ol"):
                parts.append(self._list_to_md(child, ordered=(tag_name == "ol")))
                continue

            # 表格
            if tag_name == "table":
                parts.append(self._table_to_md(child))
                continue

            # 粗體 / 斜體
            if tag_name in ("strong", "b"):
                parts.append(f"**{child.get_text(strip=True)}**")
                continue
            if tag_name in ("em", "i"):
                parts.append(f"*{child.get_text(strip=True)}*")
                continue

            # 連結
            if tag_name == "a":
                href = child.get("href", "")
                text = child.get_text(strip=True)
                if text and href:
                    parts.append(f"[{text}]({href})")
                elif text:
                    parts.append(text)
                continue

            # 其餘容器遞迴
            inner = self._element_to_md(child)
            if inner.strip():
                parts.append(inner)

        return "\n".join(parts)

    # ── 列表 ─────────────────────────────────────────
    @staticmethod
    def _list_to_md(element: Tag, ordered: bool = False) -> str:
        lines: list[str] = []
        for idx, li in enumerate(element.find_all("li", recursive=False), start=1):
            prefix = f"{idx}." if ordered else "-"
            lines.append(f"{prefix} {li.get_text(strip=True)}")
        return "\n".join(lines) + "\n"

    # ── 表格 ─────────────────────────────────────────
    @staticmethod
    def _table_to_md(element: Tag) -> str:
        rows: list[list[str]] = []
        for tr in element.find_all("tr"):
            cells = [
                (td.get_text(strip=True) or "")
                for td in tr.find_all(["th", "td"])
            ]
            if cells:
                rows.append(cells)

        if not rows:
            return ""

        col_count = max(len(r) for r in rows)
        for r in rows:
            while len(r) < col_count:
                r.append("")

        header = rows[0]
        sep = ["-" * max(len(h), 3) for h in header]
        lines = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join(sep) + " |",
        ]
        for r in rows[1:]:
            lines.append("| " + " | ".join(r) + " |")

        return "\n".join(lines) + "\n"
