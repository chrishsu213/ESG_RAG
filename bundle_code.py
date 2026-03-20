# ─── TCC RAG Code Bundle Script (UTF-8) ───
import os
from datetime import date

ROOT = os.path.dirname(os.path.abspath(__file__))
OUTPUT = os.path.join(ROOT, "code_review_bundle.txt")

# 要打包的檔案（依模組分組）
FILES = [
    # ── 設定 ──────────────────────────────────────
    "config.py",
    "config_modules.py",
    "requirements.txt",
    "requirements-api.txt",

    # ── Admin UI：Router + Utils ───────────────────
    "admin_ui/app.py",
    "admin_ui/utils/constants.py",
    "admin_ui/utils/db.py",

    # ── Admin UI：Pages ────────────────────────────
    "admin_ui/pages/overview.py",
    "admin_ui/pages/upload.py",
    "admin_ui/pages/doc_mgmt.py",
    "admin_ui/pages/search.py",
    "admin_ui/pages/chatbot.py",
    "admin_ui/pages/terms.py",
    "admin_ui/pages/settings.py",

    # ── API ────────────────────────────────────────
    "api/server.py",

    # ── 核心模組 ───────────────────────────────────
    "modules/retriever.py",
    "modules/rag_chat.py",
    "modules/embedder.py",
    "modules/chunker.py",
    "modules/cleaner.py",
    "modules/exporter.py",
    "modules/uploader.py",
    "modules/pipeline.py",

    # ── 解析器 ─────────────────────────────────────
    "modules/crawler.py",
    "modules/parser_pdf.py",
    "modules/parser_pdf_vision.py",
    "modules/parser_docx.py",
    "modules/parser_url.py",
    "modules/parser_audio.py",
    "modules/proofreader.py",

    # ── 資料庫 Schema & Migrations ─────────────────
    "sql/schema.sql",
    "sql/migrations/012_parent_child_chunks.sql",
    "sql/migrations/013_fiscal_period.sql",
    "sql/migrations/010_rag_config.sql",
    "sql/migrations/007_add_fiscal_year_filter.sql",
    "sql/migrations/008_qa_feedback.sql",
]

today = date.today().strftime("%Y-%m-%d")

with open(OUTPUT, "w", encoding="utf-8") as out:
    out.write("=" * 80 + "\n")
    out.write("TCC ESG RAG 知識庫 — 完整程式碼審查文件\n")
    out.write(f"產生時間：{today}\n")
    out.write("架構版本：Phase 1+2（UI 模組化 + Config Dataclasses）\n")
    out.write("" + "=" * 80 + "\n\n")

    out.write("【目錄】\n")
    for i, fp in enumerate(FILES, 1):
        out.write(f"  {i:02d}. {fp}\n")
    out.write("\n")

    ok_count = 0
    skip_count = 0

    for fp in FILES:
        full = os.path.join(ROOT, fp)
        if not os.path.exists(full):
            out.write(f"\n{'─' * 60}\n⚠️  檔案不存在：{fp}\n{'─' * 60}\n")
            skip_count += 1
            continue
        size = os.path.getsize(full)
        out.write(f"\n{'═' * 80}\n")
        out.write(f"📄 {fp}  ({size:,} bytes)\n")
        out.write(f"{'═' * 80}\n\n")
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            out.write(f.read())
        out.write("\n")
        ok_count += 1

    out.write(f"\n{'═' * 80}\n")
    out.write(f"打包完成：{ok_count} 個檔案（{skip_count} 個不存在）\n")
    out.write(f"{'═' * 80}\n")

total_kb = os.path.getsize(OUTPUT) // 1024
print(f"Bundle saved to: {OUTPUT}")
print(f"{ok_count} files included, {skip_count} skipped, {total_kb} KB total")
