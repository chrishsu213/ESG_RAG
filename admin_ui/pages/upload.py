"""
admin_ui/pages/upload.py — 文件入庫頁面
支援：PDF/DOCX 單檔/批次、網頁爬蟲（含 Sitemap）、錄音檔轉錄。
"""
import os
import uuid
import hashlib
import tempfile
import streamlit as st
from config import DEFAULT_GROUP
from modules.uploader import Uploader
from modules.parser_pdf import PdfParser
from modules.parser_docx import DocxParser
from modules.parser_url import UrlParser
from modules.cleaner import MarkdownCleaner
from modules.chunker import SemanticChunker
from modules.exporter import SupabaseExporter
from modules.crawler import SiteCrawler
from modules.parser_pdf_vision import VisionPdfParser
from modules.proofreader import AiProofreader
from modules.parser_audio import AudioParser
from modules.embedder import GeminiEmbedder
from admin_ui.utils.constants import (
    CATEGORY_GROUPS, CATEGORY_OPTIONS, CATEGORY_WITH_QUARTER, CATEGORY_WITH_PUBLISH_DATE,
    LANGUAGE_OPTIONS, FISCAL_YEAR_OPTIONS,
)

# 暫存目錄（絕對路徑，避免 CWD 依賴）
_BASE_DIR     = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_RAW_DATA_DIR = os.path.join(_BASE_DIR, "raw_data")


# ──────────────────────────────────────────────────────────
# 共用 helper：處理 URL pipeline
# ──────────────────────────────────────────────────────────
def _process_url(client, url: str, category: str, display_name: str,
                 report_group: str = "", group: str = "", company: str = "",
                 fiscal_year: str = "", language: str = "", publish_date: str = ""):
    """處理 URL 的完整 Pipeline（解析 → 清洗 → 切割 → 嵌入 → 入庫）"""
    uploader = Uploader(client)
    doc_info = uploader.process(url)
    if doc_info is None:
        return False, "已存在"

    parser   = UrlParser()
    meta     = parser.parse_with_meta(doc_info["source"])
    raw_md   = meta["content"]
    page_title = meta["title"]

    cleaned_md  = MarkdownCleaner().clean(raw_md)
    chunks      = SemanticChunker().chunk(cleaned_md)
    if not chunks:
        return False, "無有效內容"

    embedder   = GeminiEmbedder()
    embeddings = embedder.embed_batch([c["text_content"] for c in chunks])

    exporter   = SupabaseExporter(client)
    final_name = display_name.strip() or page_title or doc_info["file_name"]
    doc_id = exporter.insert_document(
        doc_info["file_name"], doc_info["file_hash"], doc_info["source_type"],
        category=category, display_name=final_name,
        report_group=report_group if report_group.strip() else None,
        group=group if group.strip() else None,
        company=company if company.strip() else None,
        fiscal_year=fiscal_year if fiscal_year else None,
        language=language if language else None,
        publish_date=publish_date if publish_date else None,
    )
    exporter.insert_chunks(doc_id, chunks, embeddings=embeddings)
    return True, f"{len(chunks)} 段 | 📄 {final_name}"


