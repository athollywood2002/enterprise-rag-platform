"""Genuine in-memory Office fixtures, bounded child and transactional library tests."""

import io
import zipfile

import pytest
from docx import Document
from test_library import finish, upload
from test_library import library as library_fixture

from rag.folder_parser import DocumentError, chunks_from_pages
from rag.structured_parser import parse_structured

library = library_fixture


def docx_bytes(value="Café policy", *, header=False):
    doc = Document()
    doc.add_heading("Policy — effective 2026-11-01", level=1)
    doc.add_paragraph(value)
    table = doc.add_table(rows=2, cols=2)
    for row, values in zip(table.rows, [("Name", "Amount USD"), ("Zoë", "1250")], strict=True):
        for cell, text in zip(row.cells, values, strict=True):
            cell.text = text
    doc.add_paragraph("End of policy")
    if header:
        doc.sections[0].header.paragraphs[0].text = "Header excluded"
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def modified_package(data, name, change):
    source = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for item in source.infolist():
            raw = source.read(item.filename)
            target.writestr(item.filename, change(raw) if item.filename == name else raw)
    return out.getvalue()


def test_docx_order_locations_unicode_and_warning():
    result = parse_structured(docx_bytes(header=True), "nested/policy.docx", 10000)
    blocks = result["blocks"]
    assert [b["text"] for b in blocks] == [
        "Policy — effective 2026-11-01",
        "Café policy",
        "Column 1: Name | Column 2: Amount USD",
        "Column 1 (Name): Zoë | Column 2 (Amount USD): 1250",
        "End of policy",
    ]
    assert blocks[3]["table"] == 1 and blocks[3]["row"] == 2
    assert blocks[-1]["paragraph"] == 3
    assert all(b["page_number"] is None for b in blocks)
    assert "Headers are excluded." in result["warnings"]
    chunks = chunks_from_pages(result)
    assert all("Policy — effective 2026-11-01" in c["text"] for c in chunks)


def test_rtf_unicode_paragraphs_and_surrogate_pair():
    raw = rb"{\rtf1\ansi Caf\u233?\par Next \u-10179?\u-8704?}"
    result = parse_structured(raw, "a.rtf", 10000)
    assert [b["text"] for b in result["blocks"]] == ["Café", "Next 😀"]
    assert result["blocks"][1]["location"] == "Paragraph 2"


@pytest.mark.parametrize(
    "name,data,code",
    [
        ("a.docx", b"bad zip", "malformed_office"),
        ("a.docx", b"\xd0\xcf\x11\xe0fake", "encrypted_or_legacy"),
        ("a.rtf", b"not rtf", "malformed_rtf"),
        ("a.rtf", rb"{\rtf1 broken", "malformed_rtf"),
        ("a.rtf", rb"{\rtf1 {\object hidden}}", "unsupported_rtf_content"),
    ],
)
def test_bad_office(name, data, code):
    with pytest.raises(DocumentError) as caught:
        parse_structured(data, name, 10000)
    assert caught.value.code == code


def test_revisions_and_xml_entities_are_not_silently_accepted():
    tracked = modified_package(
        docx_bytes(), "word/document.xml", lambda b: b.replace(b"<w:body>", b"<w:body><w:ins/>")
    )
    with pytest.raises(DocumentError, match="tracked changes"):
        parse_structured(tracked, "a.docx", 10000)
    unsafe = modified_package(
        docx_bytes(),
        "word/document.xml",
        lambda b: b.replace(b"<w:document", b"<!DOCTYPE unsafe><w:document"),
    )
    with pytest.raises(DocumentError, match="DTD/entity"):
        parse_structured(unsafe, "a.docx", 10000)


def test_expansion_and_text_limits(monkeypatch):
    from rag import structured_parser

    with pytest.raises(DocumentError, match="text/block"):
        parse_structured(docx_bytes(), "a.docx", 10)
    monkeypatch.setattr(structured_parser, "MAX_EXPANDED", 100)
    with pytest.raises(DocumentError, match="expanded-byte"):
        parse_structured(docx_bytes(), "a.docx", 10000)


