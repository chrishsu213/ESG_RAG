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
from modules.pipeline import DocumentIngestionPipeline


def run_pipeline(source: str, do_embed: bool = True) -> None:
    """執行完整的入庫 Pipeline。"""

    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        print("[ERROR] 請先在 .env 中設定 SUPABASE_URL 與 SUPABASE_SERVICE_ROLE_KEY")
        sys.exit(1)

    if do_embed and not GEMINI_API_KEY:
        print("[WARN] 未設定 GEMINI_API_KEY，跳過嵌入步驟（僅儲存純文字）")

    client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

    pipeline = DocumentIngestionPipeline(
        supabase_client=client,
        gemini_api_key=GEMINI_API_KEY if do_embed else None,
        on_progress=lambda stage, detail: print(f"[{stage.upper()}] {detail}"),
    )

    # 自動推斷分類
    category = DocumentIngestionPipeline.guess_category(source, "url" if source.startswith("http") else "pdf")

    result = pipeline.ingest(source, category=category)

    print(f"\n{'='*60}")
    if result.success:
        embed_status = "含嵌入向量" if result.has_embeddings else "僅純文字"
        print(f"✅ 完成！document_id={result.document_id}，共寫入 {result.chunks_count} 個 chunks（{embed_status}）。")
    else:
        print(f"❌ 失敗：{result.message}")
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