# ──────────────────────────────────────────────────────────
# 主要 render 函式
# ──────────────────────────────────────────────────────────
def render(client):
    st.title("📤 上傳與匯入")

    # ── 第一行：類別群組 → 細分類 ─────────────────────────
    col_grp_sel, col_cat = st.columns(2)
    with col_grp_sel:
        group_label = st.selectbox(
            "📂 類別群組",
            list(CATEGORY_GROUPS.keys()),
            key="upload_group_label",
        )
    with col_cat:
        upload_category = st.selectbox(
            "📁 文件分類",
            CATEGORY_GROUPS[group_label],
            key="upload_category",
        )

    # ── 第二行：顯示名稱 + 所屬報告 ───────────────────────
    col_name, col_rg = st.columns(2)
    with col_name:
        upload_display_name = st.text_input(
            "📝 自訂顯示名稱（留空用檔名）", key="upload_display_name"
        )
    with col_rg:
        upload_report_group = st.text_input(
            "📎 所屬報告（拆章節用）", placeholder="例如：2024永續報告書",
            key="upload_report_group",
            help="將多個章節歸為同一份報告。整份上傳或非報告可留空。",
        )

    # ── 第三行：年度 + 語言 ────────────────────────────────
    col_year, col_lang = st.columns(2)
    with col_year:
        _year_options = ["（不填）"] + FISCAL_YEAR_OPTIONS
        _year_sel = st.selectbox("📅 年度", _year_options, index=0, key="upload_fiscal_year")
        upload_fiscal_year = "" if _year_sel == "（不填）" else _year_sel
    with col_lang:
        _lang_options = ["（不填）"] + LANGUAGE_OPTIONS
        _lang_sel = st.selectbox("🌐 語言", _lang_options, index=1, key="upload_language")
        upload_language = "" if _lang_sel == "（不填）" else _lang_sel

    # ── 條件顯示：季度（財務報告 / 法說會） ───────────────
    if upload_category in CATEGORY_WITH_QUARTER:
        upload_fiscal_period = st.selectbox(
            "📊 季度", ["Annual", "Q1", "Q2", "Q3", "Q4"], index=0,
            key="upload_fiscal_period",
            help="年報 / 全年度選 Annual；季報請選對應季度",
        )
    else:
        upload_fiscal_period = "Annual"

    # ── 條件顯示：發布日期（新聞稿 / 電子報） ─────────────
    upload_publish_date = ""
    if upload_category in CATEGORY_WITH_PUBLISH_DATE:
        _pub_date = st.date_input(
            "📰 發布日期", value=None, key="upload_publish_date",
            help="記錄新聞稿或電子報的發布日期，供 AI 引用時精準標注",
        )
        upload_publish_date = _pub_date.isoformat() if _pub_date else ""

    # ── 集團 / 子公司 ──────────────────────────────────────
    col_grp, col_comp = st.columns(2)
    with col_grp:
        _grp_res = client.table("documents").select('"group"').not_.is_("group", "null").execute()
        _existing_groups = sorted(set(r["group"] for r in (_grp_res.data or []) if r.get("group")))
        if not _existing_groups:
            _existing_groups = [DEFAULT_GROUP]
        upload_group = st.selectbox("🏢 集團", _existing_groups + ["（新增集團）"], index=0, key="upload_group")
        if upload_group == "（新增集團）":
            upload_group = st.text_input("輸入新集團名稱", key="upload_group_new")
    with col_comp:
        if upload_group and upload_group != "（新增集團）":
            _comp_res = client.table("documents").select("company").eq("group", upload_group).not_.is_("company", "null").execute()
            _existing_comps = sorted(set(r["company"] for r in (_comp_res.data or []) if r.get("company")))
        else:
            _existing_comps = []
        if not _existing_comps:
            _existing_comps = [upload_group]
        upload_company = st.selectbox("🏭 子公司", _existing_comps + ["（新增子公司）"], index=0, key="upload_company")
        if upload_company == "（新增子公司）":
            upload_company = st.text_input("輸入新子公司名稱", key="upload_company_new")

    st.divider()

    # ── 三個子分頁 ─────────────────────────────────────────
    sub_tab1, sub_tab2, sub_tab3 = st.tabs(["📂 PDF / Word 文件", "🌐 網頁爬蟲", "🎙️ 錄音檔（開發中）"])

    with sub_tab1:
        upload_mode = st.radio(
            "上傳模式",
            ["single", "batch"],
            format_func=lambda x: {"single": "📄 單檔模式（可預覽編輯）", "batch": "📦 批次模式（多檔自動處理）"}[x],
            horizontal=True, key="upload_mode",
        )
        if upload_mode == "single":
            _render_single_upload(client, upload_category, upload_display_name, upload_report_group,
                                  upload_group, upload_company, upload_fiscal_period,
                                  upload_fiscal_year, upload_language, upload_publish_date)
        else:
            _render_batch_upload(client, upload_category, upload_display_name, upload_report_group,
                                 upload_group, upload_company,
                                 upload_fiscal_year, upload_language, upload_publish_date)

    with sub_tab2:
        _render_web_crawler(client, upload_category, upload_display_name,
                            upload_report_group, upload_group, upload_company,
                            upload_fiscal_year, upload_language, upload_publish_date)

    with sub_tab3:
        _render_audio_upload(client, upload_category, upload_display_name)


