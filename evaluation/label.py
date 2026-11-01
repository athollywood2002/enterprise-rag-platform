"""Offline, development-only PDF excerpt labeling. No parser or service calls."""

from __future__ import annotations

import argparse
import fcntl
import os
import re
import stat
import sys
import tempfile
import unicodedata
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

from pydantic import ValidationError

from evaluation.corpus import (
    CanonicalDocument,
    CorpusManifest,
    DevelopmentLabels,
    GoldQuestion,
    GoldSpan,
    corpus_sha256,
    find_page,
    load_corpus,
    load_development_labels,
    validate_gold,
)
from evaluation.spans import map_chunk

DEFAULT_OUTPUT = Path(".local/evaluation/development-labels.json")
MAX_JSON_BYTES = 16 * 1024 * 1024
_HOLDOUT_NAME = re.compile(r"(^|[^a-z0-9])(?:holdout|held[-_ ]?out)(?=$|[^a-z0-9])", re.IGNORECASE)


def checked_path(path: Path) -> Path:
    """Accidental-access guard, NOT a same-account secrecy boundary."""
    absolute = Path(os.path.abspath(path.expanduser()))
    if any(_HOLDOUT_NAME.search(part) or part.casefold() == ".git" for part in absolute.parts):
        raise ValueError("Holdout-named paths and Git metadata are refused")
    if any(part.is_symlink() for part in (absolute, *absolute.parents)):
        raise ValueError("Symlink paths are refused")
    return absolute


def read_json(path: Path) -> str:
    path = checked_path(path)
    if path.suffix.lower() != ".json":
        raise ValueError("Explicit .json input required")
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(path, flags), "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_JSON_BYTES:
            raise ValueError("Expected a bounded regular JSON file")
        data = stream.read(MAX_JSON_BYTES + 1)
    if len(data) > MAX_JSON_BYTES:
        raise ValueError("JSON size limit exceeded")
    return data.decode("utf-8", errors="strict")


def _terminal_text(text: str) -> str:
    if any(unicodedata.category(c) in {"Cc", "Cf"} for c in text):
        raise ValueError("Terminal control characters are unsupported; text was not rewritten")
    return text


def _require_pdf(corpus: CorpusManifest) -> None:
    if any(
        d.page_kind != "physical" or d.parser.profile != "unstructured-pdf-fast-v1"
        for d in corpus.documents
    ):
        raise ValueError("This helper supports PDF physical pages only")


def load_pdf_corpus(path: Path) -> CorpusManifest:
    corpus = load_corpus(read_json(path))
    _require_pdf(corpus)
    return corpus


def excerpt_span(document: CanonicalDocument, page: int, excerpt: str) -> GoldSpan:
    """Require one exact normalized occurrence; never guess among repeats."""
    if document.page_kind != "physical":
        raise ValueError("PDF physical pages only")
    location = map_chunk(document, page, excerpt)
    if location.status != "mapped" or location.start is None or location.end is None:
        raise ValueError(
            f"Excerpt mapping failed: {location.status}; use a longer canonical excerpt"
        )
    return GoldSpan(
        doc_id=document.doc_id,
        doc_version=document.doc_version,
        page=page,
        page_kind="physical",
        page_sha256=document.pages[page - 1].sha256,
        start=location.start,
        end=location.end,
        excerpt=location.text,
    )


def save_question(
    output: Path, corpus: CorpusManifest, question: GoldQuestion
) -> DevelopmentLabels:
    """Append one validated draft under a cooperative POSIX lock and atomic replace.

    Do not edit concurrently outside this CLI. Path checks are accidental-use
    guards, not protection from a hostile process running as the same OS user.
    """
    _require_pdf(corpus)
    if question.review_status != "draft":
        raise ValueError("The helper only creates drafts, not human-review claims")
    for span in question.spans:
        validate_gold(span, corpus)
    output = checked_path(output)
    if output.suffix.lower() != ".json":
        raise ValueError("Development output must use .json")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = checked_path(output.with_name(output.name + ".lock"))
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(lock_path, flags, 0o600), "a+b") as lock:
        if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode):
            raise ValueError("Expected a regular lock file")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        previous = read_json(output) if output.exists() else None
        existing = (
            load_development_labels(previous, corpus).questions if previous is not None else ()
        )
        labels = DevelopmentLabels(
            corpus_sha256=corpus_sha256(corpus), questions=(*existing, question)
        )
        # Revalidate serialized nested models too (model_copy/model_construct
        # can otherwise bypass Pydantic instance validators in direct API use).
        labels = load_development_labels(labels.model_dump_json(), corpus)
        payload = labels.model_dump_json(indent=2) + "\n"
        if len(payload.encode("utf-8")) > MAX_JSON_BYTES:
            raise ValueError("Label size limit exceeded")
        descriptor, name = tempfile.mkstemp(
            prefix=".development-labels-", suffix=".tmp", dir=output.parent
        )
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            checked_path(output)
            current = read_json(output) if output.exists() else None
            if current != previous:
                raise ValueError("Output changed during editing; refusing replacement")
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)  # Only this invocation's own staging file.
        return labels


