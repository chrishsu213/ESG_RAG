"""
admin_ui/pages/doc_mgmt.py — 文件管理頁面
功能：群組分類篩選、per-document Popover 編輯、📖 查看 Chunk、🗑️ 刪除。
"""
import pandas as pd
import streamlit as st
from admin_ui.utils.constants import (
    CATEGORY_GROUPS, CATEGORY_OPTIONS, LANGUAGE_OPTIONS,
    STATUS_OPTIONS, CONFIDENTIALITY_OPTIONS, FISCAL_YEAR_OPTIONS,
)
from admin_ui.utils.db import (
    fetch_documents, delete_document, fetch_chunks_for_document,
)

# 反向查表：category → group label
_CAT_TO_GROUP: dict[str, str] = {
    cat: grp
    for grp, cats in CATEGORY_GROUPS.items()
    for cat in cats
}


def render(client):
    st.title("🗃️ 文件管理")

    docs = fetch_documents()
    if not docs:
        st.info("目前資料庫中沒有任何文件。")
        return

    df = pd.DataFrame(docs)
    df["created_at"] = pd.to_datetime(df["created_at"]).dt.strftime("%Y-%m-%d %H:%M")

    # 確保欄位存在（相容舊資料）
    for col, default in [
        ("category", "其他"), ("display_name", None), ("report_group", None),
        ("group", None), ("company", None), ("language", "zh-TW"),
        ("status", "已發布"), ("confidentiality", "公開"),
        ("fiscal_year", None), ("fiscal_period", "Annual"), ("publish_date", None),
    ]:
        if col not in df.columns:
            df[col] = default
    df["display_name"]    = df["display_name"].fillna(df["file_name"])
    df["report_group"]    = df["report_group"].fillna("")
    df["group"]           = df["group"].fillna("")
    df["company"]         = df["company"].fillna("")
    df["language"]        = df["language"].fillna("zh-TW")
    df["status"]          = df["status"].fillna("已發布")
    df["confidentiality"] = df["confidentiality"].fillna("公開")
    df["fiscal_year"]     = df["fiscal_year"].fillna("")
    df["fiscal_period"]   = df["fiscal_period"].fillna("Annual")

    # ── 篩選列：群組 → 子分類 + 語言 ──────────────────────────
    f_col1, f_col2, f_col3 = st.columns(3)
    with f_col1:
        filter_lang = st.selectbox(
            "語言", ["全部"] + sorted(df["language"].unique().tolist()),
            key="filter_lang"
        )
    with f_col2:
        group_options = ["全部"] + list(CATEGORY_GROUPS.keys())
        filter_group_label = st.selectbox("類別群組", group_options, key="filter_group_label")
    with f_col3:
        if filter_group_label == "全部":
            cat_options = ["全部"] + CATEGORY_OPTIONS
        else:
            cat_options = ["全部"] + CATEGORY_GROUPS[filter_group_label]
        filter_cat = st.selectbox("文件分類", cat_options, key="filter_cat")

    filtered_df = df.copy()
    if filter_lang != "全部":
        filtered_df = filtered_df[filtered_df["language"] == filter_lang]
    if filter_cat != "全部":
        filtered_df = filtered_df[filtered_df["category"] == filter_cat]
    elif filter_group_label != "全部":
        # 只過濾群組，不鎖定子分類
        grp_cats = CATEGORY_GROUPS[filter_group_label]
        filtered_df = filtered_df[filtered_df["category"].isin(grp_cats)]

    st.caption(f"顯示 {len(filtered_df)} / {len(df)} 份文件")
    st.divider()

    # ── 依分類顯示，每份文件一列 + Popover 編輯 ──────────────
    for cat in sorted(filtered_df["category"].unique()):
        cat_df = filtered_df[filtered_df["category"] == cat].copy()
        grp_label = _CAT_TO_GROUP.get(cat, "其他")

        with st.expander(f"{grp_label} › {cat}（{len(cat_df)} 份）", expanded=True):
            for _, row in cat_df.iterrows():
                doc_id   = int(row["id"])
                doc_name = row["display_name"]
                year     = str(row.get("fiscal_year", "") or "")
                period   = str(row.get("fiscal_period", "Annual") or "Annual")
                company  = str(row.get("company", "") or "")

                r_name, r_edit, r_view, r_del = st.columns([6, 1, 1, 1])
                with r_name:
                    badges = ""
                    if year:
                        badges += f" `{year}`"
                    if period and period != "Annual":
                        badges += f" `{period}`"
                    if company:
                        badges += f" • {company}"
                    st.markdown(f"**{doc_name}**{badges}")

                # ── Popover 編輯（不展開整頁）──────────────
                with r_edit:
                    with st.popover("✏️", help="編輯此文件 Metadata"):
                        st.markdown(f"**編輯：{doc_name}**")
                        p_name = st.text_input(
                            "顯示名稱", value=doc_name,
                            key=f"p_name_{doc_id}"
                        )
                        p_cat = st.selectbox(
                            "分類", CATEGORY_OPTIONS,
                            index=CATEGORY_OPTIONS.index(row["category"]) if row["category"] in CATEGORY_OPTIONS else 0,
                            key=f"p_cat_{doc_id}"
                        )
                        p_year_opts = ["（不填）"] + FISCAL_YEAR_OPTIONS
                        p_year_idx  = p_year_opts.index(year) if year in p_year_opts else 0
                        p_year = st.selectbox("年度", p_year_opts, index=p_year_idx, key=f"p_year_{doc_id}")
                        p_lang = st.selectbox(
                            "語言", LANGUAGE_OPTIONS,
                            index=LANGUAGE_OPTIONS.index(row["language"]) if row["language"] in LANGUAGE_OPTIONS else 0,
                            key=f"p_lang_{doc_id}"
                        )
                        p_group   = st.text_input("集團",    value=row["group"],       key=f"p_grp_{doc_id}")
                        p_company = st.text_input("子公司",  value=row["company"],     key=f"p_comp_{doc_id}")
                        p_rg      = st.text_input("所屬報告", value=row["report_group"], key=f"p_rg_{doc_id}")
                        p_status  = st.selectbox(
                            "狀態", STATUS_OPTIONS,
                            index=STATUS_OPTIONS.index(row["status"]) if row["status"] in STATUS_OPTIONS else 0,
                            key=f"p_status_{doc_id}"
                        )

                        if st.button("💾 儲存", key=f"p_save_{doc_id}", type="primary"):
                            updates = {
                                "display_name": p_name or None,
                                "category":     p_cat,
                                "fiscal_year":  None if p_year == "（不填）" else p_year,
                                "language":     p_lang,
                                "group":        p_group or None,
                                "company":      p_company or None,
                                "report_group": p_rg or None,
                                "status":       p_status,
                            }
                            client.table("documents").update(updates).eq("id", doc_id).execute()
                            fetch_documents.clear()
                            st.toast(f"✅ 已更新：{p_name}")
                            st.rerun()

                with r_view:
                    if st.button("📖", key=f"view_{doc_id}", help="查看 Chunk 內容"):
                        if st.session_state.get("preview_doc_id") == doc_id:
                            st.session_state.pop("preview_doc_id", None)
                        else:
                            st.session_state["preview_doc_id"] = doc_id
                            st.session_state.pop("confirm_del_id", None)
                        st.rerun()

                with r_del:
                    if st.button("🗑️", key=f"del_{doc_id}", help="刪除這份文件"):
                        if st.session_state.get("confirm_del_id") == doc_id:
                            st.session_state.pop("confirm_del_id", None)
                        else:
                            st.session_state["confirm_del_id"] = doc_id
                            st.session_state.pop("preview_doc_id", None)
                        st.rerun()

                # 刪除確認
                if st.session_state.get("confirm_del_id") == doc_id:
                    with st.container(border=True):
                        st.warning(f"確定要刪除「**{doc_name}**」及所有 Chunks？")
                        cd1, cd2 = st.columns(2)
                        with cd1:
                            if st.button("✅ 確認刪除", key=f"del_yes_{doc_id}", type="primary"):
                                delete_document(client, doc_id, row["file_name"])
                                st.session_state.pop("confirm_del_id", None)
                                st.rerun()
                        with cd2:
                            if st.button("❌ 取消", key=f"del_no_{doc_id}"):
                                st.session_state.pop("confirm_del_id", None)
                                st.rerun()

                # Chunk 預覽
                if st.session_state.get("preview_doc_id") == doc_id:
                    with st.container(border=True):
                        st.markdown(f"📖 **{doc_name}** 的 Chunk 內容")
                        chunks_data = fetch_chunks_for_document(client, doc_id)
                        if not chunks_data:
                            st.info("此文件沒有 Chunk 資料。")
                        else:
                            st.caption(f"共 {len(chunks_data)} 個 Chunk")
                            for chunk in chunks_data:
                                idx       = chunk["chunk_index"]
                                meta      = chunk.get("metadata") or {}
                                title     = meta.get("section_title", "")
                                ps        = meta.get("page_start")
                                pe        = meta.get("page_end")
                                ctype     = chunk.get("chunk_type", "standalone")
                                parent_id = chunk.get("parent_chunk_id")
                                type_badge = {"parent": "🗂️ parent", "child": "📝 child",
                                              "standalone": "📄 standalone"}.get(ctype, ctype)
                                label = f"Chunk #{idx} [{type_badge}]"
                                if title:
                                    label += f" | 🔖 {title}"
                                if ps:
                                    label += f" | 📄 第{ps}{f'-{pe}' if pe and pe != ps else ''}頁"
                                if parent_id:
                                    label += f" | ↑ parent={parent_id}"
                                with st.expander(label, expanded=False):
                                    st.markdown(chunk["text_content"])
                        if st.button("✖️ 關閉預覽", key=f"close_preview_{doc_id}"):
                            st.session_state.pop("preview_doc_id", None)
                            st.rerun()
