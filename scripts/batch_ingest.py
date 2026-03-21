"""
scripts/batch_ingest.py — 無人值守批次入庫腳本

使用方式（本機或 GitHub Actions）：
    python scripts/batch_ingest.py
    python scripts/batch_ingest.py --config config/ingest_targets.yaml
    python scripts/batch_ingest.py --dry-run   # 只顯示目標，不實際入庫

本機執行前，請在專案根目錄建立 .env 檔（參考 .env.example）：
    SUPABASE_URL=...
    SUPABASE_SERVICE_ROLE_KEY=...
    GCP_PROJECT=...
    GOOGLE_APPLICATION_CREDENTIALS=C:/path/to/gcp_sa.json
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

# 自動載入 .env（本機執行用，GitHub Actions 由 Secrets 注入）
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env", override=False)
except ImportError:
    pass  # 未裝 python-dotenv 也沒問題，請自行設定環境變數

# ── 調整 Python Path（讓 modules/ 可被 import）──────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import yaml
from supabase import create_client

from modules.parser_url import UrlParser
from modules.cleaner import MarkdownCleaner
from modules.chunker import SemanticChunker
from modules.crawler import SiteCrawler as WebCrawler
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
    return GeminiEmbedder(api_key=None)


# ── PDF 入庫（等同於網頁 UI 單檔模式，完全相同的模組）──────
def _ingest_one_pdf(
    file_path: str,
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
    page_offset: int = 0,
    dry_run: bool,
) -> bool:
    """PDF 全流程入庫：VisionPdfParser → 清洗 → 切割 → 嵌入 → DB。"""
    if not os.path.isfile(file_path):
        logger.error(f"  [error] 檔案不存在：{file_path}")
        return False

    uploader = Uploader(client)
    doc_info = uploader.process(file_path)
    if doc_info is None:
        logger.info(f"  [skip] 已存在（重複）：{Path(file_path).name}")
        return False

    if dry_run:
        logger.info(f"  [dry-run] 會入庫：{Path(file_path).name}")
        return True

    try:
        logger.info(f"  解析 PDF：{Path(file_path).name}")
        from modules.parser_pdf_vision import VisionPdfParser

        def _on_pdf_progress(current: int, total: int, mode: str):
            pct = int(current / total * 100) if total else 0
            print(f"    [{mode}] 第 {current}/{total} 頁 ({pct}%)", end="\r", flush=True)

        parser = VisionPdfParser(on_progress=_on_pdf_progress)
        raw_md = parser.parse(file_path)
        print()  # 換行
        logger.info(f"  解析完成：{parser.stats['total_pages']} 頁")

        logger.info("  清洗中...")
        cleaned_md = MarkdownCleaner().clean(raw_md)

        logger.info("  切割中...")
        chunker = SemanticChunker()

        if chunk_strategy == "parent_child":
            parent_child_list = chunker.chunk_parent_child(cleaned_md)
            if not parent_child_list:
                logger.warning("  [warn] 清洗後無有效內容")
                return False

            if page_offset > 0:
                for item in parent_child_list:
                    for chunk in [item["parent"]] + item["children"]:
                        meta = chunk.get("metadata", {})
                        if meta.get("page_start") is not None:
                            meta["page_start"] += page_offset
                        if meta.get("page_end") is not None:
                            meta["page_end"] += page_offset

            embed_targets = []
            for item in parent_child_list:
                if item["children"]:
                    embed_targets.extend(item["children"])
                else:
                    embed_targets.append(item["parent"])

            logger.info(f"  嵌入中（{len(embed_targets)} 個小段落）...")
            texts = [c["text_content"] for c in embed_targets]
            vecs = embedder.embed_batch(texts) if texts else []
            embedding_map = {c["chunk_index"]: v for c, v in zip(embed_targets, vecs)}

            doc_id = exporter.insert_document(
                doc_info["file_name"], doc_info["file_hash"], "pdf",
                category=category, fiscal_year=fiscal_year,
                language=language, group=group, company=company,
                publish_date=publish_date,
            )
            p_cnt, c_cnt = exporter.insert_parent_child_chunks(doc_id, parent_child_list, embedding_map)
            logger.info(f"  [ok] {Path(file_path).name} → {p_cnt} parents, {c_cnt} children")

        else:  # flat
            chunks = chunker.chunk(cleaned_md)
            if not chunks:
                logger.warning("  [warn] 清洗後無有效內容")
                return False

            logger.info(f"  嵌入中（{len(chunks)} 段）...")
            texts = [c["text_content"] for c in chunks]
            embeddings = embedder.embed_batch(texts) if texts else None

            doc_id = exporter.insert_document(
                doc_info["file_name"], doc_info["file_hash"], "pdf",
                category=category, fiscal_year=fiscal_year,
                language=language, group=group, company=company,
                publish_date=publish_date,
            )
            exporter.insert_chunks(doc_id, chunks, embeddings=embeddings)
            logger.info(f"  [ok] {Path(file_path).name} → {len(chunks)} chunks")

        return True

    except Exception as e:
        logger.error(f"  [error] {Path(file_path).name}: {e}")
        return False


# ── URL / 網頁入庫 ──────────────────────────────────────────
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

    total_ok = total_skip = 0
    start_time = time.time()

    for idx, target in enumerate(targets, 1):
        t_type         = target.get("type", "url_list")
        category       = target.get("category", "其他")
        language       = target.get("language",       defaults.get("language", "zh-TW"))
        group          = target.get("group",          defaults.get("group"))
        company        = target.get("company",        defaults.get("company"))
        fiscal_year    = target.get("fiscal_year")
        publish_date   = target.get("publish_date")
        chunk_strategy = target.get("chunk_strategy", defaults.get("chunk_strategy", "parent_child"))

        logger.info(f"\n[{idx}/{len(targets)}] 類型={t_type}  分類={category}  "
                    f"集團={group or '-'}  公司={company or '-'}  年度={fiscal_year or '-'}")

        # ── PDF 清單 ────────────────────────────────────────
        if t_type == "pdf_list":
            pdf_files   = target.get("files", [])
            page_offset = target.get("page_offset", 0)
            logger.info(f"  PDF 清單：{len(pdf_files)} 份")
            for pdf_path in pdf_files:
                ok = _ingest_one_pdf(
                    str(pdf_path),
                    client=client, embedder=embedder, exporter=exporter,
                    category=category, language=language,
                    group=group, company=company,
                    fiscal_year=fiscal_year, publish_date=publish_date,
                    chunk_strategy=chunk_strategy, page_offset=page_offset,
                    dry_run=dry_run,
                )
                total_ok += ok
                total_skip += (not ok)
            continue

        # ── 展開 URL 清單 ───────────────────────────────────
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
                urls = urls[:target.get("max_pages", 500)]
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

        for url in urls:
            ok = _ingest_one_url(
                url,
                client=client, embedder=embedder, exporter=exporter,
                category=category, language=language,
                group=group, company=company,
                fiscal_year=fiscal_year, publish_date=publish_date,
                chunk_strategy=chunk_strategy, dry_run=dry_run,
            )
            total_ok += ok
            total_skip += (not ok)
            time.sleep(0.3)

    elapsed = time.time() - start_time
    logger.info(
        f"\n{'='*50}\n"
        f"完成！耗時 {elapsed:.0f}s\n"
        f"成功：{total_ok}　跳過/失敗：{total_skip}\n"
        f"{'='*50}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="批次入庫腳本")
    parser.add_argument("--config", default="config/ingest_targets.yaml")
    parser.add_argument("--dry-run", action="store_true", help="只顯示目標，不實際入庫")
    args = parser.parse_args()
    run(args.config, dry_run=args.dry_run)
