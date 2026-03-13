"""
search.py — CLI 語義搜尋工具

使用範例：
    python search.py --query "公司碳排放目標" --top_k 5
    python search.py --query "董事會結構" --threshold 0.6
"""
from __future__ import annotations

import argparse
import sys
import textwrap

from supabase import create_client

from config import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, GEMINI_API_KEY
from modules.retriever import SemanticRetriever


def main() -> None:
    parser = argparse.ArgumentParser(
        description="泛用型 RAG 語義搜尋工具"
    )
    parser.add_argument(
        "--query", "-q",
        required=True,
        help="自然語言查詢文字",
    )
    parser.add_argument(
        "--top_k", "-k",
        type=int,
        default=5,
        help="回傳的最大結果數量 (預設: 5)",
    )
    parser.add_argument(
        "--threshold", "-t",
        type=float,
        default=0.5,
        help="最低相似度門檻 0~1 (預設: 0.5)",
    )
    args = parser.parse_args()

    # 前置檢查
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        print("[ERROR] 請先在 .env 中設定 SUPABASE_URL 與 SUPABASE_SERVICE_ROLE_KEY")
        sys.exit(1)
    if not GEMINI_API_KEY:
        print("[ERROR] 請先在 .env 中設定 GEMINI_API_KEY")
        sys.exit(1)

    client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    retriever = SemanticRetriever(client)

    print(f"\n🔍 搜尋中：「{args.query}」 (top_k={args.top_k}, threshold={args.threshold})\n")

    results = retriever.search(
        query=args.query,
        top_k=args.top_k,
        threshold=args.threshold,
    )

    if not results:
        print("❌ 沒有找到符合條件的結果。請嘗試降低 threshold 或更換查詢詞。")
        return

    print(f"✅ 共找到 {len(results)} 筆結果：\n")
    print("=" * 70)

    for i, r in enumerate(results, 1):
        similarity = r.get("similarity", 0)
        file_name = r.get("file_name", "N/A")
        source_type = r.get("source_type", "N/A")
        section = r.get("metadata", {}).get("section_title", "")
        text = r.get("text_content", "")

        # 擷取前 200 字元作為預覽
        preview = textwrap.shorten(text, width=200, placeholder="…")

        print(f"  [{i}] 相似度: {similarity:.4f}")
        print(f"      來源: {file_name} ({source_type})")
        if section:
            print(f"      章節: {section}")
        print(f"      內容: {preview}")
        print("-" * 70)

    print()


if __name__ == "__main__":
    main()
