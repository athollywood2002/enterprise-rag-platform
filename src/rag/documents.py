"""Portable adaptation of AiMiniRig's Unstructured title-aware document chunking.

No hardcoded filesystem paths or Qdrant collection names. Do not send sensitive files.
"""
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

SUPPORTED_EXTENSIONS = {
    ".pdf", ".docx", ".pptx", ".xlsx", ".txt",
    ".html", ".htm", ".md", ".csv", ".eml", ".msg",
}


@dataclass(frozen=True)
class DocumentChunk:
    text: str
    source: str
    number: int
    page_number: int | None = None


def parse_document(data: bytes, filename: str) -> list[DocumentChunk]:
    """Parse uploaded bytes and use document-aware, title-based chunking.

    This import is delayed so lightweight API and unit tests do not require the large
    Unstructured dependency. The optional 'documents' extras must be installed.
    """
    from unstructured.partition.auto import partition
    from unstructured.chunking.title import chunk_by_title

    safe_name = Path(filename).name
    suffix = Path(safe_name).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported extension: {suffix}")
    if not data:
        raise ValueError("Empty document")

    with TemporaryDirectory(prefix="rag-input-") as temporary:
        path = Path(temporary) / ("document" + suffix)
        path.write_bytes(data)
        elements = [e for e in partition(filename=str(path)) if str(e).strip()]

    if not elements:
        return []
    chunks = chunk_by_title(
        elements,
        max_characters=1200,
        new_after_n_chars=1000,
        combine_text_under_n_chars=200,
        multipage_sections=True,
    )
    results = []
    for number, element in enumerate(chunks):
        page = getattr(getattr(element, "metadata", None), "page_number", None)
        results.append(
            DocumentChunk(
                text=str(element).strip(),
                source=safe_name,
                number=number,
                page_number=page if isinstance(page, int) else None,
            )
        )
    return [c for c in results if c.text]
