"""面向中文披露文件的章节感知 PDF 文本切分。"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass


_CHINESE_NUMBER = "零〇一二三四五六七八九十百千万"
_HEADING_PATTERNS = (
    (1, re.compile(rf"^第[{_CHINESE_NUMBER}0-9]+[篇章部]\s*")),
    (2, re.compile(rf"^第[{_CHINESE_NUMBER}0-9]+节\s*")),
    (3, re.compile(rf"^[{_CHINESE_NUMBER}]+[、．.]\s*")),
    (4, re.compile(rf"^[（(][{_CHINESE_NUMBER}]+[）)]\s*")),
    (
        5,
        re.compile(
            r"^(?:[1-9]\d?[、．]\s*|[1-9]\d?\.(?!\d)\s*|"
            r"[1-9]\d?(?:\.\d+)+(?:[、．])?\s+)"
        ),
    ),
    (6, re.compile(r"^[（(][1-9]\d?[）)]\s*")),
    (7, re.compile(r"^[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]\s*")),
)

_BIOGRAPHY_TABLE_HEADER = re.compile(
    r"^姓名\s*(?:主要工作经历|主要职业经历|个人简历|简历)\s*$"
)
_PERSON_NAME = r"[\u3400-\u9fff·]{2,6}"
_PERSON_WITH_GENDER = re.compile(
    rf"^(?P<name>{_PERSON_NAME})(?:\s+|[，,、]\s*)(?:男|女)(?:[，,、。\s]|$)"
)
_PERSON_WITH_TITLE = re.compile(
    rf"^(?P<name>{_PERSON_NAME})(?:先生|女士)(?:[，,、。\s]|$)"
)
_PERSON_REFERENCE = re.compile(
    rf"^(?P<name>{_PERSON_NAME})[，,、]\s*(?:简历|履历)(?:详见|见)"
)
_PERSON_NAME_ONLY = re.compile(rf"^(?P<name>{_PERSON_NAME})$")
_GENDER_LINE = re.compile(r"^(?:男|女)(?:[，,、。\s]|$)")
_BIOGRAPHY_INTRO = re.compile(
    r"^(?=.*(?:董事|监事|高级管理人员|核心技术人员|核心人员|主要人员))"
    r".*(?:具体情况|基本情况|简历|履历)(?:如下)?[：:]?\s*$"
)
_BIOGRAPHY_SCOPE_HEADING = re.compile(
    r"(?:董事|监事|高级管理人员|核心技术人员|核心人员).*(?:简历|履历|基本情况|具体情况)|"
    r"(?:简历|履历|基本情况|具体情况).*(?:董事|监事|高级管理人员|核心技术人员|核心人员)|"
    r"(?:董事会成员|高级管理人员)\s*$"
)
_BIOGRAPHY_END = re.compile(r"^(?:其它|其他)情况说明\s*$")


@dataclass(frozen=True)
class PdfTextChunk:
    content: str
    page_start: int
    page_end: int
    section_path: tuple[str, ...]
    chunk_index_in_section: int
    heading_level: int | None
    block_type: str | None = None
    person_name: str | None = None


def split_pdf_pages(
    pages: list[str],
    *,
    max_chars: int = 3200,
) -> tuple[PdfTextChunk, ...]:
    """按章节边界切分整份 PDF，同一 Chunk 不跨章节。"""
    if max_chars <= 0:
        raise ValueError("max_chars 必须是正整数。")
    cleaned_pages = _clean_pages(pages)
    chunks: list[PdfTextChunk] = []
    section_titles: list[str] = []
    section_levels: list[int] = []
    section_counts: Counter[tuple[str, ...]] = Counter()
    buffer: list[tuple[str, int]] = []
    buffer_has_body = False
    biography_mode = False
    current_block_type: str | None = None
    current_person_name: str | None = None

    def flush() -> None:
        nonlocal buffer, buffer_has_body
        if not buffer:
            return
        content = "\n".join(line for line, _ in buffer).strip()
        if content:
            section_path = tuple(section_titles)
            chunk_index = section_counts[section_path]
            section_counts[section_path] += 1
            chunks.append(
                PdfTextChunk(
                    content=content,
                    page_start=min(page for _, page in buffer),
                    page_end=max(page for _, page in buffer),
                    section_path=section_path,
                    chunk_index_in_section=chunk_index,
                    heading_level=section_levels[-1] if section_levels else None,
                    block_type=current_block_type,
                    person_name=current_person_name,
                )
            )
        buffer = []
        buffer_has_body = False

    for page_number, lines in cleaned_pages:
        for line_index, line in enumerate(lines):
            heading_level = detect_heading_level(line)
            if heading_level is not None:
                if buffer_has_body:
                    flush()
                biography_mode = bool(_BIOGRAPHY_SCOPE_HEADING.search(line))
                current_block_type = None
                current_person_name = None
                while section_levels and section_levels[-1] >= heading_level:
                    section_levels.pop()
                    section_titles.pop()
                section_levels.append(heading_level)
                section_titles.append(line)
                buffer.append((line, page_number))
                continue

            if _BIOGRAPHY_TABLE_HEADER.match(line):
                if buffer_has_body:
                    flush()
                biography_mode = True
                current_block_type = None
                current_person_name = None
                continue

            if _BIOGRAPHY_INTRO.match(line):
                if buffer_has_body:
                    flush()
                biography_mode = True
                current_block_type = None
                current_person_name = None
                continue

            if biography_mode and _BIOGRAPHY_END.match(line):
                if buffer_has_body:
                    flush()
                biography_mode = False
                current_block_type = None
                current_person_name = None

            if biography_mode:
                next_line = lines[line_index + 1] if line_index + 1 < len(lines) else ""
                person_name = _detect_person_start(line, next_line)
                if person_name:
                    if buffer_has_body:
                        flush()
                    current_block_type = "person_biography"
                    current_person_name = person_name

            for part in _split_long_line(line, max_chars):
                current_chars = sum(len(value) + 1 for value, _ in buffer)
                if buffer_has_body and current_chars + len(part) > max_chars:
                    flush()
                buffer.append((part, page_number))
                buffer_has_body = True
    flush()
    return tuple(chunks)


def _detect_person_start(line: str, next_line: str) -> str | None:
    for pattern in (_PERSON_WITH_GENDER, _PERSON_WITH_TITLE, _PERSON_REFERENCE):
        same_line = pattern.match(line)
        if same_line:
            return same_line.group("name")
    name_only = _PERSON_NAME_ONLY.fullmatch(line)
    if name_only and _GENDER_LINE.match(next_line):
        return name_only.group("name")
    return None


def detect_heading_level(line: str) -> int | None:
    text = _normalize_line(line)
    if not text or len(text) > 100:
        return None
    # 财务表格中的“一、项目 1,234.56 2,345.67 ...”是数据行，不是章节。
    if len(re.findall(r"\d[\d,]*\.\d+", text)) >= 2:
        return None
    for level, pattern in _HEADING_PATTERNS:
        if pattern.match(text):
            return level
    return None


def _clean_pages(pages: list[str]) -> list[tuple[int, list[str]]]:
    page_lines = [
        [_normalize_line(line) for line in page.splitlines() if _normalize_line(line)]
        for page in pages
    ]
    repeated_margins = _repeated_margin_lines(page_lines)
    cleaned: list[tuple[int, list[str]]] = []
    for page_number, lines in enumerate(page_lines, start=1):
        if _is_toc_page(lines):
            continue
        values = [
            line
            for line_index, line in enumerate(lines)
            if line not in repeated_margins
            and not _is_page_marker(line, line_index=line_index, line_count=len(lines))
        ]
        if values:
            cleaned.append((page_number, values))
    return cleaned


def _repeated_margin_lines(pages: list[list[str]]) -> set[str]:
    counts: Counter[str] = Counter()
    for lines in pages:
        margins = set((*lines[:3], *lines[-3:]))
        counts.update(line for line in margins if len(line) <= 80)
    threshold = max(2, math.ceil(len(pages) * 0.2))
    return {line for line, count in counts.items() if count >= threshold}


def _is_toc_page(lines: list[str]) -> bool:
    marker_count = sum(_is_toc_marker(line) for line in lines)
    return marker_count >= 3


def _is_toc_marker(line: str) -> bool:
    compact = re.sub(r"\s+", "", line)
    return bool(
        re.search(r"[.．。·…]{5,}", compact)
        or re.fullmatch(r"[.．。·…-]+", compact)
    )


def _is_page_marker(line: str, *, line_index: int, line_count: int) -> bool:
    compact = re.sub(r"\s+", "", line)
    if re.fullmatch(r"\d{1,3}[-－—]\d{1,3}[-－—]\d{1,4}", compact):
        return True
    if re.fullmatch(r"第?\d{1,4}页", compact):
        return True
    if not re.fullmatch(r"\d{1,4}", compact):
        return False
    # 纯数字只有位于页边缘时才可能是页码；正文表格中的年度、序号和数值必须保留。
    if line_index >= 2 and line_index < line_count - 2:
        return False
    number = int(compact)
    return not 1900 <= number <= 2100


def _split_long_line(line: str, max_chars: int) -> list[str]:
    if len(line) <= max_chars:
        return [line]
    parts = re.split(r"(?<=[。！？；])", line)
    values: list[str] = []
    buffer = ""
    for part in parts:
        if not part:
            continue
        if buffer and len(buffer) + len(part) > max_chars:
            values.append(buffer)
            buffer = ""
        while len(part) > max_chars:
            values.append(part[:max_chars])
            part = part[max_chars:]
        buffer += part
    if buffer:
        values.append(buffer)
    return values


def _normalize_line(line: str) -> str:
    return line.replace("\u00a0", " ").strip()
