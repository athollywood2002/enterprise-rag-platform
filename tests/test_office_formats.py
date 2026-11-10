"""Genuine in-memory Office fixtures, bounded child and transactional library tests."""

import io
import zipfile

import pytest
from docx import Document
from test_library import finish, linux_parser, upload
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
        ("a.rtf", rb"{\rtf1 \bin3 abc}", "unsupported_rtf_content"),
        ("a.rtf", rb"{\rtf1 \revised1 unaccepted change}", "unsupported_rtf_content"),
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
@linux_parser
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


@linux_parser
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


@linux_parser
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


def xlsx_bytes(value="Café", *, formula=False, hidden=False, oversized=False):
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = "Costs — Europe"
    sheet.append(["Vendor ID", "Name", "Amount USD", "Effective date"])
    import datetime

    sheet.append(["VEN-011", value, 2500, datetime.date(2026, 11, 9)])
    sheet["C2"].number_format = "$#,##0.00"
    if formula:
        sheet["C2"] = "=1000+1500"
    if oversized:
        sheet["B2"] = "é🚀" * 1200 + "END"
    if hidden:
        sheet.append(["SECRET", "Excluded", 99, None])
        sheet.row_dimensions[3].hidden = True
        other = book.create_sheet("Hidden")
        other.sheet_state = "hidden"
        other.append(["HIDDEN_SECRET"])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def test_xlsx_headers_values_dates_locations_and_hidden_policy():
    result = parse_structured(xlsx_bytes(hidden=True), "a.xlsx", 10000)
    assert len(result["blocks"]) == 2
    row = result["blocks"][1]
    assert row["cell_range"] == "A2:D2" and row["sheet_name"] == "Costs — Europe"
    assert all(
        word in row["text"]
        for word in ["VEN-011", "2500", "Amount USD", "2026-11-09", "number format"]
    )
    assert "SECRET" not in str(result["blocks"])
    assert any("hidden sheet" in w for w in result["warnings"])
    assert any("hidden rows" in w for w in result["warnings"])
    assert len(chunks_from_pages(result)) == 2


def test_xlsx_missing_formula_cache_is_unavailable_not_zero():
    result = parse_structured(xlsx_bytes(formula=True), "a.xlsx", 10000)
    assert "unavailable: no cached formula result" in result["blocks"][1]["text"]
    # Replace only the saved cache, without evaluating any formula in this test.
    data = modified_package(
        xlsx_bytes(formula=True),
        "xl/worksheets/sheet1.xml",
        lambda b: b.replace(b"<f>1000+1500</f><v></v>", b"<f>1000+1500</f><v>2500</v>"),
    )
    cached = parse_structured(data, "a.xlsx", 10000)
    assert "[cached formula result, not recalculated] 2500" in cached["blocks"][1]["text"]


def test_long_xlsx_and_csv_rows_keep_identity_headers_and_every_value():
    import json

    from rag.folder_parser import parse_managed

    value = "é🚀" * 1200 + "END"
    docs = [
        parse_structured(xlsx_bytes(oversized=True), "a.xlsx", 20000),
        parse_managed(
            ("ID,Name,Amount\nVEN-011," + value + ",2500\n").encode(), "a.csv", max_chars=20000
        ),
    ]
    for document in docs:
        chunks = chunks_from_pages(document)
        continuation = [
            c for c in chunks if c.get("continuation") and "Name" in c.get("cell_label", "")
        ]
        assert continuation
        assert all("VEN-011" in c["text"] and len(c["text"]) <= 900 for c in continuation)
        recovered = "".join(json.loads(c["text"].split(": ", 1)[1]) for c in continuation)
        assert recovered == value
        assert any("2500" in c["text"] for c in chunks)


def test_xlsx_limits_and_corruption(monkeypatch):
    from rag import tabular_parser

    with pytest.raises(DocumentError):
        parse_structured(b"bad", "a.xlsx", 10000)
    with pytest.raises(DocumentError, match="Encrypted Office"):
        parse_structured(b"\xd0\xcf\x11\xe0bad", "a.xlsx", 10000)
    monkeypatch.setattr(tabular_parser, "MAX_CELLS", 2)
    with pytest.raises(DocumentError, match="total-cell"):
        parse_structured(xlsx_bytes(), "a.xlsx", 10000)


@linux_parser
def test_xlsx_managed_replacement_retention_and_search(library):
    lib = library
    data = xlsx_bytes()
    first = finish(lib, upload(lib, {"one/book.xlsx": data, "two/book.xlsx": data}))
    assert first["counts"]["successful"] == 2, first
    assert finish(lib, upload(lib, {"one/book.xlsx": data}))["counts"]["skipped"] == 1
    assert (
        finish(lib, upload(lib, {"one/book.xlsx": xlsx_bytes("Replacement")}))["counts"][
            "successful"
        ]
        == 1
    )
    stable = {d["id"]: d["revision"] for d in lib.documents()["documents"]}
    assert finish(lib, upload(lib, {"one/book.xlsx": b"corrupt"}))["counts"]["failed"] == 1
    assert {d["id"]: d["revision"] for d in lib.documents()["documents"]} == stable
    sources = lib.ask("Vendor amount")["sources"]
    assert all(s["sheet_name"] == "Costs — Europe" and s["cell_range"] for s in sources)