# ──────────────────────────────────────────────────────────
# 私用 ─ 單檔 PDF/DOCX 入庫
# ──────────────────────────────────────────────────────────
def _render_single_upload(client, category, display_name, report_group,
                          group, company, fiscal_period,
                          fiscal_year="", language="", publish_date=""):
    uploaded_file = st.file_uploader("拖放或選擇 PDF / DOCX 檔案", type=["pdf", "docx", "doc"], key="single_uploader")

    pdf_mode    = "vision_pdf"  # 固定使用最高品質模式
    page_offset = 0
    if uploaded_file and uploaded_file.name.lower().endswith(".pdf"):
        page_offset = st.number_input(
            "頁碼偏移", min_value=0, value=0, step=1,
            key="page_offset", help="整份上傳填 0。拆章節時填起始頁碼 -1。"
        )

    if uploaded_file and st.button("🔍 解析並預覽", type="primary", key="parse_preview"):
        os.makedirs(_RAW_DATA_DIR, exist_ok=True)
        safe_ext  = os.path.splitext(uploaded_file.name)[1].lower()
        temp_path = os.path.join(_RAW_DATA_DIR, f"{uuid.uuid4().hex}{safe_ext}")
        with open(temp_path, "wb") as f:
            f.write(uploaded_file.getbuffer())

        parse_progress = st.progress(0, text="正在解析...")
        if uploaded_file.name.lower().endswith(".pdf"):
            def on_pdf_progress(current, total, mode):
                pct = int((current / total) * 100)
                parse_progress.progress(pct, text=f"[{mode}] 第 {current}/{total} 頁")
            parser = VisionPdfParser(mode=pdf_mode, on_progress=on_pdf_progress)
            raw_md = parser.parse(temp_path)
            stats  = parser.stats
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
        st.session_state["draft_md"]          = cleaned_md
        st.session_state["draft_path"]        = temp_path
        st.session_state["draft_filename"]    = uploaded_file.name
        st.session_state["draft_page_offset"] = page_offset if uploaded_file.name.lower().endswith(".pdf") else 0

    # 草稿預覽
    if "draft_md" in st.session_state:
        st.divider()
        st.markdown(f"#### 📝 草稿預覽 — {st.session_state.get('draft_filename', '')}")
        st.caption(f"共 {len(st.session_state['draft_md'])} 字元")

        col_ai, col_clear = st.columns([1, 1])
        with col_ai:
            if st.button("🤖 AI 自動校對", key="ai_proofread"):
                import time as _t
                _prog   = st.progress(0, text="🤖 AI 校對準備中...")
                _status = st.empty()
                _t0     = _t.time()

                def _on_proofread_progress(current: int, total: int):
                    pct = int(current / total * 100)
                    _prog.progress(pct, text=f"🤖 AI 校對中：第 {current}/{total} 段（{pct}%）")
                    remaining = max(0, int((_t.time()-_t0)/current*(total-current)))
                    _status.caption(f"⏱️ 已耗時 {_t.time()-_t0:.0f} 秒，預計還需 {remaining} 秒")

                proofreader = AiProofreader()
                result = proofreader.proofread(st.session_state["draft_md"], on_progress=_on_proofread_progress)
                elapsed = _t.time() - _t0
                _prog.progress(100, text=f"✅ AI 校對完成！共耗時 {elapsed:.0f} 秒")
                _status.empty()
                st.session_state["draft_md"] = result
                st.rerun()
        with col_clear:
            if st.button("❌ 放棄草稿", key="discard_draft"):
                draft_path = st.session_state.get("draft_path")
                if draft_path and os.path.exists(draft_path):
                    os.remove(draft_path)
                for key in ["draft_md", "draft_path", "draft_filename", "draft_page_offset"]:
                    st.session_state.pop(key, None)
                st.rerun()

        edited_md = st.text_area("可直接編輯內容", value=st.session_state["draft_md"], height=400, key="draft_editor")

        if st.button("✅ 確認入庫", type="primary", key="confirm_ingest"):
            progress = st.progress(0, text="正在處理...")
            uploader = Uploader(client)
            doc_info = uploader.process(st.session_state["draft_path"])
            if doc_info is None:
                st.warning("⚠️ 此文件已存在於資料庫中。")
                progress.empty()
            else:
                progress.progress(30, text="切割中（Parent-Child）...")
                chunker          = SemanticChunker()
                parent_child_list = chunker.chunk_parent_child(edited_md)

                offset = st.session_state.get("draft_page_offset", 0)
                if offset > 0:
                    for item in parent_child_list:
                        for chunk in [item["parent"]] + item["children"]:
                            meta = chunk.get("metadata", {})
                            if meta.get("page_start") is not None:
                                meta["page_start"] += offset
                            if meta.get("page_end") is not None:
                                meta["page_end"] += offset

                embed_targets: list[tuple[int, str]] = []
                for item in parent_child_list:
                    if item["children"]:
                        for child in item["children"]:
                            embed_targets.append((child["chunk_index"], child["text_content"]))
                    else:
                        p = item["parent"]
                        embed_targets.append((p["chunk_index"], p["text_content"]))

                child_embeddings_map: dict[int, list[float]] = {}
                if embed_targets:
                    progress.progress(50, text=f"向量嵌入中（{len(embed_targets)} 個）...")
                    embedder = GeminiEmbedder()
                    try:
                        vecs = embedder.embed_batch([t for _, t in embed_targets])
                        for (idx, _), vec in zip(embed_targets, vecs):
                            child_embeddings_map[idx] = vec
                    except Exception as e:
                        st.error(f"向量產生失敗：{e}")
                        progress.empty()
                        return

                if parent_child_list:
                    progress.progress(80, text="寫入資料庫...")
                    exporter   = SupabaseExporter(client)
                    orig_fname = st.session_state.get("draft_filename", doc_info["file_name"])
                    final_name = display_name.strip() if display_name.strip() else os.path.splitext(orig_fname)[0]
                    rg         = report_group.strip() if report_group.strip() else None
                    doc_id = exporter.insert_document(
                        orig_fname, doc_info["file_hash"], doc_info["source_type"],
                        category=category, display_name=final_name, report_group=rg,
                        group=group if group else None, company=company if company else None,
                        fiscal_period=fiscal_period,
                        fiscal_year=fiscal_year if fiscal_year else None,
                        language=language if language else None,
                        publish_date=publish_date if publish_date else None,
                    )
                    p_cnt, c_cnt = exporter.insert_parent_child_chunks(doc_id, parent_child_list, child_embeddings_map)
                    progress.progress(100, text="完成！")
                    group_info = f" [報告: {rg}]" if rg else ""
                    st.success(f"✅ 入庫成功：**{final_name}**{group_info} ({p_cnt} parents, {c_cnt} children)")

                    draft_path = st.session_state.get("draft_path")
                    if draft_path and os.path.exists(draft_path):
                        os.remove(draft_path)
                    for key in ["draft_md", "draft_path", "draft_filename", "draft_page_offset"]:
                        st.session_state.pop(key, None)


