"""
modules/exporter.py — 模組 4：Supabase Exporter
將文件主記錄與切割後的 chunks（含 embedding）寫入 Supabase。
"""
from __future__ import annotations

import json
from typing import Any, Optional

from supabase import Client


class SupabaseExporter:
    """負責將處理結果寫入 Supabase 的 documents 與 document_chunks 表。"""

    def __init__(self, supabase_client: Client) -> None:
        self._client = supabase_client

    def insert_document(
        self,
        file_name: str,
        file_hash: str,
        source_type: str,
        category: str = "其他",
        display_name: Optional[str] = None,
        report_group: Optional[str] = None,
    ) -> int:
        """
        寫入 documents 主表，回傳新建記錄的主鍵 id。

        Parameters
        ----------
        file_name : str
            檔案名稱（或 URL）。
        file_hash : str
            SHA-256 hash（或 URL hash）。
        source_type : str
            'pdf' | 'docx' | 'url'
        category : str
            文件分類：網站 | 報告書 | 政策 | 財務報告 | 其他
        display_name : str | None
            使用者自訂的顯示名稱，若為 None 則使用 file_name。
        report_group : str | None
            報告群組名稱，用於歸類同一份報告的多個章節。

        Returns
        -------
        int
            新建的 document id。
        """
        record = {
            "file_name": file_name,
            "file_hash": file_hash,
            "source_type": source_type,
            "category": category,
            "display_name": display_name or file_name,
        }
        if report_group:
            record["report_group"] = report_group
        result = (
            self._client.table("documents")
            .insert(record)
            .execute()
        )

        doc_id: int = result.data[0]["id"]
        print(f"[DB] 已寫入 documents 表，id={doc_id}")
        return doc_id

    def insert_chunks(
        self,
        document_id: int,
        chunks: list[dict[str, Any]],
        embeddings: Optional[list[list[float]]] = None,
    ) -> int:
        """
        批次寫入 document_chunks 子表。

        Parameters
        ----------
        document_id : int
            對應 documents 表的主鍵。
        chunks : list[dict]
            由 SemanticChunker 產出的 chunk 列表，每個含
            chunk_index, text_content, metadata。
        embeddings : list[list[float]] | None
            對應每個 chunk 的向量嵌入。若為 None 則不寫入 embedding 欄位。

        Returns
        -------
        int
            寫入的 chunk 數量。
        """
        rows = []
        for i, c in enumerate(chunks):
            row = {
                "document_id": document_id,
                "chunk_index": c["chunk_index"],
                "text_content": c["text_content"],
                "metadata": json.loads(
                    json.dumps(c.get("metadata", {}), ensure_ascii=False)
                ),
            }
            # 附加 embedding（若有提供）
            if embeddings is not None and i < len(embeddings):
                row["embedding"] = embeddings[i]
            rows.append(row)

        # 批次寫入（Supabase 支援單次多列 insert）
        result = (
            self._client.table("document_chunks")
            .insert(rows)
            .execute()
        )

        count = len(result.data)
        print(f"[DB] 已寫入 document_chunks 表，共 {count} 筆 chunks")
        return count