@linux_parser
def test_all_formats_server_folder_http_and_citation_contract(library, monkeypatch):
    from pathlib import Path

    from fastapi.testclient import TestClient
    from test_library import create_job

    from demo.office_fixtures import office_files
    from rag import api

    root = Path(library.source_root("shared"))
    files = {
        "fixture." + ext: data
        for ext, data in office_files({".docx", ".rtf", ".pptx", ".xlsx"}).items()
    }
    assert {Path(n).suffix for n in files} == {".docx", ".rtf", ".pptx", ".xlsx"}
    for folder in ("one", "two"):
        (root / folder).mkdir()
        for name, data in files.items():
            (root / folder / name).write_bytes(data)
    job = create_job(library, "server", "shared")
    assert finish(library, job["id"])["counts"]["successful"] == 8
    assert len(library.documents()["documents"]) == 8
    assert finish(library, create_job(library, "server", "shared")["id"])["counts"]["skipped"] == 8
    monkeypatch.setattr(api, "settings", lambda: library.config)
    monkeypatch.setattr(api, "library", lambda: library)
    api.app.state.library = library
    try:
        with TestClient(api.app) as client:
            headers = {"x-api-key": library.config.api_key}
            assert client.post("/library/ask", json={"question": "ORION"}).status_code == 401
            config = client.get("/library/config", headers=headers).json()
            assert all(ext in config["formats"] for ext in (".docx", ".rtf", ".pptx", ".xlsx"))
            response = client.post(
                "/library/ask", headers=headers, json={"question": "ORION NetworkOps", "top_k": 10}
            )
            assert response.status_code == 200
            sources = response.json()["sources"]
            assert {Path(s["source"]).suffix for s in sources} == {
                ".docx",
                ".rtf",
                ".pptx",
                ".xlsx",
            }
            assert all(s["location"] and s["page_number"] is None for s in sources)
            assert all(s["slide_number"] == 1 for s in sources if s["source"].endswith(".pptx"))
            assert all(
                s["sheet_name"] and s["cell_range"]
                for s in sources
                if s["source"].endswith(".xlsx")
            )
    finally:
        api.app.state.library = None


def test_image_only_presentation_fails_without_claiming_complete_extraction():
    from PIL import Image
    from pptx import Presentation
    from pptx.util import Inches

    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    png = io.BytesIO()
    Image.new("RGB", (2, 2)).save(png, format="PNG")
    png.seek(0)
    slide.shapes.add_picture(png, 0, 0, width=Inches(1))
    out = io.BytesIO()
    deck.save(out)
    with pytest.raises(DocumentError, match="No usable text"):
        parse_structured(out.getvalue(), "image.pptx", 10000)


def test_xlsx_hidden_columns_and_oversized_merge():
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.append(["ID", "Private", "Amount"])
    sheet.append(["A1", "DO_NOT_INDEX", 100])
    sheet.column_dimensions["B"].hidden = True
    out = io.BytesIO()
    book.save(out)
    result = parse_structured(out.getvalue(), "hidden.xlsx", 10000)
    assert "DO_NOT_INDEX" not in str(result["blocks"])
    assert any("hidden columns excluded" in warning for warning in result["warnings"])
    oversized = modified_package(
        out.getvalue(),
        "xl/worksheets/sheet1.xml",
        lambda b: b.replace(
            b"</worksheet>",
            b'<mergeCells><mergeCell ref="A1:XFD1048576"/></mergeCells></worksheet>',
        ),
    )
    with pytest.raises(DocumentError, match="Merged range"):
        parse_structured(oversized, "large.xlsx", 10000)


@pytest.mark.parametrize(
    "expression,available", [("SUM(Table1[Amount])", True), ("'[1]Sheet1'!A1", False)]
)
def test_formula_cache_distinguishes_table_reference_from_external_link(expression, available):
    data = modified_package(
        xlsx_bytes(formula=True),
        "xl/worksheets/sheet1.xml",
        lambda b: b.replace(
            b"<f>1000+1500</f><v></v>", ("<f>" + expression + "</f><v>2500</v>").encode()
        ),
    )
    text = parse_structured(data, "a.xlsx", 10000)["blocks"][1]["text"]
    if available:
        assert "[cached formula result, not recalculated] 2500" in text
    else:
        assert "[unavailable: external formula links excluded]" in text
        assert "2500" not in text