# ──────────────────────────────────────────────────────────
# 私用 ─ 批次 PDF/DOCX 入庫
# ──────────────────────────────────────────────────────────
def _render_batch_upload(client, category, display_name, report_group, group, company,
                         fiscal_year="", language="", publish_date=""):
    st.info("📦 批次模式：一次上傳多個 PDF / DOCX 檔案，系統將自動依序處理。")

    batch_pdf_mode = "vision_pdf"  # 固定使用最高品質模式
    batch_files = st.file_uploader(
        "拖放或選擇多個 PDF / DOCX 檔案", type=["pdf", "docx", "doc"],
        accept_multiple_files=True, key="batch_uploader",
    )

    if batch_files and st.button(f"🚀 開始處理 {len(batch_files)} 個檔案", type="primary", key="batch_start"):
        os.makedirs(_RAW_DATA_DIR, exist_ok=True)
        results_container = st.container()
        overall_progress  = st.progress(0, text="準備中...")
        success_count = skip_count = fail_count = 0

        for idx, bf in enumerate(batch_files):
            file_label = bf.name
            overall_progress.progress(int((idx / len(batch_files)) * 100), text=f"處理中 ({idx+1}/{len(batch_files)})：{file_label}")
            temp_path = None
            try:
                safe_ext  = os.path.splitext(bf.name)[1].lower()
                temp_path = os.path.join(_RAW_DATA_DIR, f"{uuid.uuid4().hex}{safe_ext}")
                with open(temp_path, "wb") as f:
                    f.write(bf.getbuffer())

                doc_info = Uploader(client).process(temp_path)
                if doc_info is None:
                    skip_count += 1
                    results_container.warning(f"⏭️ {file_label} — 已存在，跳過")
                    continue

                raw_md     = VisionPdfParser(mode=batch_pdf_mode).parse(temp_path) if safe_ext == ".pdf" else DocxParser().parse(temp_path)
                cleaned_md = MarkdownCleaner().clean(raw_md)
                chunks     = SemanticChunker().chunk(cleaned_md)
                if not chunks:
                    fail_count += 1
                    results_container.error(f"❌ {file_label} — 解析後無有效內容")
                    continue

                embeddings = GeminiEmbedder().embed_batch([c["text_content"] for c in chunks])
                exporter   = SupabaseExporter(client)
                doc_display = display_name.strip() if (display_name.strip() and len(batch_files) == 1) else os.path.splitext(bf.name)[0]
                rg = report_group.strip() if report_group.strip() else None
                doc_id = exporter.insert_document(
                    bf.name, doc_info["file_hash"], doc_info["source_type"],
                    category=category, display_name=doc_display, report_group=rg,
                    group=group if group else None, company=company if company else None,
                    fiscal_year=fiscal_year if fiscal_year else None,
                    language=language if language else None,
                    publish_date=publish_date if publish_date else None,
                )
                exporter.insert_chunks(doc_id, chunks, embeddings=embeddings)
                success_count += 1
                results_container.success(f"✅ {file_label} — {len(chunks)} 段已入庫")
            except Exception as e:
                fail_count += 1
                results_container.error(f"❌ {file_label} — 失敗：{e}")
            finally:
                if temp_path and os.path.exists(temp_path):
                    os.remove(temp_path)

        overall_progress.progress(100, text="全部完成！")
        st.markdown(
            f"### 📊 批次處理結果\n"
            f"- ✅ 成功：**{success_count}** 個\n"
            f"- ⏭️ 跳過（重複）：**{skip_count}** 個\n"
            f"- ❌ 失敗：**{fail_count}** 個"
        )


