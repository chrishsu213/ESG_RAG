"""
admin_ui/pages/search.py — 檢索測試頁面
"""
import streamlit as st
from modules.retriever import SemanticRetriever


def render(client):
    st.title("🔍 檢索測試 (Semantic Search)")

    with st.form("search_form"):
        query = st.text_input("輸入查詢問題", placeholder="例如：公司碳排放目標是什麼？")
        c1, c2 = st.columns(2)
        top_k     = c1.slider("回傳筆數 (Top K)", 1, 20, 5)
        threshold = c2.slider("相似度門檻", 0.0, 1.0, 0.5, step=0.05)
        submitted = st.form_submit_button("開始搜尋", type="primary")

    if submitted and query:
        with st.spinner("搜尋中..."):
            retriever = SemanticRetriever(client)
            try:
                results = retriever.search(query, top_k=top_k, threshold=threshold)
            except Exception as e:
                st.error(f"搜尋失敗：{type(e).__name__}: {e}")
                results = []

        if not results:
            st.warning("找不到符合門檻的結果，請降低 Threshold。")
        else:
            st.success(f"找到 {len(results)} 筆結果：")
            for i, res in enumerate(results, 1):
                sim      = res["similarity"]
                fname    = res["file_name"]
                stype    = res["source_type"]
                metadata = res["metadata"]
                title    = metadata.get("section_title", "無章節")
                text     = res["text_content"]
                doc_id   = res["document_id"]
                chunk_idx = res["chunk_index"]

                ps = metadata.get("page_start")
                pe = metadata.get("page_end")
                page_info = f" | 📄 第{ps}{f'-{pe}' if pe and pe != ps else ''}頁" if ps else ""

                with st.expander(f"[{i}] 相似度 {sim:.4f} | 📄 {fname} | 🔖 {title}{page_info}", expanded=(i == 1)):
                    st.caption(f"來源：{stype} · Chunk #{chunk_idx} · Doc ID: {doc_id}")
                    st.markdown("---")
                    st.markdown(text)

                    if st.button("📖 顯示上下文", key=f"ctx_{i}"):
                        context_chunks = (
                            client.table("document_chunks")
                            .select("chunk_index, text_content, metadata")
                            .eq("document_id", doc_id)
                            .gte("chunk_index", max(0, chunk_idx - 1))
                            .lte("chunk_index", chunk_idx + 1)
                            .order("chunk_index")
                            .execute()
                        ).data

                        for cc in context_chunks:
                            ci = cc["chunk_index"]
                            ct = cc["text_content"]
                            cm = cc.get("metadata") or {}
                            ct_title = cm.get("section_title", "")
                            if ci == chunk_idx:
                                st.markdown(f"**▶ Chunk #{ci}（當前結果）** {ct_title}")
                                st.info(ct)
                            elif ci < chunk_idx:
                                st.markdown(f"**⬆ Chunk #{ci}（前一段）** {ct_title}")
                                st.markdown(ct)
                            else:
                                st.markdown(f"**⬇ Chunk #{ci}（後一段）** {ct_title}")
                                st.markdown(ct)
