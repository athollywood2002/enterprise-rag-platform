"""Synthetic manifests and simulated owner keystrokes only; no real annotation."""

import io
import json
import stat
import unicodedata
from pathlib import Path
from unittest.mock import Mock

import pytest

from evaluation import label
from evaluation.canonical import MARKDOWN_PINS, PARSER_PINS, normalize, text_sha256
from evaluation.corpus import (
    CanonicalDocument,
    CanonicalPage,
    CorpusManifest,
    GoldQuestion,
    Package,
    ParserIdentity,
    SourceRecord,
    load_development_labels,
)


def test_retry_choices_numbers_and_excerpt_preserves_prior_answers(files, corpus):
    source, output = files
    answers = [
        "q-retry",
        "Which synthetic flag?",
        "wrong",
        "ANSWERABLE",
        "IDENTIFIER",
        "Medium",
        "",
        "0",
        "2",
        "1",
        "nope",
        "3",
        "1",
        "beta",
        ".",
        "missing",
        ".",
        "",
        ".",
        "Café 😀 uses --max-pods.",
        ".",
        "NO",
        "YES",
    ]
    code, out, err = invoke(["add", "--corpus", str(source), "--output", str(output)], answers)
    assert code == 0 and not err
    question = load_development_labels(output.read_text(), corpus).questions[0]
    assert question.query_id == "q-retry" and question.difficulty == "medium"
    assert question.spans[0].excerpt == "Café 😀 uses --max-pods."
    assert "ambiguous; matches: 2" in out and "unlocatable; matches: 0" in out
    assert out.count("Query ID:") == out.count("Question:") == 1
    assert out.count("Document number:") == 3
    assert out.count("Physical page number:") == 3
    assert out.count("retry this span only") == 3


def test_duplicate_id_checked_before_question_with_next_free_suggestion(files, corpus):
    source, output = files
    args = ["add", "--corpus", str(source), "--output", str(output)]
    assert invoke(args, answerable("dev-0001"))[0] == 0
    code, out, _ = invoke(args, ["dev-0001"])
    assert code == 130 and "next free suggestion: dev-0002" in out
    assert "Question:" not in out
    answers = ["dev-0001", *answerable("dev-0002")]
    assert invoke(args, answers)[0] == 0
    assert [q.query_id for q in load_development_labels(output.read_text(), corpus).questions] == [
        "dev-0001",
        "dev-0002",
    ]


def test_retry_second_span_keeps_first_and_rejects_overlap(files, corpus):
    source, output = files
    answers = answerable()[:-2] + [
        "yes",
        "1",
        "1",
        "Café 😀",
        ".",
        "missing",
        ".",
        "Alpha beta beta.",
        ".",
        "no",
        "yes",
    ]
    code, out, _ = invoke(["add", "--corpus", str(source), "--output", str(output)], answers)
    assert code == 0
    spans = load_development_labels(output.read_text(), corpus).questions[0].spans
    assert [s.excerpt for s in spans] == ["Café 😀 uses --max-pods.", "Alpha beta beta."]
    assert "overlapping supporting span" in out
    assert out.count("Question:") == 1


def test_invalid_id_question_and_tags_retry_without_echoing(files, corpus):
    source, output = files
    answers = [
        "bad/id",
        "q1",
        "",
        "A synthetic question?",
        "off_topic",
        "semantic",
        "easy",
        "bad/tag",
        "tag,tag",
        "valid",
        "yes",
    ]
    code, out, err = invoke(["add", "--corpus", str(source), "--output", str(output)], answers)
    assert code == 0 and not err
    assert "bad/id" not in out and "bad/tag" not in out
    assert load_development_labels(output.read_text(), corpus).questions[0].tags == ("valid",)


def test_display_wrap_is_copyable_without_changing_canonical_identity(corpus):
    original = corpus.documents[0]
    text = normalize(("Synthetic context --max-pods AC-2(4) " * 12) + "unique final excerpt.")
    page = CanonicalPage(page=1, text=text, sha256=text_sha256(text))
    document = CanonicalDocument(**{**original.model_dump(), "pages": (page,)})
    manifest = CorpusManifest(documents=(document,))
    before = manifest.model_dump_json()
    out = io.StringIO()
    label.show_page(manifest, document, 1, out)
    displayed = out.getvalue().split("Canonical text (copy from here, not a PDF viewer):\n")[1]
    assert len(displayed.splitlines()) > 1
    assert all(len(line) <= 88 for line in displayed.splitlines())
    assert normalize(displayed) == text
    assert "--max-\npods" not in displayed and "AC-\n2" not in displayed
    span = label.excerpt_span(document, 1, displayed)
    assert (span.start, span.end, span.page_sha256) == (0, len(text), page.sha256)
    assert manifest.model_dump_json() == before