# ──────────────────────────────────────────────────────────
# 私用 ─ 網頁爬蟲
# ──────────────────────────────────────────────────────────
def _render_web_crawler(client, category, display_name, report_group, group, company,
                        fiscal_year="", language="", publish_date=""):
    web_mode = st.radio(
        "匯入方式",
        ["single", "sitemap", "crawler"],
        format_func=lambda x: {"single": "🔗 單一網址", "sitemap": "🗺️ Sitemap 批次", "crawler": "🕷️ 全站爬蟲"}[x],
        horizontal=True, key="web_mode",
    )

    if web_mode == "single":
        url_input = st.text_input("輸入完整網址", placeholder="https://...")
        if url_input and st.button("開始抓取", type="primary", key="fetch_url"):
            with st.spinner("正在抓取..."):
                try:
                    ok, msg = _process_url(client, url_input, category, display_name, report_group, group, company,
                                          fiscal_year=fiscal_year, language=language, publish_date=publish_date)
                    if ok:
                        st.success(f"✅ 入庫成功：{msg}")
                    else:
                        st.warning(f"⚠️ {msg}")
                except Exception as e:
                    st.error(f"❌ 失敗：{e}")

    elif web_mode == "sitemap":
        sitemap_url    = st.text_input("Sitemap URL", placeholder="https://example.com/sitemap.xml", key="sitemap_url")
        sitemap_filter = st.text_input("排除關鍵字（逗號分隔）", help="例如 /en/ 排除英文頁", key="sitemap_filter")

        if sitemap_url and st.button("解析 Sitemap", key="parse_sitemap"):
            import xml.etree.ElementTree as ET
            import urllib3
            import requests as req
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            with st.spinner("正在解析 Sitemap..."):
                try:
                    try:
                        resp = req.get(sitemap_url, timeout=30)
                    except req.exceptions.SSLError:
                        resp = req.get(sitemap_url, timeout=30, verify=False)
                    resp.raise_for_status()
                    root = ET.fromstring(resp.content)
                    ns   = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
                    all_urls = [loc.text for loc in root.findall(".//s:loc", ns) if loc.text]
                    exclude_keywords = [kw.strip() for kw in sitemap_filter.split(",") if kw.strip()]
                    filtered = [u for u in all_urls if not any(kw in u for kw in exclude_keywords)] if exclude_keywords else all_urls
                    st.session_state["sitemap_urls"]      = filtered
                    st.session_state["sitemap_all_count"] = len(all_urls)
                except Exception as e:
                    st.error(f"解析失敗：{e}")

        if "sitemap_urls" in st.session_state and st.session_state["sitemap_urls"]:
            urls  = st.session_state["sitemap_urls"]
            total = st.session_state.get("sitemap_all_count", len(urls))
            st.success(f"找到 {total} 個 URL，篩選後 **{len(urls)}** 個")
            with st.expander("預覽 URL 列表", expanded=False):
                for i, u in enumerate(urls, 1):
                    st.text(f"{i}. {u}")
            if st.button(f"🚀 批次匯入 ({len(urls)} 個)", type="primary", key="batch_import"):
                bp = st.progress(0)
                ok_n = skip_n = fail_n = 0
                status = st.empty()
                for i, url in enumerate(urls):
                    bp.progress(int((i / len(urls)) * 100), text=f"({i+1}/{len(urls)})")
                    try:
                        ok, _ = _process_url(client, url, category, "", report_group, group, company,
                                             fiscal_year=fiscal_year, language=language, publish_date=publish_date)
                        if ok:
                            ok_n += 1
                        else:
                            skip_n += 1
                    except Exception:
                        fail_n += 1
                    status.caption(f"✅{ok_n} ⏭️{skip_n} ❌{fail_n}")
                bp.progress(100, text="完成！")
                st.balloons()
                del st.session_state["sitemap_urls"]

    else:  # crawler
        crawler_root    = st.text_input("網站根 URL", placeholder="https://example.com/", key="crawler_root")
        col_d, col_m    = st.columns(2)
        crawler_depth   = col_d.slider("最大深度", 1, 10, 5, key="crawler_depth")
        crawler_max     = col_m.slider("最大頁數", 10, 2000, 500, key="crawler_max")
        crawler_exclude = st.text_input("排除路徑（逗號分隔）", value="/en/", key="crawler_exclude")

        if crawler_root and st.button("🔍 開始掃描", key="start_crawl"):
            exclude_list = [p.strip() for p in crawler_exclude.split(",") if p.strip()]
            cp, status   = st.progress(0), st.empty()

            def on_crawl(found, visited, current):
                cp.progress(min(int((visited / crawler_max) * 100), 99))
                status.caption(f"發現 {found} 頁 | 掃描 {visited} 連結 | {current[:60]}...")

            crawler = SiteCrawler(root_url=crawler_root, max_pages=crawler_max,
                                  max_depth=crawler_depth, exclude_patterns=exclude_list, on_progress=on_crawl)
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
                ok_n = skip_n = fail_n = 0
                status        = st.empty()
                error_display = st.empty()
                recent_errors: list[str] = []
                for i, url in enumerate(c_urls):
                    bp.progress(int((i / len(c_urls)) * 100), text=f"({i+1}/{len(c_urls)})")
                    try:
                        ok, msg = _process_url(client, url, category, "", report_group, group, company,
                                              fiscal_year=fiscal_year, language=language, publish_date=publish_date)
                        if ok:
                            ok_n += 1
                        else:
                            skip_n += 1
                    except Exception as e:
                        fail_n += 1
                        err_msg = f"{url[:50]}... → {type(e).__name__}: {str(e)[:100]}"
                        recent_errors = (recent_errors + [err_msg])[-3:]
                        error_display.error("最近錯誤：\n" + "\n".join(recent_errors))
                    status.caption(f"✅{ok_n} ⏭️{skip_n} ❌{fail_n}")
                bp.progress(100, text="完成！")
                if ok_n > 0:
                    st.balloons()
                if recent_errors:
                    st.error(f"共 {fail_n} 筆失敗。最後錯誤：\n" + "\n".join(recent_errors))
                del st.session_state["crawler_urls"]


