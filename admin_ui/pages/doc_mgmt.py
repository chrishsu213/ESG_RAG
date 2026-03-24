"""
admin_ui/pages/doc_mgmt.py — 文件管理頁面
結構：3 篩選器（語言/分類/集團公司）→ 3 群組 Expander → 子分類標題 → 文件列表（分頁）
"""
import pandas as pd
import streamlit as st
from admin_ui.utils.constants import (
    CATEGORY_GROUPS, CATEGORY_OPTIONS, LANGUAGE_OPTIONS,
    STATUS_OPTIONS, FISCAL_YEAR_OPTIONS,
)
from admin_ui.utils.db import (
    fetch_documents, delete_document, fetch_chunks_for_document, get_custom_category_groups,
)

_CAT_TO_GROUP: dict[str, str] = {
    cat: grp
    for grp, cats in CATEGORY_GROUPS.items()
    for cat in cats
}

_PAGE_SIZE = 20


def _doc_list(client, cat_df: pd.DataFrame, page_key: str) -> None:
    """顯示單一子分類的文件列表（含分頁）。"""
    total = len(cat_df)
    if total == 0:
        return

    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    if total_pages > 1:
        page = st.number_input(
            f"頁次（共 {total_pages} 頁）",
            min_value=1, max_value=total_pages, value=1, step=1,
            key=f"page_{page_key}",
        )
    else:
        page = 1

    start = (page - 1) * _PAGE_SIZE
    page_df = cat_df.iloc[start: start + _PAGE_SIZE]

    for _, row in page_df.iterrows():
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

        with r_edit:
            with st.popover("✏️", help="編輯 Metadata"):
                st.markdown(f"**{doc_name}**")
                p_name = st.text_input("顯示名稱", value=doc_name, key=f"p_name_{doc_id}")
                _all_db_cats = sorted(df["category"].dropna().unique().tolist())
                _allowed_cats = sorted(set(CATEGORY_OPTIONS + _all_db_cats))
                p_cat = st.selectbox(
                    "分類", _allowed_cats,
                    index=_allowed_cats.index(row["category"]) if row["category"] in _allowed_cats else 0,
                    key=f"p_cat_{doc_id}",
                )
                _yr_opts = ["（不填）"] + FISCAL_YEAR_OPTIONS
                p_year = st.selectbox(
                    "年度", _yr_opts,
                    index=_yr_opts.index(year) if year in _yr_opts else 0,
                    key=f"p_year_{doc_id}",
                )
                p_lang = st.selectbox(
                    "語言", LANGUAGE_OPTIONS,
                    index=LANGUAGE_OPTIONS.index(row["language"]) if row["language"] in LANGUAGE_OPTIONS else 0,
                    key=f"p_lang_{doc_id}",
                )
                p_group   = st.text_input("集團",    value=row["group"],        key=f"p_grp_{doc_id}")
                p_company = st.text_input("子公司",  value=row["company"],      key=f"p_comp_{doc_id}")
                p_rg      = st.text_input("所屬報告", value=row["report_group"], key=f"p_rg_{doc_id}")
                p_status  = st.selectbox(
                    "狀態", STATUS_OPTIONS,
                    index=STATUS_OPTIONS.index(row["status"]) if row["status"] in STATUS_OPTIONS else 0,
                    key=f"p_status_{doc_id}",
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
            if st.button("📖", key=f"view_{doc_id}", help="查看 Chunks"):
                if st.session_state.get("preview_doc_id") == doc_id:
                    st.session_state.pop("preview_doc_id", None)
                else:
                    st.session_state["preview_doc_id"] = doc_id
                    st.session_state.pop("confirm_del_id", None)
                st.rerun()

        with r_del:
            if st.button("🗑️", key=f"del_{doc_id}", help="刪除"):
                if st.session_state.get("confirm_del_id") == doc_id:
                    st.session_state.pop("confirm_del_id", None)
                else:
                    st.session_state["confirm_del_id"] = doc_id
                    st.session_state.pop("preview_doc_id", None)
                st.rerun()

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
                            label += f" | 第{ps}{f'-{pe}' if pe and pe != ps else ''}頁"
                        if parent_id:
                            label += f" | ↑ parent={parent_id}"
                        with st.expander(label, expanded=False):
                            st.markdown(chunk["text_content"])
                if st.button("✖️ 關閉預覽", key=f"close_preview_{doc_id}"):
                    st.session_state.pop("preview_doc_id", None)
                    st.rerun()


# ── 主要 render ────────────────────────────────────────────
def render(client):
    st.title("🗃️ 文件管理")

    docs = fetch_documents()
    if not docs:
        st.info("目前資料庫中沒有任何文件。")
        return

    df = pd.DataFrame(docs)
    df["created_at"] = pd.to_datetime(df["created_at"]).dt.strftime("%Y-%m-%d %H:%M")

    for col, default in [
        ("category", "其他"), ("display_name", None), ("report_group", None),
        ("group", None), ("company", None), ("language", "zh-TW"),
        ("status", "已發布"), ("fiscal_year", None), ("fiscal_period", "Annual"),
    ]:
        if col not in df.columns:
            df[col] = default

    df["display_name"]  = df["display_name"].fillna(df["file_name"])
    df["report_group"]  = df["report_group"].fillna("")
    df["group"]         = df["group"].fillna("")
    df["company"]       = df["company"].fillna("")
    df["language"]      = df["language"].fillna("zh-TW")
    df["status"]        = df["status"].fillna("已發布")
    df["fiscal_year"]   = df["fiscal_year"].fillna("")
    df["fiscal_period"] = df["fiscal_period"].fillna("Annual")

    # ── 篩選列：語言 / 分類 / 集團公司 ───────────────────────
    # 集團公司動態從 DB 讀取（group 優先，fallback 到 company）
    _company_vals = sorted(set(
        v for v in df["group"].tolist() + df["company"].tolist() if v
    ))

    f1, f2, f3 = st.columns(3)
    with f1:
        filter_lang = st.selectbox(
            "語言", ["全部"] + sorted(df["language"].unique().tolist()),
            key="filter_lang",
        )
    _all_db_cats = sorted(df["category"].dropna().unique().tolist())
    with f2:
        filter_cat = st.selectbox(
            "分類", ["全部", "未分類"] + _all_db_cats,
            key="filter_cat",
        )
    with f3:
        filter_company = st.selectbox(
            "集團 / 公司", ["全部"] + _company_vals,
            key="filter_company",
        )

    # 套用篩選
    filtered_df = df.copy()
    if filter_lang != "全部":
        filtered_df = filtered_df[filtered_df["language"] == filter_lang]
    if filter_cat != "全部":
        if filter_cat == "未分類":
            filtered_df = filtered_df[filtered_df["category"].isna()]
        else:
            filtered_df = filtered_df[filtered_df["category"] == filter_cat]
    if filter_company != "全部":
        filtered_df = filtered_df[
            (filtered_df["group"] == filter_company) |
            (filtered_df["company"] == filter_company)
        ]

    st.caption(f"顯示 {len(filtered_df)} / {len(df)} 份文件")
    st.divider()

    # ── 3 個群組 Expander（包含動態新增的自訂分類）────────────────
    
    # 從資料庫拉取 UI 動態新增的群組對應表
    custom_groups = get_custom_category_groups(client)
    
    # 合併 constants.py 裡的預設群組與 DB 裡的自訂群組
    dynamic_groups = {}
    for g, cats in CATEGORY_GROUPS.items():
        dynamic_groups[g] = list(cats)
    
    for g, cats in custom_groups.items():
        if g not in dynamic_groups:
            dynamic_groups[g] = []
        for c in cats:
            if c not in dynamic_groups[g]:
                dynamic_groups[g].append(c)

    # 找出還是沒有歸屬的「孤兒分類」（例如舊資料或透過腳本直接打入庫的）
    known_cats = set(c for cats in dynamic_groups.values() for c in cats)
    db_cats = set(filtered_df["category"].dropna().unique())
    unknown_cats = sorted(db_cats - known_cats)
    
    # 把自訂分類裝進一個專屬的「未定義分類群組」面版
    if unknown_cats:
        dynamic_groups["📁 其他未定義分類"] = unknown_cats

    for grp_label, grp_cats in dynamic_groups.items():
        grp_df = filtered_df[filtered_df["category"].isin(grp_cats)]
        if grp_df.empty:
            continue

        _is_unmapped = (grp_label == "📁 其他未定義分類")
        with st.expander(f"{grp_label}（{len(grp_df)} 份）", expanded=_is_unmapped):
            # 只顯示有資料的子分類 Tab
            available_cats = [cat for cat in grp_cats if not grp_df[grp_df["category"] == cat].empty]
            if not available_cats:
                continue

            tabs = st.tabs(available_cats)
            for tab, cat in zip(tabs, available_cats):
                with tab:
                    cat_df = grp_df[grp_df["category"] == cat].copy()
                    st.caption(f"{len(cat_df)} 份文件")
                    _doc_list(client, cat_df, page_key=f"{grp_label}_{cat}")

