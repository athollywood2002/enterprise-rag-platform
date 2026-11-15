"""Mechanical citation diagnostics only; valid IDs never establish claim entailment."""

import re


def citation_ids(answer: str) -> list[int]:
    """Recognize numeric, grouped, citation-prefixed and bold numeric markers.

    A paragraph/page qualifier is a location, not another citation ID. Bare prose
    numbers and Markdown links are not citations. Unknown syntax needs review.
    """
    found = []
    for marker in re.finditer(r"\[([^\[\]\n]{1,200})\](?!\()", answer):
        content = marker[1].replace("*", "").strip()
        match = re.fullmatch(
            r"(?:citation\s+)?(\d{1,9}(?:\s*,\s*\d{1,9})*)"
            r"(?:\s*,\s*(?:paragraph|page)\s+\d+)?",
            content,
            re.IGNORECASE,
        )
        if match:
            found.extend(int(value) for value in re.findall(r"\d+", match[1]))
    return found


def citation_diagnostics(answer: str, sources: list[dict]) -> dict:
    ids = citation_ids(answer)
    return {
        "cited_ids": ids,
        "out_of_range_ids": sorted({i for i in ids if not 1 <= i <= len(sources)}),
        "uncited_ids": [i for i in range(1, len(sources) + 1) if i not in ids],
        "visible_empty": not answer.strip(),
        "claim_support_verified": False,
        "semantic_review_required": True,
    }
