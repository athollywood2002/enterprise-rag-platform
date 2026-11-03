"""Authored synthetic ID-grammar fixtures, never private questions/source excerpts."""

import inspect
import unicodedata
from dataclasses import dataclass
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from evaluation.canonical import PARSER_PINS, extract_pdf, normalize, text_sha256
from evaluation.corpus import (
    CanonicalDocument,
    CanonicalPage,
    Package,
    ParserIdentity,
    SourceRecord,
)
from evaluation.spans import map_chunks
from rag.documents import parse_document
from rag.requirement_chunking import (
    NIST_REQUIREMENT_POLICY,
    NIST_REQUIREMENT_STRATEGY,
    RequirementState,
    requirement_page_fragments,
)


@dataclass
class Element:
    text: str
    category: str = "NarrativeText"
    page: int | None = 1

    def __str__(self):
        return self.text

    @property
    def metadata(self):
        return SimpleNamespace(page_number=self.page)


def title(text, page=1):
    return Element(text, "Title", page)


def fragments(elements):
    return requirement_page_fragments(elements, RequirementState(in_requirements=True))


def source():
    return SourceRecord(
        title="Authored requirement-boundary fixture",
        canonical_url="urn:synthetic:requirements",
        revision="1",
        license_id="MIT",
        attribution="Repository test authors",
        redistribution="redistributable",
    )


def test_d07_style_false_title_does_not_split_sentence():
    result = fragments(
        [
            title("03.03.03 Synthetic Audit Generation"),
            Element("Keep the synthetic records retention"),
            title("policy."),
            title("DISCUSSION"),
            Element("A synthetic explanation."),
            title("REFERENCES"),
            title("Source Controls: AU-11, AU-12"),
            title("03.03.04 Synthetic Failure Response"),
            Element("Notify the synthetic operator."),
        ]
    )
    assert len(result) == 2
    assert "records retention policy." in normalize(result[0].text)
    assert "Source Controls: AU-11, AU-12" in result[0].text
    assert result[0].requirement_id == "03.03.03"
    assert "03.03.04" not in result[0].text


def test_d11_style_reference_tail_stays_with_previous_requirement():
    result = fragments(
        [
            title("03.06.01 Synthetic Handling"),
            Element("Prepare the synthetic incident exercise."),
            title("REFERENCES"),
            title("Source Controls (synthetic): IR-04"),
            Element("Supporting Publications: Synthetic Guide"),
            title("03.06.02 Synthetic Monitoring"),
            Element("Track the synthetic incident exercise."),
        ]
    )
    assert [r.requirement_id for r in result] == ["03.06.01", "03.06.02"]
    assert "Source Controls (synthetic): IR-04" in result[0].text
    assert "IR-04" not in result[1].text
    assert "Track" not in result[0].text


def test_table_inline_and_standalone_ids_do_not_create_boundaries():
    result = fragments(
        [
            title("03.06.01 Synthetic Heading"),
            Element("03.06.02 Not a heading", "Table"),
            Element("", "Table"),
            Element("An inline reference to 03.06.03 Synthetic Text."),
            title("03.06.04"),
            Element(""),
            Element(" \n "),
            Element("Terminal sentence."),
        ]
    )
    assert len(result) == 1 and result[0].requirement_id == "03.06.01"
    assert "03.06.02 Not a heading" in result[0].text
    assert "Terminal sentence." in result[0].text
    assert fragments([Element("  ")]) == []


def test_size_never_introduces_sentence_or_requirement_split():
    text = "An indivisible synthetic sentence with no sentence terminator " * 80 + "."
    result = fragments([title("03.01.01 Synthetic Heading"), Element(text)])
    assert len(result) == 1 and len(result[0].text) > 1200
    assert text in result[0].text  # No truncation, overlap, prefix or fabricated text.


