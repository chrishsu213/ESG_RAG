"""
modules/crawler.py — 全站遞迴爬蟲
從根 URL 出發，自動追蹤同域名內部連結，回傳所有發現的頁面 URL。
"""
from __future__ import annotations

import re
from typing import Callable, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


class SiteCrawler:
    """
    遞迴爬蟲：從一個根 URL 開始，追蹤所有同域名連結。

    Parameters
    ----------
    root_url : str
        起始 URL（例如 https://www.tccgroupholdings.com/）。
    max_pages : int
        最大抓取頁數上限（防止無限爬）。
    max_depth : int
        連結追蹤的最大深度。
    exclude_patterns : list[str]
        要排除的 URL 路徑模式（正則表達式）。
    on_progress : Callable | None
        進度回呼函式，接收 (已發現數, 已處理數, 當前URL) 參數。
    """

    _SKIP_EXTENSIONS = {
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".zip", ".rar", ".gz", ".tar",
        ".jpg", ".jpeg", ".png", ".gif", ".svg", ".ico", ".webp",
        ".mp3", ".mp4", ".avi", ".mov", ".wmv",
        ".css", ".js", ".xml", ".json", ".rss", ".atom",
    }

    def __init__(
        self,
        root_url: str,
        max_pages: int = 200,
        max_depth: int = 5,
        exclude_patterns: Optional[list[str]] = None,
        on_progress: Optional[Callable] = None,
    ) -> None:
        parsed = urlparse(root_url)
        self._root = root_url.rstrip("/")
        self._domain = parsed.netloc
        self._scheme = parsed.scheme
        self._max_pages = max_pages
        self._max_depth = max_depth
        self._exclude_re = [re.compile(p) for p in (exclude_patterns or [])]
        self._on_progress = on_progress

        self._visited: set[str] = set()
        self._discovered: list[str] = []

    def crawl(self) -> list[str]:
        """
        執行爬蟲，回傳所有發現的 URL 列表。

        Returns
        -------
        list[str]
            去重後的頁面 URL 列表。
        """
        self._bfs(self._root, depth=0)
        return self._discovered

    def _normalize_url(self, url: str) -> str:
        """正規化 URL：移除 fragment、trailing slash，統一 scheme。"""
        parsed = urlparse(url)
        # 移除 fragment (#)
        path = parsed.path.rstrip("/") or "/"
        normalized = f"{self._scheme}://{parsed.netloc}{path}"
        if parsed.query:
            normalized += f"?{parsed.query}"
        return normalized

    def _should_skip(self, url: str) -> bool:
        """判斷是否應該跳過此 URL。"""
        parsed = urlparse(url)

        # 不同域名
        if parsed.netloc != self._domain:
            return True

        # 跳過特定副檔名
        path_lower = parsed.path.lower()
        for ext in self._SKIP_EXTENSIONS:
            if path_lower.endswith(ext):
                return True

        # 排除模式
        for pattern in self._exclude_re:
            if pattern.search(url):
                return True

        return False

    def _bfs(self, start_url: str, depth: int) -> None:
        """廣度優先搜尋式爬取。"""
        from collections import deque
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        queue: deque[tuple[str, int]] = deque()
        queue.append((self._normalize_url(start_url), 0))

        while queue and len(self._discovered) < self._max_pages:
            url, current_depth = queue.popleft()

            if url in self._visited:
                continue
            if current_depth > self._max_depth:
                continue
            if self._should_skip(url):
                continue

            self._visited.add(url)

            # 回報進度
            if self._on_progress:
                self._on_progress(
                    len(self._discovered),
                    len(self._visited),
                    url,
                )

            # 抓取頁面
            try:
                try:
                    resp = requests.get(url, timeout=15, headers={
                        "User-Agent": "Mozilla/5.0 (compatible; RAGBot/1.0)"
                    })
                except requests.exceptions.SSLError:
                    resp = requests.get(url, timeout=15, verify=False, headers={
                        "User-Agent": "Mozilla/5.0 (compatible; RAGBot/1.0)"
                    })

                if resp.status_code != 200:
                    continue

                content_type = resp.headers.get("Content-Type", "")
                if "text/html" not in content_type:
                    continue

            except Exception:
                continue

            # 成功抓到 HTML 頁面
            self._discovered.append(url)

            # 解析連結
            if current_depth < self._max_depth:
                resp.encoding = resp.apparent_encoding
                soup = BeautifulSoup(resp.text, "html.parser")

                for a_tag in soup.find_all("a", href=True):
                    href = a_tag["href"]

                    # 跳過 javascript:, mailto:, tel: 等
                    if href.startswith(("javascript:", "mailto:", "tel:", "#")):
                        continue

                    # 轉換為絕對 URL
                    abs_url = urljoin(url, href)
                    normalized = self._normalize_url(abs_url)

                    if normalized not in self._visited and not self._should_skip(normalized):
                        queue.append((normalized, current_depth + 1))
