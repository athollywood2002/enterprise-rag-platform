"""Row-preserving CSV/XLSX extraction; formulas are never evaluated."""

import csv
import datetime
import io
import json
import re
import xml.etree.ElementTree as ET

from .folder_parser import DocumentError
from .structured_parser import Blocks, package

MAX_SHEETS = 32
MAX_ROWS = 10000
MAX_COLUMNS = 256
MAX_CELLS = 100000
MAX_CELL_CHARS = 100000


def quoted(value):
    return json.dumps(value, ensure_ascii=False)


def add_row(out, labels, values, row, sheet=None, coordinates=None):
    if len(values) > MAX_COLUMNS or row > MAX_ROWS:
        raise DocumentError("table_limit", "Table exceeds row/column limits.")
    cells = []
    for i, (label, value) in enumerate(zip(labels, values, strict=True), 1):
        if len(label) > 200:
            raise DocumentError(
                "header_limit", "Column labels exceed 200 characters; shorten the headers."
            )
        if len(value) > MAX_CELL_CHARS:
            raise DocumentError("cell_limit", "A cell exceeds the 100000-character limit.")
        cells.append(
            {
                "label": label,
                "value": value,
                "coordinate": coordinates[i - 1] if coordinates else f"column {i}",
            }
        )
    location = f"Sheet {sheet} · row {row}" if sheet is not None else f"CSV record {row}"
    cell_range = f"{coordinates[0]}:{coordinates[-1]}" if coordinates else None
    text = f"{location}: " + "; ".join(f"{quoted(c['label'])}: {quoted(c['value'])}" for c in cells)
    out.add(
        text,
        location + (f" · {cell_range}" if cell_range else ""),
        row=row,
        sheet_name=sheet,
        cell_range=cell_range,
        cells=cells,
    )


def csv_blocks(data, max_chars):
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise DocumentError("encoding", "Save CSV files as UTF-8.") from error
    if "\x00" in text:
        raise DocumentError("binary_text", "CSV contains binary data.")
    out = Blocks(max_chars)
    try:
        rows = csv.reader(io.StringIO(text, newline=""), strict=True)
        headers = next(rows, [])
        if not headers or any(not h.strip() for h in headers) or len(set(headers)) != len(headers):
            raise DocumentError("csv_header", "CSV needs nonempty, unique column headers.")
        total = 0
        for rn, values in enumerate(rows, 2):
            if not values:
                continue
            if len(values) != len(headers):
                raise DocumentError(
                    "csv_columns", f"CSV record {rn} has the wrong number of fields."
                )
            total += len(values)
            if total > MAX_CELLS:
                raise DocumentError("cell_limit", "CSV exceeds the total cell limit.")
            add_row(out, headers, values, rn)
    except csv.Error as error:
        raise DocumentError("malformed_csv", "CSV quoting or field size is invalid.") from error
    return out.result()


