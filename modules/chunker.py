"""
modules/chunker.py — 模組 3：Semantic Chunker
基於 Markdown 標題的語義切割，相鄰 Chunk 保留 ~100 字元 overlap。
"""
from __future__ import annotations

import re
from typing import Any

from config import CHUNK_OVERLAP_CHARS, MIN_CHUNK_LENGTH, MAX_CHUNK_LENGTH

# Phase 2: 可選的 dataclass 設定（完全向下相容）
try:
    from config_modules import ChunkerConfig
except ImportError:
    ChunkerConfig = None  # type: ignore


class SemanticChunker:
    """
    Header-based 語義切割器：
    以 Markdown 標題 (# ~ ######) 為邊界拆分 chunk，
    每個 chunk 盡量包含一個完整章節概念。
    超過 MAX_CHUNK_LENGTH 的 chunk 會自動在段落邊界處再分割。

    可傳入 ChunkerConfig 覆寫預設參數：
        chunker = SemanticChunker(cfg=ChunkerConfig(max_length=3000))
    """

    _HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
    _PAGE_MARKER_RE = re.compile(r"<!-- PAGE:(\d+) -->", re.MULTILINE)
    # 表格保護：完整 Markdown 表格（含標頭分隔列）視為不可切割原子單位
    _TABLE_RE = re.compile(
        r"(?:(?:\|[^\n]+\|\n)+(?:\|[-|: ]+\|\n)(?:\|[^\n]+\|\n)*)",
        re.MULTILINE,
    )
    _TABLE_PLACEHOLDER_RE = re.compile(r"__TABLE_(\d+)__")

    def __init__(self, overlap: int = CHUNK_OVERLAP_CHARS, cfg=None) -> None:
        if cfg is not None:
            self.overlap = cfg.overlap
            self.max_length = cfg.max_length
        else:
            self.overlap = overlap
            self.max_length = MAX_CHUNK_LENGTH

    def chunk(self, markdown: str, strip_page_markers: bool = True) -> list[dict[str, Any]]:
        """
        將 Markdown 文本切割為 chunk 列表。

        Parameters
        ----------
        strip_page_markers : bool
            是否移除頁碼標記（預設 True）。
            chunk_parent_child() 內部傳入 False 以保留標記供 child 解析頁碼用。
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

            # 提取頁碼範圍（在清除標記之前）
            page_start, page_end = self._extract_page_range(text)

            # 🛡️ 保留標記（strip_page_markers=False）供外層使用，否則就地清除
            clean_text = self._PAGE_MARKER_RE.sub("", text).strip() if strip_page_markers else text.strip()

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

    def chunk_parent_child(
        self,
        markdown: str,
        child_max_length: int = 400,
    ) -> list[dict[str, Any]]:
        """
        Parent-Child 切割：
        - Parent = 現有 chunk() 邏輯切出的大段（≤ MAX_CHUNK_LENGTH）
        - Child  = Parent 內再依段落切細（≤ child_max_length）

        🛡️ 表格保護：Markdown 表格視為不可切割原子單位，不會在表格中間切斷。
        """
        # 🛡️ Bug Fix: strip_page_markers=False 保留頁碼標記，讓 child 補找正確頁碼
        parents = self.chunk(markdown, strip_page_markers=False)

        result = []
        global_child_idx = len(parents)

        for p_idx, parent in enumerate(parents):
            parent_text = parent["text_content"]
            parent_meta = parent["metadata"]

            # 🛡️ 表格保護：鎖定表格避免被段落切割截斷
            protected_parent, table_map = self._atomize_tables(parent_text)
            paragraphs = [
                p.strip() for p in re.split(r"\n\s*\n", protected_parent) if p.strip()
            ]

            children: list[dict[str, Any]] = []
            current = ""

            for para in paragraphs:
                if not current:
                    current = para
                elif len(current) + len(para) + 2 <= child_max_length:
                    current += "\n\n" + para
                else:
                    page_start, page_end = self._extract_page_range(current)
                    restored = self._restore_tables(current, table_map)
                    children.append({
                        "chunk_index": global_child_idx,
                        "text_content": self._PAGE_MARKER_RE.sub("", restored).strip(),
                        "metadata": {
                            **parent_meta,
                            "page_start": page_start or parent_meta.get("page_start"),
                            "page_end": page_end or parent_meta.get("page_end"),
                        },
                    })
                    global_child_idx += 1
                    current = para

            if current:
                page_start, page_end = self._extract_page_range(current)
                restored = self._restore_tables(current, table_map)
                children.append({
                    "chunk_index": global_child_idx,
                    "text_content": self._PAGE_MARKER_RE.sub("", restored).strip(),
                    "metadata": {
                        **parent_meta,
                        "page_start": page_start or parent_meta.get("page_start"),
                        "page_end": page_end or parent_meta.get("page_end"),
                    },
                })
                global_child_idx += 1

            if len(children) <= 1:
                children = []

            result.append({
                "parent": {
                    "chunk_index": p_idx,
                    "text_content": self._PAGE_MARKER_RE.sub("", parent_text).strip(),
                    "metadata": parent_meta,
                },
                "children": children,
            })

        return result


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

    def _atomize_tables(self, text: str) -> tuple[str, dict[str, str]]:
        """將 Markdown 表格替換為不透明占位符，防止後續切割時切斷表格。

        Returns
        -------
        (processed_text, table_map)
            table_map: {"__TABLE_0__": "原始表格內容", ...}
        """
        table_map: dict[str, str] = {}
        counter = 0

        def replace_table(match: re.Match) -> str:
            nonlocal counter
            key = f"__TABLE_{counter}__"
            table_map[key] = match.group(0)
            counter += 1
            return key

        processed = self._TABLE_RE.sub(replace_table, text)
        return processed, table_map

    @staticmethod
    def _restore_tables(text: str, table_map: dict[str, str]) -> str:
        """將占位符還原為原始表格內容。"""
        for key, original in table_map.items():
            text = text.replace(key, original)
        return text

    def _split_long_section(self, section: dict) -> list[dict]:
        """將過長的 section 在段落邊界處分割為多個較短的 section。

        表格會被視為不可切割的原子單位，不會在表格中間切斷。
        """
        text = section["text"]
        title = section.get("title", "")
        level = section.get("level")

        # 🛡️ 先鎖定表格，避免在段落切割時切斷表格結構
        protected_text, table_map = self._atomize_tables(text)

        paragraphs = re.split(r"\n\s*\n", protected_text)

        sub_sections: list[dict] = []
        current_text = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if current_text and len(current_text) + len(para) + 2 > self.max_length:
                # 還原表格後存入
                sub_sections.append(self._restore_tables(current_text, table_map))
                current_text = para
            else:
                current_text = current_text + "\n\n" + para if current_text else para

        if current_text:
            sub_sections.append(self._restore_tables(current_text, table_map))

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
