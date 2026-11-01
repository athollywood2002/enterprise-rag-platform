"""Bounded, fail-closed Hugo preparation. No file, network or canonicalization I/O."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Literal, Self

from pydantic import Field, model_validator

from evaluation.corpus import Digest, Nonempty, SourceRecord, StrictRecord

PREPROCESSOR_ID = "k8s-hugo-preprocess-v1"
MAX_SOURCE_BYTES = 131_072
CHANGES_NOTICE = (
    "Prepared by k8s-hugo-preprocess-v1: removed YAML frontmatter and standalone "
    "overview/body comment markers, replaced supported glossary_tooltip shortcodes "
    "with visible text, and normalized CRLF line endings to LF. "
    "Specification: docs/kubernetes-hugo-preprocessing.md."
)
_TOKEN = re.compile(r"\{\{([<%])(.*?)([>%])\}\}", re.DOTALL)
_NAME = re.compile(r"/?[A-Za-z][A-Za-z0-9_-]*")
_ATTRIBUTE = re.compile(r'\s+(text|term_id)="([^"\\\r\n]*)"')
_MARKER = re.compile(r"^[ \t]*<!--[ \t]*(overview|body)[ \t]*-->[ \t]*\n?$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


class ShortcodeCount(StrictRecord):
    name: Nonempty
    count: int = Field(ge=1)


class PreparationRecord(StrictRecord):
    preprocessor_id: Literal["k8s-hugo-preprocess-v1"] = PREPROCESSOR_ID
    raw_sha256: Digest
    doc_version: Digest | None
    title: str | None
    content_type: str | None
    status: Literal["accepted", "excluded"]
    shortcode_counts: tuple[ShortcodeCount, ...]
    recognized_markers: int = Field(ge=0)
    exclusions: tuple[Nonempty, ...]
    changes_notice: Literal[CHANGES_NOTICE] | None

    @model_validator(mode="after")
    def consistent_result(self) -> Self:
        accepted = self.status == "accepted"
        if (
            accepted != (self.doc_version is not None)
            or accepted != (self.changes_notice is not None)
            or accepted == bool(self.exclusions)
        ):
            raise ValueError("Preparation status/hash/exclusion mismatch")
        if accepted and (not self.title or not self.content_type):
            raise ValueError("Accepted preparation requires source metadata")
        names = [item.name for item in self.shortcode_counts]
        if names != sorted(set(names)) or list(self.exclusions) != sorted(set(self.exclusions)):
            raise ValueError("Preparation counts/reasons must be sorted and unique")
        return self


class PreparationManifest(StrictRecord):
    """Sidecar source record; acceptance is not a rights or labeling approval."""

    schema_version: Literal["k8s-hugo-preparation-v1"] = "k8s-hugo-preparation-v1"
    source: SourceRecord
    preparation: PreparationRecord

    @model_validator(mode="after")
    def retain_metadata_and_changes(self) -> Self:
        if self.preparation.title and self.source.title != self.preparation.title:
            raise ValueError("Source title differs from preserved frontmatter")
        if self.preparation.status == "accepted" and CHANGES_NOTICE not in self.source.attribution:
            raise ValueError("Attribution must indicate preprocessing changes")
        return self


@dataclass(frozen=True)
class PreparedMarkdown:
    record: PreparationRecord
    data: bytes | None

    def verify(self, raw: bytes) -> None:
        """Recompute rather than trusting supplied hashes or a prepared payload."""
        if prepare_kubernetes_markdown(raw) != self:
            raise ValueError("Prepared bytes/record differ from deterministic raw-source replay")


def _scalar(value: str) -> str:
    """Deliberately small YAML scalar subset for title/content_type only."""
    if value.startswith('"'):
        result = json.loads(value)  # JSON-compatible YAML double-quoted subset.
    elif value.startswith("'"):
        if not re.fullmatch(r"'(?:[^']|'')*'", value):
            raise ValueError("Unsupported quoted metadata")
        result = value[1:-1].replace("''", "'")
    else:
        if (
            not value
            or value[0] in "[]{}|>&*!%#@`"
            or " #" in value
            or value.lower() in {"null", "~", "true", "false", "yes", "no", "on", "off"}
            or re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", value)
        ):
            raise ValueError("Unsupported plain metadata")
        result = value
    if not isinstance(result, str) or not result.strip() or any(ord(c) < 32 for c in result):
        raise ValueError("Metadata must be a nonempty single-line string")
    return result


def _glossary(body: str) -> str:
    if not body.startswith("glossary_tooltip"):
        raise ValueError("Unsupported shortcode")
    cursor = len("glossary_tooltip")
    attrs: dict[str, str] = {}
    while cursor < len(body):
        match = _ATTRIBUTE.match(body, cursor)
        if match is None or match[1] in attrs:
            raise ValueError("Unsupported glossary attributes")
        attrs[match[1]] = match[2]
        cursor = match.end()
    if set(attrs) != {"text", "term_id"}:
        raise ValueError("Explicit text and term_id required; never infer a label")
    text = attrs["text"]
    if (
        not text
        or text != text.strip()
        or not all(c.isalnum() or c in " -.,:()/+" for c in text)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", attrs["term_id"])
    ):
        raise ValueError("Unsupported glossary visible text/term")
    return text


def _ambiguous_inline_template_context(line: str) -> bool:
    opened: re.Match[str] | None = None
    spans = []
    for run in re.finditer(r"`+", line):
        if opened is None:
            opened = run
        elif len(run[0]) == len(opened[0]):
            spans.append((opened.start(), run.end()))
            opened = None
    # Multiline/unclosed inline-code contexts are outside this supported subset.
    if opened is not None:
        return True
    index = 0
    for delimiter in re.finditer(r"\{\{|\}\}", line):
        while index < len(spans) and spans[index][1] <= delimiter.start():
            index += 1
        if index < len(spans) and spans[index][0] <= delimiter.start() < spans[index][1]:
            return True
    return False


def prepare_kubernetes_markdown(raw: bytes) -> PreparedMarkdown:
    """Return complete prepared bytes or NO bytes plus sorted exclusion reasons.

    Require leading YAML delimiters and explicit title/content_type. No includes,
    template evaluation, partial output, silent removal of unknown shortcodes or
    automatic source/permission discovery. Caller must review rights separately.
    """
    raw_hash = hashlib.sha256(raw).hexdigest()
    counts: Counter[str] = Counter()
    reasons: set[str] = set()
    metadata: dict[str, str] = {}
    recognized_markers = 0

    def finish(data: bytes | None) -> PreparedMarkdown:
        return PreparedMarkdown(
            PreparationRecord(
                raw_sha256=raw_hash,
                doc_version=hashlib.sha256(data).hexdigest() if data is not None else None,
                title=metadata.get("title"),
                content_type=metadata.get("content_type"),
                status="excluded" if reasons else "accepted",
                shortcode_counts=tuple(
                    ShortcodeCount(name=name, count=count) for name, count in sorted(counts.items())
                ),
                recognized_markers=recognized_markers,
                exclusions=tuple(sorted(reasons)),
                changes_notice=CHANGES_NOTICE if data is not None else None,
            ),
            data,
        )

    if len(raw) > MAX_SOURCE_BYTES:
        reasons.add("source_size_limit")
        return finish(None)
    try:
        text = raw.decode("utf-8", errors="strict").replace("\r\n", "\n")
    except UnicodeDecodeError:
        reasons.add("invalid_utf8")
        return finish(None)
    if any((ord(c) < 32 and c not in "\n\t") or ord(c) == 127 for c in text):
        reasons.add("unsupported_control_or_line_ending")
    lines = text.splitlines(keepends=True)
    if not lines or lines[0] != "---\n":
        reasons.add("missing_leading_frontmatter")
        return finish(None)
    closing = next((i for i in range(1, len(lines)) if lines[i].rstrip("\n") == "---"), None)
    if closing is None:
        reasons.add("unclosed_frontmatter")
        return finish(None)
    for line in lines[1:closing]:
        if re.match(r"^(['\"])(title|content_type)\1[ \t]*:", line):
            reasons.add("unsupported_metadata:quoted_key")
        match = re.match(r"^(title|content_type)[ \t]*:[ \t]*(.*?)\n?$", line)
        if match:
            key, value = match.groups()
            if key in metadata:
                reasons.add(f"duplicate_metadata:{key}")
                continue
            try:
                metadata[key] = _scalar(value)
            except (ValueError, TypeError):
                reasons.add(f"unsupported_metadata:{key}")
    for key in ("title", "content_type"):
        if key not in metadata:
            reasons.add(f"missing_metadata:{key}")
    if "content_type" in metadata and not re.fullmatch(
        r"[a-z][a-z0-9_-]*", metadata["content_type"]
    ):
        reasons.add("unsupported_metadata:content_type")

    # Flag code-context ambiguity rather than modifying shortcode examples.
    body_lines = lines[closing + 1 :]
    fence: str | None = None
    body = []
    for line in body_lines:
        in_code = fence is not None
        match = _FENCE.match(line)
        if match:
            ticks, rest = match.groups()
            if fence is None:
                fence = ticks
            elif ticks[0] == fence[0] and len(ticks) >= len(fence) and not rest.strip():
                fence = None
        if (
            (in_code or match is not None)
            and ("{{" in line or "}}" in line or _MARKER.fullmatch(line))
        ) or (not in_code and match is None and _ambiguous_inline_template_context(line)):
            reasons.add("template_or_marker_in_code_context")
        if _MARKER.fullmatch(line) and not in_code:
            recognized_markers += 1
        else:
            body.append(line)
    if fence is not None:
        reasons.add("unclosed_code_fence")
    body_text = "".join(body)

    def replace_token(match: re.Match[str]) -> str:
        opening, body, ending = match.groups()
        body = body.strip()
        name_match = _NAME.match(body)
        name = name_match[0] if name_match else "malformed"
        counts[name] += 1
        if opening != "<" or ending != ">" or name != "glossary_tooltip":
            reasons.add(f"unsupported_shortcode:{name}")
            return ""
        try:
            return _glossary(body)
        except ValueError:
            reasons.add("unsupported_shortcode:glossary_tooltip")
            return ""

    # Scan non-overlapping template extents once. A page full of unclosed
    # openers must not repeatedly regex-search the entire remaining suffix.
    pieces = []
    cursor = 0
    while (start := body_text.find("{{", cursor)) != -1:
        end = body_text.find("}}", start + 2)
        if end == -1:
            break
        pieces.append(body_text[cursor:start])
        token = body_text[start : end + 2]
        match = _TOKEN.fullmatch(token)
        pieces.append(replace_token(match) if match is not None else token)
        cursor = end + 2
    pieces.append(body_text[cursor:])
    prepared = "".join(pieces)
    if "{{" in prepared or "}}" in prepared:
        reasons.add("unresolved_template_delimiter")
    if not prepared.strip():
        reasons.add("empty_prepared_body")
    return finish(None if reasons else prepared.encode("utf-8"))
