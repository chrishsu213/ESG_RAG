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
        group: Optional[str] = None,
        company: Optional[str] = None,
        fiscal_period: str = "Annual",
        fiscal_year: Optional[str] = None,
        language: Optional[str] = None,
        publish_date: Optional[str] = None,
    ) -> int:
        """
        寫入 documents 主表，回傳新建記錄的主鍵 id。

        Parameters
        ----------
        fiscal_year   : 年度（如 "2024"）
        language      : 語言（如 "zh-TW"）
        publish_date  : 發布日期（新聞稿/電子報用，格式 "YYYY-MM-DD"）
        """
        record = {
            "file_name": file_name,
            "file_hash": file_hash,
            "source_type": source_type,
            "category": category,
            "display_name": display_name or (file_name.rsplit(".", 1)[0] if "." in file_name else file_name),
            "fiscal_period": fiscal_period,
        }
        if report_group:
            record["report_group"] = report_group
        if group:
            record["group"] = group
        if company:
            record["company"] = company
        if fiscal_year:
            record["fiscal_year"] = fiscal_year
        if language:
            record["language"] = language
        if publish_date:
            record["publish_date"] = publish_date
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

    def insert_parent_child_chunks(
        self,
        document_id: int,
        parent_child_list: list[dict],
        child_embeddings_map: dict[int, list[float]],
    ) -> tuple[int, int]:
        """
        寫入 Parent-Child 結構的 chunks。

        Parameters
        ----------
        document_id : int
        parent_child_list : list[dict]
            由 SemanticChunker.chunk_parent_child() 產出。
            每個元素 = {"parent": {...}, "children": [{...}, ...]}
        child_embeddings_map : dict[int, list[float]]
            key = child 的 chunk_index，value = embedding 向量。

        Returns
        -------
        (parent_count, child_count)
        """
        total_parents = 0
        total_children = 0

        for item in parent_child_list:
            parent = item["parent"]
            children = item["children"]

            if not children:
                # 沒有 child → 當作 standalone 寫入（有 embedding）
                emb = child_embeddings_map.get(parent["chunk_index"])
                row = {
                    "document_id": document_id,
                    "chunk_index": parent["chunk_index"],
                    "text_content": parent["text_content"],
                    "metadata": json.loads(json.dumps(parent.get("metadata", {}), ensure_ascii=False)),
                    "chunk_type": "standalone",
                }
                if emb:
                    row["embedding"] = emb
                self._client.table("document_chunks").insert(row).execute()
                total_parents += 1
                continue

            # 寫入 Parent（無 embedding）
            parent_row = {
                "document_id": document_id,
                "chunk_index": parent["chunk_index"],
                "text_content": parent["text_content"],
                "metadata": json.loads(json.dumps(parent.get("metadata", {}), ensure_ascii=False)),
                "chunk_type": "parent",
            }
            parent_result = self._client.table("document_chunks").insert(parent_row).execute()
            parent_id = parent_result.data[0]["id"]
            total_parents += 1

            # 寫入 Children（有 embedding，指向 parent）
            child_rows = []
            for child in children:
                emb = child_embeddings_map.get(child["chunk_index"])
                child_row = {
                    "document_id": document_id,
                    "chunk_index": child["chunk_index"],
                    "text_content": child["text_content"],
                    "metadata": json.loads(json.dumps(child.get("metadata", {}), ensure_ascii=False)),
                    "chunk_type": "child",
                    "parent_chunk_id": parent_id,
                }
                if emb:
                    child_row["embedding"] = emb
                child_rows.append(child_row)

            if child_rows:
                self._client.table("document_chunks").insert(child_rows).execute()
                total_children += len(child_rows)

        print(f"[DB] Parent-Child 入庫完成：{total_parents} parents, {total_children} children")
        return total_parents, total_children
