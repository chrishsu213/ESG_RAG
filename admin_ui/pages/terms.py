"""
admin_ui/pages/terms.py — 專有名詞字典管理頁面
"""
import pandas as pd
import streamlit as st
from admin_ui.utils.constants import LANGUAGE_OPTIONS, TERM_CATEGORIES


def render(client):
    st.title("📖 專有名詞字典")
    st.caption("管理錄音轉錄和文件清洗時自動替換的專有名詞")

    # 載入現有字典
    try:
        terms_data = client.table("terms_dictionary").select("*").order("category").order("term").execute().data or []
    except Exception as e:
        st.error(f"無法載入字典（可能尚未執行 migrate_terms_dict.sql）：{e}")
        terms_data = []

    if terms_data:
        terms_df = pd.DataFrame(terms_data)

        cat_counts = terms_df["category"].value_counts()
        cols = st.columns(len(cat_counts))
        for i, (cat, count) in enumerate(cat_counts.items()):
            cols[i].metric(cat, f"{count} 詞")

        st.divider()

        edit_terms = terms_df[["id", "term", "full_name", "category", "language"]].copy()
        edited_terms = st.data_editor(
            edit_terms,
            column_config={
                "id":        st.column_config.NumberColumn("ID", disabled=True, width="small"),
                "term":      st.column_config.TextColumn("原始詞", width="medium"),
                "full_name": st.column_config.TextColumn("完整名稱", width="large"),
                "category":  st.column_config.SelectboxColumn("分類", options=TERM_CATEGORIES, width="small"),
                "language":  st.column_config.SelectboxColumn("語言", options=LANGUAGE_OPTIONS, width="small"),
            },
            hide_index=True,
            use_container_width=True,
            num_rows="fixed",
            key="terms_editor",
        )

        tc1, tc2 = st.columns(2)
        with tc1:
            if st.button("💾 儲存修改", key="save_terms"):
                changes = 0
                for _, row in edited_terms.iterrows():
                    orig = edit_terms[edit_terms["id"] == row["id"]]
                    if orig.empty:
                        continue
                    orig_row = orig.iloc[0]
                    updates = {}
                    for col in ["term", "full_name", "category", "language"]:
                        if str(row[col]) != str(orig_row[col]):
                            updates[col] = row[col]
                    if updates:
                        client.table("terms_dictionary").update(updates).eq("id", row["id"]).execute()
                        changes += 1
                st.toast(f"✅ 已更新 {changes} 筆" if changes else "沒有偵測到修改")
                if changes:
                    st.rerun()

        with tc2:
            del_ids = st.multiselect(
                "選擇刪除",
                options=terms_df["id"].tolist(),
                format_func=lambda x: f"{terms_df[terms_df['id']==x]['term'].values[0]} → {terms_df[terms_df['id']==x]['full_name'].values[0]}",
                key="del_terms",
            )
            if del_ids and st.button(f"🗑️ 刪除 {len(del_ids)} 筆", key="del_terms_confirm"):
                for tid in del_ids:
                    client.table("terms_dictionary").delete().eq("id", tid).execute()
                st.toast(f"已刪除 {len(del_ids)} 筆")
                st.rerun()
    else:
        st.info("字典為空。請先在 Supabase 執行 `migrate_terms_dict.sql`，或在下方新增詞彙。")

    # ── 新增詞彙 ──
    st.divider()
    st.markdown("#### ➕ 新增詞彙")
    nc1, nc2, nc3 = st.columns([1, 2, 1])
    new_term = nc1.text_input("原始詞", placeholder="例：DAKA", key="new_term")
    new_full = nc2.text_input("完整名稱", placeholder="例：台泥DAKA再生資源處理中心", key="new_full")
    new_cat  = nc3.selectbox("分類", TERM_CATEGORIES, key="new_term_cat")

    if st.button("➕ 新增", key="add_term"):
        if new_term.strip() and new_full.strip():
            try:
                client.table("terms_dictionary").insert({
                    "term": new_term.strip(),
                    "full_name": new_full.strip(),
                    "category": new_cat,
                }).execute()
                st.toast(f"✅ 已新增：{new_term} → {new_full}")
                st.rerun()
            except Exception as e:
                st.error(f"新增失敗（可能已存在）：{e}")
        else:
            st.warning("請填寫原始詞和完整名稱")
