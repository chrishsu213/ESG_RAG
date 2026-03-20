"""
admin_ui/app.py — RAG 知識庫管理介面（Router）
此檔案只負責：頁面設定、密碼保護、Supabase 初始化、側邊欄導覽。
各功能頁面邏輯請至 admin_ui/pages/ 目錄下的對應檔案查看。

啟動方式：
    streamlit run admin_ui/app.py
"""
import os
import sys

# 確保能 import 根目錄的 modules 與 config
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

import streamlit as st
from supabase import create_client
from config import _get_secret

from admin_ui.utils import db as db_utils
from admin_ui.pages import overview, upload, doc_mgmt, search, chatbot, terms, settings

# ── 頁面設定 ──────────────────────────────────────────────
st.set_page_config(
    page_title="RAG 知識庫管理中心",
    page_icon="📚",
    layout="wide",
)

# ── 密碼保護 ──────────────────────────────────────────────
def _get_admin_password() -> str:
    try:
        if "ADMIN_PASSWORD" in st.secrets:
            return str(st.secrets["ADMIN_PASSWORD"])
    except Exception:
        pass
    return os.getenv("ADMIN_PASSWORD", "")


def check_password() -> bool:
    admin_pw = _get_admin_password()
    if not admin_pw:
        return True
    if st.session_state.get("authenticated"):
        return True

    st.markdown("## 🔐 管理員登入")
    st.markdown("請輸入管理密碼以存取管理後台。")
    with st.form("login_form"):
        password  = st.text_input("密碼", type="password")
        submitted = st.form_submit_button("登入", type="primary")
    if submitted:
        if password == admin_pw:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("❌ 密碼錯誤")
    st.stop()


if not check_password():
    st.stop()

# ── Supabase 連線 ─────────────────────────────────────────
@st.cache_resource
def init_supabase():
    url = _get_secret("SUPABASE_URL")
    key = _get_secret("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        st.error("❌ 系統錯誤：尚未設定 SUPABASE_URL 或 SUPABASE_SERVICE_ROLE_KEY")
        st.stop()
    return create_client(url, key)


client = init_supabase()

# 注入 client 到 db_utils 供 @st.cache_data 函式使用
db_utils.set_client(client)

# ── 側邊欄導覽 ─────────────────────────────────────────────
with st.sidebar:
    st.title("⚙️ RAG 管理中心")
    page = st.radio(
        "選擇功能",
        ["📊 系統概況", "📤 上傳與匯入", "🗃️ 文件管理",
         "📖 專有名詞字典", "🔍 檢索測試", "💬 AI 問答", "⚙️ 系統設定"],
        label_visibility="collapsed",
    )

# ── 頁面路由 ───────────────────────────────────────────────
if page == "📊 系統概況":
    overview.render(client)
elif page == "📤 上傳與匯入":
    upload.render(client)
elif page == "🗃️ 文件管理":
    doc_mgmt.render(client)
elif page == "📖 專有名詞字典":
    terms.render(client)
elif page == "🔍 檢索測試":
    search.render(client)
elif page == "💬 AI 問答":
    chatbot.render(client)
elif page == "⚙️ 系統設定":
    settings.render(client)
