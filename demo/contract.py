"""Small fixture-specific demo assertion, not a semantic quality evaluator."""

import csv
import re
from pathlib import Path

QUESTION = "What is the recovery code for demo-router-01 and which team owns it?"


def documents(folder: Path) -> list[dict[str, str]]:
    text = (folder / "runbook.txt").read_text(encoding="utf-8").strip()
    with (folder / "inventory.csv").open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, strict=True)
        if reader.fieldnames != ["asset", "owner", "location"]:
            raise ValueError("Expected CSV columns asset,owner,location")
        rows = list(reader)
    if not rows or len(rows) > 10:
        raise ValueError("Demo needs 1 to 10 inventory rows")
    records = []
    for index, row in enumerate(rows, 1):
        if set(row) != {"asset", "owner", "location"} or any(
            not isinstance(value, str) or not value.strip() for value in row.values()
        ):
            raise ValueError("Malformed or empty CSV cell")
        records.append(
            f"Inventory row {index}: "
            + "; ".join(f"{key}: {row[key].strip()}" for key in reader.fieldnames)
        )
    docs = [
        {"source": "runbook.txt", "text": text},
        {"source": "inventory.csv", "text": "\n".join(records)},
    ]
    if any(not doc["text"] or len(doc["text"]) > 700 for doc in docs):
        raise ValueError("Keep each synthetic demo document within 700 characters")
    return docs


def validate_answer(result: dict, docs: list[dict[str, str]]) -> None:
    answer = result.get("answer", "")
    if not isinstance(answer, str) or not all(
        re.search(rf"\b{word}\b", answer, re.IGNORECASE) for word in ("ORION", "NetworkOps")
    ):
        raise ValueError("Expected recovery code ORION and owner NetworkOps")
    if result.get("generation", {}).get("status") != "complete":
        raise ValueError("Generation did not complete")
    sources = result.get("sources", [])
    expected = {doc["source"]: " ".join(doc["text"].split()) for doc in docs}
    if len(sources) != 2 or {s.get("source") for s in sources} != set(expected):
        raise ValueError("Expected both fixture filenames as sources")
    for source in sources:
        if source.get("chunk") != 0 or source.get("text") != expected[source["source"]]:
            raise ValueError("Source payload does not match the ingested fixture")
    citations = [int(n) for n in re.findall(r"\[(\d+)\]", answer)]
    if not citations or any(n < 1 or n > len(sources) for n in citations):
        raise ValueError("Missing or out-of-range citations")
    if {sources[n - 1]["source"] for n in citations} != set(expected):
        raise ValueError("Answer must cite both the runbook and inventory")
