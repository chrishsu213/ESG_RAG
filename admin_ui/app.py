"""
admin_ui/app.py — RAG 知識庫管理介面
使用 Streamlit 打造的操作儀表板。

啟動方式：
    streamlit run admin_ui/app.py
"""
import os
import sys
import time
import uuid
import pandas as pd
import streamlit as st

# 專案根目錄與暫存資料夾（使用絕對路徑，避免 CWD 依賴）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DATA_DIR = os.path.join(BASE_DIR, "raw_data")

# 確保能 import 根目錄的 modules 與 config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase import create_client
from config import _get_secret, DEFAULT_GROUP
from modules.uploader import Uploader
from modules.parser_pdf import PdfParser
from modules.parser_docx import DocxParser
from modules.parser_url import UrlParser
from modules.cleaner import MarkdownCleaner
from modules.chunker import SemanticChunker
from modules.exporter import SupabaseExporter
from modules.retriever import SemanticRetriever
from modules.crawler import SiteCrawler
from modules.parser_pdf_vision import VisionPdfParser
from modules.proofreader import AiProofreader
from modules.rag_chat import RagChat
from modules.parser_audio import AudioParser
from modules.embedder import GeminiEmbedder

# ── 頁面設定 ──────────────────────────────────────────
st.set_page_config(
    page_title="RAG 知識庫管理中心",
    page_icon="📚",
    layout="wide",
)


# ── 密碼保護 ──────────────────────────────────────────
def _get_admin_password() -> str:
    """取得管理員密碼（優先 st.secrets，其次環境變數）。"""
    try:
        if "ADMIN_PASSWORD" in st.secrets:
            return str(st.secrets["ADMIN_PASSWORD"])
    except Exception:
        pass
    return os.getenv("ADMIN_PASSWORD", "")


def check_password() -> bool:
    """顯示登入表單並驗證密碼。若未設定密碼則直接放行。"""
    admin_pw = _get_admin_password()
    if not admin_pw:
        return True  # 未設定密碼 → 開發模式，直接放行

    if st.session_state.get("authenticated"):
        return True

    st.markdown("## 🔐 管理員登入")
    st.markdown("請輸入管理密碼以存取管理後台。")

    with st.form("login_form"):
        password = st.text_input("密碼", type="password")
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


# ── 分類常數 ──────────────────────────────────────────
CATEGORY_OPTIONS = ["官網", "ESG專區", "電子報", "新聞", "永續報告書", "年度報告", "財務報告", "公司政策", "會議紀錄", "法說會", "其他"]
LANGUAGE_OPTIONS = ["zh-TW", "en", "ja", "zh-CN"]
STATUS_OPTIONS = ["已發布", "已審校", "草稿"]
CONFIDENTIALITY_OPTIONS = ["公開", "內部", "機密"]

