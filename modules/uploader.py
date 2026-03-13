"""
modules/uploader.py — 模組 1：Uploader & Deduplicator
負責計算檔案 Hash、查詢 Supabase 判斷是否重複。
"""
from __future__ import annotations

import hashlib
import os
from typing import Optional

from supabase import Client


class Uploader:
    """接收本地檔案路徑或網頁 URL，執行去重判斷。"""

    def __init__(self, supabase_client: Client) -> None:
        self._client = supabase_client

    # ── 特徵萃取 ─────────────────────────────────────
    @staticmethod
    def compute_file_hash(file_path: str) -> str:
        """讀取檔案二進位內容，回傳 SHA-256 hex digest。"""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                sha256.update(chunk)
        return sha256.hexdigest()

    @staticmethod
    def compute_url_hash(url: str) -> str:
        """將 URL 字串做 SHA-256，作為唯一鍵值。"""
        return hashlib.sha256(url.encode("utf-8")).hexdigest()

    # ── 狀態檢查 ─────────────────────────────────────
    def is_duplicate(self, file_hash: str) -> bool:
        """透過 Supabase 查詢 documents 表，比對 file_hash。"""
        result = (
            self._client.table("documents")
            .select("id")
            .eq("file_hash", file_hash)
            .execute()
        )
        return len(result.data) > 0

    # ── 主流程 ───────────────────────────────────────
    def process(self, source: str) -> Optional[dict]:
        """
        組合 hash 計算 + 重複檢查。

        Parameters
        ----------
        source : str
            本地檔案路徑 或 網頁 URL。

        Returns
        -------
        dict | None
            若不重複，回傳 {"file_name", "file_hash", "source_type"}；
            若重複則回傳 None。
        """
        is_url = source.startswith("http://") or source.startswith("https://")

        if is_url:
            file_hash = self.compute_url_hash(source)
            file_name = source
            source_type = "url"
        else:
            if not os.path.isfile(source):
                print(f"[ERROR] 檔案不存在：{source}")
                return None
            file_hash = self.compute_file_hash(source)
            file_name = os.path.basename(source)
            ext = os.path.splitext(source)[1].lower()
            source_type_map = {".pdf": "pdf", ".docx": "docx", ".doc": "docx"}
            source_type = source_type_map.get(ext)
            if source_type is None:
                print(f"[ERROR] 不支援的檔案格式：{ext}")
                return None

        # 重複檢查
        if self.is_duplicate(file_hash):
            print(f"[SKIP] 文件已存在，跳過處理：{file_name}")
            return None

        print(f"[OK] 新文件，進入處理流程：{file_name}  (hash={file_hash[:12]}…)")
        return {
            "file_name": file_name,
            "file_hash": file_hash,
            "source_type": source_type,
            "source": source,
        }
