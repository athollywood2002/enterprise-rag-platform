"""Synthetic canonical references only; no parser install or services required."""

import hashlib
import json
import unicodedata
from dataclasses import replace

import pytest
from pydantic import ValidationError

from evaluation.canonical import PARSER_PINS, extract_pdf, normalize, text_sha256
from evaluation.corpus import (
    CanonicalDocument,
    CanonicalPage,
    CorpusManifest,
    DevelopmentLabels,
    GoldQuestion,
    GoldSpan,
    HoldoutCommitment,
    Package,
    ParserIdentity,
    SourceRecord,
    corpus_sha256,
    load_corpus,
    load_development_labels,
)
from evaluation.spans import MappingFailure, chunk_relevant, map_chunk, span_coverage


def document(texts=("Alpha beta gamma delta.",), version="synthetic-v1", doc_id="synthetic"):
    return CanonicalDocument(
        doc_id=doc_id,
        doc_version=text_sha256(version),
        source=SourceRecord(
            title="Authored synthetic fixture",
            canonical_url="urn:synthetic:g1-test",
            revision="1",
            license_id="MIT",
            attribution="Repository test authors",
            redistribution="redistributable",
        ),
        parser=ParserIdentity(
            packages=tuple(Package(name=name, version=pin) for name, pin in PARSER_PINS),
            unicode_version=unicodedata.unidata_version,
        ),
        pages=tuple(
            CanonicalPage(page=i, text=normalize(text), sha256=text_sha256(normalize(text)))
            for i, text in enumerate(texts, 1)
        ),
    )


def gold(doc, excerpt="beta", page=1):
    canonical = doc.pages[page - 1]
    start = canonical.text.index(excerpt)
    return GoldSpan(
        doc_id=doc.doc_id,
        doc_version=doc.doc_version,
        page=page,
        page_sha256=canonical.sha256,
        start=start,
        end=start + len(excerpt),
        excerpt=excerpt,
    )


def label_payload(corpus, spans):
    return DevelopmentLabels(
        corpus_sha256=corpus_sha256(corpus),
        questions=(
            GoldQuestion(
                query_id="q1",
                question="Which synthetic word?",
                category="answerable",
                spans=tuple(spans),
            ),
        ),
    ).model_dump_json()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" Cafe\u0301\t‘note’\r\n“Title”\u00a0 ", "Café 'note' \"Title\""),
        ("A\u2003B\n\nC", "A B C"),
        ("\t\n", ""),
        ("Ａ — Case", "Ａ — Case"),  # No NFKC, punctuation removal or lowercasing.
    ],
)
def test_normalization_policy(raw, expected):
    assert normalize(raw) == expected
    assert normalize(expected) == expected
    assert text_sha256(expected) == hashlib.sha256(expected.encode("utf-8")).hexdigest()


def test_manifest_roundtrip_hash_and_generated_schema():
    corpus = CorpusManifest(documents=(document(),))
    restored = load_corpus(corpus.model_dump_json())
    assert restored == corpus
    assert corpus_sha256(corpus) == corpus_sha256(restored)
    assert CorpusManifest.model_json_schema()["additionalProperties"] is False
    assert DevelopmentLabels.model_json_schema()["additionalProperties"] is False


@pytest.mark.parametrize("mutation", ["text", "hash", "parser", "unicode", "extra", "schema"])
def test_manifest_rejects_drift_and_unknown_fields(mutation):
    obj = json.loads(CorpusManifest(documents=(document(),)).model_dump_json())
    doc = obj["documents"][0]
    if mutation == "text":
        doc["pages"][0]["text"] += " changed"
    elif mutation == "hash":
        doc["pages"][0]["sha256"] = "0" * 64
    elif mutation == "parser":
        doc["parser"]["packages"][0]["version"] = "0.0.0"
    elif mutation == "unicode":
        doc["parser"]["unicode_version"] = "unsupported"
    elif mutation == "extra":
        doc["extra"] = "unsupported"
    else:
        obj["schema_version"] = "canonical-corpus-v99"
    with pytest.raises(ValidationError):
        CorpusManifest.model_validate_json(json.dumps(obj))


def test_blank_physical_page_retained_without_inventing_text():
    doc = document(("", "Second physical page."))
    assert doc.pages[0].sha256 == text_sha256("")
    assert doc.pages[1].page == 2
    with pytest.raises(ValidationError):
        document(("",))