def show_page(corpus: CorpusManifest, document: CanonicalDocument, page: int, out: TextIO) -> None:
    reference = find_page(corpus, document.doc_id, document.doc_version, page)
    print(f"Document: {_terminal_text(document.doc_id)}  Version: {document.doc_version}", file=out)
    print(
        f"Source: {_terminal_text(document.source.title)} ({_terminal_text(document.source.revision)})",
        file=out,
    )
    print(f"Physical page: {page}  SHA-256: {reference.sha256}", file=out)
    print("Canonical text (copy from here, not a PDF viewer):", file=out)
    print(_terminal_text(reference.text), file=out)


def _interactive_question(
    corpus: CorpusManifest, ask: Callable[[str], str], out: TextIO
) -> GoldQuestion:
    def choice(prompt: str, values: tuple[str, ...]) -> str:
        value = ask(f"{prompt} ({'/'.join(values)}; required): ").strip()
        if value not in values:
            raise ValueError(f"Explicit {prompt.lower()} choice required")
        return value

    def number(prompt: str) -> int:
        value = ask(prompt).strip()
        if len(value) > 9 or re.fullmatch(r"[1-9][0-9]*", value) is None:
            raise ValueError("Positive integer selection required")
        return int(value)

    query_id = ask("Query ID: ").strip()
    question = _terminal_text(ask("Question: ").strip())
    category = choice("Category", ("answerable", "near_miss", "off_topic"))
    query_type = choice("Question type", ("identifier", "semantic", "mixed"))
    difficulty = choice("Difficulty", ("easy", "medium", "hard"))
    tags = tuple(
        t.strip() for t in ask("Tags (comma separated; blank for none): ").split(",") if t.strip()
    )
    spans = []
    if category == "answerable":
        while True:
            for i, document in enumerate(corpus.documents, 1):
                print(f"[{i}] {_terminal_text(document.doc_id)}  {document.doc_version}", file=out)
            selected = number("Document number: ")
            if not 1 <= selected <= len(corpus.documents):
                raise ValueError("Document number outside corpus")
            document = corpus.documents[selected - 1]
            page = number("Physical page number: ")
            show_page(corpus, document, page, out)
            print("Paste supporting excerpt, then a line containing only . to finish:", file=out)
            lines = []
            length = 0
            while (line := ask("")) != ".":
                length += len(line) + 1
                if length > MAX_JSON_BYTES:
                    raise ValueError("Excerpt size limit exceeded")
                lines.append(line)
            spans.append(excerpt_span(document, page, "\n".join(lines)))
            if choice("Another supporting span", ("yes", "no")) == "no":
                break
    return GoldQuestion(
        query_id=query_id,
        question=question,
        category=category,
        query_type=query_type,
        difficulty=difficulty,
        tags=tags,
        spans=tuple(spans),
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    input_fn: Callable[[], str] = input,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    out, err = out or sys.stdout, err or sys.stderr
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("show", "add"):
        command = commands.add_parser(name)
        command.add_argument("--corpus", type=Path, required=True)
        command.add_argument("--split", choices=("development",), default="development")
        if name == "show":
            command.add_argument("--doc-id", required=True)
            command.add_argument("--doc-version", required=True)
            command.add_argument("--page", type=int, required=True)
        else:
            command.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)  # Reject holdout mode before any file access.
    saving = False
    try:
        source_path = checked_path(args.corpus)
        if args.command == "add":
            output_path = checked_path(args.output)
            if output_path.suffix.lower() != ".json":
                raise ValueError("Development output must use .json")
            if source_path == output_path or (
                output_path.exists() and os.path.samefile(source_path, output_path)
            ):
                raise ValueError("Corpus input and labels output must differ")
        corpus = load_pdf_corpus(source_path)
        if args.command == "show":
            document = next(
                (
                    d
                    for d in corpus.documents
                    if (d.doc_id, d.doc_version) == (args.doc_id, args.doc_version)
                ),
                None,
            )
            if document is None:
                raise ValueError("Unknown document version")
            show_page(corpus, document, args.page, out)
            return 0

        def ask(prompt: str) -> str:
            print(prompt, end="", file=out, flush=True)
            return input_fn()

        print(
            "Development PDF labels only. No holdout/encryption support or secrecy guarantee.",
            file=out,
        )
        question = _interactive_question(corpus, ask, out)
        print(
            f"Draft {question.query_id}: {len(question.spans)} supporting spans. No human-review status set.",
            file=out,
        )
        if ask("Save this development draft? Type yes to confirm: ").strip() != "yes":
            print("Cancelled; no labels saved.", file=out)
            return 0
        if corpus_sha256(load_pdf_corpus(source_path)) != corpus_sha256(corpus):
            raise ValueError("Corpus changed during labeling; reload before retrying")
        saving = True
        labels = save_question(output_path, corpus, question)
        print(f"Saved development draft. Total questions: {len(labels.questions)}.", file=out)
        return 0
    except (EOFError, KeyboardInterrupt, StopIteration):
        print(
            "Interrupted during save; inspect development output before retrying."
            if saving
            else "Cancelled; no labels saved.",
            file=err,
        )
        return 130
    except ValidationError:
        print(
            "Schema validation failed; no labels saved. Check references and required fields.",
            file=err,
        )
        return 2
    except (OSError, ValueError) as error:
        # No raw JSON/validation payload is echoed. OS errors may contain paths.
        message = "Local file operation failed" if isinstance(error, OSError) else str(error)
        suffix = "inspect development output before retrying" if saving else "no labels saved"
        print(f"{message}; {suffix}.", file=err)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
