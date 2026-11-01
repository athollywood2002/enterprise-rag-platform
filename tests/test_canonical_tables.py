"""Synthetic tables through the actual pinned Markdown parser/title chunker."""

from dataclasses import asdict
from io import BytesIO
from itertools import pairwise
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from evaluation.canonical import extract_markdown, extract_pdf, normalize
from evaluation.corpus import CorpusManifest, GoldSpan, SourceRecord
from evaluation.spans import span_coverage
from rag.chunking import TITLE_CHUNKING

pytestmark = pytest.mark.documents


def table_markdown() -> bytes:
    # Oversized rows followed by empty separator rows make the pinned real
    # chunker flush empty TableChunks with nonempty text_as_html metadata.
    text = "# Synthetic options\n\n| Flag | Description |\n| --- | --- |\n"
    for i in range(4):
        description = " ".join(f"row-{i:02d}-word-{j:03d}" for j in range(100))
        text += f"| --synthetic-{i:03d} | {description} |\n| | |\n"
    return (text + "\nFinal synthetic paragraph.\n").encode()


@pytest.fixture
def source():
    return SourceRecord(
        title="Authored synthetic table",
        canonical_url="urn:synthetic:table",
        revision="1",
        license_id="MIT",
        attribution="Repository test authors",
        redistribution="redistributable",
    )


def assert_serving_locations(result, serving):
    assert len(result.chunks) == len(serving)
    assert [c.text for c in result.chunks] == [normalize(c.text) for c in serving]
    assert all(c.status == "mapped" for c in result.chunks)
    cursors = {}
    for location, served in zip(result.chunks, serving, strict=True):
        page_number = served.page_number or 1
        page = result.document.pages[page_number - 1]
        expected = normalize(served.text)
        previous = cursors.get(page_number, 0)
        start = page.text.find(expected, previous)
        assert page.text[previous:start] in ("", " ")
        assert (location.page, location.start, location.end) == (
            page_number,
            start,
            start + len(expected),
        )
        assert location.page_sha256 == page.sha256
        cursors[page_number] = location.end
    assert all(cursors[number] == len(result.document.pages[number - 1].text) for number in cursors)
    for left, right in pairwise(result.chunks):
        if left.page == right.page:
            assert left.end <= right.start
    # Exercise scoring's post-deserialization bounds/prefix validation for all
    # retained chunks, including those after the last skipped empty TableChunk.
    last = result.chunks[-1]
    span = GoldSpan(
        doc_id=last.doc_id,
        doc_version=last.doc_version,
        page=last.page,
        page_kind=last.page_kind,
        page_sha256=last.page_sha256,
        start=last.start,
        end=last.end,
        excerpt=last.text,
    )
    assert span_coverage(span, result.chunks, CorpusManifest(documents=(result.document,))) == 1


def test_real_markdown_table_empty_chunks_are_counted_and_serving_parity_holds(monkeypatch, source):
    from unstructured.chunking import title
    from unstructured.documents.elements import TableChunk

    from rag.documents import parse_document

    emitted = []
    real_chunker = title.chunk_by_title

    def observe(elements, **kwargs):
        chunks = real_chunker(elements, **kwargs)
        emitted.append(chunks)
        return chunks

    monkeypatch.setattr(title, "chunk_by_title", observe)
    data = table_markdown()
    result = extract_markdown(data, doc_id="synthetic-table", source=source)
    assert len(emitted) == 1
    empty = [c for c in emitted[0] if not normalize(str(c))]
    assert len(empty) == 4
    assert all(isinstance(c, TableChunk) and c.metadata.text_as_html for c in empty)
    assert result.empty_skipped == 4
    assert result.mapping_counts == {"mapped": len(result.chunks), "empty_skipped": 4}
    # #58 evidence, not a row-aware fix: an oversized table row splits its flag
    # from its description under the unchanged serving policy.
    assert any(c.text == "--synthetic-000" for c in result.chunks)
    assert not any(
        "--synthetic-000" in c.text and "row-00-word-000" in c.text for c in result.chunks
    )
    assert_serving_locations(result, parse_document(data, "fixture.md"))
    assert result == extract_markdown(data, doc_id="synthetic-table", source=source)


def test_pdf_adapter_counts_real_table_chunker_empties_across_physical_pages(
    monkeypatch, pdf_factory, source
):
    from unstructured.chunking.title import chunk_by_title

    from rag import documents

    # Actual Markdown partition/Table output and actual title chunker; PDF
    # partition is controlled here because fast PDF parsing is text-only and
    # does not promise table structure. Physical PDF page count is real.
    with TemporaryDirectory(prefix="synthetic-table-") as directory:
        path = Path(directory) / "fixture.md"
        path.write_bytes(table_markdown())
        elements = documents._partition_document(path, ".md")
    for element in elements:
        element.metadata.page_number = 1
    elements[-1].metadata.page_number = 2
    raw_chunks = chunk_by_title(elements[:-1], **asdict(TITLE_CHUNKING))
    assert sum(not normalize(str(c)) for c in raw_chunks) == 4
    monkeypatch.setattr(documents, "_partition_document", lambda *args: elements)
    data = pdf_factory(("Synthetic table page.", "Final synthetic paragraph."))
    result = extract_pdf(data, doc_id="synthetic-pdf-table", source=source)
    assert result.empty_skipped == 4
    assert all(c.page_kind == "physical" for c in result.chunks)
    assert result.chunks[-1].page == 2 and result.chunks[-1].start == 0
    assert_serving_locations(result, documents.parse_document(data, "fixture.pdf"))


def test_real_fast_pdf_table_keeps_text_and_serving_locations(source):
    from reportlab.pdfgen.canvas import Canvas

    from rag.documents import parse_document

    stream = BytesIO()
    canvas = Canvas(stream, invariant=1, pageCompression=0)
    for i, (flag, meaning) in enumerate(
        (
            ("Flag", "Meaning"),
            ("--synthetic-one", "First authored option"),
            ("--synthetic-two", "Second authored option"),
        )
    ):
        y = 740 - i * 28
        canvas.drawString(72, y, flag)
        canvas.drawString(250, y, meaning)
        canvas.line(68, y - 8, 500, y - 8)
    canvas.save()
    data = stream.getvalue()
    result = extract_pdf(data, doc_id="real-fast-pdf-table", source=source)
    assert "--synthetic-two" in result.document.pages[0].text
    assert_serving_locations(result, parse_document(data, "grid.pdf"))
