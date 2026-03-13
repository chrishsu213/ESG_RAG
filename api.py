"""
api.py — FastAPI REST 服務

提供兩個端點：
  POST /ingest  — 處理本地檔案或 URL，執行完整 Pipeline（解析、清洗、切割、嵌入、入庫）
  POST /search  — 語義搜尋 RAG 知識庫

啟動方式：
  python api.py                             # 預設 0.0.0.0:8000
  uvicorn api:app --reload --port 8000      # 開發模式
"""
from __future__ import annotations

import os
import traceback
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from supabase import create_client

from config import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, GEMINI_API_KEY
from modules.retriever import SemanticRetriever

app = FastAPI(
    title="TCC RAG 知識庫 API",
    description="泛用型 RAG 文件處理與語義搜尋服務，供組內系統串接使用。",
    version="1.0.0",
)

# ── 啟動時建立共用連線 ─────────────────────────────────


def _get_supabase():
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("SUPABASE_URL 或 SUPABASE_SERVICE_ROLE_KEY 未設定")
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


# ── Request / Response Models ─────────────────────────


class IngestRequest(BaseModel):
    source: str = Field(..., description="本地檔案路徑 (PDF/DOCX) 或網頁 URL")
    do_embed: bool = Field(True, description="是否產生向量嵌入（預設 True）")


class IngestResponse(BaseModel):
    success: bool
    document_id: Optional[int] = None
    chunks_count: int = 0
    has_embeddings: bool = False
    message: str = ""


class SearchRequest(BaseModel):
    query: str = Field(..., description="自然語言查詢文字")
    top_k: int = Field(5, ge=1, le=50, description="回傳的最大結果數量")
    threshold: float = Field(0.5, ge=0.0, le=1.0, description="最低相似度門檻")


class SearchResult(BaseModel):
    id: int
    document_id: int
    chunk_index: int
    text_content: str
    metadata: dict = {}
    file_name: str = ""
    source_type: str = ""
    similarity: float = 0.0


class SearchResponse(BaseModel):
    query: str
    results_count: int
    results: list[SearchResult]


# ── Endpoints ─────────────────────────────────────────


@app.post("/ingest", response_model=IngestResponse, tags=["Ingestion"])
def ingest_document(req: IngestRequest):
    """
    處理一份文件（PDF / DOCX / URL），執行完整的 RAG Pipeline：
    解析 → 清洗 → 切割 → 嵌入 → 入庫。
    """
    try:
        # 延遲匯入避免啟動時間過長
        from modules.uploader import Uploader
        from modules.parser_pdf import PdfParser
        from modules.parser_docx import DocxParser
        from modules.parser_url import UrlParser
        from modules.cleaner import MarkdownCleaner
        from modules.chunker import SemanticChunker
        from modules.exporter import SupabaseExporter

        PARSERS = {"pdf": PdfParser, "docx": DocxParser, "url": UrlParser}

        client = _get_supabase()

        # 1) 去重
        uploader = Uploader(client)
        doc_info = uploader.process(req.source)
        if doc_info is None:
            return IngestResponse(
                success=False,
                message="文件已存在（重複）或來源無效，已跳過處理。",
            )

        # 2) 解析
        parser_cls = PARSERS.get(doc_info["source_type"])
        if parser_cls is None:
            raise HTTPException(
                status_code=400,
                detail=f"不支援的 source_type: {doc_info['source_type']}",
            )
        raw_md = parser_cls().parse(doc_info["source"])

        # 3) 清洗
        cleaned_md = MarkdownCleaner().clean(raw_md)

        # 4) 切割
        chunks = SemanticChunker().chunk(cleaned_md)

        # 5) 嵌入
        embeddings = None
        if req.do_embed and GEMINI_API_KEY:
            from modules.embedder import GeminiEmbedder

            embedder = GeminiEmbedder()
            texts = [c["text_content"] for c in chunks]
            embeddings = embedder.embed_batch(texts)

        # 6) 入庫（自動推斷分類）
        _fn = doc_info["file_name"].lower()
        if doc_info["source_type"] == "pdf":
            if "永續" in _fn or "sustain" in _fn:
                cat = "永續報告書"
            elif "年報" in _fn or "annual" in _fn:
                cat = "年度報告"
            else:
                cat = "其他"
        else:
            if "/esg/" in _fn or "esg" in _fn:
                cat = "ESG專區"
            elif "news" in _fn or "新聞" in _fn:
                cat = "新聞"
            elif "newsletter" in _fn or "電子報" in _fn:
                cat = "電子報"
            else:
                cat = "官網"

        exporter = SupabaseExporter(client)
        doc_id = exporter.insert_document(
            doc_info["file_name"], doc_info["file_hash"], doc_info["source_type"],
            category=cat, report_group=cat,
        )
        exporter.insert_chunks(doc_id, chunks, embeddings=embeddings)

        return IngestResponse(
            success=True,
            document_id=doc_id,
            chunks_count=len(chunks),
            has_embeddings=embeddings is not None,
            message=f"成功處理 {doc_info['file_name']}",
        )

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/search", response_model=SearchResponse, tags=["Search"])
def search_chunks(req: SearchRequest):
    """
    對 RAG 知識庫進行語義搜尋，回傳 Top-K 相似文件片段。
    """
    if not GEMINI_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="GEMINI_API_KEY 未設定，無法執行語義搜尋。",
        )

    try:
        client = _get_supabase()
        retriever = SemanticRetriever(client)
        results = retriever.search(
            query=req.query,
            top_k=req.top_k,
            threshold=req.threshold,
        )

        return SearchResponse(
            query=req.query,
            results_count=len(results),
            results=[SearchResult(**r) for r in results],
        )

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health", tags=["System"])
def health_check():
    """健康檢查端點。"""
    return {"status": "ok", "service": "TCC RAG API"}


# ── 啟動 ──────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("api:app", host="0.0.0.0", port=port, reload=True)