def test_layout_separate_and_only_attribution_crosses_pages(monkeypatch):
    elements = [
        Element("Synthetic header", "Header", 1),
        title("3.6. Synthetic Family", 1),
        title("03.06.01 Synthetic Handling", 1),
        Element("First physical page body.", page=1),
        Element("1", "Footer", 1),
        Element("Synthetic header", "Header", 2),
        title("REFERENCES", 2),
        title("Source Controls (synthetic): IR-04", 2),
        title("03.06.02 Synthetic Monitoring", 2),
        Element("Second requirement body.", page=2),
    ]
    monkeypatch.setattr("rag.documents._partition_document", lambda *a: elements)
    chunks = parse_document(
        b"synthetic stub", "fixture.pdf", chunking_strategy=NIST_REQUIREMENT_STRATEGY
    )
    reference = next(c for c in chunks if "IR-04" in c.text)
    assert reference.page_number == 2 and reference.requirement_id == "03.06.01"
    assert "First physical page" not in reference.text
    assert all(c.requirement_id is None for c in chunks if "Synthetic header" in c.text)
    assert [c.number for c in chunks] == list(range(len(chunks)))
    assert {c.page_number for c in chunks} == {1, 2}


@pytest.mark.parametrize(
    "section", ["3.7. Synthetic Family", "References", "Appendix A. Synthetic"]
)
def test_section_boundaries_reset_attribution(section):
    state = RequirementState(in_requirements=True)
    result = requirement_page_fragments(
        [
            title("03.06.01 Synthetic Handling"),
            Element("A rule."),
            title(section),
            Element("Other text."),
        ],
        state,
    )
    assert result[-1].requirement_id is None
    assert "Other text." not in result[0].text


def test_appendix_lookalike_ids_are_not_requirements():
    state = RequirementState(in_requirements=True)
    result = requirement_page_fragments(
        [
            title("03.06.01 Synthetic Handling"),
            Element("Rule."),
            title("References"),
            title("Appendix A. Synthetic"),
            title("3.6. Synthetic appendix family lookalike"),
            title("03.06.01 A table lookalike"),
        ],
        state,
    )
    assert state.seen == {"03.06.01"}
    assert result[-1].requirement_id is None


def test_duplicate_heading_fails_closed():
    with pytest.raises(ValueError, match="Duplicate"):
        fragments([title("03.06.01 First"), title("03.06.01 Duplicate")])


def test_intro_example_heading_is_not_the_real_requirement():
    state = RequirementState()
    result = requirement_page_fragments(
        [
            title("03.13.11 Synthetic introductory example"),
            Element("This example is not a requirement body."),
            title("3.13. Synthetic Family"),
            title("03.13.11 Synthetic real requirement"),
            Element("The actual synthetic body."),
        ],
        state,
    )
    assert state.seen == {"03.13.11"}
    assert result[0].requirement_id is None
    assert result[-1].requirement_id == "03.13.11"
    assert "introductory" not in result[-1].text


@pytest.mark.parametrize("pages", [(None,), (2, 1), (1, 2, 1)])
def test_unknown_or_backtracking_pages_rejected(monkeypatch, pages):
    elements = [
        title("3.6. Synthetic Family", pages[0]),
        title("03.06.01 Synthetic Heading", pages[0]),
    ]
    elements += [Element("Continuation.", page=p) for p in pages[1:]]
    monkeypatch.setattr("rag.documents._partition_document", lambda *a: elements)
    with pytest.raises(ValueError, match="physical pages"):
        parse_document(
            b"synthetic stub", "fixture.pdf", chunking_strategy=NIST_REQUIREMENT_STRATEGY
        )


def test_non_nist_opt_in_fails_but_default_signature_unchanged(monkeypatch):
    assert inspect.signature(parse_document).parameters["chunking_strategy"].default == "title"
    monkeypatch.setattr("rag.documents._partition_document", lambda *a: [Element("Generic prose.")])
    with pytest.raises(ValueError, match="No supported requirement"):
        parse_document(
            b"synthetic stub", "fixture.pdf", chunking_strategy=NIST_REQUIREMENT_STRATEGY
        )


