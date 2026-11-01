"""Versioned canonical text for offline evaluation, separate from serving code."""

from __future__ import annotations

import hashlib
import os
import unicodedata
from collections import Counter
from dataclasses import dataclass
from importlib.metadata import version
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from evaluation.corpus import CanonicalDocument, SourceRecord
    from evaluation.spans import ChunkLocation

NORMALIZATION_VERSION = "nfc-quotes-whitespace-v1"
PARSER_PROFILE = "unstructured-pdf-fast-v1"
PARSER_PINS = (
    ("unstructured", "0.18.32"),
    ("unstructured-inference", "1.6.17"),
    ("pdfminer.six", "20260107"),
    ("pypdf", "6.21.4"),
    ("nltk", "3.10.4"),
)
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})


def normalize(text: str) -> str:
    """NFC, four curly-quote folds, Unicode whitespace to one ASCII space, strip.

    No case folding, punctuation removal, NFKC or byte-based indexing. Offsets
    refer only to the resulting string, never back into raw PDF/parser text.
    """
    return " ".join(unicodedata.normalize("NFC", text).translate(_QUOTES).split())


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CanonicalExtraction:
    document: CanonicalDocument
    chunks: tuple[ChunkLocation, ...]
    chunking_policy: str = "unstructured-title-page-local-v1"

    @property
    def mapping_counts(self) -> dict[str, int]:
        return dict(Counter(chunk.status for chunk in self.chunks))


def extract_pdf(data: bytes, *, doc_id: str, source: SourceRecord) -> CanonicalExtraction:
    """One pinned Unstructured pass supplies both canonical pages and real chunks.

    Local embedded-text PDFs only. No downloads, OCR, model/database calls or
    network setup. Caller supplies bytes and reviewed source/rights metadata.
    Package mismatch fails before parsing; unknown page attribution fails closed.
    """
    from evaluation.corpus import CanonicalDocument, CanonicalPage, Package, ParserIdentity
    from evaluation.spans import map_chunk

    if any(
        os.environ.get(name) != expected
        for name, expected in (
            ("AUTO_DOWNLOAD_NLTK", "false"),
            ("HF_HUB_OFFLINE", "1"),
            ("TRANSFORMERS_OFFLINE", "1"),
        )
    ):
        raise ValueError("Set explicit offline parser environment before extraction")
    packages = tuple(Package(name=name, version=version(name)) for name, _ in PARSER_PINS)
    identity = ParserIdentity(packages=packages, unicode_version=unicodedata.unidata_version)
    if not data:
        raise ValueError("Empty PDF")

    from pypdf import PdfReader
    from unstructured.chunking.title import chunk_by_title

    from rag.documents import _page_number, _partition_document

    reader = PdfReader(BytesIO(data), strict=True)
    if reader.is_encrypted:
        raise ValueError("Encrypted PDF is unsupported")
    page_count = len(reader.pages)
    with TemporaryDirectory(prefix="canonical-pdf-") as temporary:
        path = Path(temporary) / "document.pdf"
        path.write_bytes(data)
        elements = [e for e in _partition_document(path, ".pdf") if str(e).strip()]
    grouped: dict[int, list] = {number: [] for number in range(1, page_count + 1)}
    for element in elements:
        number = _page_number(element)
        if number not in grouped:
            raise ValueError("Unknown/out-of-range parser page; canonicalization rejected")
        grouped[number].append(element)
    pages = []
    for number, page_elements in grouped.items():
        # Separator is part of the specified pre-normalization procedure. Final
        # whitespace collapse makes both paragraph breaks and line wraps spaces.
        text = normalize("\n\n".join(str(e) for e in page_elements))
        pages.append(CanonicalPage(page=number, text=text, sha256=text_sha256(text)))
    document = CanonicalDocument(
        doc_id=doc_id,
        doc_version=hashlib.sha256(data).hexdigest(),
        source=source,
        parser=identity,
        pages=tuple(pages),
    )
    located = []
    for number, page_elements in grouped.items():
        if not page_elements:
            continue
        chunks = chunk_by_title(
            page_elements,
            max_characters=1200,
            new_after_n_chars=1000,
            combine_text_under_n_chars=200,
            multipage_sections=False,
        )
        located.extend(map_chunk(document, number, str(chunk)) for chunk in chunks)
    return CanonicalExtraction(document=document, chunks=tuple(located))
