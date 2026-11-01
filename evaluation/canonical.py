"""Versioned canonical text for offline evaluation, separate from serving code."""

from __future__ import annotations

import hashlib
import os
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from importlib.metadata import version
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from rag.chunking import TITLE_CHUNKING

if TYPE_CHECKING:
    from evaluation.corpus import CanonicalDocument, SourceRecord
    from evaluation.spans import ChunkLocation

NORMALIZATION_VERSION = "nfc-quotes-artifacts-whitespace-v2"
PARSER_PROFILE = "unstructured-pdf-fast-v1"
PARSER_PINS = (
    ("unstructured", "0.18.32"),
    ("unstructured-inference", "1.6.17"),
    ("pdfminer.six", "20260107"),
    ("pypdf", "6.21.4"),
    ("nltk", "3.10.4"),
)
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})
_ARTIFACTS = str.maketrans(
    {
        **dict(zip("ﬀﬁﬂﬃﬄﬅﬆ", ("ff", "fi", "fl", "ffi", "ffl", "st", "st"))),
        **dict.fromkeys("\u00ad\u200b\u200c\u200d\ufeff", None),
    }
)


def normalize(text: str) -> str:
    """Targeted PDF artifacts, NFC/quote folds, whitespace collapse and strip.

    No case folding, universal dehyphenation, NFKC or byte-based indexing. Offsets
    refer only to the resulting string, never back into raw PDF/parser text.
    """
    return " ".join(
        unicodedata.normalize("NFC", text.translate(_ARTIFACTS)).translate(_QUOTES).split()
    )


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CanonicalExtraction:
    document: CanonicalDocument
    chunks: tuple[ChunkLocation, ...]
    chunking_policy: str = TITLE_CHUNKING.policy_id

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
    from evaluation.spans import map_chunks

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
    previous_page = 1
    for element in elements:
        number = _page_number(element)
        if number not in grouped:
            raise ValueError("Unknown/out-of-range parser page; canonicalization rejected")
        if number < previous_page:
            raise ValueError("Parser pages out of order; canonicalization rejected")
        previous_page = number
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
            **asdict(TITLE_CHUNKING),
        )
        located.extend(map_chunks(document, number, tuple(str(chunk) for chunk in chunks)))
    return CanonicalExtraction(document=document, chunks=tuple(located))


def extract_markdown(data: bytes, *, doc_id: str, source: SourceRecord) -> CanonicalExtraction:
    """UTF-8 Markdown SOURCE text, not rendered prose, as one logical page.

    Keep headings, links, fences and identifiers verbatim before normalization.
    No HTML interpretation, includes, frontmatter evaluation or remote resources.
    """
    from evaluation.corpus import CanonicalDocument, CanonicalPage, ParserIdentity
    from evaluation.spans import map_chunks

    text = normalize(data.decode("utf-8", errors="strict"))
    document = CanonicalDocument(
        doc_id=doc_id,
        doc_version=hashlib.sha256(data).hexdigest(),
        source=source,
        parser=ParserIdentity(
            profile="markdown-source-utf8-v1",
            packages=(),
            unicode_version=unicodedata.unidata_version,
        ),
        page_kind="logical",
        pages=(CanonicalPage(page=1, text=text, sha256=text_sha256(text)),),
    )
    # Source-text adapter has no title semantics. It exposes the entire logical
    # page as one chunk; do not misrepresent it as the serving Markdown parser.
    return CanonicalExtraction(
        document, map_chunks(document, 1, (text,)), chunking_policy="markdown-source-whole-file-v1"
    )


def extract_document(
    data: bytes, *, filename: str, doc_id: str, source: SourceRecord
) -> CanonicalExtraction:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return extract_pdf(data, doc_id=doc_id, source=source)
    if suffix == ".md":
        return extract_markdown(data, doc_id=doc_id, source=source)
    raise ValueError(f"Unsupported canonical source format: {suffix} (HTML not implemented)")