def test_display_never_breaks_long_identifiers(corpus):
    original = corpus.documents[0]
    identifier = "--" + "synthetic-" * 15
    text = normalize("before " + identifier + " after")
    page = CanonicalPage(page=1, text=text, sha256=text_sha256(text))
    document = CanonicalDocument(**{**original.model_dump(), "pages": (page,)})
    out = io.StringIO()
    label.show_page(CorpusManifest(documents=(document,)), document, 1, out)
    assert identifier in out.getvalue().splitlines()


def test_duplicate_introduced_during_prompt_is_still_rejected_at_save(files, corpus):
    source, output = files
    args = ["add", "--corpus", str(source), "--output", str(output)]
    answers = iter(answerable())

    def answer():
        value = next(answers)
        if value == "yes":
            assert invoke(args, answerable())[0] == 0
        return value

    code = label.main(args, input_fn=answer, out=io.StringIO(), err=io.StringIO())
    assert code == 2
    assert len(load_development_labels(output.read_text(), corpus).questions) == 1


@pytest.fixture
def corpus():
    texts = ("Café 😀 uses --max-pods. Alpha beta beta.", "Second physical page has a unique fact.")
    doc = CanonicalDocument(
        doc_id="synthetic",
        doc_version=text_sha256("authored synthetic version"),
        source=SourceRecord(
            title="Authored test PDF",
            canonical_url="urn:synthetic:label-cli",
            revision="1",
            license_id="MIT",
            attribution="Repository test authors",
            redistribution="redistributable",
        ),
        parser=ParserIdentity(
            packages=tuple(Package(name=n, version=v) for n, v in PARSER_PINS),
            unicode_version=unicodedata.unidata_version,
        ),
        pages=tuple(
            CanonicalPage(page=i, text=normalize(t), sha256=text_sha256(normalize(t)))
            for i, t in enumerate(texts, 1)
        ),
    )
    return CorpusManifest(documents=(doc,))


@pytest.fixture
def files(tmp_path, corpus):
    source = tmp_path / "corpus.json"
    source.write_text(corpus.model_dump_json())
    return source, tmp_path / "development.json"


