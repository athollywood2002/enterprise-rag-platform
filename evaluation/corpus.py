"""Strict v1 corpus and development gold schemas; no holdout contents or I/O."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from itertools import pairwise
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from evaluation.canonical import NORMALIZATION_VERSION, PARSER_PINS, normalize, text_sha256

Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")]
Nonempty = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Package(StrictRecord):
    name: Nonempty
    version: Nonempty


class ParserIdentity(StrictRecord):
    profile: Literal["unstructured-pdf-fast-v1"] = "unstructured-pdf-fast-v1"
    normalization: Literal["nfc-quotes-whitespace-v1"] = NORMALIZATION_VERSION
    unicode_version: Nonempty
    packages: tuple[Package, ...]

    @model_validator(mode="after")
    def require_supported_profile(self) -> Self:
        actual = tuple((p.name, p.version) for p in self.packages)
        if sorted(actual) != sorted(PARSER_PINS) or len(actual) != len(PARSER_PINS):
            raise ValueError("Parser profile drift; rebuild/revalidate corpus and labels")
        if self.unicode_version != unicodedata.unidata_version:
            raise ValueError("Unicode runtime drift; canonical text must be revalidated")
        return self


class SourceRecord(StrictRecord):
    title: Nonempty
    canonical_url: Annotated[
        str, StringConstraints(pattern=r"^(https://[^\s]+|urn:synthetic:[^\s]+)$")
    ]
    revision: Nonempty
    license_id: Nonempty
    attribution: Nonempty
    redistribution: Literal["unverified", "local_only", "redistributable"]


class CanonicalPage(StrictRecord):
    page: Annotated[int, Field(ge=1)]
    text: str
    sha256: Digest

    @model_validator(mode="after")
    def verify_text(self) -> Self:
        if self.text != normalize(self.text) or self.sha256 != text_sha256(self.text):
            raise ValueError("Canonical text/hash mismatch")
        return self


class CanonicalDocument(StrictRecord):
    doc_id: Identifier
    doc_version: Digest  # SHA-256 of source bytes, independent of chunking policy.
    source: SourceRecord
    parser: ParserIdentity
    pages: Annotated[tuple[CanonicalPage, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def physical_pages(self) -> Self:
        if tuple(p.page for p in self.pages) != tuple(range(1, len(self.pages) + 1)):
            raise ValueError("Physical pages must be ordered, contiguous and unique")
        if not any(p.text for p in self.pages):
            raise ValueError("Document contains no extractable canonical text")
        return self


class CorpusManifest(StrictRecord):
    schema_version: Literal["canonical-corpus-v1"] = "canonical-corpus-v1"
    documents: Annotated[tuple[CanonicalDocument, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_documents(self) -> Self:
        keys = [(d.doc_id, d.doc_version) for d in self.documents]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate document version")
        return self


def corpus_sha256(corpus: CorpusManifest) -> str:
    """Hash sorted-key compact UTF-8 JSON; list order remains significant."""
    canonical = json.dumps(
        corpus.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class GoldSpan(StrictRecord):
    doc_id: Identifier
    doc_version: Digest
    page: Annotated[int, Field(ge=1)]
    page_sha256: Digest
    start: Annotated[int, Field(ge=0)]
    end: Annotated[int, Field(ge=1)]
    excerpt: Nonempty

    @model_validator(mode="after")
    def nonempty_normalized_span(self) -> Self:
        if self.end <= self.start or self.excerpt != normalize(self.excerpt):
            raise ValueError("Gold span must be nonempty and canonical")
        return self


class GoldQuestion(StrictRecord):
    query_id: Identifier
    question: Nonempty
    category: Literal["answerable", "near_miss", "off_topic"]
    review_status: Literal["draft", "human_reviewed"] = "draft"
    spans: tuple[GoldSpan, ...] = ()

    @model_validator(mode="after")
    def category_and_spans(self) -> Self:
        if not self.question.strip() or bool(self.spans) != (self.category == "answerable"):
            raise ValueError("Answerable questions require gold; unknown categories forbid gold")
        grouped: dict[tuple[str, str, int], list[GoldSpan]] = {}
        for span in self.spans:
            grouped.setdefault((span.doc_id, span.doc_version, span.page), []).append(span)
        for spans in grouped.values():
            ordered = sorted(spans, key=lambda span: span.start)
            if any(left.end > right.start for left, right in pairwise(ordered)):
                raise ValueError("Duplicate/overlapping gold spans; use disjoint spans")
        return self


class DevelopmentLabels(StrictRecord):
    schema_version: Literal["span-labels-v1"] = "span-labels-v1"
    split: Literal["development"] = "development"
    corpus_sha256: Digest
    questions: Annotated[tuple[GoldQuestion, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_queries(self) -> Self:
        ids = [q.query_id for q in self.questions]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate query ID")
        return self


class HoldoutCommitment(StrictRecord):
    """Hash/count only. No label, question, path, encryption key or access claim."""

    schema_version: Literal["holdout-commitment-v1"] = "holdout-commitment-v1"
    plaintext_sha256: Digest
    question_count: Annotated[int, Field(ge=1)]


def find_page(corpus: CorpusManifest, doc_id: str, doc_version: str, page: int) -> CanonicalPage:
    for document in corpus.documents:
        if (document.doc_id, document.doc_version) == (doc_id, doc_version):
            if 1 <= page <= len(document.pages):
                return document.pages[page - 1]
            break
    raise ValueError("Unknown document version/page; reannotation required")


def validate_gold(span: GoldSpan, corpus: CorpusManifest) -> None:
    page = find_page(corpus, span.doc_id, span.doc_version, span.page)
    if page.sha256 != span.page_sha256:
        raise ValueError("Gold page hash drift; reannotation required")
    if span.end > len(page.text) or page.text[span.start : span.end] != span.excerpt:
        raise ValueError("Gold excerpt/offset mismatch; reannotation required")


def _check_versioned_json(payload: str, version: str) -> None:
    def unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    obj = json.loads(payload, object_pairs_hook=unique_keys)
    if not isinstance(obj, dict) or obj.get("schema_version") != version:
        raise ValueError("Missing/unsupported schema version")


def load_corpus(payload: str) -> CorpusManifest:
    """Require an explicit v1 tag and reject duplicate JSON keys at every level."""
    _check_versioned_json(payload, "canonical-corpus-v1")
    return CorpusManifest.model_validate_json(payload)


def load_development_labels(payload: str, corpus: CorpusManifest) -> DevelopmentLabels:
    """Validate caller-supplied development JSON; never discover/open any files."""
    _check_versioned_json(payload, "span-labels-v1")
    labels = DevelopmentLabels.model_validate_json(payload)
    if labels.corpus_sha256 != corpus_sha256(corpus):
        raise ValueError("Corpus identity drift; labels require revalidation")
    for question in labels.questions:
        for span in question.spans:
            validate_gold(span, corpus)
    return labels