@pytest.mark.parametrize(
    "strategy,filename", [("unknown", "fixture.pdf"), (NIST_REQUIREMENT_STRATEGY, "fixture.txt")]
)
def test_invalid_opt_in_fails_before_temp_or_partition(monkeypatch, strategy, filename):
    temporary = Mock(side_effect=AssertionError("No temporary file allowed"))
    partition = Mock(side_effect=AssertionError("No partition allowed"))
    monkeypatch.setattr("rag.documents.TemporaryDirectory", temporary)
    monkeypatch.setattr("rag.documents._partition_document", partition)
    with pytest.raises(ValueError, match="strategy"):
        parse_document(b"synthetic", filename, chunking_strategy=strategy)
    if strategy == "unknown":
        with pytest.raises(ValueError, match="strategy"):
            extract_pdf(
                b"synthetic", doc_id="synthetic-req", source=source(), chunking_strategy=strategy
            )
    temporary.assert_not_called()
    partition.assert_not_called()


def test_page_local_canonical_offsets_and_full_coverage(monkeypatch):
    elements = [
        title("3.6. Synthetic Family"),
        title("03.06.01 Synthetic Handling"),
        Element("A repeated phrase."),
        title("REFERENCES"),
        title("Source Controls (synthetic): IR-04"),
        title("03.06.02 Synthetic Monitoring"),
        Element("A repeated phrase."),
    ]
    text = normalize("\n\n".join(map(str, elements)))
    document = CanonicalDocument(
        doc_id="synthetic-req",
        doc_version=text_sha256("synthetic-v1"),
        source=source(),
        parser=ParserIdentity(
            packages=tuple(Package(name=n, version=v) for n, v in PARSER_PINS),
            unicode_version=unicodedata.unidata_version,
        ),
        pages=(CanonicalPage(page=1, text=text, sha256=text_sha256(text)),),
    )
    monkeypatch.setattr("rag.documents._partition_document", lambda *a: elements)
    serving = parse_document(
        b"synthetic stub", "fixture.pdf", chunking_strategy=NIST_REQUIREMENT_STRATEGY
    )
    locations = map_chunks(document, 1, tuple(c.text for c in serving))
    assert all(c.status == "mapped" and c.page == 1 for c in locations)
    assert normalize(" ".join(c.text for c in locations)) == text
    for c in locations:
        assert text[c.start : c.end] == c.text and c.page_sha256 == document.pages[0].sha256
    assert locations[0].end < locations[1].start


@pytest.mark.documents
def test_real_synthetic_pdf_variant_serving_and_canonical_parity():
    from reportlab.pdfgen.canvas import Canvas

    buffer = BytesIO()
    pdf = Canvas(buffer, invariant=1)
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(72, 775, "3.6. Synthetic Family")
    pdf.drawString(72, 740, "03.06.01 Synthetic Incident Handling")
    pdf.setFont("Helvetica", 12)
    pdf.drawString(72, 710, "Prepare the synthetic incident exercise.")
    pdf.drawString(72, 680, "REFERENCES")
    pdf.drawString(72, 650, "Source Controls (synthetic): IR-04")
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(72, 600, "03.06.02 Synthetic Monitoring")
    pdf.setFont("Helvetica", 12)
    pdf.drawString(72, 570, "Track the synthetic incident exercise.")
    pdf.showPage()
    pdf.setFont("Helvetica", 12)
    pdf.drawString(72, 740, "A continuation on the second physical page.")
    pdf.drawString(72, 710, "REFERENCES")
    pdf.drawString(72, 680, "Source Controls: IR-05")
    pdf.save()
    data = buffer.getvalue()
    default = extract_pdf(data, doc_id="synthetic-req", source=source())
    variant = extract_pdf(
        data, doc_id="synthetic-req", source=source(), chunking_strategy=NIST_REQUIREMENT_STRATEGY
    )
    serving = parse_document(data, "fixture.pdf", chunking_strategy=NIST_REQUIREMENT_STRATEGY)
    assert variant.document == default.document
    assert variant.chunking_policy == NIST_REQUIREMENT_POLICY
    assert all(c.status == "mapped" for c in variant.chunks)
    assert [(c.page, c.text) for c in variant.chunks] == [
        (c.page_number, normalize(c.text)) for c in serving
    ]
    assert all(c.requirement_id == "03.06.01" for c in serving if "IR-04" in c.text)
    assert all(c.requirement_id == "03.06.02" for c in serving if "IR-05" in c.text)
