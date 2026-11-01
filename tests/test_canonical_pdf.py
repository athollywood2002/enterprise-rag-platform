"""Tiny generated PDFs; actual parser/chunker only under explicit opt-in."""

from io import BytesIO
from unittest.mock import Mock

import pytest

from evaluation.canonical import PARSER_PINS, extract_pdf, normalize, text_sha256
from evaluation.corpus import CorpusManifest, SourceRecord

pytestmark = pytest.mark.documents


@pytest.fixture
def source():
    return SourceRecord(
        title="Synthetic G1 PDF",
        canonical_url="urn:synthetic:g1-pdf",
        revision="1",
        license_id="MIT",
        attribution="Repository test authors",
        redistribution="redistributable",
    )


def test_real_canonical_pdf_and_chunks_share_single_partition(monkeypatch, pdf_factory, source):
    from pypdf import PdfReader

    from rag import documents

    facts = (
        "The synthetic deployment window lasts exactly 23 minutes.",
        "The synthetic reserve stores exactly 41 silver lanterns.",
    )
    data = pdf_factory(facts)
    oracle = PdfReader(BytesIO(data)).pages
    partition = Mock(wraps=documents._partition_document)
    monkeypatch.setattr(documents, "_partition_document", partition)
    first = extract_pdf(data, doc_id="synthetic-pdf", source=source)
    partition.assert_called_once()
    assert len(first.document.pages) == len(first.chunks) == 2
    assert first.mapping_counts == {"mapped": 2}
    for page, fact in enumerate(facts, 1):
        canonical = first.document.pages[page - 1]
        assert fact in canonical.text
        assert fact in normalize(oracle[page - 1].extract_text())
        assert canonical.sha256 == text_sha256(canonical.text)
        chunk = first.chunks[page - 1]
        assert chunk.status == "mapped" and chunk.page == page
        assert canonical.text[chunk.start : chunk.end] == chunk.text
    second = extract_pdf(data, doc_id="synthetic-pdf", source=source)
    assert first == second  # Same-runtime canonical hashes, spans and chunk ordering.
    serving = documents.parse_document(data, "fixture.pdf")
    assert [normalize(c.text) for c in serving] == [c.text for c in first.chunks]
    assert "max=1200:new=1000:combine=200:multipage=false" in first.chunking_policy
    assert CorpusManifest.model_validate_json(
        CorpusManifest(documents=(first.document,)).model_dump_json()
    ).documents == (first.document,)
    assert len(oracle) == 2


def test_unknown_page_metadata_is_rejected(monkeypatch, pdf_factory, source):
    from unstructured.documents.elements import Text

    monkeypatch.setattr("rag.documents._partition_document", lambda *args: [Text("A fact.")])
    with pytest.raises(ValueError, match="Unknown/out-of-range"):
        extract_pdf(pdf_factory(("A fact.",)), doc_id="synthetic-pdf", source=source)


def test_parser_version_drift_stops_before_partition(monkeypatch, source):
    monkeypatch.setattr("evaluation.canonical.version", lambda name: "0.0.0")
    partition = Mock(side_effect=AssertionError("Must not parse"))
    monkeypatch.setattr("rag.documents._partition_document", partition)
    with pytest.raises(ValueError, match="Parser profile drift"):
        extract_pdf(b"not a PDF", doc_id="synthetic-pdf", source=source)
    partition.assert_not_called()


def test_long_element_split_and_page_boundary_use_real_chunker(monkeypatch, pdf_factory, source):
    from unstructured.documents.elements import ElementMetadata, Text, Title

    text = " ".join(f"synthetic-word-{n:04d}" for n in range(180))
    elements = [
        Title("Synthetic title", metadata=ElementMetadata(page_number=1)),
        Text(text, metadata=ElementMetadata(page_number=1)),
        Text("Final physical page.", metadata=ElementMetadata(page_number=2)),
    ]
    monkeypatch.setattr("rag.documents._partition_document", lambda *args: elements)
    result = extract_pdf(
        pdf_factory(("Physical page one.", "Physical page two.")),
        doc_id="synthetic-pdf",
        source=source,
    )
    assert len(result.chunks) > 2
    assert all(chunk.status == "mapped" for chunk in result.chunks)
    assert result.document.pages[0].text == normalize("Synthetic title\n\n" + text)
    assert result.chunks[-1].page == 2
    assert result.chunks[-1].text == "Final physical page."


def test_recorded_parser_pins_match_extractor(source, pdf_factory):
    result = extract_pdf(pdf_factory(("Synthetic fact.",)), doc_id="synthetic-pdf", source=source)
    assert tuple((p.name, p.version) for p in result.document.parser.packages) == PARSER_PINS


def test_real_chunker_repeating_control_boilerplate(monkeypatch, pdf_factory, source):
    from unstructured.documents.elements import ElementMetadata, Text, Title

    elements = []
    for control in ("AC-1", "AC-2"):
        elements.extend(
            [
                Title(control, metadata=ElementMetadata(page_number=1)),
                Text("Discussion: " + "synthetic " * 130, metadata=ElementMetadata(page_number=1)),
                Text("Related Controls: None.", metadata=ElementMetadata(page_number=1)),
            ]
        )
    monkeypatch.setattr("rag.documents._partition_document", lambda *args: elements)
    result = extract_pdf(
        pdf_factory(("Synthetic control page.",)), doc_id="controls", source=source
    )
    assert len(result.chunks) >= 4
    assert all(c.status == "mapped" for c in result.chunks)
    assert any(c.match_count > 1 for c in result.chunks)
    assert all(a.end <= b.start for a, b in zip(result.chunks, result.chunks[1:]))


def test_out_of_order_parser_pages_are_rejected(monkeypatch, pdf_factory, source):
    from unstructured.documents.elements import ElementMetadata, Text

    elements = [Text("Synthetic page.", metadata=ElementMetadata(page_number=p)) for p in (1, 2, 1)]
    monkeypatch.setattr("rag.documents._partition_document", lambda *args: elements)
    with pytest.raises(ValueError, match="pages out of order"):
        extract_pdf(pdf_factory(("Page one.", "Page two.")), doc_id="bad-order", source=source)
