"""
api/server.py — FastAPI 服務
提供 RESTful API 供其他系統（如 IR 平台）串接 RAG 知識庫。

啟動方式：
    uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload

端點：
    POST /api/search  — 搜尋知識庫（回傳相關段落）
    POST /api/ask     — RAG 問答（AI 生成答案 + 引用出處）
    GET  /api/health  — 健康檢查
    GET  /api/stats   — 知識庫統計
"""
from __future__ import annotations

import functools
import os
import sys
from contextlib import asynccontextmanager
import logging
from typing import Optional

from fastapi import FastAPI, HTTPException, Security, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

# 確保上層模組可 import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, GEMINI_API_KEY
from supabase import create_client
from modules.retriever import SemanticRetriever
from modules.rag_chat import RagChat


logger = logging.getLogger(__name__)

# ── Supabase Client（Singleton）────────────────────────
@functools.lru_cache(maxsize=1)
def get_supabase():
    """全域共用單一 Supabase 連線，避免每次請求重建 HTTP Session。"""
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


# ── API Key 驗證（Fail-Closed）────────────────────────
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
# 從環境變數取得允許的 API key 列表（逗號分隔）
ALLOWED_API_KEYS = set(
    k.strip()
    for k in os.getenv("RAG_API_KEYS", "").split(",")
    if k.strip()
)
_IS_PRODUCTION = os.getenv("ENV", "").lower() == "production"


def verify_api_key(api_key: str = Security(API_KEY_HEADER)):
    """驗證 API Key。
    - 生產環境（ENV=production）：未設定 RAG_API_KEYS 時拒絕所有請求（Fail-Closed）。
    - 開發環境：未設定 RAG_API_KEYS 時放行（方便本地測試）。
    """
    if not ALLOWED_API_KEYS:
        if _IS_PRODUCTION:
            logger.error("生產環境未設定 RAG_API_KEYS，拒絕所有 API 請求")
            raise HTTPException(status_code=503, detail="API 尚未設定驗證金鑰，請聯繫管理員")
        return  # 開發模式 → 不驗證
    if not api_key or api_key not in ALLOWED_API_KEYS:
        raise HTTPException(status_code=403, detail="無效的 API Key")


# ── Pydantic Models ──────────────────────────────────
class SearchRequest(BaseModel):
    query: str = Field(..., description="搜尋關鍵字或自然語言問題")
    top_k: int = Field(5, ge=1, le=20, description="回傳結果數量")
    threshold: float = Field(0.3, ge=0, le=1, description="最低相似度門檻")
    use_hybrid: bool = Field(True, description="是否使用混合搜尋")
    language: Optional[str] = Field(None, description="限制搜尋語言（如 'en'、'zh-TW'），Null 則不限")
    fiscal_year: Optional[str] = Field(None, description="限制會計年度（如 '2024'），Null 則不限")


class AskRequest(BaseModel):
    question: str = Field(..., description="使用者問題")
    top_k: int = Field(5, ge=1, le=15, description="參考段落數量")
    search_mode: str = Field(
        "hybrid",
        description="搜尋模式：'hybrid' 或 'hybrid_rerank'"
    )
    language: Optional[str] = Field(None, description="限制搜尋語言（如 'en'），Null 則不限")
    fiscal_year: Optional[str] = Field(None, description="限制會計年度（如 '2024'），Null 則不限")
    history: Optional[list[dict]] = Field(
        None,
        description="對話歷史，格式 [{role: 'user'|'assistant', content: '...'}]"
    )


class SearchResult(BaseModel):
    text_content: str
    file_name: str
    source_type: str
    display_name: Optional[str] = None
    report_group: Optional[str] = None
    section_title: Optional[str] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    similarity: float
    search_type: Optional[str] = None
    # ── 文件元資料 ──
    category: Optional[str] = None
    language: Optional[str] = None
    fiscal_year: Optional[str] = None
    status: Optional[str] = None
    confidentiality: Optional[str] = None
    tags: Optional[list] = None
    publish_date: Optional[str] = None


class SearchResponse(BaseModel):
    results: list[SearchResult]
    count: int


class AskResponse(BaseModel):
    answer: str
    sources: list[dict]
    search_results_count: int


class StatsResponse(BaseModel):
    total_documents: int
    total_chunks: int
    categories: dict
    source_types: dict


# ── FastAPI App ──────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """啟動時檢查必要設定。"""
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 未設定")
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY 未設定")
    yield


