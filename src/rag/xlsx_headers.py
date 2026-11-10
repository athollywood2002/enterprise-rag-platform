"""Conservative worksheet header selection. Explicit Excel Tables override inference."""

from .folder_parser import DocumentError


def header_error(sheet):
    return DocumentError(
        "xlsx_header",
        f"Sheet {sheet}: ambiguous or unavailable headers. Create an Excel Table with one "
        "visible, nonempty, unique text header per column (include units in labels), "
        "or place those headers after sparse title/metadata rows. Split multiple plain tables "
        "into separate sheets. Hidden or formula headers cannot be used.",
    )


def associate_headers(sheet, rows, formula_sheet):
    """Return row subsets with labels. Never fill missing/merged header values.

    Plain sheets: first row covering every populated visible column is the header;
    all its cells must be distinct short strings. Earlier sparse rows are context,
    not headers. This is a documented layout convention, not semantic guessing.
    Explicit table ranges resolve layouts that do not follow the convention.
    """
    from openpyxl.utils.cell import coordinate_to_tuple, get_column_letter, range_boundaries

    if not rows:
        return []
    by_number = {rn: (values, coords) for rn, values, coords in rows}
    used = set()
    groups = []

    def group(header_row, columns, last_row, table_name=None):
        if header_row not in by_number or not columns:
            raise header_error(sheet.title)
        _, coords = by_number[header_row]
        labels = []
        for col in columns:
            coord = f"{get_column_letter(col)}{header_row}"
            raw = formula_sheet[coord]
            if (
                coord not in coords
                or not isinstance(raw.value, str)
                or raw.data_type == "f"
                or not raw.value.strip()
                or len(raw.value) > 190
            ):
                raise header_error(sheet.title)
            labels.append(raw.value.strip())
        if len({v.casefold() for v in labels}) != len(labels):
            raise header_error(sheet.title)
        labels = [
            f"{get_column_letter(col)} {label}" for col, label in zip(columns, labels, strict=True)
        ]
        header_range = f"{get_column_letter(columns[0])}{header_row}:{get_column_letter(columns[-1])}{header_row}"
        for rn, values, coords in rows:
            if not header_row <= rn <= last_row:
                continue
            lookup = dict(zip(coords, values, strict=True))
            selected = [f"{get_column_letter(c)}{rn}" for c in columns]
            if any(c in used for c in selected):
                raise header_error(sheet.title)
            used.update(selected)
            values = [lookup.get(c, "") for c in selected]
            if not any(values):
                continue
            groups.append(
                (
                    rn,
                    labels,
                    values,
                    selected,
                    {
                        "header_row": header_row,
                        "header_range": header_range,
                        "column_labels": labels,
                        "row_kind": "header" if rn == header_row else "data",
                        **({"table_name": table_name} if table_name else {}),
                    },
                )
            )

    if sheet.tables:
        from .tabular_parser import MAX_COLUMNS, MAX_ROWS

        for table in sheet.tables.values():
            left, top, right, bottom = range_boundaries(table.ref)
            if not (1 <= left <= right <= MAX_COLUMNS and 1 <= top <= bottom <= MAX_ROWS):
                raise DocumentError("table_limit", "Excel Table range exceeds worksheet limits.")
            if table.headerRowCount != 1:
                raise header_error(sheet.title)
            # Visible header coordinates only: never recover hidden labels from table metadata.
            visible = {coordinate_to_tuple(c)[1] for _, _, coords in rows for c in coords}
            columns = [c for c in range(left, right + 1) if c in visible]
            group(top, columns, bottom, table.name)
            if table.totalsRowCount:
                groups[:] = [
                    (
                        rn,
                        labels,
                        values,
                        coords,
                        {**meta, "row_kind": "totals"}
                        if meta.get("table_name") == table.name
                        and rn > bottom - table.totalsRowCount
                        else meta,
                    )
                    for rn, labels, values, coords, meta in groups
                ]
    else:
        columns = sorted(
            {
                coordinate_to_tuple(c)[1]
                for _, values, coords in rows
                for value, c in zip(values, coords, strict=True)
                if value
            }
        )
        candidate = next(
            (
                rn
                for rn, values, coords in rows
                if {coordinate_to_tuple(c)[1] for v, c in zip(values, coords, strict=True) if v}
                == set(columns)
            ),
            None,
        )
        if candidate is None:
            raise header_error(sheet.title)
        # A near-full preamble could instead be a damaged header. Multiple full
        # text rows before typed data could be multi-level headers or metadata.
        # Neither layout is safe to guess: an explicit Excel Table resolves it.
        for rn, values, _ in rows:
            populated = sum(bool(v) for v in values)
            if rn < candidate and populated > 1 and populated * 2 >= len(columns):
                raise header_error(sheet.title)
        text_rows = 0
        for rn, values, coords in rows:
            if rn < candidate:
                continue
            filled = [formula_sheet[c] for v, c in zip(values, coords, strict=True) if v]
            if any(not isinstance(c.value, str) or c.data_type == "f" for c in filled):
                if text_rows > 1:
                    raise header_error(sheet.title)
                break
            if len(filled) == len(columns):
                text_rows += 1
        group(candidate, columns, rows[-1][0])
        # A blank-separated second full text block could have different headers.
        previous = candidate
        for rn, values, coords in rows:
            if rn <= candidate:
                continue
            if rn > previous + 1:
                filled = [formula_sheet[c] for v, c in zip(values, coords, strict=True) if v]
                if len(filled) == len(columns) and all(
                    isinstance(c.value, str) and c.data_type != "f" for c in filled
                ):
                    raise header_error(sheet.title)
            previous = rn

    # Keep all visible values outside tables/preamble as coordinate-labeled context,
    # never invent a relationship between a title and a data column.
    for rn, values, coords in rows:
        remaining = [(v, c) for v, c in zip(values, coords, strict=True) if c not in used and v]
        if remaining:
            vals, locs = zip(*remaining, strict=True)
            groups.append((rn, list(locs), list(vals), list(locs), {"row_kind": "context"}))
    return sorted(groups, key=lambda g: (g[0], g[3][0]))
