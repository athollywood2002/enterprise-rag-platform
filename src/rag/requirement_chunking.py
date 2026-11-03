"""Opt-in bounded, conservative sentence/page fragments with layout diagnostics."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal, Protocol

ChunkingStrategy = Literal["title", "nist-requirement-page-v2"]
NIST_REQUIREMENT_STRATEGY = "nist-requirement-page-v2"
TARGET_CHARACTERS = 1200
MAX_CHARACTERS = 2400
NIST_REQUIREMENT_POLICY = (
    "nist-requirement-page-v2:conservative-sentence-v1:target=1200:max=2400:"
    "layout-diagnostic-only:multipage=false"
)
_HEADING = re.compile(r"^(03\.\d{2}\.\d{2})\s+[A-Za-z]")
_FAMILY = re.compile(r"^3\.\d+\.\s+\S")
_APPENDIX = re.compile(r"^Appendix [A-Z]\.")
PINNED_NIST_SHA256 = "3e4631df8b5d61f40a6e542b52779ef30ddbbfff31e09214fa94ad6e6f5e6d08"
PINNED_HEADINGS_SHA256 = "6ac4ea0f53817c72786ef34ab123246c867aeb5b308754d3b067bccc9e5676c9"
_FAMILY_COUNTS = (22, 3, 9, 12, 12, 5, 6, 9, 2, 8, 4, 5, 16, 8, 3, 3, 3)
PINNED_REQUIREMENT_IDS = frozenset(
    f"03.{family:02}.{number:02}"
    for family, count in enumerate(_FAMILY_COUNTS, 1)
    for number in range(1, count + 1)
)
_ABBREVIATIONS = frozenset(
    (
        "e.g.",
        "i.e.",
        "etc.",
        "fig.",
        "sec.",
        "no.",
        "dr.",
        "mr.",
        "mrs.",
        "vs.",
        "al.",
        "rev.",
        "vol.",
        "ed.",
        "eds.",
        "pp.",
        "ch.",
        "pub.",
        "approx.",
        "dept.",
        "inc.",
        "corp.",
        "ltd.",
        "jr.",
        "sr.",
    )
)


def sentence_units(text: str) -> list[str]:
    """Conservative terminal-punctuation splits, retaining source substrings.

    Paragraphs, titles, semicolons and line wraps are NOT sentence boundaries.
    Protect dotted IDs, decimals, initials, list labels and common abbreviations.
    Ambiguous/no-punctuation units stay intact and can fail the hard bound.
    This grammar is intentionally narrower than a general NLP sentence detector.
    """
    starts = [0]
    for match in re.finditer(r'[.!?][\)\]"\u201d\u2019]*\s+(?=\S)', text):
        end = match.start() + 1
        if text[match.start()] == ".":
            token = text[:end].rsplit(None, 1)[-1].lower().lstrip('([{"\u201c\u2018')
            if (
                token in _ABBREVIATIONS
                or re.fullmatch(r"(?:[a-z]\.)+", token)
                or re.fullmatch(r"\d+(?:\.\d+)*\.", token)
            ):
                continue
        starts.append(match.end())
    ends = starts[1:] + [len(text)]
    return [text[a:b].strip() for a, b in zip(starts, ends) if text[a:b].strip()]


def bounded_fragments(fragment: RequirementFragment) -> list[RequirementFragment]:
    """Greedily pack complete units; retain a REFERENCES tail as one unit.

    1,200 is a target, 2,400 a hard raw-character bound. Indivisible sentences,
    tables or reference tails above target remain whole up to the hard limit.
    Above the hard limit reject the document: never truncate or silently drop.
    """
    if not fragment.indexable:
        return [fragment]
    text = fragment.text
    reference = re.search(r"(?m)^REFERENCES\s*$", text)
    body = text[: reference.start()].rstrip() if reference else text
    units = sentence_units(body)
    if reference:
        units.append(text[reference.start() :].strip())
    result = []
    buffer = ""
    for unit in units:
        if len(unit) > MAX_CHARACTERS:
            raise ValueError("Indivisible sentence/table/reference tail exceeds 2400 characters")
        candidate = f"{buffer}\n\n{unit}" if buffer else unit
        if buffer and len(candidate) > TARGET_CHARACTERS:
            result.append(RequirementFragment(buffer, fragment.requirement_id))
            buffer = unit
        else:
            buffer = candidate
    if buffer:
        result.append(RequirementFragment(buffer, fragment.requirement_id))
    return result


class TextElement(Protocol):
    category: str

    def __str__(self) -> str: ...


@dataclass
class RequirementState:
    """Fresh per document; carries attribution, not text, across physical pages."""

    current: str | None = None
    seen: set[str] = field(default_factory=set)
    headings: list[str] = field(default_factory=list)
    in_requirements: bool = False
    ended: bool = False


@dataclass(frozen=True)
class RequirementFragment:
    text: str
    requirement_id: str | None
    indexable: bool = True


def validate_requirement_identity(state: RequirementState, source_sha256: str) -> None:
    if not state.seen:
        raise ValueError("No supported requirement headings; use the default title strategy")
    if source_sha256 == PINNED_NIST_SHA256 and (
        state.seen != PINNED_REQUIREMENT_IDS
        or len(state.headings) != 130
        or hashlib.sha256("\n".join(state.headings).encode()).hexdigest() != PINNED_HEADINGS_SHA256
    ):
        raise ValueError("Pinned NIST heading identity drift: expected 130 exact ordered headings")


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
            result.extend(
                bounded_fragments(
                    RequirementFragment(
                        "\n\n".join(buffer),
                        key[1] if key else None,
                        indexable=key is not None and key[0] == "body",
                    )
                )
            )
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
            state.headings.append(" ".join(text.split()))
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