def xlsx_blocks(data, max_chars):
    from openpyxl import load_workbook
    from openpyxl.utils.cell import coordinate_to_tuple, get_column_letter, range_boundaries

    archive = package(data, "xl/workbook.xml")
    sheets = [
        n for n in archive.namelist() if n.startswith("xl/worksheets/") and n.endswith(".xml")
    ]
    if len(sheets) > MAX_SHEETS:
        raise DocumentError("sheet_limit", "Workbook exceeds 32 worksheets.")
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    count = 0
    # Bound actual cell coordinates before constructing two workbook models.
    for name in sheets:
        root = ET.fromstring(archive.read(name))
        for cell in root.iter(ns + "c"):
            count += 1
            rn, cn = coordinate_to_tuple(cell.attrib["r"])
            if rn > MAX_ROWS or cn > MAX_COLUMNS or count > MAX_CELLS:
                raise DocumentError("table_limit", "Workbook exceeds row/column/total-cell limits.")
        for row in root.iter(ns + "row"):
            if int(row.attrib.get("r", "0")) > MAX_ROWS:
                raise DocumentError("table_limit", "Workbook row index exceeds the limit.")
        for merged in root.iter(ns + "mergeCell"):
            left, top, right, bottom = range_boundaries(merged.attrib["ref"])
            if (
                right > MAX_COLUMNS
                or bottom > MAX_ROWS
                or (right - left + 1) * (bottom - top + 1) > MAX_CELLS
            ):
                raise DocumentError("table_limit", "Merged range exceeds worksheet limits.")
    values_book = load_workbook(io.BytesIO(data), data_only=True, keep_links=False)
    formulas_book = load_workbook(io.BytesIO(data), data_only=False, keep_links=False)
    out = Blocks(max_chars)
    try:
        if len(values_book.worksheets) > MAX_SHEETS:
            raise DocumentError("sheet_limit", "Workbook exceeds 32 worksheets.")
        for value_sheet, formula_sheet in zip(
            values_book.worksheets, formulas_book.worksheets, strict=True
        ):
            name = value_sheet.title
            if value_sheet.sheet_state != "visible":
                out.warnings.add(f"Sheet {name}: hidden sheet excluded.")
                continue
            if value_sheet.max_row > MAX_ROWS or value_sheet.max_column > MAX_COLUMNS:
                raise DocumentError("table_limit", "Worksheet dimensions exceed row/column limits.")
            hidden_columns = set()
            for dimension in value_sheet.column_dimensions.values():
                if dimension.hidden:
                    hidden_columns.update(range(dimension.min, dimension.max + 1))
            if hidden_columns:
                out.warnings.add(f"Sheet {name}: hidden columns excluded.")
            if any(d.hidden for d in value_sheet.row_dimensions.values()):
                out.warnings.add(f"Sheet {name}: hidden rows excluded.")
            if value_sheet.merged_cells.ranges:
                out.warnings.add(
                    f"Sheet {name}: merged cells use anchor values only; blank cells are not filled."
                )
            if value_sheet._charts or value_sheet._images:
                out.warnings.add(f"Sheet {name}: charts/images excluded; no OCR.")
            headers = None
            for rn in range(1, value_sheet.max_row + 1):
                if value_sheet.row_dimensions[rn].hidden:
                    continue
                values, coords = [], []
                for cn in range(1, value_sheet.max_column + 1):
                    if cn in hidden_columns:
                        continue
                    cell, formula = value_sheet.cell(rn, cn), formula_sheet.cell(rn, cn)
                    value = cell.value
                    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
                        value = value.isoformat()
                    value = "" if value is None else str(value)
                    if formula.data_type == "f":
                        expression = str(formula.value)
                        if re.search(r"\[[^\]]+\][^!]*!", expression):
                            value = "[unavailable: external formula links excluded]"
                        elif cell.value is None:
                            value = "[unavailable: no cached formula result]"
                        else:
                            value = "[cached formula result, not recalculated] " + value
                        out.warnings.add(
                            f"Sheet {name}: formulas use supplied cached values only; unavailable results are not calculated."
                        )
                    if cell.number_format != "General" and value:
                        value += " (number format: " + cell.number_format + ")"
                    values.append(value)
                    coords.append(cell.coordinate)
                if not any(values):
                    continue
                if headers is None:
                    headers = [
                        f"{get_column_letter(coordinate_to_tuple(c)[1])} {v or '(unnamed)'}"
                        for c, v in zip(coords, values, strict=True)
                    ]
                add_row(out, headers, values, rn, name, coords)
        names = archive.namelist()
        for marker, message in [
            ("xl/externalLinks/", "External links excluded; never fetched."),
            ("xl/embeddings/", "Embedded objects excluded; never executed."),
            ("xl/comments", "Cell comments excluded."),
        ]:
            if any(n.startswith(marker) for n in names):
                out.warnings.add(message)
        return out.result()
    finally:
        values_book.close()
        formulas_book.close()


def row_chunks(block, warnings, size):
    """Ordinary row stays together. Long rows carry identity/header context per cell part."""
    metadata = {k: v for k, v in block.items() if k not in {"text", "cells"}}
    if len(block["text"]) <= size:
        return [{**metadata, "text": block["text"], "warnings": warnings}]
    # First two short values are useful row identity. Long identifiers retain their
    # coordinate and full value in continuations; they are never truncated.
    identity = "; ".join(
        f"{c['coordinate']}={quoted(c['value'])}"
        for c in block["cells"][:2]
        if len(c["value"]) <= 80
    )
    result = []
    for cell in block["cells"]:
        prefix = f"Row {block['row']} ({identity}) · {cell['coordinate']} {quoted(cell['label'])}"
        if block.get("sheet_name"):
            prefix = f"Sheet {block['sheet_name']} · " + prefix
        width = size - len(prefix) - 60
        if width < 32:
            raise DocumentError(
                "row_context_limit",
                "Row identity/header context is too large; shorten labels or identifiers.",
            )
        # JSON escaping can expand each character six-fold; bound actual serialized size.
        offset = 0
        value = cell["value"]
        while offset < len(value) or (not value and offset == 0):
            end = min(len(value), offset + width)
            while len(quoted(value[offset:end])) > width and end > offset:
                end -= 1
            if end == offset and value:
                raise DocumentError(
                    "row_context_limit", "Cell cannot fit in a bounded continuation."
                )
            result.append(
                {
                    **metadata,
                    "text": f"{prefix} · continuation {offset + 1}–{end}: {quoted(value[offset:end])}",
                    "continuation": True,
                    "value_start": offset,
                    "value_end": end,
                    "cell": cell["coordinate"],
                    "cell_label": cell["label"],
                    "warnings": warnings,
                }
            )
            if end >= len(value):
                break
            offset = end
    return result