def invoke(args, answers=()):
    iterator = iter(answers)
    out, err = io.StringIO(), io.StringIO()
    code = label.main(args, input_fn=lambda: next(iterator), out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def answerable(query_id="q1", *, another=False):
    answers = [
        query_id,
        "Which synthetic flag?",
        "answerable",
        "identifier",
        "easy",
        "synthetic,flags",
        "1",
        "1",
        "Cafe\u0301 😀 uses --max-pods.",
        ".",
        "yes" if another else "no",
    ]
    if another:
        answers += ["1", "2", "Second physical page has a unique fact.", ".", "no"]
    return answers + ["yes"]


def test_show_displays_exact_canonical_page_without_writing(files, corpus):
    source, output = files
    doc = corpus.documents[0]
    code, out, err = invoke(
        [
            "show",
            "--corpus",
            str(source),
            "--doc-id",
            doc.doc_id,
            "--doc-version",
            doc.doc_version,
            "--page",
            "1",
        ]
    )
    assert code == 0 and not err
    assert doc.pages[0].text in out and doc.pages[0].sha256 in out
    assert "Physical page: 1" in out and "copy from here" in out
    assert not output.exists()
    assert sorted(p.name for p in source.parent.iterdir()) == ["corpus.json"]


def test_add_multispan_draft_roundtrip_explicit_strata_and_private_permissions(files, corpus):
    source, output = files
    code, out, err = invoke(
        ["add", "--corpus", str(source), "--output", str(output)], answerable(another=True)
    )
    assert code == 0 and not err
    saved = load_development_labels(output.read_text(), corpus)
    question = saved.questions[0]
    assert saved.split == "development" and question.review_status == "draft"
    assert question.query_type == "identifier" and question.difficulty == "easy"
    assert question.tags == ("synthetic", "flags")
    assert len(question.spans) == 2 and question.spans[0].start == 0
    assert question.spans[0].excerpt == "Café 😀 uses --max-pods."
    assert question.spans[1].page == 2
    assert "Question type" in out and "Difficulty" in out
    assert corpus.documents[0].pages[0].text in out
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert stat.S_IMODE(output.with_name(output.name + ".lock").stat().st_mode) == 0o600


def test_append_valid_development_question_and_preserve_previous(files, corpus):
    source, output = files
    args = ["add", "--corpus", str(source), "--output", str(output)]
    assert invoke(args, answerable())[0] == 0
    first = load_development_labels(output.read_text(), corpus).questions[0]
    answers = ["q2", "Absent synthetic topic?", "off_topic", "semantic", "hard", "", "yes"]
    assert invoke(args, answers)[0] == 0
    saved = load_development_labels(output.read_text(), corpus)
    assert saved.questions[0] == first and saved.questions[1].spans == ()


@pytest.mark.parametrize("category", ["near_miss", "off_topic"])
def test_unknown_categories_do_not_request_or_create_gold(files, corpus, category):
    source, output = files
    answers = ["q1", "Absent fact?", category, "semantic", "medium", "", "yes"]
    code, out, _ = invoke(["add", "--corpus", str(source), "--output", str(output)], answers)
    assert code == 0 and "Paste supporting excerpt" not in out
    assert load_development_labels(output.read_text(), corpus).questions[0].spans == ()


@pytest.mark.parametrize(
    "excerpt,status", [("", "empty"), ("missing", "unlocatable"), ("beta", "ambiguous")]
)
def test_excerpt_requires_exactly_one_match(corpus, excerpt, status):
    with pytest.raises(ValueError, match=status):
        label.excerpt_span(corpus.documents[0], 1, excerpt)


def test_unicode_offsets_are_codepoints_and_hash_bound(corpus):
    span = label.excerpt_span(corpus.documents[0], 1, "😀")
    assert span.end - span.start == 1
    assert span.page_sha256 == corpus.documents[0].pages[0].sha256


@pytest.mark.parametrize("index", [3, 4])
def test_type_and_difficulty_never_silently_default(files, index):
    source, output = files
    answers = answerable()
    answers.insert(index, "")
    code, out, _ = invoke(["add", "--corpus", str(source), "--output", str(output)], answers)
    assert code == 0 and output.exists()
    assert "choice required; try again" in out


@pytest.mark.parametrize("answers", [[], answerable()[:-1], answerable()[:-1] + ["no"]])
def test_eof_or_declined_confirmation_never_saves(files, answers):
    source, output = files
    code, _, _ = invoke(["add", "--corpus", str(source), "--output", str(output)], answers)
    assert code in (0, 130) and not output.exists()
    assert not output.with_name(output.name + ".lock").exists()


@pytest.mark.parametrize("layout", ["repo", "worktree"])
def test_holdout_split_is_rejected_before_any_reads_or_writes(tmp_path, monkeypatch, layout):
    root = tmp_path / layout
    root.mkdir()
    if layout == "repo":
        (root / ".git").mkdir()
    else:
        (root / ".git").write_text("gitdir: not-accessed\n")
    forbidden = Mock(side_effect=AssertionError("No holdout I/O permitted"))
    monkeypatch.setattr(label, "read_json", forbidden)
    monkeypatch.setattr(label, "save_question", forbidden)
    with pytest.raises(SystemExit) as error:
        invoke(
            [
                "add",
                "--corpus",
                str(root / "holdout.json"),
                "--output",
                str(root / "labels.json"),
                "--split",
                "holdout",
            ]
        )
    assert error.value.code == 2
    forbidden.assert_not_called()
    assert not (root / "labels.json").exists()


@pytest.mark.parametrize("name", ["holdout.json", "heldout.json", "held-out.json", "HELD_OUT.json"])
def test_holdout_named_paths_are_refused_without_reading(tmp_path, monkeypatch, name):
    forbidden = Mock(side_effect=AssertionError("Must not open forbidden path"))
    monkeypatch.setattr(label, "read_json", forbidden)
    code, _, _ = invoke(
        ["add", "--corpus", str(tmp_path / name), "--output", str(tmp_path / "dev.json")]
    )
    assert code == 2
    forbidden.assert_not_called()


def test_holdout_named_output_is_refused_before_corpus_read(files, monkeypatch):
    source, _ = files
    forbidden = Mock(side_effect=AssertionError("Output preflight first"))
    monkeypatch.setattr(label, "read_json", forbidden)
    assert (
        invoke(["add", "--corpus", str(source), "--output", str(source.parent / "holdout.json")])[0]
        == 2
    )
    forbidden.assert_not_called()


@pytest.mark.parametrize("which", ["input", "output", "parent"])
def test_symlink_paths_are_refused(files, tmp_path, which):
    source, output = files
    if which == "input":
        link = tmp_path / "source-link.json"
        link.symlink_to(source)
        source = link
    elif which == "output":
        output.symlink_to(tmp_path / "absent.json")
    else:
        directory = tmp_path / "linked"
        directory.symlink_to(tmp_path, target_is_directory=True)
        output = directory / "dev.json"
    code, _, _ = invoke(["add", "--corpus", str(source), "--output", str(output)], answerable())
    assert code == 2 and not (tmp_path / "absent.json").exists()


def test_corpus_cannot_be_output(files):
    source, _ = files
    original = source.read_bytes()
    assert invoke(["add", "--corpus", str(source), "--output", str(source)], answerable())[0] == 2
    assert source.read_bytes() == original


@pytest.mark.parametrize("mutation", ["invalid", "holdout", "drift", "duplicate"])
def test_existing_invalid_or_incompatible_data_is_never_replaced(files, corpus, mutation):
    source, output = files
    args = ["add", "--corpus", str(source), "--output", str(output)]
    if mutation == "invalid":
        output.write_text("owner-authored unrelated content")
    else:
        assert invoke(args, answerable())[0] == 0
        obj = json.loads(output.read_text())
        if mutation == "holdout":
            obj["split"] = "heldout"
        elif mutation == "drift":
            obj["corpus_sha256"] = "0" * 64
        output.write_text(json.dumps(obj))
    before = output.read_bytes()
    assert invoke(args, ["q1"] if mutation == "duplicate" else answerable())[0] == (
        130 if mutation == "duplicate" else 2
    )
    assert output.read_bytes() == before


def test_atomic_replace_failure_preserves_previous_data_and_removes_own_staging(files, monkeypatch):
    source, output = files
    args = ["add", "--corpus", str(source), "--output", str(output)]
    assert invoke(args, answerable())[0] == 0
    before = output.read_bytes()
    monkeypatch.setattr(label.os, "replace", Mock(side_effect=OSError("simulated failure")))
    assert invoke(args, answerable("q2"))[0] == 2
    assert output.read_bytes() == before
    assert not list(output.parent.glob(".development-labels-*.tmp"))


def test_default_output_is_development_only_and_ignored(files, monkeypatch):
    source, _ = files
    monkeypatch.chdir(source.parent)
    assert invoke(["add", "--corpus", str(source)], answerable())[0] == 0
    assert label.DEFAULT_OUTPUT.name == "development-labels.json"
    assert label.DEFAULT_OUTPUT.exists()
    ignore = (Path(__file__).resolve().parents[1] / ".gitignore").read_text()
    assert "/.local/evaluation/" in ignore


def test_logical_markdown_corpus_is_explicitly_not_supported(files, corpus):
    source, _ = files
    original = corpus.documents[0]
    parser = ParserIdentity(
        profile="unstructured-markdown-v1",
        packages=tuple(Package(name=n, version=v) for n, v in MARKDOWN_PINS),
        unicode_version=unicodedata.unidata_version,
    )
    markdown = CanonicalDocument(
        **{
            **original.model_dump(),
            "parser": parser,
            "page_kind": "logical",
            "pages": (original.pages[0],),
        }
    )
    source.write_text(CorpusManifest(documents=(markdown,)).model_dump_json())
    with pytest.raises(ValueError, match="PDF physical pages only"):
        label.load_pdf_corpus(source)
    question = GoldQuestion(
        query_id="q1",
        question="Absent?",
        category="off_topic",
        query_type="semantic",
        difficulty="easy",
    )
    output = source.parent / "dev.json"
    with pytest.raises(ValueError, match="PDF physical pages only"):
        label.save_question(output, CorpusManifest(documents=(markdown,)), question)
    assert not output.exists()


def test_terminal_controls_are_refused_not_rewritten(files, corpus):
    source, _ = files
    doc = corpus.documents[0]
    text = "Synthetic\x1b[31mcontrol"
    page = CanonicalPage(page=1, text=text, sha256=text_sha256(text))
    changed = CanonicalDocument(**{**doc.model_dump(), "pages": (page,)})
    source.write_text(CorpusManifest(documents=(changed,)).model_dump_json())
    code, out, _ = invoke(
        [
            "show",
            "--corpus",
            str(source),
            "--doc-id",
            doc.doc_id,
            "--doc-version",
            doc.doc_version,
            "--page",
            "1",
        ]
    )
    assert code == 2 and "\x1b" not in out


def test_save_revalidates_forged_nested_question_before_writing(files, corpus):
    _, output = files
    question = GoldQuestion(
        query_id="q1",
        question="Absent?",
        category="off_topic",
        query_type="semantic",
        difficulty="easy",
    )
    forged = question.model_copy(update={"question": " "})
    with pytest.raises(ValueError):
        label.save_question(output, corpus, forged)
    assert not output.exists()


def test_helper_never_creates_human_review_status(files, corpus):
    _, output = files
    question = GoldQuestion(
        query_id="q1",
        question="Absent?",
        category="off_topic",
        query_type="semantic",
        difficulty="easy",
        review_status="human_reviewed",
    )
    with pytest.raises(ValueError, match="only creates drafts"):
        label.save_question(output, corpus, question)
    assert not output.exists()


def test_interruption_after_atomic_commit_does_not_claim_nothing_was_saved(
    files, monkeypatch, corpus
):
    source, output = files
    replace = label.os.replace

    def interrupt_after_commit(*args):
        replace(*args)
        raise KeyboardInterrupt

    monkeypatch.setattr(label.os, "replace", interrupt_after_commit)
    code, _, err = invoke(["add", "--corpus", str(source), "--output", str(output)], answerable())
    assert code == 130 and "inspect development output" in err
    assert "no labels saved" not in err
    assert len(load_development_labels(output.read_text(), corpus).questions) == 1


def test_busy_cooperative_lock_fails_without_overwriting(files, monkeypatch):
    source, output = files
    args = ["add", "--corpus", str(source), "--output", str(output)]
    assert invoke(args, answerable())[0] == 0
    before = output.read_bytes()
    monkeypatch.setattr(label.fcntl, "flock", Mock(side_effect=BlockingIOError("busy")))
    assert invoke(args, answerable("q2"))[0] == 2
    assert output.read_bytes() == before


def test_lock_symlink_is_refused_and_target_untouched(files):
    source, output = files
    target = source.parent / "owner.txt"
    target.write_text("unrelated owner work")
    output.with_name(output.name + ".lock").symlink_to(target)
    assert invoke(["add", "--corpus", str(source), "--output", str(output)], answerable())[0] == 2
    assert not output.exists() and target.read_text() == "unrelated owner work"


@pytest.mark.parametrize("metadata", [".git", ".GIT"])
def test_git_metadata_output_is_refused_before_read(files, monkeypatch, metadata):
    source, _ = files
    forbidden = Mock(side_effect=AssertionError("No source read after bad output path"))
    monkeypatch.setattr(label, "read_json", forbidden)
    assert (
        invoke(
            ["add", "--corpus", str(source), "--output", str(source.parent / metadata / "dev.json")]
        )[0]
        == 2
    )
    forbidden.assert_not_called()


def test_oversized_input_fails_before_json_decode(files, monkeypatch):
    source, _ = files
    monkeypatch.setattr(label, "MAX_JSON_BYTES", 10)
    with pytest.raises(ValueError, match="bounded regular JSON file"):
        label.read_json(source)


def test_invalid_numeric_input_is_not_echoed(files):
    source, output = files
    answers = answerable()
    answers.insert(6, "private-paste-not-a-number")
    code, out, err = invoke(["add", "--corpus", str(source), "--output", str(output)], answers)
    assert code == 0 and output.exists()
    assert "private-paste-not-a-number" not in out + err


def test_non_json_output_is_refused_before_source_read(files, monkeypatch):
    source, _ = files
    forbidden = Mock(side_effect=AssertionError("Must preflight output before input read"))
    monkeypatch.setattr(label, "read_json", forbidden)
    assert (
        invoke(["add", "--corpus", str(source), "--output", str(source.parent / "notes.txt")])[0]
        == 2
    )
    forbidden.assert_not_called()


def test_non_json_input_is_refused(files):
    source, _ = files
    with pytest.raises(ValueError, match="Explicit .json"):
        label.read_json(source.parent / "unrelated.txt")


def test_corpus_changed_while_prompting_aborts_before_save(files):
    source, output = files
    answers = iter(answerable())

    def answer():
        value = next(answers)
        if value == "yes":
            obj = json.loads(source.read_text())
            obj["documents"][0]["source"]["revision"] = "changed-during-prompt"
            source.write_text(json.dumps(obj))
        return value

    out, err = io.StringIO(), io.StringIO()
    assert (
        label.main(
            ["add", "--corpus", str(source), "--output", str(output)],
            input_fn=answer,
            out=out,
            err=err,
        )
        == 2
    )
    assert "Corpus changed" in err.getvalue()
    assert not output.exists() and not output.with_name(output.name + ".lock").exists()