def test_duplicate_versions_pages_and_package_entries_rejected():
    doc = document()
    with pytest.raises(ValidationError):
        CorpusManifest(documents=(doc, doc))
    with pytest.raises(ValidationError):
        CanonicalDocument(**{**doc.model_dump(), "pages": (doc.pages[0], doc.pages[0])})
    with pytest.raises(ValidationError):
        ParserIdentity(
            packages=doc.parser.packages + (doc.parser.packages[0],),
            unicode_version=unicodedata.unidata_version,
        )


def test_label_roundtrip_multispan_and_review_remains_draft():
    doc = document(("Alpha beta gamma.", "Delta epsilon."))
    corpus = CorpusManifest(documents=(doc,))
    payload = label_payload(corpus, [gold(doc), gold(doc, "epsilon", 2)])
    labels = load_development_labels(payload, corpus)
    assert len(labels.questions[0].spans) == 2
    assert labels.questions[0].review_status == "draft"


@pytest.mark.parametrize(
    "mutation",
    ["offset", "excerpt", "page_hash", "version", "page", "corpus", "bool", "heldout", "extra"],
)
def test_gold_loader_rejects_wrong_references(mutation):
    doc = document()
    corpus = CorpusManifest(documents=(doc,))
    obj = json.loads(label_payload(corpus, [gold(doc)]))
    span = obj["questions"][0]["spans"][0]
    if mutation == "offset":
        span["end"] += 1
    elif mutation == "excerpt":
        span["excerpt"] = "Alpha"
    elif mutation == "page_hash":
        span["page_sha256"] = "0" * 64
    elif mutation == "version":
        span["doc_version"] = "0" * 64
    elif mutation == "page":
        span["page"] = 2
    elif mutation == "corpus":
        obj["corpus_sha256"] = "0" * 64
    elif mutation == "bool":
        span["start"] = True
    elif mutation == "heldout":
        obj["split"] = "heldout"
    else:
        span["unexpected"] = 1
    with pytest.raises(ValueError):
        load_development_labels(json.dumps(obj), corpus)


@pytest.mark.parametrize(
    ("start", "end", "excerpt"), [(1, 1, "x"), (2, 1, "x"), (-1, 1, "x"), (0, 1, ""), (0, 1, " x ")]
)
def test_invalid_empty_gold(start, end, excerpt):
    with pytest.raises(ValidationError):
        GoldSpan(
            doc_id="test",
            doc_version="0" * 64,
            page=1,
            page_sha256="0" * 64,
            start=start,
            end=end,
            excerpt=excerpt,
        )


@pytest.mark.parametrize("category", ["near_miss", "off_topic"])
def test_unknown_categories_have_no_gold(category):
    question = GoldQuestion(query_id="unknown", question="Absent fact?", category=category)
    assert question.spans == ()
    with pytest.raises(ValidationError):
        GoldQuestion(
            query_id="unknown",
            question="Absent fact?",
            category=category,
            spans=(gold(document()),),
        )
    with pytest.raises(ValidationError):
        GoldQuestion(query_id="known", question="Present fact?", category="answerable")


def test_duplicate_queries_and_overlapping_gold_rejected():
    doc = document()
    question = GoldQuestion(
        query_id="q1", question="A fact?", category="answerable", spans=(gold(doc),)
    )
    with pytest.raises(ValidationError):
        DevelopmentLabels(corpus_sha256="0" * 64, questions=(question, question))
    with pytest.raises(ValidationError):
        GoldQuestion(
            query_id="q1", question="A fact?", category="answerable", spans=(gold(doc), gold(doc))
        )


@pytest.mark.parametrize(
    ("text", "status"), [("invented title beta", "unlocatable"), ("", "empty"), (" ", "empty")]
)
def test_mapping_failures_are_not_misses(text, status):
    doc = document()
    corpus = CorpusManifest(documents=(doc,))
    location = map_chunk(doc, 1, text)
    assert location.status == status
    assert location.start is None and location.end is None
    with pytest.raises(MappingFailure):
        span_coverage(gold(doc), (location,), corpus)


@pytest.mark.parametrize("page", [None, 0, 2, True])
def test_missing_or_wrong_page_mapping(page):
    location = map_chunk(document(), page, "beta")
    assert location.status == "missing_page"


def test_repeated_and_overlapping_substrings_are_ambiguous():
    doc = document(("banana beta beta",))
    assert map_chunk(doc, 1, "beta").match_count == 2
    assert map_chunk(doc, 1, "ana").status == "ambiguous"
    assert map_chunk(doc, 1, "ana").match_count == 2