# ── Supabase 連線 ─────────────────────────────────────
@st.cache_resource
def init_supabase():
    url = _get_secret("SUPABASE_URL")
    key = _get_secret("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        st.error("❌ 系統錯誤：尚未設定 SUPABASE_URL 或 SUPABASE_SERVICE_ROLE_KEY")
        st.stop()
    return create_client(url, key)

client = init_supabase()

# ── 通用函式 ──────────────────────────────────────────
def fetch_system_stats():
    doc_res = client.table("documents").select("id", count="exact").execute()
    chunk_res = client.table("document_chunks").select("id", count="exact").execute()
    return doc_res.count, chunk_res.count

@st.cache_data(ttl=10)
def fetch_documents():
    res = (client.table("documents")
        .select("id, file_name, file_hash, source_type, category, display_name, report_group, \"group\", company, language, status, confidentiality, fiscal_year, tags, created_at")
        .order("created_at", desc=True)
        .execute()
    )
    return res.data

def delete_document(doc_id: int, file_name: str):
    client.table("documents").delete().eq("id", doc_id).execute()
    fetch_documents.clear()
    st.toast(f"✅ 已刪除文件：{file_name}")

def fetch_chunks_for_document(doc_id: int):
    res = (
        client.table("document_chunks")
        .select("chunk_index, text_content, metadata")
        .eq("document_id", doc_id)
        .order("chunk_index")
        .execute()
    )
    return res.data

def process_url(url: str, category: str, display_name: str, report_group: str = "", group: str = "", company: str = ""):
    """處理 URL 的完整 Pipeline（自動提取頁面標題）"""
    uploader = Uploader(client)
    doc_info = uploader.process(url)
    if doc_info is None:
        return False, "已存在"
    
    # 使用 parse_with_meta 取得內容 + 標題 + 語言
    parser = UrlParser()
    meta = parser.parse_with_meta(doc_info["source"])
    raw_md = meta["content"]
    page_title = meta["title"]
    page_lang = meta["language"]
    
    cleaned_md = MarkdownCleaner().clean(raw_md)
    chunks = SemanticChunker().chunk(cleaned_md)
    
    if not chunks:
        return False, "無有效內容"
    
    embeddings = None
    if chunks:
        embedder = GeminiEmbedder()
        texts = [c["text_content"] for c in chunks]
        embeddings = embedder.embed_batch(texts)
    
    exporter = SupabaseExporter(client)
    # 優先順序：手動輸入 > 網頁標題 > URL
    if display_name.strip():
        final_name = display_name.strip()
    elif page_title:
        final_name = page_title
    else:
        final_name = doc_info["file_name"]
    
    doc_id = exporter.insert_document(
        doc_info["file_name"],
        doc_info["file_hash"],
        doc_info["source_type"],
        category=category,
        display_name=final_name,
        report_group=report_group if report_group.strip() else None,
        group=group if group.strip() else None,
        company=company if company.strip() else None,
    )
    exporter.insert_chunks(doc_id, chunks, embeddings=embeddings)
    return True, f"{len(chunks)} 段 | 📄 {final_name}"

# ── 側邊欄導覽 ────────────────────────────────────────
with st.sidebar:
    st.title("⚙️ RAG 管理中心")

        
    page = st.radio(
        "選擇功能",
        ["📊 系統概況", "📤 上傳與匯入", "🗃️ 文件管理", "📖 專有名詞字典", "🔍 檢索測試", "💬 AI 問答"],
        label_visibility="collapsed"
    )

# ══════════════════════════════════════════════════════
# 頁面：系統概況
# ══════════════════════════════════════════════════════
if page == "📊 系統概況":
    st.title("📊 系統概況")
    
    doc_count, chunk_count = fetch_system_stats()
    
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

# ══════════════════════════════════════════════════════
# 頁面：上傳與匯入
# ══════════════════════════════════════════════════════
elif page == "📤 上傳與匯入":
    st.title("📤 上傳與匯入")
    
    # ── 共用欄位：分類、命名、報告群組 ──────────────
    col_cat, col_name, col_rg = st.columns(3)
    with col_cat:
        upload_category = st.selectbox(
            "📁 文件分類",
            CATEGORY_OPTIONS,
            index=4,
            key="upload_category"
        )
    with col_name:
        upload_display_name = st.text_input(
            "📝 自訂顯示名稱（留空用檔名）",
            key="upload_display_name"
        )
    with col_rg:
        upload_report_group = st.text_input(
            "📎 所屬報告（拆章節用）",
            placeholder="例如：2024永續報告書",
            key="upload_report_group",
            help="將多個章節歸為同一份報告。整份上傳或非報告可留空。"
        )
    
    # ── 集團 / 子公司 ──────────────────────────────
    col_grp, col_comp = st.columns(2)
    with col_grp:
        # 動態撈取已有的集團名稱
        _grp_res = client.table("documents").select('"group"').not_.is_("group", "null").execute()
        _existing_groups = sorted(set(r["group"] for r in (_grp_res.data or []) if r.get("group")))
        if not _existing_groups:
            _existing_groups = [DEFAULT_GROUP]
        upload_group = st.selectbox(
            "🏢 集團",
            _existing_groups + ["（新增集團）"],
            index=0,
            key="upload_group",
        )
        if upload_group == "（新增集團）":
            upload_group = st.text_input("輸入新集團名稱", key="upload_group_new")
    with col_comp:
        # 動態撈取同集團內的子公司
        if upload_group and upload_group != "（新增集團）":
            _comp_res = client.table("documents").select("company").eq("group", upload_group).not_.is_("company", "null").execute()
            _existing_comps = sorted(set(r["company"] for r in (_comp_res.data or []) if r.get("company")))
        else:
            _existing_comps = []
        if not _existing_comps:
            _existing_comps = [upload_group]  # 預設子公司名 = 集團名
        upload_company = st.selectbox(
            "🏭 子公司",
            _existing_comps + ["（新增子公司）"],
            index=0,
            key="upload_company",
        )
        if upload_company == "（新增子公司）":
            upload_company = st.text_input("輸入新子公司名稱", key="upload_company_new")
    
    st.divider()
    
    # ── 三個子分頁 ─────────────────────────────────
    sub_tab1, sub_tab2, sub_tab3 = st.tabs([
        "📂 PDF / Word 文件",
        "🌐 網頁爬蟲",
        "🎙️ 錄音檔（開發中）"
    ])
    
    # ─────────────────────────────────────────────
    # 子分頁 1：PDF / Word
    # ─────────────────────────────────────────────
    with sub_tab1:
        upload_mode = st.radio(
            "上傳模式",
            ["single", "batch"],
            format_func=lambda x: {"single": "📄 單檔模式（可預覽編輯）", "batch": "📦 批次模式（多檔自動處理）"}[x],
            horizontal=True,
            key="upload_mode",
        )

        # ═══════════════════════════════════════════
        # 單檔模式（原有流程）
        # ═══════════════════════════════════════════
        if upload_mode == "single":
            uploaded_file = st.file_uploader("拖放或選擇 PDF / DOCX 檔案", type=["pdf", "docx", "doc"], key="single_uploader")
            
            # PDF 專用選項
            pdf_mode = "text"
            if uploaded_file and uploaded_file.name.lower().endswith(".pdf"):
                col_mode, col_offset = st.columns([3, 1])
                with col_mode:
                    pdf_mode = st.radio(
                        "PDF 解析模式",
                        ["text", "auto", "vision", "vision_pdf"],
                        index=3,
                        format_func=lambda x: {
                            "text": "📝 純文字（免費）",
                            "auto": "✨ 智能混合",
                            "vision": "👁️ 逐頁 Vision",
                            "vision_pdf": "📄 整份 PDF 上傳（推薦）",
                        }[x],
                        key="pdf_mode",
                        horizontal=True,
                    )
                with col_offset:
                    page_offset = st.number_input(
                        "頁碼偏移",
                        min_value=0, value=0, step=1,
                        key="page_offset",
                        help="整份上傳填 0。拆章節時填起始頁碼 -1。"
                    )
            
            if uploaded_file and st.button("🔍 解析並預覽", type="primary", key="parse_preview"):
                os.makedirs(RAW_DATA_DIR, exist_ok=True)
                # 使用 uuid4 重命名避免 Path Traversal 攻擊
                safe_ext = os.path.splitext(uploaded_file.name)[1].lower()
                temp_path = os.path.join(RAW_DATA_DIR, f"{uuid.uuid4().hex}{safe_ext}")
                with open(temp_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                
                parse_progress = st.progress(0, text="正在解析...")
                
                if uploaded_file.name.lower().endswith(".pdf"):
                    def on_pdf_progress(current, total, mode):
                        pct = int((current / total) * 100)
                        parse_progress.progress(pct, text=f"[{mode}] 第 {current}/{total} 頁")
                    
                    parser = VisionPdfParser(mode=pdf_mode, on_progress=on_pdf_progress)
                    raw_md = parser.parse(temp_path)
                    
                    stats = parser.stats
                    st.caption(
                        f"📊 解析統計：總頁數 {stats['total_pages']} | "
                        f"文字 {stats['text_pages']} 頁 | "
                        f"Vision {stats['vision_pages']} 頁 | "
                        f"跳過 {stats['skipped_pages']} 頁"
                    )
                else:
                    raw_md = DocxParser().parse(temp_path)
                
                parse_progress.progress(100, text="解析完成！")
                cleaned_md = MarkdownCleaner().clean(raw_md)
                
                st.session_state["draft_md"] = cleaned_md
                st.session_state["draft_path"] = temp_path
                st.session_state["draft_filename"] = uploaded_file.name
                st.session_state["draft_page_offset"] = page_offset if uploaded_file.name.lower().endswith(".pdf") else 0
            
            # ── 草稿預覽與校對 ─────────────────────
            if "draft_md" in st.session_state:
                st.divider()
                st.markdown(f"#### 📝 草稿預覽 — {st.session_state.get('draft_filename', '')}")
                st.caption(f"共 {len(st.session_state['draft_md'])} 字元")
                
                col_ai, col_clear = st.columns([1, 1])
                with col_ai:
                    if st.button("🤖 AI 自動校對", key="ai_proofread"):
                        with st.spinner("正在 AI 校對中，請稍候..."):
                            proofreader = AiProofreader()
                            st.session_state["draft_md"] = proofreader.proofread(st.session_state["draft_md"])
                            st.toast("✅ AI 校對完成！")
                            st.rerun()
                with col_clear:
                    if st.button("❌ 放棄草稿", key="discard_draft"):
                        # 清理磁碟上的暫存檔
                        draft_path = st.session_state.get("draft_path")
                        if draft_path and os.path.exists(draft_path):
                            os.remove(draft_path)
                        for key in ["draft_md", "draft_path", "draft_filename", "draft_page_offset"]:
                            st.session_state.pop(key, None)
                        st.rerun()
                
                edited_md = st.text_area(
                    "可直接編輯內容",
                    value=st.session_state["draft_md"],
                    height=400,
                    key="draft_editor"
                )
                
                if st.button("✅ 確認入庫", type="primary", key="confirm_ingest"):
                    progress = st.progress(0, text="正在處理...")
                    
                    uploader = Uploader(client)
                    doc_info = uploader.process(st.session_state["draft_path"])
                    if doc_info is None:
                        st.warning("⚠️ 此文件已存在於資料庫中。")
                        progress.empty()
                    else:
                        progress.progress(30, text="切割中...")
                        chunks = SemanticChunker().chunk(edited_md)
                        
                        # 套用頁碼偏移
                        offset = st.session_state.get("draft_page_offset", 0)
                        if offset > 0:
                            for c in chunks:
                                meta = c.get("metadata", {})
                                if meta.get("page_start") is not None:
                                    meta["page_start"] += offset
                                if meta.get("page_end") is not None:
                                    meta["page_end"] += offset
                        
                        embeddings = None
                        if chunks:
                            progress.progress(50, text=f"向量嵌入中 ({len(chunks)} 段)...")
                            embedder = GeminiEmbedder()
                            texts = [c["text_content"] for c in chunks]
                            try:
                                embeddings = embedder.embed_batch(texts)
                            except Exception as e:
                                st.error(f"向量產生失敗：{e}")
                                progress.empty()
                        
                        if chunks:
                            progress.progress(80, text="寫入資料庫...")
                            exporter = SupabaseExporter(client)
                            # 使用原始中文檔名（而非 uuid 暫存檔名）
                            original_filename = st.session_state.get("draft_filename", doc_info["file_name"])
                            final_name = upload_display_name.strip() if upload_display_name.strip() else os.path.splitext(original_filename)[0]
                            rg = upload_report_group.strip() if upload_report_group.strip() else None
                            doc_id = exporter.insert_document(
                                original_filename,
                                doc_info["file_hash"],
                                doc_info["source_type"],
                                category=upload_category,
                                display_name=final_name,
                                report_group=rg,
                                group=upload_group if upload_group else None,
                                company=upload_company if upload_company else None,
                            )
                            exporter.insert_chunks(doc_id, chunks, embeddings=embeddings)
                            
                            progress.progress(100, text="完成！")
                            group_info = f" [報告: {rg}]" if rg else ""
                            st.success(f"✅ 入庫成功：**{final_name}**{group_info} ({len(chunks)} 段)")
                            
                            # 清理磁碟上的暫存檔
                            draft_path = st.session_state.get("draft_path")
                            if draft_path and os.path.exists(draft_path):
                                os.remove(draft_path)
                            for key in ["draft_md", "draft_path", "draft_filename", "draft_page_offset"]:
                                st.session_state.pop(key, None)

        # ═══════════════════════════════════════════
        # 批次模式（多檔自動處理）
        # ═══════════════════════════════════════════
        else:
            st.info("📦 批次模式：一次上傳多個 PDF / DOCX 檔案，系統將自動依序處理（解析→清洗→切割→嵌入→入庫），不進入預覽編輯流程。")
            
            batch_pdf_mode = st.radio(
                "PDF 解析模式（套用至所有 PDF）",
                ["text", "auto", "vision", "vision_pdf"],
                index=3,
                format_func=lambda x: {
                    "text": "📝 純文字（免費）",
                    "auto": "✨ 智能混合",
                    "vision": "👁️ 逐頁 Vision",
                    "vision_pdf": "📄 整份 PDF 上傳（推薦）",
                }[x],
                key="batch_pdf_mode",
                horizontal=True,
            )
            
            batch_files = st.file_uploader(
                "拖放或選擇多個 PDF / DOCX 檔案",
                type=["pdf", "docx", "doc"],
                accept_multiple_files=True,
                key="batch_uploader",
            )
            
            if batch_files and st.button(f"🚀 開始處理 {len(batch_files)} 個檔案", type="primary", key="batch_start"):
                os.makedirs(RAW_DATA_DIR, exist_ok=True)
                
                results_container = st.container()
                overall_progress = st.progress(0, text="準備中...")
                
                success_count = 0
                skip_count = 0
                fail_count = 0
                
                for idx, bf in enumerate(batch_files):
                    file_label = bf.name
                    pct = int(((idx) / len(batch_files)) * 100)
                    overall_progress.progress(pct, text=f"處理中 ({idx+1}/{len(batch_files)})：{file_label}")
                    
                    temp_path = None
                    try:
                        # 1) 暫存
                        safe_ext = os.path.splitext(bf.name)[1].lower()
                        temp_path = os.path.join(RAW_DATA_DIR, f"{uuid.uuid4().hex}{safe_ext}")
                        with open(temp_path, "wb") as f:
                            f.write(bf.getbuffer())
                        
                        # 2) 去重
                        uploader_obj = Uploader(client)
                        doc_info = uploader_obj.process(temp_path)
                        if doc_info is None:
                            skip_count += 1
                            results_container.warning(f"⏭️ {file_label} — 已存在，跳過")
                            continue
                        
                        # 3) 解析
                        if safe_ext == ".pdf":
                            parser = VisionPdfParser(mode=batch_pdf_mode)
                            raw_md = parser.parse(temp_path)
                        else:
                            raw_md = DocxParser().parse(temp_path)
                        
                        # 4) 清洗 + 切割
                        cleaned_md = MarkdownCleaner().clean(raw_md)
                        chunks = SemanticChunker().chunk(cleaned_md)
                        
                        if not chunks:
                            fail_count += 1
                            results_container.error(f"❌ {file_label} — 解析後無有效內容")
                            continue
                        
                        # 5) 嵌入
                        embeddings = None
                        if chunks:
                            embedder = GeminiEmbedder()
                            texts = [c["text_content"] for c in chunks]
                            embeddings = embedder.embed_batch(texts)
                        
                        # 6) 寫入 DB
                        exporter = SupabaseExporter(client)
                        display = upload_display_name.strip() if upload_display_name.strip() else os.path.splitext(bf.name)[0]
                        rg = upload_report_group.strip() if upload_report_group.strip() else None
                        doc_id = exporter.insert_document(
                            bf.name,
                            doc_info["file_hash"],
                            doc_info["source_type"],
                            category=upload_category,
                            display_name=display if len(batch_files) == 1 else os.path.splitext(bf.name)[0],
                            report_group=rg,
                            group=upload_group if upload_group else None,
                            company=upload_company if upload_company else None,
                        )
                        exporter.insert_chunks(doc_id, chunks, embeddings=embeddings)
                        
                        success_count += 1
                        results_container.success(f"✅ {file_label} — {len(chunks)} 段已入庫")
                    
                    except Exception as e:
                        fail_count += 1
                        results_container.error(f"❌ {file_label} — 失敗：{e}")
                    
                    finally:
                        # 清理暫存檔
                        if temp_path and os.path.exists(temp_path):
                            os.remove(temp_path)
                
                overall_progress.progress(100, text="全部完成！")
                st.divider()
                st.markdown(
                    f"### 📊 批次處理結果\n"
                    f"- ✅ 成功：**{success_count}** 個\n"
                    f"- ⏭️ 跳過（重複）：**{skip_count}** 個\n"
                    f"- ❌ 失敗：**{fail_count}** 個"
                )
    
    # ─────────────────────────────────────────────
    # 子分頁 2：網頁爬蟲
    # ─────────────────────────────────────────────
    with sub_tab2:
        web_mode = st.radio(
            "匯入方式",
            ["single", "sitemap", "crawler"],
            format_func=lambda x: {
                "single": "🔗 單一網址",
                "sitemap": "🗺️ Sitemap 批次",
                "crawler": "🕷️ 全站爬蟲",
            }[x],
            horizontal=True,
            key="web_mode",
        )
        
        if web_mode == "single":
            url_input = st.text_input("輸入完整網址", placeholder="https://...")
            if url_input and st.button("開始抓取", type="primary", key="fetch_url"):
                with st.spinner("正在抓取..."):
                    try:
                        ok, msg = process_url(url_input, upload_category, upload_display_name, upload_report_group, upload_group, upload_company)
                        if ok:
                            st.success(f"✅ 入庫成功：{msg}")
                        else:
                            st.warning(f"⚠️ {msg}")
                    except Exception as e:
                        st.error(f"❌ 失敗：{e}")
        
        elif web_mode == "sitemap":
            sitemap_url = st.text_input("Sitemap URL", placeholder="https://example.com/sitemap.xml", key="sitemap_url")
            sitemap_filter = st.text_input("排除關鍵字（逗號分隔）", help="例如 /en/ 排除英文頁", key="sitemap_filter")
            
            if sitemap_url and st.button("解析 Sitemap", key="parse_sitemap"):
                import xml.etree.ElementTree as ET
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                
                with st.spinner("正在解析 Sitemap..."):
                    try:
                        import requests as req
                        try:
                            resp = req.get(sitemap_url, timeout=30)
                        except req.exceptions.SSLError:
                            resp = req.get(sitemap_url, timeout=30, verify=False)
                        resp.raise_for_status()
                        
                        root = ET.fromstring(resp.content)
                        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
                        all_urls = [loc.text for loc in root.findall(".//s:loc", ns) if loc.text]
                        
                        exclude_keywords = [kw.strip() for kw in sitemap_filter.split(",") if kw.strip()]
                        if exclude_keywords:
                            filtered = [u for u in all_urls if not any(kw in u for kw in exclude_keywords)]
                        else:
                            filtered = all_urls
                        
                        st.session_state["sitemap_urls"] = filtered
                        st.session_state["sitemap_all_count"] = len(all_urls)
                    except Exception as e:
                        st.error(f"解析失敗：{e}")
            
            if "sitemap_urls" in st.session_state and st.session_state["sitemap_urls"]:
                urls = st.session_state["sitemap_urls"]
                total = st.session_state.get("sitemap_all_count", len(urls))
                st.success(f"找到 {total} 個 URL，篩選後 **{len(urls)}** 個")
                
                with st.expander(f"預覽 URL 列表", expanded=False):
                    for i, u in enumerate(urls, 1):
                        st.text(f"{i}. {u}")
                
                if st.button(f"🚀 批次匯入 ({len(urls)} 個)", type="primary", key="batch_import"):
                    bp = st.progress(0)
                    ok_n, skip_n, fail_n = 0, 0, 0
                    status = st.empty()
                    
                    for i, url in enumerate(urls):
                        bp.progress(int((i / len(urls)) * 100), text=f"({i+1}/{len(urls)})")
                        try:
                            ok, _ = process_url(url, upload_category, "", upload_report_group, upload_group, upload_company)
                            ok_n += 1 if ok else 0
                            skip_n += 0 if ok else 1
                        except Exception:
                            fail_n += 1
                        status.caption(f"✅{ok_n} ⏭️{skip_n} ❌{fail_n}")
                    
                    bp.progress(100, text="完成！")
                    st.balloons()
                    del st.session_state["sitemap_urls"]
        
        else:  # crawler
            crawler_root = st.text_input("網站根 URL", placeholder="https://example.com/", key="crawler_root")
            col_d, col_m = st.columns(2)
            with col_d:
                crawler_depth = st.slider("最大深度", 1, 10, 5, key="crawler_depth")
            with col_m:
                crawler_max = st.slider("最大頁數", 10, 2000, 500, key="crawler_max")
            
            crawler_exclude = st.text_input("排除路徑（逗號分隔）", value="/en/", key="crawler_exclude")
            
            if crawler_root and st.button("🔍 開始掃描", key="start_crawl"):
                exclude_list = [p.strip() for p in crawler_exclude.split(",") if p.strip()]
                status = st.empty()
                cp = st.progress(0)
                
                def on_crawl(found, visited, current):
                    cp.progress(min(int((visited / crawler_max) * 100), 99))
                    status.caption(f"發現 {found} 頁 | 掃描 {visited} 連結 | {current[:60]}...")
                
                crawler = SiteCrawler(
                    root_url=crawler_root, max_pages=crawler_max,
                    max_depth=crawler_depth, exclude_patterns=exclude_list,
                    on_progress=on_crawl,
                )
                discovered = crawler.crawl()
                cp.progress(100, text="掃描完成！")
                status.empty()
                st.session_state["crawler_urls"] = discovered
            
            if "crawler_urls" in st.session_state and st.session_state["crawler_urls"]:
                c_urls = st.session_state["crawler_urls"]
                st.success(f"共發現 **{len(c_urls)}** 個頁面")
                
                with st.expander("預覽 URL", expanded=False):
                    for i, u in enumerate(c_urls, 1):
                        st.text(f"{i}. {u}")
                
                if st.button(f"🚀 批次入庫 ({len(c_urls)} 個)", type="primary", key="crawl_batch"):
                    bp = st.progress(0)
                    ok_n, skip_n, fail_n = 0, 0, 0
                    status = st.empty()
                    error_display = st.empty()
                    recent_errors = []
                    
                    for i, url in enumerate(c_urls):
                        bp.progress(int((i / len(c_urls)) * 100), text=f"({i+1}/{len(c_urls)})")
                        try:
                            ok, msg = process_url(url, upload_category, "", upload_report_group, upload_group, upload_company)
                            if ok:
                                ok_n += 1
                            else:
                                skip_n += 1
                        except Exception as e:
                            fail_n += 1
                            err_msg = f"{url[:50]}... → {type(e).__name__}: {str(e)[:100]}"
                            recent_errors.append(err_msg)
                            recent_errors = recent_errors[-3:]  # 只保留最近 3 筆
                            error_display.error("最近錯誤：\n" + "\n".join(recent_errors))
                        status.caption(f"✅{ok_n} ⏭️{skip_n} ❌{fail_n}")
                    
                    bp.progress(100, text="完成！")
                    if ok_n > 0:
                        st.balloons()
                    if recent_errors:
                        st.error(f"共 {fail_n} 筆失敗。最後錯誤：\n" + "\n".join(recent_errors))
                    del st.session_state["crawler_urls"]
    
    # ─────────────────────────────────────────────
    # 子分頁 3：錄音檔（佔位）
    # ─────────────────────────────────────────────
    with sub_tab3:
        st.markdown("**🎙️ 上傳錄音檔 → Gemini 轉錄 → 審校 → 入庫**")
        st.caption(f"支援格式：{', '.join(AudioParser.get_supported_formats())}")
        
        if True:
            audio_file = st.file_uploader(
                "上傳錄音檔",
                type=[ext.lstrip('.') for ext in AudioParser.get_supported_formats()],
                key="audio_upload"
            )
            
            a_col1, a_col2 = st.columns(2)
            audio_category = a_col1.selectbox("分類", CATEGORY_OPTIONS, index=CATEGORY_OPTIONS.index("會議紀錄") if "會議紀錄" in CATEGORY_OPTIONS else 0, key="audio_cat")
            audio_name = a_col2.text_input("文件名稱（選填，自動以檔名命名）", key="audio_name")
            
            if audio_file and st.button("🎤 開始轉錄", type="primary", key="start_transcribe"):
                import tempfile
                # 儲存暫存檔
                with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(audio_file.name)[1]) as tmp:
                    tmp.write(audio_file.read())
                    tmp_path = tmp.name
                
                progress_placeholder = st.empty()
                
                def on_progress(msg):
                    progress_placeholder.info(msg)
                
                try:
                    # 載入專有名詞字典
                    terms_dict = {}
                    try:
                        terms_res = client.table("terms_dictionary").select("term, full_name").execute()
                        terms_dict = {t["term"]: t["full_name"] for t in (terms_res.data or [])}
                    except Exception:
                        pass  # 字典表可能尚未建立
                    
                    parser = AudioParser(on_progress=on_progress)
                    result = parser.parse(tmp_path, terms_dict=terms_dict)
                    
                    progress_placeholder.success("轉錄完成！")
                    
                    if result["terms_applied"]:
                        st.info(f"已自動替換 {len(result['terms_applied'])} 個專有名詞：{', '.join(result['terms_applied'])}")
                    
                    # 儲存到 session state 供編輯
                    st.session_state["audio_transcript"] = result["corrected_transcript"]
                    st.session_state["audio_file_name"] = audio_file.name
                
                except Exception as e:
                    progress_placeholder.error(f"轉錄失敗：{e}")
                finally:
                    os.unlink(tmp_path)
            
            # ── 草稿編輯區 ──────────────────────
            if "audio_transcript" in st.session_state:
                st.divider()
                st.markdown("#### ✏️ 草稿審校")
                st.caption("請檢查並修正講者名稱、專有名詞、聽不清楚的段落")
                
                edited_transcript = st.text_area(
                    "轉錄內容（可直接編輯）",
                    value=st.session_state["audio_transcript"],
                    height=400,
                    key="audio_editor"
                )
                
                ac1, ac2, ac3 = st.columns(3)
                
                with ac1:
                    if st.button("📥 確認入庫", type="primary", key="audio_save"):
                        if edited_transcript.strip():
                            # 清洗 → Chunk → Embed → 入庫
                            cleaned = MarkdownCleaner().clean(edited_transcript)
                            chunks = SemanticChunker().chunk(cleaned)
                            
                            if chunks:
                                embeddings = None
                                if chunks:
                                    embedder = GeminiEmbedder()
                                    texts = [c["text_content"] for c in chunks]
                                    embeddings = embedder.embed_batch(texts)
                                
                                exporter = SupabaseExporter(client)
                                fname = st.session_state.get("audio_file_name", "audio_recording")
                                final_name = audio_name.strip() if audio_name.strip() else fname
                                
                                import hashlib
                                file_hash = hashlib.sha256(edited_transcript.encode()).hexdigest()
                                doc_id = exporter.insert_document(
                                    fname, file_hash, "audio",
                                    category=audio_category,
                                    display_name=final_name,
                                )
                                exporter.insert_chunks(doc_id, chunks, embeddings=embeddings)
                                st.success(f"✅ 已入庫：{final_name}（{len(chunks)} 段）")
                                del st.session_state["audio_transcript"]
                                del st.session_state["audio_file_name"]
                            else:
                                st.warning("清洗後無有效內容")
                        else:
                            st.warning("轉錄內容為空")
                
                with ac2:
                    st.download_button(
                        "💾 下載 Markdown",
                        data=edited_transcript,
                        file_name=f"{st.session_state.get('audio_file_name', 'transcript')}.md",
                        mime="text/markdown",
                        key="audio_download"
                    )
                
                with ac3:
                    if st.button("🗑️ 捨棄草稿", key="audio_discard"):
                        del st.session_state["audio_transcript"]
                        del st.session_state["audio_file_name"]
                        st.rerun()

# ══════════════════════════════════════════════════════
# 頁面：文件管理（inline 編輯 + 分類群組）
# ══════════════════════════════════════════════════════
elif page == "🗃️ 文件管理":
    st.title("🗃️ 文件管理")
    
    docs = fetch_documents()
    if not docs:
        st.info("目前資料庫中沒有任何文件。")
    else:
        df = pd.DataFrame(docs)
        df["created_at"] = pd.to_datetime(df["created_at"]).dt.strftime("%Y-%m-%d %H:%M")
        
        # 確保欄位存在（相容舊資料）
        for col, default in [("category", "其他"), ("display_name", None), ("report_group", None),
                             ("group", None), ("company", None),
                             ("language", "zh-TW"), ("status", "已發布"), ("confidentiality", "公開"),
                             ("fiscal_year", None), ("tags", None)]:
            if col not in df.columns:
                df[col] = default
        df["display_name"] = df["display_name"].fillna(df["file_name"])
        df["report_group"] = df["report_group"].fillna("")
        df["group"] = df["group"].fillna("")
        df["company"] = df["company"].fillna("")
        df["language"] = df["language"].fillna("zh-TW")
        df["status"] = df["status"].fillna("已發布")
        df["confidentiality"] = df["confidentiality"].fillna("公開")
        df["fiscal_year"] = df["fiscal_year"].fillna("")
        
        # ── 篩選列 ──────────────────────────
        f_col1, f_col2 = st.columns(2)
        with f_col1:
            lang_options = ["全部"] + sorted(df["language"].unique().tolist())
            filter_lang = st.selectbox("🌐 篩選語言", lang_options, key="filter_lang")
        with f_col2:
            cat_options = ["全部"] + sorted(df["category"].unique().tolist())
            filter_cat = st.selectbox("📂 篩選分類", cat_options, key="filter_cat")
        
        # 套用篩選
        filtered_df = df.copy()
        if filter_lang != "全部":
            filtered_df = filtered_df[filtered_df["language"] == filter_lang]
        if filter_cat != "全部":
            filtered_df = filtered_df[filtered_df["category"] == filter_cat]
        
        st.caption(f"顯示 {len(filtered_df)} / {len(df)} 份文件")
        
        # ── 按分類分群顯示 ─────────────────────
        categories = sorted(filtered_df["category"].unique())
        
        for cat in categories:
            cat_df = filtered_df[filtered_df["category"] == cat].copy()
            
            with st.expander(f"📂 {cat}（{len(cat_df)} 份）", expanded=False):
                # 使用 data_editor 實現 inline 編輯
                edit_df = cat_df[["id", "display_name", "category", "group", "company", "report_group",
                                  "language", "status", "confidentiality", "fiscal_year",
                                  "source_type", "created_at"]].copy()
                
                edited = st.data_editor(
                    edit_df,
                    column_config={
                        "id": st.column_config.NumberColumn("ID", disabled=True, width="small"),
                        "display_name": st.column_config.TextColumn("文件名稱", width="large"),
                        "category": st.column_config.SelectboxColumn("分類", options=CATEGORY_OPTIONS, width="small"),
                        "group": st.column_config.TextColumn("集團", width="small"),
                        "company": st.column_config.TextColumn("子公司", width="small"),
                        "report_group": st.column_config.TextColumn("所屬報告", width="medium"),
                        "language": st.column_config.SelectboxColumn("語言", options=LANGUAGE_OPTIONS, width="small"),
                        "status": st.column_config.SelectboxColumn("狀態", options=STATUS_OPTIONS, width="small"),
                        "confidentiality": st.column_config.SelectboxColumn("機密", options=CONFIDENTIALITY_OPTIONS, width="small"),
                        "fiscal_year": st.column_config.TextColumn("年度", width="small"),
                        "source_type": st.column_config.TextColumn("格式", disabled=True, width="small"),
                        "created_at": st.column_config.TextColumn("入庫時間", disabled=True, width="medium"),
                    },
                    hide_index=True,
                    use_container_width=True,
                    num_rows="fixed",
                    key=f"editor_{cat}",
                )
                
                # 偵測變更並儲存
                col_save, col_del = st.columns([1, 1])
                
                with col_save:
                    if st.button(f"💾 儲存 {cat} 的修改", key=f"save_{cat}"):
                        changes = 0
                        editable_cols = ["display_name", "category", "group", "company", "report_group",
                                         "language", "status", "confidentiality", "fiscal_year"]
                        for idx, row in edited.iterrows():
                            orig = edit_df[edit_df["id"] == row["id"]]
                            if orig.empty:
                                continue
                            orig_row = orig.iloc[0]
                            updates = {}
                            for col in editable_cols:
                                new_val = row[col]
                                old_val = orig_row[col]
                                if str(new_val) != str(old_val):
                                    updates[col] = new_val if new_val else None
                            if updates:
                                client.table("documents").update(updates).eq("id", row["id"]).execute()
                                changes += 1
                        if changes:
                            fetch_documents.clear()
                            st.toast(f"✅ 已更新 {changes} 份文件")
                            st.rerun()
                        else:
                            st.toast("沒有偵測到修改")
                
                with col_del:
                    delete_ids = st.multiselect(
                        "選擇要刪除的文件",
                        options=cat_df["id"].tolist(),
                        format_func=lambda x: f"ID {x} — {cat_df[cat_df['id']==x]['display_name'].values[0]}",
                        key=f"del_{cat}",
                    )
                    if delete_ids and st.button(f"🗑️ 刪除 {len(delete_ids)} 份", key=f"del_confirm_{cat}"):
                        for doc_id in delete_ids:
                            fname = cat_df[cat_df["id"] == doc_id]["file_name"].values[0]
                            delete_document(doc_id, fname)
                        st.rerun()
        
        # ── Chunk 預覽 ────────────────────────────
        st.divider()
        st.markdown("#### 📖 檢視文件 Chunk 內容")
        preview_id = st.selectbox(
            "選擇文件",
            options=df["id"].tolist(),
            format_func=lambda x: f"ID {x} — {df[df['id']==x]['display_name'].values[0]}",
            key="preview_select"
        )
        if st.button("載入 Chunk", key="load_chunks"):
            chunks = fetch_chunks_for_document(preview_id)
            if not chunks:
                st.info("此文件沒有 Chunk 資料。")
            else:
                preview_name = df[df["id"] == preview_id]["display_name"].values[0]
                st.markdown(f"**{preview_name}** — 共 {len(chunks)} 個 Chunk")
                for chunk in chunks:
                    idx = chunk["chunk_index"]
                    meta = chunk.get("metadata") or {}
                    title = meta.get("section_title", "")
                    ps = meta.get("page_start")
                    pe = meta.get("page_end")
                    label = f"Chunk #{idx}"
                    if title:
                        label += f" | 🔖 {title}"
                    if ps:
                        label += f" | 📄 第{ps}{f'-{pe}' if pe and pe != ps else ''}頁"
                    with st.expander(label, expanded=False):
                        st.markdown(chunk["text_content"])

# ══════════════════════════════════════════════════════
# 頁面：檢索測試
# ══════════════════════════════════════════════════════
elif page == "🔍 檢索測試":
    st.title("🔍 檢索測試 (Semantic Search)")
    

    
    with st.form("search_form"):
        query = st.text_input("輸入查詢問題", placeholder="例如：公司碳排放目標是什麼？")
        
        c1, c2 = st.columns(2)
        top_k = c1.slider("回傳筆數 (Top K)", 1, 20, 5)
        threshold = c2.slider("相似度門檻", 0.0, 1.0, 0.5, step=0.05)
        
        submitted = st.form_submit_button("開始搜尋", type="primary")

    if submitted and query:
        with st.spinner("搜尋中..."):
            retriever = SemanticRetriever(client)
            results = retriever.search(query, top_k=top_k, threshold=threshold)
            
        if not results:
            st.warning("找不到符合門檻的結果，請降低 Threshold。")
        else:
            st.success(f"找到 {len(results)} 筆結果：")
            
            for i, res in enumerate(results, 1):
                sim = res["similarity"]
                fname = res["file_name"]
                stype = res["source_type"]
                metadata = res["metadata"]
                title = metadata.get("section_title", "無章節")
                text = res["text_content"]
                doc_id = res["document_id"]
                chunk_idx = res["chunk_index"]
                
                # 頁碼資訊
                ps = metadata.get("page_start")
                pe = metadata.get("page_end")
                page_info = ""
                if ps:
                    page_info = f" | 📄 第{ps}{f'-{pe}' if pe and pe != ps else ''}頁"
                
                with st.expander(f"[{i}] 相似度 {sim:.4f} | 📄 {fname} | 🔖 {title}{page_info}", expanded=(i==1)):
                    st.caption(f"來源：{stype} · Chunk #{chunk_idx} · Doc ID: {doc_id}")
                    st.markdown("---")
                    st.markdown(text)
                    
                    # 上下文擴展按鈕
                    if st.button(f"📖 顯示上下文", key=f"ctx_{i}"):
                        # 載入前後 chunk
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

# ══════════════════════════════════════════════════════
# 頁面：AI 問答（RAG Chatbot）
# ══════════════════════════════════════════════════════
elif page == "💬 AI 問答":
    st.title("💬 AI 問答 (RAG Chatbot)")
    

    
    # ── 側邊欄搜尋設定 ────────────────────────────
    with st.sidebar:
        st.divider()
        st.markdown("#### 🔧 搜尋設定")
        search_mode = st.radio(
            "搜尋模式",
            ["hybrid", "hybrid_rerank"],
            format_func=lambda x: {
                "hybrid": "🔍 混合搜尋（免費）",
                "hybrid_rerank": "🎯 混合 + AI 精排",
            }[x],
            key="chat_search_mode",
            help="混合搜尋結合向量語義和關鍵字匹配。AI 精排會多一次 API 呼叫。"
        )
        chat_top_k = st.slider("參考段落數", 3, 10, 5, key="chat_top_k")
        
        # ── 進階篩選 ──────────────────────────────
        with st.expander("▶ 進階篩選", expanded=False):
            # 動態撈取選項
            _all_docs = client.table("documents").select('"group", company, fiscal_year, category').execute().data or []
            _all_groups = sorted(set(r["group"] for r in _all_docs if r.get("group")))
            _all_companies = sorted(set(r["company"] for r in _all_docs if r.get("company")))
            _all_years = sorted(set(r["fiscal_year"] for r in _all_docs if r.get("fiscal_year")), reverse=True)
            _all_cats = sorted(set(r["category"] for r in _all_docs if r.get("category")))
            
            if not _all_groups:
                _all_groups = [DEFAULT_GROUP]
            
            # 集團（多選，預設台泥企業團）
            chat_groups = st.multiselect(
                "🏢 集團",
                _all_groups,
                default=[DEFAULT_GROUP] if DEFAULT_GROUP in _all_groups else _all_groups[:1],
                key="chat_groups",
            )
            
            # 子公司（checkbox 全部 + 多選鎖定）
            if chat_groups:
                _grp_companies = sorted(set(
                    r["company"] for r in _all_docs
                    if r.get("company") and r.get("group") in chat_groups
                ))
            else:
                _grp_companies = _all_companies
            
            chat_company_all = st.checkbox("全部子公司", value=True, key="chat_company_all")
            if chat_company_all:
                chat_companies = st.multiselect("🏭 子公司", _grp_companies, default=_grp_companies, disabled=True, key="chat_companies")
            else:
                chat_companies = st.multiselect("🏭 子公司", _grp_companies, key="chat_companies")
            
            # 年度（checkbox 全部 + 多選鎖定）
            chat_year_all = st.checkbox("全部年度", value=True, key="chat_year_all")
            if chat_year_all:
                chat_years = st.multiselect("📅 年度", _all_years, default=_all_years, disabled=True, key="chat_years")
            else:
                chat_years = st.multiselect("📅 年度", _all_years, key="chat_years")
            
            # 報告類別（checkbox 全部 + 多選鎖定）
            chat_cat_all = st.checkbox("全部類別", value=True, key="chat_cat_all")
            if chat_cat_all:
                chat_categories = st.multiselect("📂 報告類別", _all_cats, default=_all_cats, disabled=True, key="chat_categories")
            else:
                chat_categories = st.multiselect("📂 報告類別", _all_cats, key="chat_categories")
        
        if st.button("🗑️ 清除對話", key="clear_chat"):
            st.session_state["chat_history"] = []
            st.rerun()
    
    # ── 解析篩選條件 ──────────────────────────────
    _selected_group = chat_groups[0] if len(chat_groups) == 1 else None
    _selected_company = None
    if not chat_company_all and len(chat_companies) == 1:
        _selected_company = chat_companies[0]
    _selected_fiscal_year = None
    if not chat_year_all and len(chat_years) == 1:
        _selected_fiscal_year = chat_years[0]
    
    # ── 初始化對話歷史 ────────────────────────────
    if "chat_history" not in st.session_state:
        st.session_state["chat_history"] = []
    
    # ── 顯示歷史訊息 ──────────────────────────────
    for msg in st.session_state["chat_history"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            # 顯示來源（如果有）
            if msg.get("sources"):
                with st.expander(f"📚 引用來源 ({len(msg['sources'])} 筆)", expanded=False):
                    for src in msg["sources"]:
                        page_info = ""
                        if src.get("page_start"):
                            ps = src["page_start"]
                            pe = src.get("page_end")
                            page_info = f" · 📄 第{ps}{f'-{pe}' if pe and pe != ps else ''}頁"
                        
                        section = f" · 🔖 {src['section_title']}" if src.get("section_title") else ""
                        search_badge = f" · 🏷️ {src['search_type']}" if src.get("search_type") else ""
                        
                        st.caption(
                            f"**[來源{src['index']}]** {src['document_name']}"
                            f"{page_info}{section}{search_badge}"
                        )
    
    # ── 聊天輸入 ──────────────────────────────────
    if prompt := st.chat_input("請輸入您的問題..."):
        # 顯示使用者訊息
        st.session_state["chat_history"].append({
            "role": "user",
            "content": prompt,
        })
        with st.chat_message("user"):
            st.markdown(prompt)
        
        # 生成 AI 回答
        with st.chat_message("assistant"):
            rag = RagChat(client)
            
            # 傳入歷史對話（不含來源資訊）
            history_for_rag = [
                {"role": m["role"], "content": m["content"]}
                for m in st.session_state["chat_history"][:-1]  # 排除剛加入的
            ]
            
            # 判斷是否觸發多輪比較
            _is_compare = False
            _compare_groups = []
            
            if len(chat_groups) >= 2:
                # 多集團比較
                _is_compare = True
                _compare_groups = [{"group": g} for g in chat_groups]
            else:
                # Regex 偵測比較意圖
                _known = _all_companies if '_all_companies' in dir() else []
                _detect = rag.detect_comparison(prompt, _known)
                if _detect and _detect.get("dimension") == "company" and len(_detect.get("values", [])) >= 2:
                    _is_compare = True
                    _compare_groups = [{"company": v} for v in _detect["values"]]
            
            if _is_compare:
                with st.spinner("比較搜尋中..."):
                    result = rag.ask_compare(
                        question=prompt,
                        groups=_compare_groups,
                        history=history_for_rag,
                        search_mode=search_mode,
                        top_k=chat_top_k,
                        language=None,
                        source="admin_ui_compare",
                    )
                    sources = result["sources"]
            else:
                # 普通搜尋
                with st.spinner("搜尋知識庫中..."):
                    result = rag.ask_stream(
                        question=prompt,
                        history=history_for_rag,
                        search_mode=search_mode,
                        top_k=chat_top_k,
                        fiscal_year=_selected_fiscal_year,
                        group=_selected_group,
                        company=_selected_company,
                    )
                    sources = result["sources"]
            
            # 串流輸出答案（逐 token 顯示）
            answer_text = st.write_stream(result["stream"])
            
            # 顯示來源
            if sources:
                with st.expander(f"📚 引用來源 ({len(sources)} 筆)", expanded=False):
                    for src in sources:
                        page_info = ""
                        if src.get("page_start"):
                            ps = src["page_start"]
                            pe = src.get("page_end")
                            page_info = f" · 📄 第{ps}{f'-{pe}' if pe and pe != ps else ''}頁"
                        
                        section = f" · 🔖 {src['section_title']}" if src.get("section_title") else ""
                        sim = f" · 相似度 {src['similarity']:.3f}" if src.get("similarity") else ""
                        search_badge = f" · 🏷️ {src['search_type']}" if src.get("search_type") else ""
                        
                        st.caption(
                            f"**[來源{src['index']}]** {src['document_name']}"
                            f"{page_info}{section}{sim}{search_badge}"
                        )
            
            # 儲存助手回答到歷史（含 chunk IDs 用於回饋）
            chunk_ids = [r.get("id") for r in result.get("search_results", []) if r.get("id")]
            msg_idx = len(st.session_state["chat_history"])
            st.session_state["chat_history"].append({
                "role": "assistant",
                "content": answer_text,
                "sources": sources,
                "question": prompt,
                "chunk_ids": chunk_ids,
                "msg_idx": msg_idx,
            })
    
    # ── 回饋按鈕（只對最新一則未回饋的 AI 回答顯示）────
    last_assistant_idx = None
    for i, msg in enumerate(st.session_state["chat_history"]):
        if msg["role"] == "assistant" and not msg.get("feedback_sent"):
            last_assistant_idx = i

    if last_assistant_idx is not None:
        msg = st.session_state["chat_history"][last_assistant_idx]
        fb_key = f"fb_{last_assistant_idx}"
        col_up, col_down, col_spacer = st.columns([1, 1, 8])
        with col_up:
            if st.button("👍", key=f"{fb_key}_up", help="回答有幫助"):
                try:
                    client.table("qa_feedback").insert({
                        "question": msg.get("question", ""),
                        "answer": msg["content"],
                        "rating": "up",
                        "chunk_ids": msg.get("chunk_ids", []),
                    }).execute()
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).error(f"回饋寫入失敗：{e}")
                msg["feedback_sent"] = True
                st.toast("✅ 感謝回饋！")
                st.rerun()
        with col_down:
            if st.button("👎", key=f"{fb_key}_down", help="回答需改善"):
                try:
                    client.table("qa_feedback").insert({
                        "question": msg.get("question", ""),
                        "answer": msg["content"],
                        "rating": "down",
                        "chunk_ids": msg.get("chunk_ids", []),
                    }).execute()
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).error(f"回饋寫入失敗：{e}")
                msg["feedback_sent"] = True
                st.toast("📝 感謝回饋，我們會持續改進！")
                st.rerun()

