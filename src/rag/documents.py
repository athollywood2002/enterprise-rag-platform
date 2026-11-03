"""Portable adaptation of AiMiniRig's Unstructured title-aware document chunking.

No hardcoded filesystem paths or Qdrant collection names. Do not send sensitive files.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import groupby
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from rag.chunking import TITLE_CHUNKING
from rag.requirement_chunking import (
    NIST_REQUIREMENT_STRATEGY,
    ChunkingStrategy,
    RequirementState,
    requirement_page_fragments,
    validate_chunking_strategy,
)

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
    requirement_id: str | None = None


def parse_document(
    data: bytes, filename: str, *, chunking_strategy: ChunkingStrategy = "title"
) -> list[DocumentChunk]:
    """Parse local uploads into page-local, title-aware chunks.

    Optional imports follow input validation. PDF extraction is text-only (fast),
    never an automatic OCR/model fallback. Unknown pages stay unknown.
    """
    safe_name = sanitize_document_filename(filename)
    suffix = Path(safe_name).suffix.lower()
    validate_chunking_strategy(chunking_strategy)
    if chunking_strategy == NIST_REQUIREMENT_STRATEGY and suffix != ".pdf":
        raise ValueError("The opt-in requirement strategy supports PDF only")
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

    if chunking_strategy == NIST_REQUIREMENT_STRATEGY:
        results = []
        state = RequirementState()
        previous_page = 0
        for page, page_elements in groupby(elements, key=_page_number):
            if page is None or page <= previous_page:
                raise ValueError("Requirement strategy needs known, increasing physical pages")
            previous_page = page
            for fragment in requirement_page_fragments(page_elements, state):
                results.append(
                    DocumentChunk(
                        text=fragment.text,
                        source=safe_name,
                        number=len(results),
                        page_number=page,
                        requirement_id=fragment.requirement_id,
                    )
                )
        if not state.seen:
            raise ValueError("No supported requirement headings; use the default title strategy")
        return results

    from unstructured.chunking.title import chunk_by_title

    results: list[DocumentChunk] = []
    # Group consecutive elements before chunking: even short-section combination
    # cannot mix a known page with another page or an unknown page.
    for page, page_elements in groupby(elements, key=_page_number):
        chunks = chunk_by_title(
            list(page_elements),
            **asdict(TITLE_CHUNKING),
        )
        for element in chunks:
            text = str(element).strip()
            if not text:
                continue
            results.append(
                DocumentChunk(text=text, source=safe_name, number=len(results), page_number=page)
            )
    return results


def sanitize_document_filename(filename: str) -> str:
    """Return only a cross-platform basename; never accept control characters."""
    if any(ord(char) < 32 for char in filename):
        raise ValueError("Invalid filename")
    return Path(filename.replace("\\", "/")).name


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
