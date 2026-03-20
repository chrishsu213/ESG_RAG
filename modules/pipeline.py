"""
modules/pipeline.py — 統一文件入庫 Pipeline

將「去重 → 解析 → 清洗 → 切割 → 嵌入 → 寫入 DB」封裝為單一服務，
消除 main.py, api.py, admin_ui/app.py, auto_crawl.py 中的重複邏輯。

使用方式：
    from modules.pipeline import DocumentIngestionPipeline

    pipeline = DocumentIngestionPipeline(supabase_client, gemini_api_key="...")
    # 傳統平行 chunks
    result = pipeline.ingest("path/to/file.pdf", category="永續報告書")
    # Parent-Child 模式
    result = pipeline.ingest("path/to/file.pdf", category="永續報告書", chunk_strategy="parent_child")
"""
from __future__ import annotations

import os
import logging
from typing import Optional, Callable

from supabase import Client

from modules.uploader import Uploader
from modules.parser_pdf import PdfParser
from modules.parser_docx import DocxParser
from modules.parser_url import UrlParser
from modules.cleaner import MarkdownCleaner
from modules.chunker import SemanticChunker
from modules.exporter import SupabaseExporter

logger = logging.getLogger(__name__)


class IngestionResult:
    """入庫結果。"""
    def __init__(
        self,
        success: bool,
        document_id: Optional[int] = None,
        chunks_count: int = 0,
        parent_count: int = 0,
        child_count: int = 0,
        has_embeddings: bool = False,
        display_name: str = "",
        message: str = "",
    ):
        self.success = success
        self.document_id = document_id
        self.chunks_count = chunks_count
        self.parent_count = parent_count
        self.child_count = child_count
        self.has_embeddings = has_embeddings
        self.display_name = display_name
        self.message = message


