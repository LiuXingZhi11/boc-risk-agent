"""PDF/HTML 数据源适配层。"""

from .html_adapter import HtmlSourceAdapter
from .models import SourceAsset
from .pdf_adapter import PdfSourceAdapter
from .registry import ingest_source

__all__ = ["HtmlSourceAdapter", "PdfSourceAdapter", "SourceAsset", "ingest_source"]
