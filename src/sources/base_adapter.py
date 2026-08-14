"""数据源适配器公共逻辑。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

from src.evidence.hashing import hash_file, hash_text
from src.evidence.models import EvidenceUnit

from .models import SourceAsset


def source_id_for(path: str | Path, case_id: str) -> str:
    value = f"{case_id}:{Path(path).resolve()}".encode("utf-8")
    return f"src_{hashlib.sha1(value).hexdigest()[:16]}"


def build_source(path: str | Path, case_id: str, *, source_date: str | None, title: str | None) -> SourceAsset:
    file_path = Path(path)
    suffix = file_path.suffix.lower().lstrip(".")
    return SourceAsset(
        source_id=source_id_for(file_path, case_id),
        case_id=case_id,
        source_type=suffix,
        path=str(file_path),
        title=title or file_path.stem,
        source_date=source_date,
        content_hash=hash_file(file_path),
    )


def split_block(text: str, max_chars: int) -> Iterable[str]:
    """按长度切分单个已识别的 HTML 块，不承担 PDF 结构识别。"""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    text = "\n".join(lines).strip()
    if not text:
        return
    paragraphs = [part.strip() for part in text.split("\n") if part.strip()]
    buffer = ""
    for paragraph in paragraphs:
        if len(paragraph) <= max_chars and len(buffer) + len(paragraph) + 1 <= max_chars:
            buffer = f"{buffer}\n{paragraph}".strip()
            continue
        if buffer:
            yield buffer
        while len(paragraph) > max_chars:
            yield paragraph[:max_chars]
            paragraph = paragraph[max_chars:]
        buffer = paragraph
    if buffer:
        yield buffer


def make_unit(
    *,
    source: SourceAsset,
    content: str,
    index: int,
    location: dict,
    metadata: dict,
) -> EvidenceUnit:
    unit_hash = hash_text(content)
    return EvidenceUnit(
        evidence_unit_id=f"{source.source_id}:eu_{index:05d}",
        source_id=source.source_id,
        case_id=source.case_id,
        content_type="document_chunk",
        content=content,
        location=location,
        metadata=metadata,
        source_date=source.source_date,
        content_hash=unit_hash,
    )