class DocumentIngestionPipeline:
    """
    統一的文件入庫 Pipeline。

    Parameters
    ----------
    supabase_client : Client
        Supabase 連線。
    gemini_api_key : str | None
        Gemini API Key（傳入時啟用向量嵌入）。
    on_progress : Callable | None
        進度回呼 (stage: str, detail: str)。
    """

    _PARSERS = {
        "pdf": PdfParser,
        "docx": DocxParser,
        "url": UrlParser,
    }

    def __init__(
        self,
        supabase_client: Client,
        gemini_api_key: Optional[str] = None,
        on_progress: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self._client = supabase_client
        self._api_key = gemini_api_key
        self._on_progress = on_progress

    def _progress(self, stage: str, detail: str = "") -> None:
        if self._on_progress:
            self._on_progress(stage, detail)
        logger.info(f"[{stage}] {detail}")

    def ingest(
        self,
        source: str,
        *,
        category: str = "其他",
        display_name: str = "",
        report_group: Optional[str] = None,
        language: Optional[str] = None,
        do_embed: bool = True,
        page_offset: int = 0,
        chunk_strategy: str = "flat",  # 'flat' 或 'parent_child'
    ) -> IngestionResult:
        """
        執行完整的入庫 Pipeline。

        Parameters
        ----------
        source : str
            檔案路徑或 URL。
        category : str
            文件分類。
        display_name : str
            顯示名稱（留空自動推斷）。
        report_group : str | None
            所屬報告群組。
        language : str | None
            語言標記。
        do_embed : bool
            是否產生向量嵌入。
        page_offset : int
            PDF 頁碼偏移。

        Returns
        -------
        IngestionResult
        """
        # 1) 去重
        self._progress("upload", "去重複檢查中...")
        uploader = Uploader(self._client)
        doc_info = uploader.process(source)
        if doc_info is None:
            return IngestionResult(
                success=False,
                message="文件已存在（重複）或來源無效。",
            )

        file_name = doc_info["file_name"]
        source_type = doc_info["source_type"]
        actual_source = doc_info["source"]

        # 2) 解析
        self._progress("parse", f"解析中 ({source_type})...")
        parser_cls = self._PARSERS.get(source_type)
        if parser_cls is None:
            return IngestionResult(
                success=False,
                message=f"不支援的格式：{source_type}",
            )

        raw_md = parser_cls().parse(actual_source)

        # 3) 清洗
        self._progress("clean", "清洗中...")
        cleaned_md = MarkdownCleaner().clean(raw_md)

        # 4) 切割
        self._progress("chunk", "語義切割中...")
        chunker = SemanticChunker()

        # 6) 寫入 DB
        self._progress("export", "寫入資料庫中...")
        final_name = display_name.strip() if display_name.strip() else file_name
        exporter = SupabaseExporter(self._client)

        if chunk_strategy == "parent_child":
            # ── Parent-Child 模式 ──────────────────────────
            parent_child_list = chunker.chunk_parent_child(cleaned_md)

            if not parent_child_list:
                return IngestionResult(
                    success=False,
                    message="清洗後無有效內容。",
                )

            # 套用頁碼偏移
            if page_offset > 0:
                for item in parent_child_list:
                    for chunk in [item["parent"]] + item["children"]:
                        meta = chunk.get("metadata", {})
                        if meta.get("page_start") is not None:
                            meta["page_start"] += page_offset
                        if meta.get("page_end") is not None:
                            meta["page_end"] += page_offset

            # 收集 embed 目標（children + standalone）
            embed_targets: list[tuple[int, str]] = []
            for item in parent_child_list:
                if item["children"]:
                    for child in item["children"]:
                        embed_targets.append((child["chunk_index"], child["text_content"]))
                else:
                    p = item["parent"]
                    embed_targets.append((p["chunk_index"], p["text_content"]))

            child_embeddings_map: dict[int, list[float]] = {}
            if do_embed and self._api_key and embed_targets:
                self._progress("embed", f"向量嵌入中（{len(embed_targets)} 個 children）...")
                from modules.embedder import GeminiEmbedder
                embedder = GeminiEmbedder(api_key=self._api_key)
                texts = [t for _, t in embed_targets]
                vecs = embedder.embed_batch(texts)
                for (idx, _), vec in zip(embed_targets, vecs):
                    child_embeddings_map[idx] = vec

            doc_id = exporter.insert_document(
                file_name,
                doc_info["file_hash"],
                source_type,
                category=category,
                display_name=final_name,
                report_group=report_group if report_group else None,
            )
            p_cnt, c_cnt = exporter.insert_parent_child_chunks(
                doc_id, parent_child_list, child_embeddings_map
            )

            if language:
                try:
                    self._client.table("documents").update(
                        {"language": language}
                    ).eq("id", doc_id).execute()
                except Exception:
                    pass

            self._progress("done", f"完成！{final_name} ({p_cnt} parents, {c_cnt} children)")
            return IngestionResult(
                success=True,
                document_id=doc_id,
                chunks_count=p_cnt + c_cnt,
                parent_count=p_cnt,
                child_count=c_cnt,
                has_embeddings=bool(child_embeddings_map),
                display_name=final_name,
                message=f"{p_cnt} parents, {c_cnt} children | 📄 {final_name}",
            )

        else:
            # ── 傳統平行 chunks 模式 ───────────────────────
            chunks = chunker.chunk(cleaned_md)

            if not chunks:
                return IngestionResult(
                    success=False,
                    message="清洗後無有效內容。",
                )

            # 套用頁碼偏移
            if page_offset > 0:
                for c in chunks:
                    meta = c.get("metadata", {})
                    if meta.get("page_start") is not None:
                        meta["page_start"] += page_offset
                    if meta.get("page_end") is not None:
                        meta["page_end"] += page_offset

            # 5) 嵌入
            embeddings = None
            if do_embed and self._api_key:
                self._progress("embed", f"向量嵌入中 ({len(chunks)} 段)...")
                from modules.embedder import GeminiEmbedder
                embedder = GeminiEmbedder(api_key=self._api_key)
                texts = [c["text_content"] for c in chunks]
                embeddings = embedder.embed_batch(texts)

            doc_id = exporter.insert_document(
                file_name,
                doc_info["file_hash"],
                source_type,
                category=category,
                display_name=final_name,
                report_group=report_group if report_group else None,
            )
            exporter.insert_chunks(doc_id, chunks, embeddings=embeddings)

            if language:
                try:
                    self._client.table("documents").update(
                        {"language": language}
                    ).eq("id", doc_id).execute()
                except Exception:
                    pass

            self._progress("done", f"完成！{final_name} ({len(chunks)} 段)")
            return IngestionResult(
                success=True,
                document_id=doc_id,
                chunks_count=len(chunks),
                has_embeddings=embeddings is not None,
                display_name=final_name,
                message=f"{len(chunks)} 段 | 📄 {final_name}",
            )

    @staticmethod
    def guess_category(file_name: str, source_type: str) -> str:
        """根據檔名自動推斷分類。"""
        fn = file_name.lower()
        if source_type == "pdf":
            if "永續" in fn or "sustain" in fn:
                return "永續報告書"
            elif "年報" in fn or "annual" in fn:
                return "年度報告"
            else:
                return "其他"
        else:
            if "/esg/" in fn or "esg" in fn:
                return "ESG專區"
            elif "news" in fn or "新聞" in fn:
                return "新聞"
            elif "newsletter" in fn or "電子報" in fn:
                return "電子報"
            else:
                return "官網"
