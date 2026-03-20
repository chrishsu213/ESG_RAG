"""
admin_ui/pages/chatbot.py — AI 問答（RAG Chatbot）頁面
"""
import logging
import streamlit as st
from config import DEFAULT_GROUP
from modules.rag_chat import RagChat


def render(client):
    st.title("💬 AI 問答 (RAG Chatbot)")

    # ── 側邊欄搜尋設定 ──
    with st.sidebar:
        st.divider()
        st.markdown("#### 🔧 搜尋設定")
        st.caption("🎯 Reranking 全面啟用（混合搜尋 + AI 精排）")
        chat_top_k = st.slider("參考段落數", 3, 10, 5, key="chat_top_k")

        with st.expander("▶ 進階篩選", expanded=False):
            _all_docs = client.table("documents").select('"group", company, fiscal_year, category').execute().data or []
            _all_groups    = sorted(set(r["group"] for r in _all_docs if r.get("group")))
            _all_companies = sorted(set(r["company"] for r in _all_docs if r.get("company")))
            _all_years     = sorted(set(r["fiscal_year"] for r in _all_docs if r.get("fiscal_year")), reverse=True)
            _all_cats      = sorted(set(r["category"] for r in _all_docs if r.get("category")))

            if not _all_groups:
                _all_groups = [DEFAULT_GROUP]

            chat_groups = st.multiselect(
                "🏢 集團", _all_groups,
                default=[DEFAULT_GROUP] if DEFAULT_GROUP in _all_groups else _all_groups[:1],
                key="chat_groups",
            )

            if chat_groups:
                _grp_companies = sorted(set(
                    r["company"] for r in _all_docs
                    if r.get("company") and r.get("group") in chat_groups
                ))
            else:
                _grp_companies = _all_companies

            chat_company_all = st.checkbox("全部子公司", value=True, key="chat_company_all")
            if chat_company_all:
                _selected_company = None
            else:
                _sel = st.selectbox("🏭 子公司", ["（請選擇）"] + _grp_companies, key="chat_company_sel")
                _selected_company = _sel if _sel != "（請選擇）" else None

            chat_year_all = st.checkbox("全部年度", value=True, key="chat_year_all")
            if chat_year_all:
                _selected_fiscal_year = None
            else:
                _sel_yr = st.selectbox("📅 年度", ["（請選擇）"] + list(_all_years), key="chat_year_sel")
                _selected_fiscal_year = _sel_yr if _sel_yr != "（請選擇）" else None

            chat_cat_all = st.checkbox("全部類別", value=True, key="chat_cat_all")
            if chat_cat_all:
                chat_categories = st.multiselect("📂 報告類別", _all_cats, default=_all_cats, disabled=True, key="chat_categories")
            else:
                chat_categories = st.multiselect("📂 報告類別", _all_cats, key="chat_categories")

        if st.button("🗑️ 清除對話", key="clear_chat"):
            st.session_state["chat_history"] = []
            st.rerun()

    # ── 解析篩選條件 ──
    _selected_group = chat_groups[0] if len(chat_groups) == 1 else None
    if chat_company_all:
        _selected_company = None
    if chat_year_all:
        _selected_fiscal_year = None

    # ── 初始化對話歷史 ──
    if "chat_history" not in st.session_state:
        st.session_state["chat_history"] = []

    # ── 顯示歷史訊息 ──
    for msg in st.session_state["chat_history"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("sources"):
                with st.expander(f"📚 引用來源 ({len(msg['sources'])} 筆)", expanded=False):
                    for src in msg["sources"]:
                        ps = src.get("page_start")
                        pe = src.get("page_end")
                        page_info    = f" · 📄 第{ps}{f'-{pe}' if pe and pe != ps else ''}頁" if ps else ""
                        section      = f" · 🔖 {src['section_title']}" if src.get("section_title") else ""
                        search_badge = f" · 🏷️ {src['search_type']}" if src.get("search_type") else ""
                        st.caption(f"**[來源{src['index']}]** {src['document_name']}{page_info}{section}{search_badge}")

    # ── 聊天輸入 ──
    if prompt := st.chat_input("請輸入您的問題..."):
        st.session_state["chat_history"].append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            rag = RagChat(client)
            history_for_rag = [
                {"role": m["role"], "content": m["content"]}
                for m in st.session_state["chat_history"][:-1]
            ]

            # 比較模式判斷
            _is_compare    = False
            _compare_groups = []

            if len(chat_groups) >= 2:
                _is_compare = True
                _compare_groups = [
                    {"group": g, "company": _selected_company, "fiscal_year": _selected_fiscal_year}
                    for g in chat_groups
                ]
            else:
                _detect = rag.detect_comparison(prompt, _all_companies)
                if _detect:
                    dim  = _detect.get("dimension")
                    vals = _detect.get("values", [])
                    if dim == "company" and len(vals) >= 2:
                        _is_compare = True
                        _compare_groups = [
                            {"company": v, "group": _selected_group, "fiscal_year": _selected_fiscal_year}
                            for v in vals
                        ]
                    elif dim == "fiscal_year" and len(vals) >= 2:
                        _is_compare = True
                        _compare_groups = [
                            {"fiscal_year": v, "group": _selected_group, "company": _selected_company}
                            for v in vals
                        ]

            if _is_compare:
                with st.spinner("比較搜尋中..."):
                    result = rag.ask_compare(
                        question=prompt, groups=_compare_groups,
                        history=history_for_rag, top_k=chat_top_k,
                        language=None, source="admin_ui_compare",
                    )
            else:
                with st.spinner("搜尋知識庫中..."):
                    result = rag.ask_stream(
                        question=prompt, history=history_for_rag,
                        top_k=chat_top_k, fiscal_year=_selected_fiscal_year,
                        group=_selected_group, company=_selected_company,
                    )

            sources     = result["sources"]
            answer_text = st.write_stream(result["stream"])

            _sr = result.get("search_results", [])
            _rm = _sr[0].get("_rerank_method") if _sr else None
            if _rm == "ranking_api":
                st.caption("✅ Rerank: Vertex AI Ranking API")
            elif _rm == "gemini_fallback":
                st.caption("⚠️ Rerank: Gemini Fallback")

            if sources:
                with st.expander(f"📚 引用來源 ({len(sources)} 筆)", expanded=False):
                    for src in sources:
                        ps = src.get("page_start")
                        pe = src.get("page_end")
                        page_info    = f" · 📄 第{ps}{f'-{pe}' if pe and pe != ps else ''}頁" if ps else ""
                        section      = f" · 🔖 {src['section_title']}" if src.get("section_title") else ""
                        sim          = f" · 相似度 {src['similarity']:.3f}" if src.get("similarity") else ""
                        search_badge = f" · 🏷️ {src['search_type']}" if src.get("search_type") else ""
                        st.caption(f"**[來源{src['index']}]** {src['document_name']}{page_info}{section}{sim}{search_badge}")

            chunk_ids = [r.get("id") for r in result.get("search_results", []) if r.get("id")]
            st.session_state["chat_history"].append({
                "role": "assistant", "content": answer_text,
                "sources": sources, "question": prompt,
                "chunk_ids": chunk_ids,
                "msg_idx": len(st.session_state["chat_history"]),
            })

    # ── 回饋按鈕（最新 AI 回答）──
    last_assistant_idx = None
    for i, msg in enumerate(st.session_state["chat_history"]):
        if msg["role"] == "assistant" and not msg.get("feedback_sent"):
            last_assistant_idx = i

    if last_assistant_idx is not None:
        msg    = st.session_state["chat_history"][last_assistant_idx]
        fb_key = f"fb_{last_assistant_idx}"
        col_up, col_down, _ = st.columns([1, 1, 8])

        def _write_feedback(rating: str):
            try:
                client.table("qa_feedback").insert({
                    "question": msg.get("question", ""),
                    "answer": msg["content"],
                    "rating": rating,
                    "chunk_ids": msg.get("chunk_ids", []),
                }).execute()
            except Exception as e:
                logging.getLogger(__name__).error(f"回饋寫入失敗：{e}")
            msg["feedback_sent"] = True

        with col_up:
            if st.button("👍", key=f"{fb_key}_up", help="回答有幫助"):
                _write_feedback("up")
                st.toast("✅ 感謝回饋！")
                st.rerun()
        with col_down:
            if st.button("👎", key=f"{fb_key}_down", help="回答需改善"):
                _write_feedback("down")
                st.toast("📝 感謝回饋，我們會持續改進！")
                st.rerun()
