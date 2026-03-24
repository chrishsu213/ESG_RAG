"""
scripts/cleanup_today.py — 清除今天入庫的文件（用於重跑 batch_ingest）
"""
import os, sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env", override=False)

from supabase import create_client

client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

# 今天 UTC 開始時間
today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00+00:00")

# 查詢今天新增的文件
result = client.table("documents").select("id, file_name, created_at").gte("created_at", today_utc).execute()
docs = result.data or []

if not docs:
    print("今天沒有新增的文件，無需清除。")
else:
    print(f"找到 {len(docs)} 份今天入庫的文件：")
    for d in docs:
        print(f"  id={d['id']}  {d['file_name']}")

    confirm = input(f"\n確認刪除這 {len(docs)} 份文件及其 chunks？(輸入 yes 確認) ")
    if confirm.strip().lower() == "yes":
        ids = [d["id"] for d in docs]
        # 逐一刪 chunks（一次全刪容易 timeout）
        for doc_id in ids:
            client.table("document_chunks").delete().eq("document_id", doc_id).execute()
            print(f"  chunks 已刪：doc_id={doc_id}")
        # 再刪 documents
        client.table("documents").delete().in_("id", ids).execute()
        print(f"✅ 已刪除 {len(docs)} 份文件及其所有 chunks。")
    else:
        print("取消。")
