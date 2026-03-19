"""
modules/parser_url.py — 模組 2c：URL → Markdown
使用 requests + BeautifulSoup + markdownify 擷取網頁主體內容。
表格、列表、標題、粗體均正確轉換為 Markdown 格式。
"""
from __future__ import annotations

import re
import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md_convert


class UrlParser:
    """將網頁 URL 解析為 Markdown 格式字串。"""

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
            - content: str (Markdown，表格保留為 Markdown 格式)
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

        # 移除不需要的元素（導覽、頁尾、廣告等）
        for tag in soup.find_all(["script", "style", "nav", "footer",
                                  "header", "aside", "noscript"]):
            tag.decompose()

        # 優先取 <article> 或 <main>，否則取 <body>
        main_content = soup.find("article") or soup.find("main") or soup.find("body")
        if not main_content:
            return {"content": "", "title": title, "language": language}

        # 用 markdownify 轉換
        # - heading_style="ATX" → # 標題格式
        # - bullets="-" → 列表用 -
        # - strip=["img","svg"] → 略過圖片（不影響表格）
        content = md_convert(
            str(main_content),
            heading_style="ATX",
            bullets="-",
            strip=["img", "svg"],
        )

        # 清理多餘空行（超過 2 個連續換行 → 2 個）
        content = re.sub(r"\n{3,}", "\n\n", content).strip()

        return {
            "content": content,
            "title": title,
            "language": language,
        }
