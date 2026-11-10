"""Real XLSX bytes and deterministic retrieval; no model-quality claims."""

import io
import json
from types import SimpleNamespace as NS

import httpx
import pytest
from openpyxl import Workbook
from openpyxl.worksheet.table import Table
from test_library import library as library_fixture
from test_library import linux_parser

library = library_fixture

from rag.config import Settings
from rag.core import RagEngine
from rag.folder_parser import DocumentError, chunks_from_pages
from rag.structured_parser import parse_structured


def workbook(preamble=3, offset=0, explicit=False, long=False):
    book = Workbook()
    sheet = book.active
    sheet.title = "Systems — Europe"
    for row in range(1, preamble + 1):
        sheet.cell(row, offset + 1, f"Catalog context {row}; effective 2026-07-01")
    headers = ["Service ID", "Service", "Owner", "Tier", "RTO hours", "RPO minutes"]
    rows = [
        headers,
        ["SVC-002", "Gatehouse SSO", "Zoë", "Tier 1", 2, 0],
        ["SVC-007", "Beacon security", "Priya", "Tier 1", 2, 5],
        ["SVC-005", "LedgerLoop expenses", "Jordan Ellis", "Tier 2", 24, 1440],
    ]
    if long:
        rows[1][2] = "é🚀" * 1000 + "END"
    for rn, row in enumerate(rows, preamble + 1):
        for cn, value in enumerate(row, offset + 1):
            sheet.cell(rn, cn, value)
    if explicit:
        from openpyxl.utils import get_column_letter as letter

        sheet.add_table(
            Table(
                displayName="Recovery",
                ref=f"{letter(offset + 1)}{preamble + 1}:{letter(offset + 6)}{preamble + 4}",
            )
        )
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


@pytest.mark.parametrize(
    "preamble,offset,explicit", [(0, 0, False), (2, 0, False), (5, 2, False), (4, 1, True)]
)
def test_header_association_with_varied_preambles(preamble, offset, explicit):
    doc = parse_structured(workbook(preamble, offset, explicit), "nested/catalog.xlsx", 100000)
    row = next(b for b in doc["blocks"] if '"Gatehouse SSO"' in b["text"])
    assert 'RTO hours": "2"' in row["text"]
    assert 'RPO minutes": "0"' in row["text"]
    assert row["header_row"] == preamble + 1
    assert row["row"] == preamble + 2
    assert row["header_range"] != row["cell_range"]
    assert "Gatehouse SSO" in row["row_entities"]
    assert not any("unnamed" in b["text"] for b in doc["blocks"])


def test_continuations_keep_header_units_coordinates_and_full_values():
    chunks = chunks_from_pages(parse_structured(workbook(long=True), "a.xlsx", 100000))
    owner = [
        c
        for c in chunks
        if c.get("continuation") and c.get("cell_label", "").endswith("Owner") and c["row"] == 5
    ]
    assert owner
    assert "".join(json.loads(c["text"].split(": ", 1)[1]) for c in owner) == "é🚀" * 1000 + "END"
    for c in owner:
        assert c["header_row"] == 4
        assert "RTO hours" in str(c["column_labels"])
        assert "SVC-002" in c["text"]
        assert c["cell"] == "C5"
        assert len(c["text"]) <= 900


@pytest.mark.parametrize(
    "headers", [["ID", None, "Hours"], ["ID", "Value", "Value"], ["Title", 42, "Metadata"]]
)
def test_ambiguous_headers_fail_actionably(headers):
    book = Workbook()
    sheet = book.active
    sheet.append(headers)
    sheet.append(["A", "Name", 12])
    out = io.BytesIO()
    book.save(out)
    with pytest.raises(DocumentError, match="Excel Table"):
        parse_structured(out.getvalue(), "ambiguous.xlsx", 10000)


def test_n10_service_rows_reach_answer_context_with_distractor_dense_ranking(monkeypatch):
    doc = parse_structured(workbook(), "catalog.xlsx", 100000)
    chunks = chunks_from_pages(doc)
    rows = [
        NS(id=f"row-{i}", score=0.01, payload={**c, "source": "catalog.xlsx", "chunk": i})
        for i, c in enumerate(chunks)
    ]
    notes = [
        NS(
            id=f"note-{i}",
            score=0.99 - i / 100,
            payload={"source": "catalog.xlsx", "chunk": 100 + i, "text": text},
        )
        for i, text in enumerate(
            [
                "Gatehouse SSO recovery objectives: see service catalog. What are RTO and RPO?",
                "Beacon security recovery objectives and RTO RPO definitions.",
                "RTO begins when disaster recovery is invoked. RPO is the targeted data-loss interval.",
                "Gatehouse SSO has a vendor relationship. Recovery objectives are not support SLAs.",
                "Recovery objectives, missing RPO values and zero values: see services.",
            ]
        )
    ]
    sent = []
    marker = object()

    class DB:
        def collection_exists(self, name):
            return True

        def query_points(self, **kw):
            assert kw["query_filter"] is marker
            return NS(points=notes)

        def scroll(self, **kw):
            assert kw["scroll_filter"] is marker
            return rows + notes, None

    def model(request):
        if request.url.path == "/api/embed":
            return httpx.Response(200, json={"embeddings": [[1.0, 0.0]]})
        sent.append(json.loads(request.content))
        return httpx.Response(
            200, json={"message": {"content": "synthetic transport only"}, "done": True}
        )

    engine = RagEngine(
        Settings(_env_file=None, api_key="synthetic", ollama_url="http://invalid"),
        qdrant=DB(),
        model_client=lambda _: httpx.Client(transport=httpx.MockTransport(model)),
    )
    from rag import retrieval

    query = "Compare the recovery objectives for Gatehouse SSO and Beacon security. What are their RTOs and RPOs, and does Gatehouse’s zero mean its RPO is missing?"
    with monkeypatch.context() as baseline:
        baseline.setattr(retrieval, "row_rank", lambda *_: [])
        header_only = engine.ask(query, 5, query_filter=marker, collection_names=["current"])
    assert not [s for s in header_only["sources"] if s.get("row_kind") == "data"]
    result = engine.ask(
        "Compare the recovery objectives for Gatehouse SSO and Beacon security. What are their RTOs and RPOs, and does Gatehouse’s zero mean its RPO is missing?",
        5,
        query_filter=marker,
        collection_names=["current"],
    )
    service_rows = [s for s in result["sources"] if s.get("row_kind") == "data"]
    assert {s["row"] for s in service_rows} >= {5, 6}
    context = "\n".join(m["content"] for m in sent[-1]["messages"])
    for value in ["Gatehouse SSO", "Beacon security", "RTO hours", "RPO minutes"]:
        assert value in context
    assert len(sent) == 2  # Two deliberate offline conditions, never an automatic retry.


