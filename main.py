"""
main.py — 泛用型 RAG 文件清洗與向量化 Pipeline 進入點

使用範例：
    python main.py --source ./raw_data/sample.pdf
    python main.py --source ./raw_data/report.docx
    python main.py --source https://example.com/article
    python main.py --source ./raw_data/sample.pdf --no-embed   # 跳過嵌入
"""
from __future__ import annotations

import argparse
import sys

from supabase import create_client

from config import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, GEMINI_API_KEY
from modules.uploader import Uploader
from modules.parser_pdf import PdfParser
from modules.parser_docx import DocxParser
from modules.parser_url import UrlParser
from modules.cleaner import MarkdownCleaner
from modules.chunker import SemanticChunker
from modules.exporter import SupabaseExporter


# ── 解析器工廠 ────────────────────────────────────────
PARSERS = {
    "pdf": PdfParser,
    "docx": DocxParser,
    "url": UrlParser,
}


def run_pipeline(source: str, do_embed: bool = True) -> None:
    """執行完整的：上傳 → 去重 → 解析 → 清洗 → 切割 → 嵌入 → 寫入 DB 流程。"""

    # 0) 建立 Supabase client
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        print("[ERROR] 請先在 .env 中設定 SUPABASE_URL 與 SUPABASE_SERVICE_ROLE_KEY")
        sys.exit(1)

    client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

    # 1) 上傳 & 去重
    uploader = Uploader(client)
    doc_info = uploader.process(source)
    if doc_info is None:
        return  # 重複或錯誤，已在 process() 印出訊息

    file_name = doc_info["file_name"]
    file_hash = doc_info["file_hash"]
    source_type = doc_info["source_type"]
    actual_source = doc_info["source"]

    # 2) 解析
    parser_cls = PARSERS.get(source_type)
    if parser_cls is None:
        print(f"[ERROR] 找不到 source_type={source_type} 的解析器")
        return

    print(f"[PARSE] 開始解析 ({source_type})：{file_name}")
    parser = parser_cls()
    raw_md = parser.parse(actual_source)
    print(f"[PARSE] 原始 Markdown 長度：{len(raw_md)} 字元")

    # 3) 清洗
    cleaner = MarkdownCleaner()
    cleaned_md = cleaner.clean(raw_md)
    print(f"[CLEAN] 清洗後 Markdown 長度：{len(cleaned_md)} 字元")

    # 4) 語義切割
    chunker = SemanticChunker()
    chunks = chunker.chunk(cleaned_md)
    print(f"[CHUNK] 共切割為 {len(chunks)} 個 chunks")

    # （除錯用）印出前 3 個 chunk 摘要
    for c in chunks[:3]:
        preview = c["text_content"][:80].replace("\n", " ")
        print(f"  chunk[{c['chunk_index']}] title={c['metadata'].get('section_title', '')!r}  "
              f"len={len(c['text_content'])}  preview={preview!r}…")

    # 5) 向量嵌入
    embeddings = None
    if do_embed:
        if not GEMINI_API_KEY:
            print("[WARN] 未設定 GEMINI_API_KEY，跳過嵌入步驟（僅儲存純文字）")
        else:
            from modules.embedder import GeminiEmbedder

            print(f"[EMBED] 開始產生向量嵌入（共 {len(chunks)} 個 chunks）…")
            embedder = GeminiEmbedder()
            texts = [c["text_content"] for c in chunks]
            embeddings = embedder.embed_batch(texts)
            print(f"[EMBED] 嵌入完成，維度={len(embeddings[0])}")
    else:
        print("[EMBED] 已跳過嵌入步驟（--no-embed）")

    # 6) 寫入 Supabase
    exporter = SupabaseExporter(client)
    doc_id = exporter.insert_document(file_name, file_hash, source_type)
    exporter.insert_chunks(doc_id, chunks, embeddings=embeddings)

    print(f"\n{'='*60}")
    embed_status = "含嵌入向量" if embeddings else "僅純文字"
    print(f"✅ 完成！document_id={doc_id}，共寫入 {len(chunks)} 個 chunks（{embed_status}）。")
    print(f"{'='*60}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="泛用型 RAG 文件清洗與向量化 Pipeline"
    )
    parser.add_argument(
        "--source",
        required=True,
        help="本地檔案路徑 (PDF/DOCX) 或網頁 URL",
    )
    parser.add_argument(
        "--no-embed",
        action="store_true",
        default=False,
        help="跳過向量嵌入，僅儲存純文字 chunks",
    )
    args = parser.parse_args()
    run_pipeline(args.source, do_embed=not args.no_embed)


if __name__ == "__main__":
    main()
