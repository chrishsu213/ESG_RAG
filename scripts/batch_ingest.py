"""
scripts/batch_ingest.py — 無人值守批次入庫腳本

使用方式（本機或 GitHub Actions）：
    python scripts/batch_ingest.py
    python scripts/batch_ingest.py --config config/ingest_targets.yaml
    python scripts/batch_ingest.py --dry-run   # 只顯示目標，不實際入庫

環境變數（由 GitHub Secrets 注入）：
    SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, GCP_PROJECT, GOOGLE_APPLICATION_CREDENTIALS
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

# ── 調整 Python Path（讓 modules/ 可被 import）──────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import yaml
from supabase import create_client

from modules.parser_url import UrlParser
from modules.cleaner import MarkdownCleaner
from modules.chunker import SemanticChunker
from modules.crawler import WebCrawler
from modules.exporter import SupabaseExporter
from modules.uploader import Uploader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────
def _build_supabase():
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def _get_embedder():
    """建立 Embedder（Vertex AI ADC）。"""
    from modules.embedder import GeminiEmbedder
    # batch_ingest 不傳 api_key → GeminiEmbedder 會從 ADC 取得認證
    return GeminiEmbedder(api_key=None)


def _ingest_one_url(
    url: str,
    *,
    client,
    embedder,
    exporter: SupabaseExporter,
    category: str,
    language: str,
    group: str | None,
    company: str | None,
    fiscal_year: str | None,
    publish_date: str | None,
    chunk_strategy: str,
    dry_run: bool,
) -> bool:
    """處理單一 URL：解析 → 清洗 → 切割 → 嵌入 → 寫入 DB。"""
    uploader = Uploader(client)
    doc_info = uploader.process(url)
    if doc_info is None:
        logger.info(f"  [skip] 已存在或無效：{url}")
        return False

    if dry_run:
        logger.info(f"  [dry-run] 會入庫：{url}")
        return True

    try:
        raw_md = UrlParser().parse(url)
        cleaned_md = MarkdownCleaner().clean(raw_md)
        chunker = SemanticChunker()

        # 選擇切割策略
        if chunk_strategy == "parent_child":
            parent_child_list = chunker.chunk_parent_child(cleaned_md)
            if not parent_child_list:
                logger.warning(f"  [warn] 無有效內容：{url}")
                return False

            embed_targets = []
            for item in parent_child_list:
                if item["children"]:
                    embed_targets.extend(item["children"])
                else:
                    embed_targets.append(item["parent"])

            texts = [c["text_content"] for c in embed_targets]
            vecs = embedder.embed_batch(texts) if texts else []
            embedding_map = {c["chunk_index"]: v for c, v in zip(embed_targets, vecs)}

            doc_id = exporter.insert_document(
                doc_info["file_name"], doc_info["file_hash"], "url",
                category=category, fiscal_year=fiscal_year, language=language,
                group=group, company=company, publish_date=publish_date,
            )
            p_cnt, c_cnt = exporter.insert_parent_child_chunks(doc_id, parent_child_list, embedding_map)
            logger.info(f"  [ok] {url} → {p_cnt} parents, {c_cnt} children")

        else:  # flat
            chunks = chunker.chunk(cleaned_md)
            if not chunks:
                logger.warning(f"  [warn] 無有效內容：{url}")
                return False

            texts = [c["text_content"] for c in chunks]
            embeddings = embedder.embed_batch(texts) if texts else None

            doc_id = exporter.insert_document(
                doc_info["file_name"], doc_info["file_hash"], "url",
                category=category, fiscal_year=fiscal_year, language=language,
                group=group, company=company, publish_date=publish_date,
            )
            exporter.insert_chunks(doc_id, chunks, embeddings=embeddings)
            logger.info(f"  [ok] {url} → {len(chunks)} chunks")

        return True

    except Exception as e:
        logger.error(f"  [error] {url}: {e}")
        return False


# ────────────────────────────────────────────────────────────
def run(config_path: str, dry_run: bool = False) -> None:
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    defaults = cfg.get("defaults", {})
    targets = cfg.get("targets", [])

    client = _build_supabase()
    embedder = _get_embedder() if not dry_run else None
    exporter = SupabaseExporter(client) if not dry_run else None

    total_ok = total_skip = total_err = 0
    start_time = time.time()

    for idx, target in enumerate(targets, 1):
        t_type    = target.get("type", "url_list")
        category  = target.get("category", "其他")
        language  = target.get("language",    defaults.get("language", "zh-TW"))
        group     = target.get("group",       defaults.get("group"))
        company   = target.get("company",     defaults.get("company"))
        fiscal_year   = target.get("fiscal_year")
        publish_date  = target.get("publish_date")
        chunk_strategy = target.get("chunk_strategy", defaults.get("chunk_strategy", "parent_child"))

        logger.info(f"\n[{idx}/{len(targets)}] 類型={t_type} 分類={category}")

        # 展開 URL 清單
        urls: list[str] = []
        if t_type == "url_list":
            urls = target.get("urls", [])

        elif t_type == "sitemap":
            from xml.etree import ElementTree as ET
            import requests
            try:
                resp = requests.get(target["url"], timeout=15)
                root = ET.fromstring(resp.text)
                ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
                urls = [loc.text.strip() for loc in root.findall("sm:url/sm:loc", ns)]
                max_pages = target.get("max_pages", 500)
                urls = urls[:max_pages]
                logger.info(f"  Sitemap 展開：{len(urls)} 個 URL")
            except Exception as e:
                logger.error(f"  Sitemap 解析失敗：{e}")
                continue

        elif t_type == "crawler":
            try:
                crawler = WebCrawler(
                    max_depth=target.get("max_depth", 2),
                    max_pages=target.get("max_pages", 200),
                )
                urls = crawler.crawl(target["url"])
                logger.info(f"  Crawler 發現：{len(urls)} 個 URL")
            except Exception as e:
                logger.error(f"  Crawler 失敗：{e}")
                continue

        # 逐一入庫
        for url in urls:
            result = _ingest_one_url(
                url,
                client=client, embedder=embedder, exporter=exporter,
                category=category, language=language,
                group=group, company=company,
                fiscal_year=fiscal_year, publish_date=publish_date,
                chunk_strategy=chunk_strategy, dry_run=dry_run,
            )
            if result:
                total_ok += 1
            else:
                total_skip += 1
            time.sleep(0.3)  # 避免過快撞 Rate Limit

    elapsed = time.time() - start_time
    logger.info(
        f"\n{'='*50}\n"
        f"完成！耗時 {elapsed:.0f}s\n"
        f"成功：{total_ok}　跳過：{total_skip}　失敗：{total_err}\n"
        f"{'='*50}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="批次入庫腳本")
    parser.add_argument("--config", default="config/ingest_targets.yaml")
    parser.add_argument("--dry-run", action="store_true", help="只顯示目標，不實際入庫")
    args = parser.parse_args()
    run(args.config, dry_run=args.dry_run)
