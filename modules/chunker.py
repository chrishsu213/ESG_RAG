"""
modules/chunker.py — 模組 3：Semantic Chunker
基於 Markdown 標題的語義切割，相鄰 Chunk 保留 ~100 字元 overlap。
"""
from __future__ import annotations

import re
from typing import Any

from config import CHUNK_OVERLAP_CHARS, MIN_CHUNK_LENGTH, MAX_CHUNK_LENGTH


class SemanticChunker:
    """
    Header-based 語義切割器：
    以 Markdown 標題 (# ~ ######) 為邊界拆分 chunk，
    每個 chunk 盡量包含一個完整章節概念。
    超過 MAX_CHUNK_LENGTH 的 chunk 會自動在段落邊界處再分割。
    """

    _HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
    _PAGE_MARKER_RE = re.compile(r"<!-- PAGE:(\d+) -->", re.MULTILINE)

    def __init__(self, overlap: int = CHUNK_OVERLAP_CHARS) -> None:
        self.overlap = overlap
        self.max_length = MAX_CHUNK_LENGTH

    def chunk(self, markdown: str) -> list[dict[str, Any]]:
        """
        將 Markdown 文本切割為 chunk 列表。
        """
        sections = self._split_by_heading(markdown)

        # 合併過短的片段到前一個 section
        merged = self._merge_short_sections(sections)

        # 分割過長的片段
        split_sections: list[dict] = []
        for sec in merged:
            if len(sec["text"]) > self.max_length:
                split_sections.extend(self._split_long_section(sec))
            else:
                split_sections.append(sec)

        # 產生帶 overlap 的 chunks
        chunks: list[dict[str, Any]] = []
        for idx, section in enumerate(split_sections):
            text = section["text"]

            # 加入前一個 chunk 的尾部 overlap
            if idx > 0 and self.overlap > 0:
                prev_text = split_sections[idx - 1]["text"]
                overlap_text = prev_text[-self.overlap:]
                text = overlap_text + "\n" + text

            # 提取頁碼範圍
            page_start, page_end = self._extract_page_range(text)

            # 移除頁碼標記
            clean_text = self._PAGE_MARKER_RE.sub("", text).strip()

            chunks.append({
                "chunk_index": idx,
                "text_content": clean_text,
                "metadata": {
                    "section_title": section.get("title", ""),
                    "heading_level": section.get("level"),
                    "page_start": page_start,
                    "page_end": page_end,
                },
            })

        return chunks

    # ── 內部方法 ─────────────────────────────────────
    def _split_by_heading(self, markdown: str) -> list[dict]:
        """
        依 Markdown 標題行拆分為 section 列表。
        每個 section = {title, level, text}
        """
        sections: list[dict] = []
        # 找出所有標題位置
        matches = list(self._HEADING_RE.finditer(markdown))

        if not matches:
            # 整份文件沒有任何標題 → 視為單一 section
            return [{"title": "", "level": None, "text": markdown.strip()}]

        # 標題前的文字（如果有的話）
        first_start = matches[0].start()
        if first_start > 0:
            preamble = markdown[:first_start].strip()
            if preamble:
                sections.append({"title": "(前言)", "level": None, "text": preamble})

        for i, match in enumerate(matches):
            level = len(match.group(1))
            title = match.group(2).strip()
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
            text = markdown[start:end].strip()
            sections.append({"title": title, "level": level, "text": text})

        return sections

    def _merge_short_sections(self, sections: list[dict]) -> list[dict]:
        """將過短的 section 合併到前一個 section。"""
        if not sections:
            return sections

        merged: list[dict] = [sections[0]]
        for sec in sections[1:]:
            if len(sec["text"]) < MIN_CHUNK_LENGTH and merged:
                # 合併到前一個
                merged[-1]["text"] += "\n\n" + sec["text"]
            else:
                merged.append(sec)

        return merged

    def _split_long_section(self, section: dict) -> list[dict]:
        """將過長的 section 在段落邊界處分割為多個較短的 section。"""
        text = section["text"]
        title = section.get("title", "")
        level = section.get("level")

        # 以雙換行分段
        paragraphs = re.split(r"\n\s*\n", text)
        
        sub_sections: list[dict] = []
        current_text = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            # 如果加入這段後會超過上限，先存起來
            if current_text and len(current_text) + len(para) + 2 > self.max_length:
                sub_sections.append(current_text)
                current_text = para
            else:
                current_text = current_text + "\n\n" + para if current_text else para

        if current_text:
            sub_sections.append(current_text)

        # 轉為 section dict 列表
        if len(sub_sections) <= 1:
            return [section]

        return [
            {
                "title": f"{title} ({i+1}/{len(sub_sections)})" if title else "",
                "level": level,
                "text": sub_text,
            }
            for i, sub_text in enumerate(sub_sections)
        ]

    @classmethod
    def _extract_page_range(cls, text: str) -> tuple[int | None, int | None]:
        """從文本中提取頁碼範圍（由 PDF Parser 插入的 <!-- PAGE:N --> 標記）。"""
        pages = [int(m.group(1)) for m in cls._PAGE_MARKER_RE.finditer(text)]
        if not pages:
            return None, None
        return min(pages), max(pages)
