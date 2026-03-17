# ─── TCC RAG Code Bundle Script (UTF-8) ───
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
OUTPUT = os.path.join(ROOT, "code_review_bundle.txt")

# 要打包的檔案（依模組分組）
FILES = [
    "config.py",
    "admin_ui/app.py",
    "api/server.py",
    "modules/retriever.py",
    "modules/rag_chat.py",
    "modules/embedder.py",
    "modules/pipeline.py",
    "modules/uploader.py",
    "modules/exporter.py",
    "modules/chunker.py",
    "modules/cleaner.py",
    "modules/crawler.py",
    "modules/parser_pdf.py",
    "modules/parser_pdf_vision.py",
    "modules/parser_docx.py",
    "modules/parser_audio.py",
    "modules/proofreader.py",
    "sql/schema.sql",
    "sql/migrations/007_add_fiscal_year_filter.sql",
    "sql/migrations/008_qa_feedback.sql",
    "requirements.txt",
    "requirements-api.txt",
    "Dockerfile",
    "API_INTEGRATION_GUIDE.md",
]

with open(OUTPUT, "w", encoding="utf-8") as out:
    out.write("=" * 80 + "\n")
    out.write("TCC RAG 知識庫 — 完整程式碼打包\n")
    out.write(f"產生時間：2026-03-17\n")
    out.write("=" * 80 + "\n\n")

    for fp in FILES:
        full = os.path.join(ROOT, fp)
        if not os.path.exists(full):
            out.write(f"\n{'─' * 60}\n⚠️ 檔案不存在：{fp}\n{'─' * 60}\n")
            continue
        out.write(f"\n{'═' * 80}\n")
        out.write(f"📄 {fp}\n")
        out.write(f"{'═' * 80}\n\n")
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            out.write(f.read())
        out.write("\n")

    out.write(f"\n{'═' * 80}\n")
    out.write("打包完成\n")
    out.write(f"{'═' * 80}\n")

print(f"Bundle saved to: {OUTPUT}")
