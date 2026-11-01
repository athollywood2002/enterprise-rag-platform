"""Unique canonical chunk mapping and page-bound gold coverage, not dataset metrics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from evaluation.canonical import normalize
from evaluation.corpus import CanonicalDocument, CorpusManifest, GoldSpan, find_page, validate_gold


class MappingFailure(ValueError):
    """An explicit mapping failure cannot silently become a retrieval miss."""


@dataclass(frozen=True)
class ChunkLocation:
    doc_id: str
    doc_version: str
    page: int | None
    page_sha256: str | None
    text: str
    status: Literal["mapped", "empty", "missing_page", "unlocatable", "ambiguous"]
    match_count: int
    start: int | None = None
    end: int | None = None


def map_chunk(document: CanonicalDocument, page: int | None, text: str) -> ChunkLocation:
    candidate = normalize(text)
    fields = {
        "doc_id": document.doc_id,
        "doc_version": document.doc_version,
        "page": page,
        "page_sha256": None,
        "text": candidate,
    }
    if type(page) is not int or not 1 <= page <= len(document.pages):
        return ChunkLocation(**fields, status="missing_page", match_count=0)
    canonical = document.pages[page - 1]
    fields["page_sha256"] = canonical.sha256
    if not candidate:
        return ChunkLocation(**fields, status="empty", match_count=0)
    matches = []
    start = canonical.text.find(candidate)
    while start != -1:
        matches.append(start)
        start = canonical.text.find(candidate, start + 1)  # Include overlapping occurrences.
    if len(matches) != 1:
        return ChunkLocation(
            **fields, status="ambiguous" if matches else "unlocatable", match_count=len(matches)
        )
    return ChunkLocation(
        **fields, status="mapped", match_count=1, start=matches[0], end=matches[0] + len(candidate)
    )


def _validated_location(chunk: ChunkLocation, corpus: CorpusManifest) -> None:
    if chunk.status != "mapped":
        raise MappingFailure("Unmapped chunk requires separate failure reporting")
    if (
        type(chunk.start) is not int
        or type(chunk.end) is not int
        or type(chunk.page) is not int
        or type(chunk.match_count) is not int
        or chunk.start < 0
        or chunk.end <= chunk.start
        or chunk.match_count != 1
    ):
        raise MappingFailure("Invalid mapped chunk bounds")
    page = find_page(corpus, chunk.doc_id, chunk.doc_version, chunk.page)
    if (
        page.sha256 != chunk.page_sha256
        or chunk.end > len(page.text)
        or not chunk.text
        or chunk.text != normalize(chunk.text)
        or page.text[chunk.start : chunk.end] != chunk.text
    ):
        raise MappingFailure("Mapped chunk differs from canonical page")
    # Serialized/constructed locations must not bypass uniqueness checks.
    if page.text.find(chunk.text) != page.text.rfind(chunk.text):
        raise MappingFailure("Mapped chunk is ambiguous")


def span_coverage(
    span: GoldSpan, chunks: tuple[ChunkLocation, ...], corpus: CorpusManifest
) -> float:
    """Union of covered gold code points / gold length; half-open intervals."""
    validate_gold(span, corpus)
    intervals = []
    for chunk in chunks:
        _validated_location(chunk, corpus)
        if (chunk.doc_id, chunk.doc_version, chunk.page, chunk.page_sha256) != (
            span.doc_id,
            span.doc_version,
            span.page,
            span.page_sha256,
        ):
            continue
        start, end = max(span.start, chunk.start), min(span.end, chunk.end)
        if start < end:
            intervals.append((start, end))
    covered, previous_end = 0, span.start
    for start, end in sorted(intervals):
        covered += max(0, end - max(start, previous_end))
        previous_end = max(previous_end, end)
    return covered / (span.end - span.start)


def chunk_relevant(span: GoldSpan, chunk: ChunkLocation, corpus: CorpusManifest) -> bool:
    """>=50% gold coverage OR full normalized excerpt; always bound to doc/page/hash."""
    coverage = span_coverage(span, (chunk,), corpus)
    same_page = (chunk.doc_id, chunk.doc_version, chunk.page, chunk.page_sha256) == (
        span.doc_id,
        span.doc_version,
        span.page,
        span.page_sha256,
    )
    return coverage >= 0.5 or (same_page and span.excerpt in chunk.text)
