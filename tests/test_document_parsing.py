"""Real local parsing and chunking; synthetic fixtures, no model/database services."""

from io import BytesIO

import pytest

from rag.documents import parse_document

pytestmark = pytest.mark.documents

PAGE_FACTS = (
    "The cobalt observatory stores exactly seventeen brass telescopes.",
    "The amber greenhouse grows exactly forty-three violet orchids.",
)


@pytest.fixture
def two_page_pdf() -> bytes:
    from reportlab.pdfgen.canvas import Canvas

    data = BytesIO()
    pdf = Canvas(data, invariant=1, pageCompression=0)
    pdf.setAuthor("Synthetic test fixture")
    pdf.setTitle("Parser provenance fixture")
    for page, fact in enumerate(PAGE_FACTS, 1):
        pdf.setFont("Helvetica-Bold", 18)
        pdf.drawString(72, 740, f"Synthetic Section {page}")
        pdf.setFont("Helvetica", 12)
        pdf.drawString(72, 700, fact)
        pdf.showPage()
    pdf.save()
    return data.getvalue()


@pytest.fixture
def elements():
    from unstructured.documents.elements import ElementMetadata, NarrativeText, Title

    def make(kind, text, page):
        cls = Title if kind == "title" else NarrativeText
        return cls(text=text, metadata=ElementMetadata(page_number=page))

    return make


def supply_elements(monkeypatch, values):
    def partition(path, suffix):
        assert path.is_file()
        return values

    monkeypatch.setattr("rag.documents._partition_document", partition)


def test_real_two_page_pdf_has_true_page_attribution(two_page_pdf):
    from pypdf import PdfReader

    # Independent extraction confirms what the generated fixture actually contains.
    pages = PdfReader(BytesIO(two_page_pdf)).pages
    assert len(pages) == 2
    for index, fact in enumerate(PAGE_FACTS):
        assert fact in pages[index].extract_text()
        assert PAGE_FACTS[1 - index] not in pages[index].extract_text()

    chunks = parse_document(two_page_pdf, "two-page-fixture.pdf")
    assert {chunk.page_number for chunk in chunks} == {1, 2}
    for page, fact in enumerate(PAGE_FACTS, 1):
        hits = [chunk for chunk in chunks if fact in chunk.text]
        assert hits and all(chunk.page_number == page for chunk in hits)
        assert all(PAGE_FACTS[2 - page] not in chunk.text for chunk in hits)
    assert [chunk.number for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.source == "two-page-fixture.pdf" for chunk in chunks)


def test_section_continuing_across_pages_is_split(monkeypatch, elements):
    supply_elements(
        monkeypatch,
        [
            elements("title", "Shared section", 1),
            elements("text", PAGE_FACTS[0], 1),
            elements("text", PAGE_FACTS[1], 2),
        ],
    )
    chunks = parse_document(b"synthetic stub", "fixture.pdf")
    assert len(chunks) == 2
    assert PAGE_FACTS[0] in chunks[0].text and chunks[0].page_number == 1
    assert PAGE_FACTS[1] in chunks[1].text and chunks[1].page_number == 2
    assert not any(all(fact in chunk.text for fact in PAGE_FACTS) for chunk in chunks)


def test_titles_create_semantic_boundaries_within_page(monkeypatch, elements):
    first = "The synthetic observatory records a calibration measurement. " * 5
    second = "The synthetic greenhouse records a humidity measurement. " * 5
    supply_elements(
        monkeypatch,
        [
            elements("title", "Observatory", 1),
            elements("text", first, 1),
            elements("title", "Greenhouse", 1),
            elements("text", second, 1),
        ],
    )
    chunks = parse_document(b"synthetic stub", "fixture.pdf")
    assert len(chunks) == 2
    assert chunks[0].text.startswith("Observatory\n\n")
    assert chunks[1].text.startswith("Greenhouse\n\n")
    assert "Greenhouse" not in chunks[0].text
    assert "Observatory" not in chunks[1].text
    assert all(chunk.page_number == 1 for chunk in chunks)