# ══════════════════════════════════════════════════════
# 頁面：專有名詞字典管理
# ══════════════════════════════════════════════════════
elif page == "📖 專有名詞字典":
    st.title("📖 專有名詞字典")
    st.caption("管理錄音轉錄和文件清洗時自動替換的專有名詞")
    
    # 載入現有字典
    try:
        terms_res = client.table("terms_dictionary").select("*").order("category").order("term").execute()
        terms_data = terms_res.data or []
    except Exception as e:
        st.error(f"無法載入字典（可能尚未執行 migrate_terms_dict.sql）：{e}")
        terms_data = []
    
    if terms_data:
        terms_df = pd.DataFrame(terms_data)
        
        # 分類統計
        cat_counts = terms_df["category"].value_counts()
        cols = st.columns(len(cat_counts))
        for i, (cat, count) in enumerate(cat_counts.items()):
            cols[i].metric(cat, f"{count} 詞")
        
        st.divider()
        
        # 可編輯表格
        TERM_CATEGORIES = ["一般", "人名", "組織", "技術"]
        edit_terms = terms_df[["id", "term", "full_name", "category", "language"]].copy()
        
        edited_terms = st.data_editor(
            edit_terms,
            column_config={
                "id": st.column_config.NumberColumn("ID", disabled=True, width="small"),
                "term": st.column_config.TextColumn("原始詞", width="medium"),
                "full_name": st.column_config.TextColumn("完整名稱", width="large"),
                "category": st.column_config.SelectboxColumn("分類", options=TERM_CATEGORIES, width="small"),
                "language": st.column_config.SelectboxColumn("語言", options=LANGUAGE_OPTIONS, width="small"),
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
                for idx, row in edited_terms.iterrows():
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
                if changes:
                    st.toast(f"✅ 已更新 {changes} 筆")
                    st.rerun()
                else:
                    st.toast("沒有偵測到修改")
        
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
    
    # ── 新增詞彙 ──────────────────────────────────
    st.divider()
    st.markdown("#### ➕ 新增詞彙")
    nc1, nc2, nc3 = st.columns([1, 2, 1])
    new_term = nc1.text_input("原始詞", placeholder="例：DAKA", key="new_term")
    new_full = nc2.text_input("完整名稱", placeholder="例：台泥DAKA再生資源處理中心", key="new_full")
    new_cat = nc3.selectbox("分類", ["一般", "人名", "組織", "技術"], key="new_term_cat")
    
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
