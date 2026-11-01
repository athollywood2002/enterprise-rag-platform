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
    status: Literal[
        "mapped", "empty", "missing_page", "unlocatable", "ambiguous", "overlap", "blocked"
    ]
    match_count: int
    start: int | None = None
    end: int | None = None
    page_kind: Literal["physical", "logical"] = "physical"
    # Full normalized ordered prefix is replayed at deserialization validation.
    # A bare cursor integer would let callers skip to an arbitrary repeat.
    prefix: tuple[str, ...] | None = None


def map_chunk(document: CanonicalDocument, page: int | None, text: str) -> ChunkLocation:
    candidate = normalize(text)
    fields = {
        "doc_id": document.doc_id,
        "doc_version": document.doc_version,
        "page": page,
        "page_sha256": None,
        "text": candidate,
        "page_kind": document.page_kind,
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


def _next_start(text: str, cursor: int) -> int:
    return cursor + (1 if text[cursor : cursor + 1] == " " else 0)


def map_chunks(
    document: CanonicalDocument, page: int, texts: tuple[str, ...]
) -> tuple[ChunkLocation, ...]:
    """Validate actual ordered output against the entire canonical page prefix.

    Only canonical separator spaces may be skipped. Never jump over content to
    resolve a repeat. Failure blocks the suffix, avoiding a poisoned cursor.
    """
    from dataclasses import replace

    results = []
    if not texts:
        return (map_chunk(document, page, ""),)
    prefix: tuple[str, ...] = ()
    cursor = 0
    blocked = False
    for text in texts:
        location = map_chunk(document, page, text)
        if blocked:
            results.append(replace(location, status="blocked", start=None, end=None))
            continue
        if location.status in ("missing_page", "empty"):
            results.append(location)
            blocked = True
            continue
        canonical = document.pages[page - 1].text
        start = _next_start(canonical, cursor)
        if canonical.startswith(location.text, start):
            end = start + len(location.text)
            results.append(replace(location, status="mapped", start=start, end=end, prefix=prefix))
            prefix += (location.text,)
            cursor = end
        else:
            status = "ambiguous" if location.match_count > 1 else "unlocatable"
            first = canonical.find(location.text)
            if 0 <= first < cursor:
                status = "overlap"
            results.append(replace(location, status=status, start=None, end=None))
            blocked = True
    # No silently omitted trailing elements: output must cover the whole page.
    if results and not blocked and cursor != len(document.pages[page - 1].text):
        results[-1] = replace(results[-1], status="unlocatable", start=None, end=None)
    return tuple(results)


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
        or chunk.match_count < 1
    ):
        raise MappingFailure("Invalid mapped chunk bounds")
    page = find_page(corpus, chunk.doc_id, chunk.doc_version, chunk.page)
    document = next(
        d
        for d in corpus.documents
        if (d.doc_id, d.doc_version) == (chunk.doc_id, chunk.doc_version)
    )
    if chunk.page_kind != document.page_kind:
        raise MappingFailure("Mapped page kind mismatch")
    if (
        page.sha256 != chunk.page_sha256
        or chunk.end > len(page.text)
        or not chunk.text
        or chunk.text != normalize(chunk.text)
        or page.text[chunk.start : chunk.end] != chunk.text
    ):
        raise MappingFailure("Mapped chunk differs from canonical page")
    # Serialized/constructed locations must not bypass uniqueness checks.
    count = sum(page.text.startswith(chunk.text, i) for i in range(len(page.text)))
    if count != chunk.match_count:
        raise MappingFailure("Mapped match count mismatch")
    if chunk.prefix is None:
        if count != 1:
            raise MappingFailure("Mapped chunk is ambiguous")
    else:
        if type(chunk.prefix) is not tuple:
            raise MappingFailure("Invalid cursor prefix")
        cursor = 0
        for prior in chunk.prefix:
            if not isinstance(prior, str) or not prior or prior != normalize(prior):
                raise MappingFailure("Invalid cursor prefix text")
            start = _next_start(page.text, cursor)
            if not page.text.startswith(prior, start):
                raise MappingFailure("Cursor prefix does not cover canonical text")
            cursor = start + len(prior)
        if chunk.start != _next_start(page.text, cursor):
            raise MappingFailure("Cursor location differs from validated prefix")


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
    """>=50% coverage at the gold location, never identical text elsewhere."""
    return span_coverage(span, (chunk,), corpus) >= 0.5
