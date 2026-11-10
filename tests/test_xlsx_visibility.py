import io
import xml.etree.ElementTree as ET
import zipfile

import pytest
from openpyxl import Workbook

from rag.structured_parser import parse_structured


def visibility_workbook(default_hidden, visible_value="0", relocate=False):
    book = Workbook()
    sheet = book.active
    sheet.title = "Budgets"
    sheet.sheet_format.zeroHeight = default_hidden
    for row in [
        ("Name", "USD"),
        ("Default row", 100),
        ("Visible exception", 200),
        ("Hidden row", 300),
    ]:
        sheet.append(row)
    sheet.row_dimensions[4].hidden = True
    out = io.BytesIO()
    book.save(out)
    source = zipfile.ZipFile(io.BytesIO(out.getvalue()))
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w") as target:
        for item in source.infolist():
            raw = source.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                root = ET.fromstring(raw)
                for row in root.iter(
                    "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row"
                ):
                    if row.attrib["r"] in {"1", "3"}:
                        row.set("hidden", visible_value)
                raw = ET.tostring(root)
            filename = item.filename
            if relocate:
                if filename == "xl/_rels/workbook.xml.rels":
                    raw = raw.replace(b"/xl/worksheets/sheet1.xml", b"worksheets/budgets.xml")
                elif filename == "[Content_Types].xml":
                    raw = raw.replace(b"/xl/worksheets/sheet1.xml", b"/xl/worksheets/budgets.xml")
                elif filename == "xl/worksheets/sheet1.xml":
                    filename = "xl/worksheets/budgets.xml"
            target.writestr(filename, raw)
    return result.getvalue()


@pytest.mark.parametrize("visible_value", ["0", "false"])
@pytest.mark.parametrize("relocate", [False, True])
def test_xlsx_hidden_default_respects_explicit_visible_exceptions(visible_value, relocate):
    result = parse_structured(visibility_workbook(True, visible_value, relocate), "a.xlsx", 10000)
    assert [b["row"] for b in result["blocks"]] == [1, 3]
    assert '"A Name": "Visible exception"' in result["blocks"][1]["text"]
    assert result["blocks"][1]["cell_range"] == "A3:B3"
    assert "Sheet Budgets: hidden rows excluded." in result["warnings"]


def test_xlsx_ordinary_hidden_rows_are_still_excluded():
    result = parse_structured(visibility_workbook(False), "a.xlsx", 10000)
    assert [b["row"] for b in result["blocks"]] == [1, 2, 3]
    assert "Sheet Budgets: hidden rows excluded." in result["warnings"]