app = FastAPI(
    title="TCC RAG Knowledge Base API",
    description="ESG/IR 知識庫搜尋與問答 API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS（允許 IR 平台等前端呼叫）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 正式環境應限制為特定 domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 端點 ─────────────────────────────────────────────
@app.get("/api/health")
async def health_check():
    """健康檢查。"""
    return {"status": "ok", "service": "rag-api"}


@app.get("/api/stats", response_model=StatsResponse)
def get_stats(_=Depends(verify_api_key)):
    """取得知識庫統計資訊。"""
    client = get_supabase()
    try:
        docs = client.table("documents").select("id, category, source_type").execute()
        chunks = client.table("document_chunks").select("id", count="exact").execute()

        categories = {}
        source_types = {}
        for d in docs.data or []:
            cat = d.get("category", "未分類")
            categories[cat] = categories.get(cat, 0) + 1
            st = d.get("source_type", "unknown")
            source_types[st] = source_types.get(st, 0) + 1

        return StatsResponse(
            total_documents=len(docs.data or []),
            total_chunks=chunks.count or 0,
            categories=categories,
            source_types=source_types,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/search", response_model=SearchResponse)
def search(req: SearchRequest, _=Depends(verify_api_key)):
    """搜尋知識庫，回傳相關段落。"""
    client = get_supabase()
    retriever = SemanticRetriever(client)

    try:
        if req.use_hybrid:
            results = retriever.hybrid_search(
                req.query, top_k=req.top_k, threshold=req.threshold,
                language=req.language, fiscal_year=req.fiscal_year,
            )
        else:
            results = retriever.search(
                req.query, top_k=req.top_k, threshold=req.threshold,
                language=req.language, fiscal_year=req.fiscal_year,
            )

        items = []
        for r in results:
            meta = r.get("metadata") or {}
            items.append(SearchResult(
                text_content=r["text_content"],
                file_name=r.get("file_name", ""),
                source_type=r.get("source_type", ""),
                display_name=r.get("display_name"),
                report_group=r.get("report_group"),
                section_title=meta.get("section_title"),
                page_start=meta.get("page_start"),
                page_end=meta.get("page_end"),
                similarity=r.get("similarity", 0),
                search_type=r.get("search_type"),
                category=r.get("category"),
                language=r.get("language"),
                fiscal_year=r.get("fiscal_year"),
                status=r.get("status"),
                confidentiality=r.get("confidentiality"),
                tags=r.get("tags"),
                publish_date=str(r["publish_date"]) if r.get("publish_date") else None,
            ))

        return SearchResponse(results=items, count=len(items))

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ask", response_model=AskResponse)
def ask(req: AskRequest, _=Depends(verify_api_key)):
    """RAG 問答：搜尋知識庫 + AI 生成答案 + 引用出處。"""
    client = get_supabase()
    rag = RagChat(client)

    try:
        result = rag.ask(
            question=req.question,
            history=req.history,
            search_mode=req.search_mode,
            top_k=req.top_k,
            language=req.language,
            fiscal_year=req.fiscal_year,
            source="api",
        )
        return AskResponse(
            answer=result["answer"],
            sources=result["sources"],
            search_results_count=len(result["search_results"]),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ask/stream")
def ask_stream(req: AskRequest, _=Depends(verify_api_key)):
    """RAG 問答串流版：以 Server-Sent Events (SSE) 逐 token 回傳。

    事件格式：
      data: {"event": "sources", "sources": [...], "count": N}
      data: {"event": "token", "text": "..."}
      data: {"event": "done"}
    """
    import json as _json
    from fastapi.responses import StreamingResponse

    client = get_supabase()
    rag = RagChat(client)

    def event_generator():
        try:
            result = rag.ask_stream(
                question=req.question,
                history=req.history,
                search_mode=req.search_mode,
                top_k=req.top_k,
                language=req.language,
                fiscal_year=req.fiscal_year,
                source="api_stream",
            )

            # 先送出 sources 資訊
            sources_event = _json.dumps({
                "event": "sources",
                "sources": result["sources"],
                "count": len(result["search_results"]),
            }, ensure_ascii=False)
            yield f"data: {sources_event}\n\n"

            # 逐 token 串流
            for text_chunk in result["stream"]:
                token_event = _json.dumps({
                    "event": "token",
                    "text": text_chunk,
                }, ensure_ascii=False)
                yield f"data: {token_event}\n\n"

            # 結束信號
            yield f"data: {_json.dumps({'event': 'done'})}\n\n"

        except Exception as e:
            error_event = _json.dumps({
                "event": "error",
                "detail": str(e),
            }, ensure_ascii=False)
            yield f"data: {error_event}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
