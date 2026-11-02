"""Authored synthetic PDF inspection; no external documents or acquisition."""

import json
from dataclasses import replace
from io import BytesIO

import pytest

from evaluation import pdf_audit
from evaluation.corpus import SourceRecord


@pytest.mark.parametrize(
    "text,expected",
    [
        ("ordinary text", {}),
        ("a\u200eb\u2060c\u200e", {"U+200E": 2, "U+2060": 1}),
        (
            "\u00ad\u200b\u200c\u200d\ufeff",
            {"U+00AD": 1, "U+200B": 1, "U+200C": 1, "U+200D": 1, "U+FEFF": 1},
        ),
    ],
)
def test_format_counts_preserves_input_and_counts_cf_only(text, expected):
    original = text
    assert pdf_audit.format_counts(text) == expected
    assert text == original


@pytest.fixture
def pdf_input():
    from reportlab.pdfgen import canvas

    stream = BytesIO()
    drawing = canvas.Canvas(stream)
    drawing.drawString(50, 740, "Authored synthetic unique private-body marker --flag=1.")
    drawing.showPage()
    drawing.showPage()
    drawing.save()
    return stream.getvalue(), SourceRecord(
        title="Synthetic PDF audit",
        canonical_url="urn:synthetic:pdf-audit",
        revision="1",
        license_id="MIT",
        attribution="Repository test authors",
        redistribution="local_only",
    )


@pytest.mark.documents
def test_real_pdf_audit_records_all_pages_and_metadata_only(pdf_input):
    data, source = pdf_input
    result = pdf_audit.audit_pdf(data, doc_id="synthetic", source=source)
    assert result["physical_pages"] == 2
    assert [p["blank"] for p in result["pages"]] == [False, True]
    assert all(p["partition_repeat_matches_canonical"] for p in result["pages"])
    assert all(p["nonspace_characters_outside_mapped_chunks"] == 0 for p in result["pages"])
    assert result["all_candidate_chunks_mapped"]
    assert result["serving_normalized_text_and_page_parity"]
    assert result["inspection_only"] and not result["corpus_admitted"]
    assert result["mapping_failures"] == []
    assert "private-body marker" not in json.dumps(result)
    assert result == pdf_audit.audit_pdf(data, doc_id="synthetic", source=source)


@pytest.mark.documents
def test_audit_does_not_hide_mapping_failures(pdf_input, monkeypatch):
    data, source = pdf_input
    real = pdf_audit.extract_pdf(data, doc_id="synthetic", source=source)
    failed = replace(
        real, chunks=(replace(real.chunks[0], status="unlocatable", start=None, end=None),)
    )
    monkeypatch.setattr(pdf_audit, "extract_pdf", lambda *args, **kwargs: failed)
    result = pdf_audit.audit_pdf(data, doc_id="synthetic", source=source)
    assert not result["all_candidate_chunks_mapped"]
    assert result["mapping_failures"][0]["status"] == "unlocatable"
    assert result["pages"][0]["nonspace_characters_outside_mapped_chunks"] > 0
    assert "private-body marker" not in json.dumps(result)


@pytest.mark.documents
def test_repeat_partition_format_drift_is_reported_not_normalized_away(pdf_input, monkeypatch):
    from rag import documents

    data, source = pdf_input
    original = documents._partition_document
    calls = 0

    def partition(*args):
        nonlocal calls
        calls += 1
        elements = original(*args)
        if calls == 2:
            elements[0].text += "\u200e"
        return elements

    monkeypatch.setattr(documents, "_partition_document", partition)
    result = pdf_audit.audit_pdf(data, doc_id="synthetic", source=source)
    assert result["pages"][0]["raw_partition_cf"] == {"U+200E": 1}
    assert result["pages"][0]["canonical_cf"] == {}
    assert not result["pages"][0]["partition_repeat_matches_canonical"]
