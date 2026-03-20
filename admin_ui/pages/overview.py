"""
admin_ui/pages/overview.py — 系統概況頁面
"""
import streamlit as st
from admin_ui.utils.db import fetch_system_stats


def render(client):
    st.title("📊 系統概況")

    doc_count, chunk_count = fetch_system_stats(client)

    c1, c2, c3 = st.columns(3)
    c1.metric("總文件數", f"{doc_count} 份")
    c2.metric("知識庫段落 (Chunks)", f"{chunk_count} 段")
    c3.metric("向量模型", "Gemini 768d")

    st.divider()
    st.markdown("""
    ### 歡迎使用 RAG 知識庫管理系統
    這是一個通用的文件嵌入處理與檢索後台。您的文件上傳後，會經過以下自動化 Pipeline：
    1. **去重複檢查**：利用 SHA-256 / URL 避免重複入庫。
    2. **內文解析**：支援 PDF (`PyMuPDF` + `Gemini Vision`)、DOCX、網頁。
    3. **雜訊清洗**：自動過濾浮水印、頁碼、目錄等無效文字。
    4. **語義切割**：依據原文件的標題層級進行語義 Chunking。
    5. **向量嵌入**：呼叫 Gemini API 產生 768 維高維向量。
    6. **入庫與搜尋**：存入 Supabase pgvector，支援極速的 HNSW 近鄰檢索。
    """)