def test_title_prefix_and_split_element_boundaries():
    doc = document(("Title\n\nOne café fact.\n\nSecond fact.",))
    for text in ("Title\n\nOne café fact.", "fé fact.", "Second fact."):
        chunk = map_chunk(doc, 1, text)
        assert chunk.status == "mapped"
        assert doc.pages[0].text[chunk.start : chunk.end] == normalize(text)
    assert map_chunk(doc, 1, "Invented Title\n\nOne café fact.").status == "unlocatable"


def test_unicode_offsets_are_codepoints_not_bytes():
    doc = document(("Cafe\u0301 😀 beta",))
    corpus = CorpusManifest(documents=(doc,))
    span = gold(doc, "😀")
    assert span.end - span.start == 1
    assert len(span.excerpt.encode("utf-8")) == 4
    assert span_coverage(span, (map_chunk(doc, 1, "😀"),), corpus) == 1


def test_half_open_page_boundaries_and_no_cross_page_match():
    doc = document(("Alpha beta", "gamma delta"))
    corpus = CorpusManifest(documents=(doc,))
    span = gold(doc)
    assert not chunk_relevant(span, map_chunk(doc, 1, "Alpha "), corpus)
    assert not chunk_relevant(span, map_chunk(doc, 2, "gamma"), corpus)
    assert map_chunk(doc, 1, "beta gamma").status == "unlocatable"
    assert map_chunk(doc, 1, "beta").end == len(doc.pages[0].text)


def test_exact_fifty_percent_and_union_without_double_counting():
    doc = document(("abcdefghij",))
    corpus = CorpusManifest(documents=(doc,))
    span = gold(doc, "abcdefghij")
    assert chunk_relevant(span, map_chunk(doc, 1, "abcde"), corpus)
    assert not chunk_relevant(span, map_chunk(doc, 1, "abcd"), corpus)
    chunks = tuple(map_chunk(doc, 1, text) for text in ("abcdef", "efgh", "ij", "abcdef"))
    assert span_coverage(span, chunks, corpus) == 1
    assert span_coverage(span, (), corpus) == 0


@pytest.mark.parametrize("other", [document(version="synthetic-v2"), document(doc_id="different")])
def test_same_text_other_document_version_is_not_relevant(other):
    doc = document()
    corpus = CorpusManifest(documents=(doc, other))
    assert not chunk_relevant(gold(doc), map_chunk(other, 1, "beta"), corpus)


def test_adjacent_multispans_are_disjoint_and_loadable():
    doc = document(("abcdefghij",))
    corpus = CorpusManifest(documents=(doc,))
    labels = load_development_labels(
        label_payload(corpus, [gold(doc, "abcde"), gold(doc, "fghij")]), corpus
    )
    assert len(labels.questions[0].spans) == 2


def test_constructed_location_cannot_bypass_validation():
    doc = document()
    corpus = CorpusManifest(documents=(doc,))
    location = map_chunk(doc, 1, "beta")
    for bad in (
        replace(location, start=0),
        replace(location, page_sha256="0" * 64),
        replace(location, match_count=2),
        replace(location, match_count=True),
    ):
        with pytest.raises(MappingFailure):
            span_coverage(gold(doc), (bad,), corpus)


def test_holdout_commitment_accepts_only_hash_and_count():
    commitment = HoldoutCommitment(plaintext_sha256="0" * 64, question_count=50)
    assert commitment.question_count == 50
    for extra in ({"path": "not-allowed"}, {"questions": []}, {"key": "not-allowed"}):
        with pytest.raises(ValidationError):
            HoldoutCommitment(plaintext_sha256="0" * 64, question_count=50, **extra)


@pytest.mark.parametrize(
    "payload",
    [
        "[]",
        "{}",
        '{"schema_version":"canonical-corpus-v1","schema_version":"canonical-corpus-v1"}',
    ],
)
def test_versioned_loader_rejects_untagged_or_duplicate_keys(payload):
    with pytest.raises(ValueError):
        load_corpus(payload)


def test_gold_loader_requires_explicit_schema_version():
    doc = document()
    corpus = CorpusManifest(documents=(doc,))
    obj = json.loads(label_payload(corpus, [gold(doc)]))
    del obj["schema_version"]
    with pytest.raises(ValueError, match="schema version"):
        load_development_labels(json.dumps(obj), corpus)


@pytest.mark.parametrize("name", ["AUTO_DOWNLOAD_NLTK", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"])
def test_extractor_requires_explicit_offline_environment(monkeypatch, name):
    monkeypatch.delenv(name)
    with pytest.raises(ValueError, match="offline parser environment"):
        extract_pdf(b"synthetic", doc_id="synthetic", source=document().source)
