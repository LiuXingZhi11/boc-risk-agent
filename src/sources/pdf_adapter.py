"""PDF 证据提取适配器。

优先使用已安装的 pypdf；当前开发环境没有该包时，使用系统 pdftotext
提取文字，保留页码和内容哈希。
"""

from __future__ import annotations

import shutil
import subprocess
import os
from pathlib import Path

from src.evidence.models import EvidenceUnit

from .base_adapter import build_source, make_unit
from .models import SourceAsset
from .pdf_chunker import split_pdf_pages


class PdfSourceAdapter:
    extensions = (".pdf",)

    def __init__(self, *, max_chars: int = 3200) -> None:
        self.max_chars = max_chars

    def load(
        self,
        path: str | Path,
        *,
        case_id: str,
        source_date: str | None = None,
        title: str | None = None,
    ) -> tuple[SourceAsset, tuple[EvidenceUnit, ...]]:
        file_path = Path(path)
        source = build_source(file_path, case_id, source_date=source_date, title=title)
        pages = self._extract_pages(file_path)
        units: list[EvidenceUnit] = []
        for chunk in split_pdf_pages(pages, max_chars=self.max_chars):
            section_title = (
                f"人员履历：{chunk.person_name}"
                if chunk.person_name
                else chunk.section_path[-1] if chunk.section_path else source.title
            )
            metadata = {
                "title": section_title,
                "source_title": source.title,
                "section_path": list(chunk.section_path),
                "chunk_index_in_section": chunk.chunk_index_in_section,
                "heading_level": chunk.heading_level,
                "page": chunk.page_start,
            }
            if chunk.block_type:
                metadata["block_type"] = chunk.block_type
            if chunk.person_name:
                metadata["person_name"] = chunk.person_name
            units.append(
                make_unit(
                    source=source,
                    content=chunk.content,
                    index=len(units),
                    location={
                        "kind": "pdf",
                        "page_start": chunk.page_start,
                        "page_end": chunk.page_end,
                    },
                    metadata=metadata,
                )
            )
        return source, tuple(units)

    @staticmethod
    def _extract_pages(path: Path) -> list[str]:
        try:
            from pypdf import PdfReader  # type: ignore

            return [(page.extract_text() or "") for page in PdfReader(str(path)).pages]
        except Exception:
            command = _find_pdftotext()
            if not command:
                raise RuntimeError("PDF 解析需要 pypdf 或系统 pdftotext。")
            result = subprocess.run(
                [command, "-layout", str(path), "-"],
                check=True,
                capture_output=True,
                timeout=180,
            )
            return result.stdout.decode("utf-8", errors="ignore").split("\f")


def _find_pdftotext() -> str | None:
    """优先使用环境变量或可直接运行的 Poppler 版本。"""
    override = os.environ.get("PDFTOTEXT")
    if override:
        return override
    candidates: list[str] = []
    for name in ("pdftotext", "pdftotext.exe"):
        found = shutil.which(name)
        if found and found not in candidates:
            candidates.append(found)
    where = shutil.which("where")
    if where:
        result = subprocess.run([where, "pdftotext"], capture_output=True, text=True, check=False)
        candidates.extend(line.strip() for line in result.stdout.splitlines() if line.strip())
    candidates = list(dict.fromkeys(candidates))
    return next((path for path in candidates if "miktex" not in path.lower()), candidates[0] if candidates else None)
