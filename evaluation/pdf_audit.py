"""Metadata-only offline PDF inspection, not corpus admission or label creation."""

from __future__ import annotations

import hashlib
import unicodedata
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from evaluation.canonical import extract_pdf, normalize
from evaluation.corpus import SourceRecord


def format_counts(text: str) -> dict[str, int]:
    """Count Unicode Cf code points without changing or echoing text."""
    return dict(
        sorted(Counter(f"U+{ord(c):04X}" for c in text if unicodedata.category(c) == "Cf").items())
    )


def audit_pdf(data: bytes, *, doc_id: str, source: SourceRecord) -> dict[str, Any]:
    """Run real fast extraction and independent partition/serving passes.

    Caller supplies checked local bytes and reviewed inspection metadata. Offline
    environment is enforced by extract_pdf before parser imports. Network denial
    must additionally be enforced by the caller/test environment. No admission,
    storage, downloader, labels, model inference or normalization changes here.
    """
    extraction = extract_pdf(data, doc_id=doc_id, source=source)
    document = extraction.document

    from rag.documents import _page_number, _partition_document, parse_document

    # A second real partition pass inventories pre-normalization format characters
    # and checks page reproducibility without altering the canonical extractor.
    with TemporaryDirectory(prefix="pdf-audit-") as temporary:
        path = Path(temporary) / "document.pdf"
        path.write_bytes(data)
        elements = [e for e in _partition_document(path, ".pdf") if str(e).strip()]
    raw_pages: dict[int, list[str]] = {page.page: [] for page in document.pages}
    for element in elements:
        page = _page_number(element)
        if page not in raw_pages:
            raise ValueError("Audit partition has unknown/out-of-range page")
        raw_pages[page].append(str(element))

    serving = parse_document(data, "inspection.pdf")
    serving_locations = [(c.page_number, normalize(c.text)) for c in serving if normalize(c.text)]
    candidates = [(c.page, c.text) for c in extraction.chunks]
    pages = []
    for page in document.pages:
        raw = "\n\n".join(raw_pages[page.page])
        chunks = [c for c in extraction.chunks if c.page == page.page]
        covered = set()
        for chunk in chunks:
            if chunk.status == "mapped":
                if chunk.start is None or chunk.end is None:
                    raise ValueError("Mapped chunk lacks bounds")
                covered.update(range(chunk.start, chunk.end))
        pages.append(
            {
                "page": page.page,
                "canonical_sha256": page.sha256,
                "canonical_characters": len(page.text),
                "blank": not page.text,
                "raw_partition_cf": format_counts(raw),
                "canonical_cf": format_counts(page.text),
                "canonical_cc": dict(
                    sorted(
                        Counter(
                            f"U+{ord(c):04X}" for c in page.text if unicodedata.category(c) == "Cc"
                        ).items()
                    )
                ),
                "partition_repeat_matches_canonical": normalize(raw) == page.text,
                "mapping_counts": dict(sorted(Counter(c.status for c in chunks).items())),
                "nonspace_characters_outside_mapped_chunks": sum(
                    i not in covered and not c.isspace() for i, c in enumerate(page.text)
                ),
            }
        )
    return {
        "doc_id": doc_id,
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "source_bytes": len(data),
        "source": source.model_dump(mode="json"),
        "parser": document.parser.model_dump(mode="json"),
        "normalization": document.parser.normalization,
        "chunking_policy": extraction.chunking_policy,
        "physical_pages": len(pages),
        "pages": pages,
        "mapping_counts": dict(sorted(extraction.mapping_counts.items())),
        "all_candidate_chunks_mapped": all(c.status == "mapped" for c in extraction.chunks),
        "mapping_failures": [
            {
                "index": i,
                "page": c.page,
                "status": c.status,
                "chunk_sha256": hashlib.sha256(c.text.encode("utf-8")).hexdigest(),
                "match_count": c.match_count,
                "start": c.start,
                "end": c.end,
            }
            for i, c in enumerate(extraction.chunks)
            if c.status != "mapped"
        ],
        "serving_normalized_text_and_page_parity": serving_locations == candidates,
        "serving_raw_chunks": len(serving),
        "serving_normalized_empty_chunks": sum(not normalize(c.text) for c in serving),
        "inspection_only": True,
        "corpus_admitted": False,
    }