def test_long_page_is_split_without_losing_page(monkeypatch, elements):
    supply_elements(monkeypatch, [elements("text", "Synthetic facts. " * 200, 2)])
    chunks = parse_document(b"synthetic stub", "fixture.pdf")
    assert len(chunks) >= 3
    assert all(0 < len(chunk.text) <= 1200 and chunk.page_number == 2 for chunk in chunks)
    assert [chunk.number for chunk in chunks] == list(range(len(chunks)))


@pytest.mark.parametrize("page", [None, 0, -1, True])
def test_unknown_or_invalid_page_is_not_borrowed_from_neighbor(monkeypatch, elements, page):
    supply_elements(
        monkeypatch,
        [
            elements("text", "Known synthetic fact.", 1),
            elements("text", "Unknown synthetic fact.", page),
        ],
    )
    chunks = parse_document(b"synthetic stub", "fixture.pdf")
    assert len(chunks) == 2
    assert chunks[0].page_number == 1
    assert chunks[1].page_number is None


@pytest.mark.parametrize("filename", ["../../fixture.PDF", r"C:\synthetic\fixture.PDF"])
def test_filename_is_basename_only(monkeypatch, elements, filename):
    supply_elements(monkeypatch, [elements("text", "Synthetic fact.", 1)])
    chunks = parse_document(b"synthetic stub", filename)
    assert chunks[0].source == "fixture.PDF"


@pytest.mark.parametrize("values", [[], [" \n\t"]])
def test_no_extracted_text_is_rejected(monkeypatch, values):
    supply_elements(monkeypatch, values)
    with pytest.raises(ValueError, match="no extractable text"):
        parse_document(b"synthetic stub", "fixture.pdf")


@pytest.mark.parametrize("data", [b"not a PDF", b"%PDF-1.4\ntruncated"])
def test_real_malformed_pdf_is_rejected(data):
    with pytest.raises(ValueError, match="Invalid PDF|no extractable text"):
        parse_document(data, "invalid.pdf")


def test_real_blank_pdf_is_rejected():
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    data = BytesIO()
    writer.write(data)
    with pytest.raises(ValueError, match="no extractable text"):
        parse_document(data.getvalue(), "blank.pdf")


@pytest.mark.parametrize("fail", [False, True])
def test_temporary_input_is_cleaned_up_after_partition(monkeypatch, elements, fail):
    paths = []

    def partition(path, suffix):
        paths.append(path)
        assert path.read_bytes() == b"synthetic temporary content"
        if fail:
            raise ValueError("Synthetic parser failure")
        return [elements("text", "Synthetic fact.", 1)]

    monkeypatch.setattr("rag.documents._partition_document", partition)
    if fail:
        with pytest.raises(ValueError, match="Synthetic parser failure"):
            parse_document(b"synthetic temporary content", "fixture.pdf")
    else:
        assert parse_document(b"synthetic temporary content", "fixture.pdf")
    assert paths and all(not path.exists() and not path.parent.exists() for path in paths)


def test_pdf_backend_is_explicitly_fast_and_local(monkeypatch, two_page_pdf):
    import unstructured.partition.pdf as pdf_backend

    def forbidden(*args, **kwargs):
        raise AssertionError("PDF fast parsing attempted OCR or a layout model")

    monkeypatch.setattr(pdf_backend, "_partition_pdf_or_image_local", forbidden)
    monkeypatch.setattr(pdf_backend, "_partition_pdf_or_image_with_ocr", forbidden)
    assert parse_document(two_page_pdf, "fixture.pdf")


def test_real_text_without_pages_does_not_invent_page_numbers():
    chunks = parse_document(PAGE_FACTS[0].encode(), "fixture.txt")
    assert chunks and PAGE_FACTS[0] in " ".join(chunk.text for chunk in chunks)
    assert all(chunk.page_number is None for chunk in chunks)


def test_real_whitespace_document_is_rejected():
    with pytest.raises(ValueError, match="no extractable text"):
        parse_document(b" \n\t", "fixture.txt")


def test_real_encrypted_pdf_is_rejected():
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt("synthetic-fixture-only")
    data = BytesIO()
    writer.write(data)
    with pytest.raises(ValueError, match="encrypted"):
        parse_document(data.getvalue(), "encrypted-fixture.pdf")
