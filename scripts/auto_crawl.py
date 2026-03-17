"""
scripts/auto_crawl.py — 定時自動爬蟲腳本
可搭配 Windows 排程工作（Task Scheduler）或 n8n 定期執行。

功能：
- 爬取指定網站的新頁面
- 已入庫的 URL 會自動跳過（靠 file_hash 去重）
- 支援多個網站同時爬
- 執行結果寫入日誌檔

使用方式：
    python scripts/auto_crawl.py

Windows 排程設定：
    1. 打開「工作排程器」(taskschd.msc)
    2. 建立基本工作 → 每日/每週
    3. 動作：啟動程式
       程式：C:\\Users\\chris.hsu\\AppData\\Local\\Python\\pythoncore-3.14-64\\python.exe
       引數：scripts\\auto_crawl.py
       起始位置：C:\\Users\\chris.hsu\\Desktop\\ESG_Parser & Cleaner
"""
import os
import sys
import json
import logging
from datetime import datetime

# 確保根目錄可 import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, GEMINI_API_KEY
from supabase import create_client
from modules.crawler import SiteCrawler
from modules.pipeline import DocumentIngestionPipeline

# ── 設定 ─────────────────────────────────────────────
# 要定時爬的網站清單
CRAWL_TARGETS = [
    {
        "root_url": "https://www.tccgroupholdings.com/",
        "category": "網站",
        "language": "zh-TW",
        "max_pages": 500,
        "max_depth": 5,
        "exclude_patterns": ["/en/"],
    },
    {
        "root_url": "https://www.tccgroupholdings.com/en/",
        "category": "網站",
        "language": "en",
        "max_pages": 500,
        "max_depth": 5,
        "exclude_patterns": [],
    },
    # 可以新增更多網站：
    # {
    #     "root_url": "https://esg.tccgroupholdings.com/",
    #     "category": "永續報告書",
    #     "language": "zh-TW",
    #     "max_pages": 200,
    #     "max_depth": 3,
    #     "exclude_patterns": [],
    # },
]

# 日誌設定
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, f"auto_crawl_{datetime.now().strftime('%Y%m%d')}.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


def process_url(client, url: str, category: str, language: str = "zh-TW") -> tuple[bool, str]:
    """處理單一 URL 的完整 Pipeline。"""
    pipeline = DocumentIngestionPipeline(
        supabase_client=client,
        gemini_api_key=GEMINI_API_KEY,
    )
    result = pipeline.ingest(url, category=category, language=language)
    if result.success:
        return True, result.message
    else:
        return False, result.message or "already_exists"


def run_crawl_target(client, target: dict) -> dict:
    """執行單一爬蟲目標。"""
    root_url = target["root_url"]
    log.info(f"開始爬取：{root_url}")

    crawler = SiteCrawler(
        root_url=root_url,
        max_pages=target.get("max_pages", 500),
        max_depth=target.get("max_depth", 5),
        exclude_patterns=target.get("exclude_patterns", []),
    )
    urls = crawler.crawl()
    log.info(f"發現 {len(urls)} 個頁面")

    stats = {"discovered": len(urls), "new": 0, "skipped": 0, "failed": 0}

    for i, url in enumerate(urls):
        try:
            ok, msg = process_url(
                client, url,
                category=target.get("category", "網站"),
                language=target.get("language", "zh-TW"),
            )
            if ok:
                stats["new"] += 1
                log.info(f"  [{i+1}/{len(urls)}] NEW: {msg}")
            else:
                stats["skipped"] += 1
        except Exception as e:
            stats["failed"] += 1
            log.error(f"  [{i+1}/{len(urls)}] FAIL: {url} — {e}")

    log.info(
        f"完成 {root_url}: "
        f"新增 {stats['new']}, 跳過 {stats['skipped']}, 失敗 {stats['failed']}"
    )
    return stats


def main():
    log.info("=" * 60)
    log.info("自動爬蟲開始")
    log.info("=" * 60)

    client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

    total_stats = {"discovered": 0, "new": 0, "skipped": 0, "failed": 0}

    for target in CRAWL_TARGETS:
        stats = run_crawl_target(client, target)
        for k in total_stats:
            total_stats[k] += stats[k]

    log.info("=" * 60)
    log.info(
        f"全部完成: 發現 {total_stats['discovered']}, "
        f"新增 {total_stats['new']}, "
        f"跳過 {total_stats['skipped']}, "
        f"失敗 {total_stats['failed']}"
    )
    log.info("=" * 60)

    # 寫入最新執行摘要（可供 n8n/監控用）
    summary_path = os.path.join(LOG_DIR, "last_run.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "stats": total_stats,
            "targets": [t["root_url"] for t in CRAWL_TARGETS],
        }, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
