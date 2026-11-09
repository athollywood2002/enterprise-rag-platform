import io

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from rag.folder_parser import DocumentError
from rag.structured_parser import parse_structured


def omit(row, leading=0, trailing=0):
    for _ in range(leading):
        row._tr.remove(row._tr.tc_lst[0])
    for _ in range(trailing):
        row._tr.remove(row._tr.tc_lst[-1])
    for tag, count in (("gridBefore", leading), ("gridAfter", trailing)):
        if count:
            node = OxmlElement("w:" + tag)
            node.set(qn("w:val"), str(count))
            row._tr.get_or_add_trPr().append(node)


def extract(doc):
    stream = io.BytesIO()
    doc.save(stream)
    return parse_structured(stream.getvalue(), "nested/table.docx", 10000)["blocks"]


def test_docx_omitted_cells_preserve_header_and_data_grid_positions():
    doc = Document()
    table = doc.add_table(rows=3, cols=4)
    for row, values in zip(
        table.rows,
        [
            ("", "Amount USD", "Approver", ""),
            ("", "1200", "Manager", ""),
            ("Zoë", "2400", "Director", "Active"),
        ],
        strict=True,
    ):
        for cell, value in zip(row.cells, values, strict=True):
            cell.text = value
    omit(table.rows[0], leading=1, trailing=1)
    omit(table.rows[1], leading=1, trailing=1)
    blocks = extract(doc)
    assert blocks[0]["text"] == "Column 2: Amount USD | Column 3: Approver"
    assert blocks[1]["text"] == "Column 2 (Amount USD): 1200 | Column 3 (Approver): Manager"
    assert blocks[2]["text"] == (
        "Column 1: Zoë | Column 2 (Amount USD): 2400 | Column 3 (Approver): Director | Column 4: Active"
    )


def test_docx_merged_spans_use_all_corresponding_headers():
    doc = Document()
    table = doc.add_table(rows=3, cols=4)
    table.cell(0, 0).text = "Identity"
    table.cell(0, 0).merge(table.cell(0, 1))
    table.cell(0, 2).text = "Amount USD"
    table.cell(0, 3).text = "Approver"
    table.cell(1, 0).text = "Zoë"
    table.cell(1, 1).text = "EMP-7"
    table.cell(1, 2).text = "1200 / Manager"
    table.cell(1, 2).merge(table.cell(1, 3))
    omit(table.rows[2], leading=1, trailing=1)
    table.rows[2].cells[0].text = "EMP-8"
    table.rows[2].cells[1].text = "2500"
    blocks = extract(doc)
    assert "Columns 1–2: Identity" in blocks[0]["text"]
    assert "Column 2 (Identity): EMP-7" in blocks[1]["text"]
    assert "Columns 3–4 (Amount USD / Approver): 1200 / Manager" in blocks[1]["text"]
    assert blocks[2]["text"] == "Column 2 (Identity): EMP-8 | Column 3 (Amount USD): 2500"


@pytest.mark.parametrize("codepage,text", [(1252, "Price € 10"), (1251, "Привет мир")])
@pytest.mark.parametrize("escaped", [False, True])
def test_rtf_literal_and_escaped_codepage_bytes(codepage, text, escaped):
    data = text.encode(f"cp{codepage}")
    if escaped:
        data = b"".join(f"\\'{byte:02x}".encode() for byte in data)
    raw = f"{{\\rtf1\\ansi\\ansicpg{codepage} ".encode() + data + b"}"
    assert parse_structured(raw, "encoded.rtf", 10000)["blocks"][0]["text"] == text


def test_rtf_codepage_bytes_unicode_fallback_and_font_default():
    raw = (
        rb"{\rtf1\ansi\ansicpg1251{\fonttbl{\f0\fcharset0 Arial;}}\f0 "
        b"\xcf" + rb"\'f0\u1080?\u1074\'e5\u1077?\u1090?\par "
        rb"\uc2\u-10179??\u-8704??}"
    )
    assert [b["text"] for b in parse_structured(raw, "unicode.rtf", 10000)["blocks"]] == [
        "Привет",
        "😀",
    ]


@pytest.mark.parametrize(
    "controls",
    [
        rb"\ansicpg99999",
        rb"\ansicpg65001",
        rb"\ansicpg1252\ansicpg1251",
        rb"\ansicpg1252{\fonttbl{\f0\fcharset204 Arial;}}\f0",
        rb"\mac",
    ],
)
def test_rtf_unsupported_encoding_combinations_fail_explicitly(controls):
    with pytest.raises(DocumentError) as caught:
        parse_structured(rb"{\rtf1" + controls + b" value}", "unsupported.rtf", 10000)
    assert caught.value.code == "unsupported_rtf_encoding"
