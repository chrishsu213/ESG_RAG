"""
admin_ui/utils/db.py
共用 DB helper 函式 (stateless, client 由呼叫者傳入)。
每個 page.render(client) 使用這些函式存取 Supabase。

Cache 策略：
  fetch_documents 使用 Streamlit @st.cache_data(ttl=10)。
  實作方式：在 app.py 初始化時呼叫 set_client(client) 注入，
  讓 cache decorator 可在無參數的情況下運作。
"""
import streamlit as st

# ── Module-level client singleton（由 app.py 啟動時注入）──
_client = None


def set_client(client) -> None:
    """在 app.py 啟動時呼叫一次，供 @st.cache_data 函式使用。"""
    global _client
    _client = client


# ── Cached queries ─────────────────────────────────────────

@st.cache_data(ttl=10)
def fetch_documents():
    """從 documents 表取得所有文件（快取 10 秒）。"""
    res = (
        _client.table("documents")
        .select(
            "id, file_name, file_hash, source_type, category, display_name,"
            " report_group, \"group\", company, language, status, confidentiality,"
            " fiscal_year, fiscal_period, tags, created_at"
        )
        .order("created_at", desc=True)
        .execute()
    )
    return res.data


# ── Non-cached helpers ──────────────────────────────────────

def delete_document(client, doc_id: int, file_name: str) -> None:
    client.table("documents").delete().eq("id", doc_id).execute()
    fetch_documents.clear()
    st.toast(f"✅ 已刪除文件：{file_name}")


def fetch_chunks_for_document(client, doc_id: int) -> list:
    res = (
        client.table("document_chunks")
        .select("id, chunk_index, text_content, metadata, chunk_type, parent_chunk_id")
        .eq("document_id", doc_id)
        .order("chunk_index")
        .execute()
    )
    return res.data


def fetch_system_stats(client) -> tuple[int, int]:
    doc_res   = client.table("documents").select("id", count="exact").execute()
    chunk_res = client.table("document_chunks").select("id", count="exact").execute()
    return doc_res.count, chunk_res.count
