"""数据源适配器注册和统一入口。"""

from __future__ import annotations

from pathlib import Path

from src.evidence.models import EvidenceUnit

from .html_adapter import HtmlSourceAdapter
from .models import SourceAsset
from .pdf_adapter import PdfSourceAdapter


ADAPTERS = {
    ".html": HtmlSourceAdapter(),
    ".htm": HtmlSourceAdapter(),
    ".pdf": PdfSourceAdapter(),
}


def ingest_source(
    path: str | Path,
    *,
    case_id: str,
    source_date: str | None = None,
    title: str | None = None,
) -> tuple[SourceAsset, tuple[EvidenceUnit, ...]]:
    file_path = Path(path)
    try:
        adapter = ADAPTERS[file_path.suffix.lower()]
    except KeyError as exc:
        raise ValueError(f"暂不支持的数据源格式：{file_path.suffix}") from exc
    return adapter.load(file_path, case_id=case_id, source_date=source_date, title=title)
