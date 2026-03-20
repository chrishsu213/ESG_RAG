"""
admin_ui/pages/settings.py — 系統設定頁面（RAG 搜尋參數 + System Prompt）
"""
import streamlit as st
from config import RagConfig


def render(client):
    rag_cfg = RagConfig(client)
    cfg = rag_cfg.get_all()

    st.title("⚙️ RAG 系統設定")
    st.caption("調整後 60 秒內自動生效（Streamlit + API 同步）。不需要重新部署。")

    # ── 搜尋參數 ──────────────────────────────────
    st.subheader("🔍 搜尋參數")
    col1, col2 = st.columns(2)
    with col1:
        new_threshold = st.slider(
            "混合搜尋門檻 (hybrid_threshold)",
            min_value=0.05, max_value=0.60, step=0.05,
            value=float(cfg.get("hybrid_threshold", "0.2")),
            help="越低 → 候選池越大，但可能引入雜訊。建議範圍：0.1~0.4",
        )
        new_top_k_mul = st.selectbox(
            "候選池倍數 (top_k_multiplier)",
            options=[1, 2, 3, 5],
            index=[1, 2, 3, 5].index(int(cfg.get("top_k_multiplier", "2"))),
            help="hybrid_search 取 top_k × N 倍作為候選池，再用加權排序取最終結果",
        )
    with col2:
        st.markdown("**加權配比**（合計應為 1.0）")
        new_sim = st.slider("語義相似度 (sim_weight)",  0.0, 1.0, float(cfg.get("sim_weight", "0.60")), step=0.05)
        new_yr  = st.slider("年份新舊 (year_weight)",   0.0, 1.0, float(cfg.get("year_weight", "0.25")), step=0.05)
        new_src = st.slider("來源類型 (source_weight)", 0.0, 1.0, float(cfg.get("source_weight", "0.15")), step=0.05)

        total = round(new_sim + new_yr + new_src, 2)
        if abs(total - 1.0) < 0.01:
            st.success(f"✅ 合計 = {total}")
        else:
            st.error(f"⚠️ 合計 = {total}，需為 1.0")

    st.divider()

    # ── System Prompt ───────────────────────────────
    st.subheader("🤖 System Prompt")
    st.caption("留空或填寫 `{{DEFAULT}}` 則使用程式碼內建 Prompt。")

    current_prompt = cfg.get("system_prompt", "{{DEFAULT}}")
    if current_prompt == "{{DEFAULT}}":
        prompt_placeholder = "（使用程式碼預設值。如需自訂，請在此輸入完整 Prompt）"
        display_prompt = ""
    else:
        prompt_placeholder = "請輸入 System Prompt..."
        display_prompt = current_prompt

    new_prompt = st.text_area(
        "System Prompt 內容",
        value=display_prompt,
        placeholder=prompt_placeholder,
        height=300,
        help="AI 每次回答前都會收到此 Prompt。修改後 60 秒內生效。",
    )

    st.divider()

    # ── 操作按鈕 ────────────────────────────────────
    sc1, sc2 = st.columns([1, 4])
    with sc1:
        if st.button("💾 儲存設定", type="primary", use_container_width=True):
            errors = []
            if abs((new_sim + new_yr + new_src) - 1.0) >= 0.01:
                errors.append("加權配比合計需為 1.0")

            if errors:
                for e in errors:
                    st.error(f"❌ {e}")
            else:
                ok = all([
                    rag_cfg.set("hybrid_threshold", str(round(new_threshold, 2))),
                    rag_cfg.set("top_k_multiplier", str(new_top_k_mul)),
                    rag_cfg.set("sim_weight",        str(round(new_sim, 2))),
                    rag_cfg.set("year_weight",       str(round(new_yr, 2))),
                    rag_cfg.set("source_weight",     str(round(new_src, 2))),
                    rag_cfg.set("system_prompt",     new_prompt.strip() if new_prompt.strip() else "{{DEFAULT}}"),
                ])
                if ok:
                    rag_cfg.invalidate_cache()
                    st.success("✅ 設定已儲存！60 秒內全面生效。")
                else:
                    st.error("❌ 部分設定儲存失敗，請確認 Supabase 連線。")

    with sc2:
        if st.button("🔄 還原預設值", use_container_width=True):
            defaults = {
                "hybrid_threshold": "0.2",
                "top_k_multiplier": "2",
                "sim_weight":       "0.60",
                "year_weight":      "0.25",
                "source_weight":    "0.15",
                "system_prompt":    "{{DEFAULT}}",
            }
            for k, v in defaults.items():
                rag_cfg.set(k, v)
            rag_cfg.invalidate_cache()
            st.success("✅ 已還原所有預設值")
            st.rerun()

    # ── 目前資料庫設定值 ─────────────────────────────
    with st.expander("📋 目前資料庫設定值"):
        try:
            rows = client.table("rag_config").select("key,value,note,updated_at").order("key").execute().data or []
            if rows:
                st.dataframe(
                    [{"設定鍵": r["key"], "值": r["value"], "說明": r.get("note", ""), "最後更新": r.get("updated_at", "")} for r in rows],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("資料庫中尚無設定（請先執行 SQL migration 010_rag_config.sql）")
        except Exception as e:
            st.error(f"讀取失敗：{e}")
