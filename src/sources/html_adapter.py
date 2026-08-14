"""基于标准库的 HTML 证据提取。"""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

from .base_adapter import build_source, make_unit, split_block
from .models import SourceAsset
from src.evidence.models import EvidenceUnit


class _HtmlBlockParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, str, tuple[str, ...]]] = []
        self.section_levels: list[str] = []
        self.current_section: list[str] = []
        self.buffer: list[str] = []
        self.cells: list[str] = []
        self.block_type = "paragraph"
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "nav", "footer", "aside"}:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._flush()
            self.block_type = "heading"
            self.section_levels = self.current_section[: max(0, int(tag[1:]) - 1)]
        elif tag == "tr":
            self._flush()
            self.cells = []
            self.block_type = "table_row"
        elif tag in {"td", "th"}:
            self.buffer = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "nav", "footer", "aside"} and self.skip_depth:
            self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            text = self._text()
            if text:
                level = int(tag[1:])
                self.current_section = self.current_section[: level - 1] + [text]
                self.section_levels = self.current_section[:]
            self._flush()
        elif tag in {"p", "li", "pre", "blockquote", "div", "br"}:
            self._flush()
        elif tag in {"td", "th"}:
            if self._text():
                self.cells.append(self._text())
            self.buffer = []
        elif tag == "tr":
            self._flush(" | ".join(self.cells))
            self.cells = []

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.buffer.append(data)

    def _text(self) -> str:
        return " ".join(" ".join(self.buffer).split())

    def _flush(self, forced: str | None = None) -> None:
        text = forced or self._text()
        self.buffer = []
        if text:
            self.blocks.append((self.block_type, text, tuple(self.section_levels or self.current_section)))
        self.block_type = "paragraph"


class HtmlSourceAdapter:
    extensions = (".html", ".htm")

    def __init__(self, *, max_chars: int = 2400) -> None:
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
        parser = _HtmlBlockParser()
        parser.feed(file_path.read_text(encoding="utf-8", errors="ignore"))
        units: list[EvidenceUnit] = []
        for block_type, text, section in parser.blocks:
            for part in split_block(text, self.max_chars):
                units.append(
                    make_unit(
                        source=source,
                        content=part,
                        index=len(units),
                        location={"kind": "html", "node_path": f"block[{len(units)}]"},
                        metadata={
                            "title": source.title,
                            "section_path": list(section),
                            "block_type": block_type,
                        },
                    )
                )
        return source, tuple(units)