def test_explicit_tables_keep_separate_headers_and_outside_values():
    book = Workbook()
    s = book.active
    for row in [
        ["Title"],
        ["ID", "Duration hours"],
        ["A", 2],
        [],
        ["ID", "Size GB"],
        ["B", 50],
        ["Footer text"],
    ]:
        s.append(row)
    s.add_table(Table(displayName="Durations", ref="A2:B3"))
    s.add_table(Table(displayName="Sizes", ref="A5:B6"))
    out = io.BytesIO()
    book.save(out)
    blocks = parse_structured(out.getvalue(), "a.xlsx", 10000)["blocks"]
    assert "Duration hours" in next(b["text"] for b in blocks if b["row"] == 3)
    assert "Size GB" in next(b["text"] for b in blocks if b["row"] == 6)
    assert next(b for b in blocks if b["row"] == 7)["row_kind"] == "context"
    assert "Footer text" in str(blocks)


@pytest.mark.parametrize("mode", ["hidden", "formula", "merge"])
def test_unavailable_headers_never_recovered_from_table_metadata(mode):
    book = Workbook()
    s = book.active
    s.append(["ID", "Hours"])
    s.append(["A", 2])
    s.add_table(Table(displayName="Data", ref="A1:B2"))
    if mode == "hidden":
        s.row_dimensions[1].hidden = True
    if mode == "formula":
        s["B1"] = '="Hours"'
    if mode == "merge":
        s.merge_cells("A1:B1")
    out = io.BytesIO()
    book.save(out)
    with pytest.raises(DocumentError, match="Excel Table"):
        parse_structured(out.getvalue(), "a.xlsx", 10000)


@linux_parser
def test_ambiguous_replacement_retains_previous_searchable_workbook(library):
    from test_library import finish, upload

    data = workbook(preamble=2)
    paths = {"one/catalog.xlsx": data, "two/catalog.xlsx": data}
    assert finish(library, upload(library, paths))["counts"]["successful"] == 2
    before = library.documents()["documents"]
    assert finish(library, upload(library, paths))["counts"]["skipped"] == 2
    book = Workbook()
    s = book.active
    s.append(["ID", None, "Hours"])
    s.append(["A", "Name", 1])
    out = io.BytesIO()
    book.save(out)
    assert (
        finish(library, upload(library, {"one/catalog.xlsx": out.getvalue()}))["counts"]["failed"]
        == 1
    )
    assert library.documents()["documents"] == before
    assert library.ask("Gatehouse SSO RTO hours")["sources"]
    assert (
        finish(library, upload(library, {"one/catalog.xlsx": workbook(preamble=4)}))["counts"][
            "successful"
        ]
        == 1
    )
    after = library.documents()["documents"]
    assert {d["id"]: d["revision"] for d in after} != {d["id"]: d["revision"] for d in before}


@pytest.mark.parametrize(
    "rows",
    [
        [["ID", None, "Hours"], ["A", "Name", "twelve"]],
        [["Version", "Owner"], ["ID", "Hours"], ["A", 12]],
        [["Identity", "Recovery"], ["ID", "Hours"], ["A", 12]],
    ],
)
def test_competing_header_rows_need_explicit_selection(rows):
    book = Workbook()
    sheet = book.active
    for row in rows:
        sheet.append(row)
    out = io.BytesIO()
    book.save(out)
    with pytest.raises(DocumentError, match="Excel Table"):
        parse_structured(out.getvalue(), "ambiguous.xlsx", 10000)


def test_explicit_table_resolves_full_width_metadata():
    book = Workbook()
    sheet = book.active
    for row in [["Version", "Owner"], ["ID", "Hours"], ["A", 12]]:
        sheet.append(row)
    sheet.add_table(Table(displayName="Chosen", ref="A2:B3"))
    out = io.BytesIO()
    book.save(out)
    result = parse_structured(out.getvalue(), "explicit.xlsx", 10000)
    assert result["blocks"][0]["row_kind"] == "context"
    assert result["blocks"][2]["header_row"] == 2
    assert '"B Hours": "12"' in result["blocks"][2]["text"]