@pytest.mark.parametrize(
    "name,data,new_data,bad",
    [
        ("policy.docx", docx_bytes(), docx_bytes("Replacement fact"), b"invalid zip"),
        ("policy.rtf", rb"{\rtf1 first}", rb"{\rtf1 replacement}", b"invalid rtf"),
    ],
)
def test_managed_nested_names_reimport_replacement_and_failed_replacement(
    library, name, data, new_data, bad
):
    lib = library
    job = upload(lib, {"one/" + name: data, "two/" + name: data})
    assert finish(lib, job)["counts"]["successful"] == 2
    before = lib.documents()["documents"]
    assert len(before) == 2 and len({d["id"] for d in before}) == 2
    assert finish(lib, upload(lib, {"one/" + name: data}))["counts"]["skipped"] == 1
    assert finish(lib, upload(lib, {"one/" + name: new_data}))["counts"]["successful"] == 1
    stable = {d["id"]: d["revision"] for d in lib.documents()["documents"]}
    assert finish(lib, upload(lib, {"one/" + name: bad}))["counts"]["failed"] == 1
    assert {d["id"]: d["revision"] for d in lib.documents()["documents"]} == stable
    answer = lib.ask("policy")
    assert answer["sources"] and all(s["location"] for s in answer["sources"])
    assert all(s["page_number"] is None for s in answer["sources"])


def test_old_parser_index_remains_searchable(library, monkeypatch):
    lib = library
    current = lib.model_context
    monkeypatch.setattr(
        lib, "model_context", lambda *args: current("folder-v1-pypdf-text-csv-labels")
    )
    assert finish(lib, upload(lib, {"old.txt": b"Old retained fact"}))["counts"]["successful"] == 1
    monkeypatch.setattr(lib, "model_context", current)
    assert lib.ask("retained")["sources"][0]["text"] == "Old retained fact"


def pptx_bytes(value="Café launch", *, notes=False):
    from pptx import Presentation
    from pptx.util import Inches

    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[5])
    slide.shapes.title.text = value
    group = slide.shapes.add_group_shape()
    group.shapes.add_textbox(0, 0, Inches(2), Inches(1)).text = "Grouped Unicode — Zoë"
    table = slide.shapes.add_table(2, 2, 0, Inches(2), Inches(4), Inches(2)).table
    for row, values in zip(table.rows, [("Product", "Budget USD"), ("Atlas", "3200")], strict=True):
        for cell, text in zip(row.cells, values, strict=True):
            cell.text = text
    if notes:
        slide.notes_slide.notes_text_frame.text = "Private speaker notes"
    out = io.BytesIO()
    deck.save(out)
    return out.getvalue()


def test_pptx_group_tables_notes_and_slide_locations():
    result = parse_structured(pptx_bytes(notes=True), "a.pptx", 10000)
    assert all(b["slide_number"] == 1 and b["page_number"] is None for b in result["blocks"])
    assert any("Grouped Unicode" in b["text"] for b in result["blocks"])
    assert any("Atlas" in b["text"] and "3200" in b["text"] for b in result["blocks"])
    assert result["warnings"] == ["Slide 1: speaker notes are excluded."]
    assert "Private speaker notes" not in str(result["blocks"])
    with pytest.raises(DocumentError, match="slide limit"):
        parse_structured(pptx_bytes(), "a.pptx", 10000, max_pages=0)


def test_pptx_managed_replacement_and_corruption(library):
    lib = library
    data = pptx_bytes()
    assert finish(lib, upload(lib, {"nested/deck.pptx": data}))["counts"]["successful"] == 1
    assert finish(lib, upload(lib, {"nested/deck.pptx": data}))["counts"]["skipped"] == 1
    assert (
        finish(lib, upload(lib, {"nested/deck.pptx": pptx_bytes("New title")}))["counts"][
            "successful"
        ]
        == 1
    )
    previous = lib.documents()["documents"][0]["revision"]
    assert finish(lib, upload(lib, {"nested/deck.pptx": b"bad"}))["counts"]["failed"] == 1
    assert lib.documents()["documents"][0]["revision"] == previous
    assert all(s["slide_number"] == 1 for s in lib.ask("title")["sources"])
