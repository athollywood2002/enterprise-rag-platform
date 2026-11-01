"""Portable adaptation of AiMiniRig's Unstructured title-aware document chunking.

No hardcoded filesystem paths or Qdrant collection names. Do not send sensitive files.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from unstructured.documents.elements import Element

SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".txt",
    ".html",
    ".htm",
    ".md",
    ".csv",
    ".eml",
    ".msg",
}


@dataclass(frozen=True)
class DocumentChunk:
    text: str
    source: str
    number: int
    page_number: int | None = None


def parse_document(data: bytes, filename: str) -> list[DocumentChunk]:
    """Parse local uploads into page-local, title-aware chunks.

    Optional imports follow input validation. PDF extraction is text-only (fast),
    never an automatic OCR/model fallback. Unknown pages stay unknown.
    """
    if any(ord(char) < 32 for char in filename):
        raise ValueError("Invalid filename")
    safe_name = Path(filename.replace("\\", "/")).name
    suffix = Path(safe_name).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported extension: {suffix}")
    if not data:
        raise ValueError("Empty document")

    with TemporaryDirectory(prefix="rag-input-") as temporary:
        path = Path(temporary) / ("document" + suffix)
        path.write_bytes(data)
        elements = [e for e in _partition_document(path, suffix) if str(e).strip()]

    if not elements:
        raise ValueError("Document contains no extractable text")

    from unstructured.chunking.title import chunk_by_title

    results: list[DocumentChunk] = []
    # Group consecutive elements before chunking: even short-section combination
    # cannot mix a known page with another page or an unknown page.
    for page, page_elements in groupby(elements, key=_page_number):
        chunks = chunk_by_title(
            list(page_elements),
            max_characters=1200,
            new_after_n_chars=1000,
            combine_text_under_n_chars=200,
            multipage_sections=False,
        )
        for element in chunks:
            text = str(element).strip()
            if not text:
                continue
            results.append(
                DocumentChunk(text=text, source=safe_name, number=len(results), page_number=page)
            )
    return results


def _page_number(element: Element) -> int | None:
    page = getattr(getattr(element, "metadata", None), "page_number", None)
    return page if type(page) is int and page > 0 else None


def _partition_document(path: Path, suffix: str) -> list[Element]:
    if suffix == ".pdf":
        # Reject malformed/encrypted PDFs rather than letting type detection
        # reinterpret their bytes as text or auto-fallback to OCR.
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        try:
            reader = PdfReader(path, strict=True)
            if reader.is_encrypted:
                raise ValueError("Invalid PDF: encrypted documents are not supported")
            len(reader.pages)
        except PdfReadError as error:
            raise ValueError("Invalid PDF document") from error

        from unstructured.partition.pdf import partition_pdf

        return partition_pdf(filename=str(path), strategy="fast", languages=["eng"])

    from unstructured.partition.auto import partition

    return partition(filename=str(path))
