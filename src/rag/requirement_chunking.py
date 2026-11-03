"""Opt-in NIST-style requirement/page fragments, without a size-based split.

Within a 3.x family, Title elements beginning with 03.xx.xx and a name are boundaries.
REFERENCES, Source Controls and misleading titles inside sentences stay with the
preceding requirement. Page breaks are NEVER joined. Oversized page fragments are
intentional: inspect sizes/token budgets before indexing, never silently truncate.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal, Protocol

ChunkingStrategy = Literal["title", "nist-requirement-page-v1"]
NIST_REQUIREMENT_STRATEGY = "nist-requirement-page-v1"
NIST_REQUIREMENT_POLICY = (
    "nist-requirement-page-v1:heading-only:layout-separate:multipage=false:no-size-cap"
)
_HEADING = re.compile(r"^(03\.\d{2}\.\d{2})\s+[A-Za-z]")
_FAMILY = re.compile(r"^3\.\d+\.\s+\S")
_APPENDIX = re.compile(r"^Appendix [A-Z]\.")


class TextElement(Protocol):
    category: str

    def __str__(self) -> str: ...


@dataclass
class RequirementState:
    """Fresh per document; carries attribution, not text, across physical pages."""

    current: str | None = None
    seen: set[str] = field(default_factory=set)
    in_requirements: bool = False
    ended: bool = False


@dataclass(frozen=True)
class RequirementFragment:
    text: str
    requirement_id: str | None


def validate_chunking_strategy(strategy: str) -> None:
    if strategy not in ("title", NIST_REQUIREMENT_STRATEGY):
        raise ValueError("Unsupported chunking strategy")


def requirement_page_fragments(
    elements: Iterable[TextElement], state: RequirementState
) -> list[RequirementFragment]:
    """Partition a SINGLE page in source order, keeping every nonempty element.

    Headers/footers and family headings have separate unattributed fragments.
    A main References/Appendix title ends requirement attribution. Uppercase
    REFERENCES within a requirement does not. Table/inline/standalone identifiers
    are not headings. This is a pinned-parser grammar, not a universal NIST parser.
    """
    result: list[RequirementFragment] = []
    buffer: list[str] = []
    key: tuple[str, str | None] | None = None

    def flush() -> None:
        if buffer:
            result.append(RequirementFragment("\n\n".join(buffer), key[1] if key else None))
            buffer.clear()

    for element in elements:
        text = str(element).strip()
        if not text:
            continue
        category = element.category
        heading = (
            _HEADING.match(text)
            if category == "Title" and state.in_requirements and not state.ended
            else None
        )
        section = category == "Title" and (
            _FAMILY.match(text) or text == "References" or _APPENDIX.match(text)
        )
        if heading:
            flush()
            requirement_id = heading[1]
            if requirement_id in state.seen:
                raise ValueError("Duplicate requirement heading; inspect document/parser")
            state.seen.add(requirement_id)
            state.current = requirement_id
            next_key = ("body", requirement_id)
        elif section:
            flush()
            if not state.ended and _FAMILY.match(text):
                state.in_requirements = True
            if state.in_requirements and (text == "References" or _APPENDIX.match(text)):
                state.ended = True
                state.in_requirements = False
            state.current = None
            next_key = ("section", None)
        elif category in ("Header", "Footer"):
            next_key = ("layout", None)
        else:
            next_key = ("body", state.current)
        if next_key != key:
            flush()
            key = next_key
        buffer.append(text)
    flush()
    return result