# ──────────────────────────────────────────────────────────
# 私用 ─ 錄音檔轉錄
# ──────────────────────────────────────────────────────────
def _render_audio_upload(client, category, display_name):
    st.markdown("**🎙️ 上傳錄音檔 → Gemini 轉錄 → 審校 → 入庫**")
    st.caption(f"支援格式：{', '.join(AudioParser.get_supported_formats())}")

    audio_file = st.file_uploader(
        "上傳錄音檔",
        type=[ext.lstrip('.') for ext in AudioParser.get_supported_formats()],
        key="audio_upload",
    )
    a_col1, a_col2 = st.columns(2)
    audio_category = a_col1.selectbox(
        "分類", CATEGORY_OPTIONS,
        index=CATEGORY_OPTIONS.index("會議紀錄") if "會議紀錄" in CATEGORY_OPTIONS else 0,
        key="audio_cat",
    )
    audio_name = a_col2.text_input("文件名稱（選填，自動以檔名命名）", key="audio_name")

    if audio_file and st.button("🎤 開始轉錄", type="primary", key="start_transcribe"):
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(audio_file.name)[1]) as tmp:
            tmp.write(audio_file.read())
            tmp_path = tmp.name

        progress_placeholder = st.empty()
        try:
            terms_dict = {}
            try:
                terms_res  = client.table("terms_dictionary").select("term, full_name").execute()
                terms_dict = {t["term"]: t["full_name"] for t in (terms_res.data or [])}
            except Exception:
                pass

            parser = AudioParser(on_progress=lambda msg: progress_placeholder.info(msg))
            result = parser.parse(tmp_path, terms_dict=terms_dict)
            progress_placeholder.success("轉錄完成！")

            if result["terms_applied"]:
                st.info(f"已自動替換 {len(result['terms_applied'])} 個專有名詞：{', '.join(result['terms_applied'])}")

            st.session_state["audio_transcript"] = result["corrected_transcript"]
            st.session_state["audio_file_name"]  = audio_file.name
        except Exception as e:
            progress_placeholder.error(f"轉錄失敗：{e}")
        finally:
            os.unlink(tmp_path)

    # 草稿編輯區
    if "audio_transcript" in st.session_state:
        st.divider()
        st.markdown("#### ✏️ 草稿審校")
        st.caption("請檢查並修正講者名稱、專有名詞、聽不清楚的段落")

        edited_transcript = st.text_area(
            "轉錄內容（可直接編輯）",
            value=st.session_state["audio_transcript"],
            height=400, key="audio_editor",
        )
        ac1, ac2, ac3 = st.columns(3)

        with ac1:
            if st.button("📥 確認入庫", type="primary", key="audio_save"):
                if edited_transcript.strip():
                    cleaned = MarkdownCleaner().clean(edited_transcript)
                    chunks  = SemanticChunker().chunk(cleaned)
                    if chunks:
                        embeddings = GeminiEmbedder().embed_batch([c["text_content"] for c in chunks])
                        exporter   = SupabaseExporter(client)
                        fname      = st.session_state.get("audio_file_name", "audio_recording")
                        final_name = audio_name.strip() if audio_name.strip() else fname
                        file_hash  = hashlib.sha256(edited_transcript.encode()).hexdigest()
                        doc_id = exporter.insert_document(fname, file_hash, "audio", category=audio_category, display_name=final_name)
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
                mime="text/markdown", key="audio_download",
            )
        with ac3:
            if st.button("🗑️ 捨棄草稿", key="audio_discard"):
                del st.session_state["audio_transcript"]
                del st.session_state["audio_file_name"]
                st.rerun()
