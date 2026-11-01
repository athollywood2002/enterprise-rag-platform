"""Authored synthetic Hugo only: no source acquisition or real labels in tests."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from evaluation.corpus import SourceRecord
from evaluation.kubernetes_hugo import (
    CHANGES_NOTICE,
    MAX_SOURCE_BYTES,
    PREPROCESSOR_ID,
    PreparationManifest,
    prepare_kubernetes_markdown,
)


def source_bytes(
    body="Synthetic body.\n", metadata="title: Synthetic pods\ncontent_type: concept\n"
):
    return ("---\n" + metadata + "---\n" + body).encode()


def citation(attribution=CHANGES_NOTICE):
    return SourceRecord(
        title="Synthetic pods",
        canonical_url="urn:synthetic:hugo",
        revision="synthetic-v1",
        license_id="MIT",
        attribution=attribution,
        redistribution="redistributable",
    )


def test_deterministic_transformation_metadata_hashes_and_replay():
    raw = source_bytes(
        "<!-- overview -->\n# Synthetic pods\n\n"
        'Use {{< glossary_tooltip text="containers" term_id="container" >}}.\n'
        "<!-- body -->\n\n```sh\nkubectl get pods --max-pods=110\n```\n"
        "<!-- other comment remains unchanged -->\n",
        'reviewers:\n- synthetic-author\ntitle: "Synthetic pods"\n'
        "nested:\n  title: not-the-title\ncontent_type: concept\nweight: 10\n",
    )
    result = prepare_kubernetes_markdown(raw)
    assert result.data == (
        b"# Synthetic pods\n\nUse containers.\n\n```sh\nkubectl get pods --max-pods=110\n```\n"
        b"<!-- other comment remains unchanged -->\n"
    )
    assert result.record.preprocessor_id == PREPROCESSOR_ID
    assert result.record.title == "Synthetic pods"
    assert result.record.content_type == "concept"
    assert result.record.recognized_markers == 2
    assert result.record.raw_sha256 == hashlib.sha256(raw).hexdigest()
    assert result.record.doc_version == hashlib.sha256(result.data).hexdigest()
    assert result.record.doc_version != result.record.raw_sha256
    assert [(c.name, c.count) for c in result.record.shortcode_counts] == [("glossary_tooltip", 1)]
    assert result == prepare_kubernetes_markdown(raw)
    result.verify(raw)
    with pytest.raises(ValueError, match="replay"):
        replace(result, data=b"forged").verify(raw)
    with pytest.raises(ValueError, match="replay"):
        result.verify(raw + b"changed")


@pytest.mark.parametrize(
    "token",
    [
        '{{< glossary_tooltip text="API server" term_id="api-server" >}}',
        '{{< glossary_tooltip term_id="api-server" text="API server" >}}',
        '{{< glossary_tooltip\n text="API server"\n term_id="api-server" >}}',
    ],
)
def test_supported_glossary_attribute_order_and_wrapping(token):
    result = prepare_kubernetes_markdown(source_bytes("Before " + token + " after.\n"))
    assert result.data == b"Before API server after.\n"


@pytest.mark.parametrize(
    "token",
    [
        '{{< glossary_tooltip term_id="node" >}}',
        '{{< glossary_tooltip text="node" >}}',
        '{{< glossary_tooltip text="node" text="other" term_id="node" >}}',
        '{{< glossary_tooltip text="node" term_id="node" extra="unknown" >}}',
        "{{< glossary_tooltip text='node' term_id='node' >}}",
        '{{% glossary_tooltip text="node" term_id="node" %}}',
        '{{< glossary_tooltip text="[link](url)" term_id="node" >}}',
        '{{< glossary_tooltip text="**bold**" term_id="node" >}}',
        '{{< glossary_tooltip text="a &amp; b" term_id="node" >}}',
        '{{< glossary_tooltip text="" term_id="node" >}}',
        '{{< glossary_tooltip text=" node " term_id="node" >}}',
        '{{< glossary_tooltip text="node" term_id="../node" >}}',
        '{{< glossary_tooltip text="escaped\\nnode" term_id="node" >}}',
    ],
)
def test_unsupported_glossary_never_guesses_visible_text(token):
    result = prepare_kubernetes_markdown(source_bytes(token))
    assert result.data is None and result.record.doc_version is None
    assert result.record.status == "excluded"
    assert result.record.changes_notice is None
    assert "unsupported_shortcode:glossary_tooltip" in result.record.exclusions


@pytest.mark.parametrize(
    "name,token",
    [
        ("code_sample", '{{% code_sample file="../../secret.yaml" %}}'),
        ("include", '{{< include "remote.md" >}}'),
        ("tabs", "{{< tabs >}}"),
        ("/tabs", "{{< /tabs >}}"),
        ("note", "{{< note >}}"),
        ("feature-state", '{{< feature-state state="stable" >}}'),
        ("param", '{{< param "version" >}}'),
        ("heading", '{{% heading "whatsnext" %}}'),
        ("figure", '{{< figure src="/images/example.svg" >}}'),
        ("api-reference", '{{< api-reference page="core/pod-v1" >}}'),
    ],
)
def test_other_shortcodes_exclude_the_whole_document_without_following_includes(name, token):
    result = prepare_kubernetes_markdown(source_bytes("Safe preceding text.\n" + token + "\n"))
    assert result.data is None
    assert result.record.exclusions == (f"unsupported_shortcode:{name}",)
    assert [(c.name, c.count) for c in result.record.shortcode_counts] == [(name, 1)]


def test_counts_report_all_types_even_when_output_is_excluded():
    result = prepare_kubernetes_markdown(
        source_bytes(
            '{{< note >}}\n{{< /note >}}\n{{% code_sample file="synthetic.yaml" %}}\n'
            '{{< glossary_tooltip term_id="node" >}}\n'
            '{{< glossary_tooltip text="node" term_id="node" >}}\n'
        )
    )
    assert result.data is None
    assert [(c.name, c.count) for c in result.record.shortcode_counts] == [
        ("/note", 1),
        ("code_sample", 1),
        ("glossary_tooltip", 2),
        ("note", 1),
    ]


@pytest.mark.parametrize(
    "body",
    [
        "{{< unclosed",
        "{{% unclosed",
        "orphan >}}",
        "{{ .Params.title }}",
        '{{< glossary_tooltip text="{{< note >}}" term_id="node" >}}',
    ],
)
def test_malformed_or_other_template_delimiters_fail_closed(body):
    result = prepare_kubernetes_markdown(source_bytes(body))
    assert result.data is None
    assert "unresolved_template_delimiter" in result.record.exclusions


def test_many_unclosed_openers_are_rejected_without_partial_output():
    result = prepare_kubernetes_markdown(source_bytes("{{<" * 20_000))
    assert result.data is None
    assert result.record.shortcode_counts == ()
    assert "unresolved_template_delimiter" in result.record.exclusions


@pytest.mark.parametrize(
    "body",
    [
        '```text\n{{< glossary_tooltip text="node" term_id="node" >}}\n```\n',
        '~~~text\n{{< glossary_tooltip text="node" term_id="node" >}}\n~~~\n',
        '`{{< glossary_tooltip text="node" term_id="node" >}}`\n',
        "```html\n<!-- overview -->\n```\n",
    ],
)
def test_template_examples_in_code_are_excluded_not_rewritten(body):
    result = prepare_kubernetes_markdown(source_bytes(body))
    assert result.data is None
    assert "template_or_marker_in_code_context" in result.record.exclusions


@pytest.mark.parametrize(
    "metadata,reason",
    [
        ("content_type: concept\n", "missing_metadata:title"),
        ("title: Synthetic pods\n", "missing_metadata:content_type"),
        ("title: One\ntitle: Two\ncontent_type: concept\n", "duplicate_metadata:title"),
        ("title: One\ntitle : Two\ncontent_type: concept\n", "duplicate_metadata:title"),
        ('title: One\n"title": Two\ncontent_type: concept\n', "unsupported_metadata:quoted_key"),
        ("title: true\ncontent_type: concept\n", "unsupported_metadata:title"),
        ("title: 123\ncontent_type: concept\n", "unsupported_metadata:title"),
        ("title: |\n  Multiline\ncontent_type: concept\n", "unsupported_metadata:title"),
        ("title: &alias Node\ncontent_type: concept\n", "unsupported_metadata:title"),
        (
            "title: !!python/object:example {}\ncontent_type: concept\n",
            "unsupported_metadata:title",
        ),
        ("title: Node # comment\ncontent_type: concept\n", "unsupported_metadata:title"),
        ('title: "unclosed\ncontent_type: concept\n', "unsupported_metadata:title"),
        (
            "title: Node\ncontent_type: Not a simple identifier\n",
            "unsupported_metadata:content_type",
        ),
    ],
)
def test_frontmatter_subset_is_explicit_and_rejects_ambiguity(metadata, reason):
    result = prepare_kubernetes_markdown(source_bytes(metadata=metadata))
    assert result.data is None and reason in result.record.exclusions


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Synthetic pods", "Synthetic pods"),
        ('"Caf\\u00e9 pods"', "Café pods"),
        ("'Pod''s guide'", "Pod's guide"),
    ],
)
def test_supported_frontmatter_scalars(title, expected):
    result = prepare_kubernetes_markdown(
        source_bytes(metadata=f"title: {title}\ncontent_type: concept\n")
    )
    assert result.record.title == expected and result.data is not None


@pytest.mark.parametrize(
    "raw,reason",
    [
        (b"no frontmatter", "missing_leading_frontmatter"),
        (b"---\ntitle: Synthetic\n", "unclosed_frontmatter"),
        (b"\xff", "invalid_utf8"),
        (b"a" * (MAX_SOURCE_BYTES + 1), "source_size_limit"),
        (source_bytes("bad\x00body"), "unsupported_control_or_line_ending"),
        (source_bytes("bad\rbody"), "unsupported_control_or_line_ending"),
        (source_bytes("```\nunclosed"), "unclosed_code_fence"),
        (source_bytes("Unpaired `inline\ncontinued."), "template_or_marker_in_code_context"),
        (b"\xef\xbb\xbf" + source_bytes(), "missing_leading_frontmatter"),
        (source_bytes("<!-- overview -->\n"), "empty_prepared_body"),
    ],
)
def test_invalid_or_oversized_input_has_no_partial_output(raw, reason):
    result = prepare_kubernetes_markdown(raw)
    assert result.data is None and reason in result.record.exclusions
    assert result.record.raw_sha256 == hashlib.sha256(raw).hexdigest()


def test_line_endings_and_body_identifiers_are_not_normalized_as_canonical_text():
    lf = source_bytes("  --max-pods kube-apiserver AC-2(4) a.b\n\n")
    crlf = lf.replace(b"\n", b"\r\n")
    first, second = map(prepare_kubernetes_markdown, (lf, crlf))
    assert first.data == second.data == b"  --max-pods kube-apiserver AC-2(4) a.b\n\n"
    assert first.record.raw_sha256 != second.record.raw_sha256
    assert first.record.doc_version == second.record.doc_version


def test_source_manifest_retains_metadata_changes_and_roundtrips():
    result = prepare_kubernetes_markdown(source_bytes())
    manifest = PreparationManifest(source=citation(), preparation=result.record)
    assert PreparationManifest.model_validate_json(manifest.model_dump_json()) == manifest
    assert manifest.preparation.content_type == "concept"
    with pytest.raises(ValueError, match="Attribution"):
        PreparationManifest(source=citation("Missing change notice"), preparation=result.record)
    with pytest.raises(ValueError, match="Source title"):
        PreparationManifest(
            source=SourceRecord(**{**citation().model_dump(), "title": "Wrong"}),
            preparation=result.record,
        )
    with pytest.raises(ValidationError):
        PreparationManifest(source=citation(), preparation=result.record, unknown="extra")


def test_excluded_source_manifest_does_not_claim_prepared_output_or_changes():
    result = prepare_kubernetes_markdown(source_bytes('{{% code_sample file="synthetic.yaml" %}}'))
    manifest = PreparationManifest(
        source=citation("Inspection only; source excluded."), preparation=result.record
    )
    assert manifest.preparation.status == "excluded"
    assert manifest.preparation.doc_version is manifest.preparation.changes_notice is None


def test_published_inspection_is_metadata_only_and_records_exclusion():
    path = Path(__file__).resolve().parents[1] / "docs/kubernetes-source-inspection.json"
    evidence = json.loads(path.read_text())
    manifest = PreparationManifest.model_validate_json(json.dumps(evidence["manifest"]))
    assert evidence["selected_source_count"] == 1 and evidence["accepted_source_count"] == 0
    assert manifest.preparation.status == "excluded"
    assert manifest.preparation.doc_version is manifest.preparation.changes_notice is None
    assert sum(c.count for c in manifest.preparation.shortcode_counts) == 46
    assert len(manifest.preparation.shortcode_counts) == 10
    assert manifest.preparation.recognized_markers == 2
    assert manifest.source.redistribution == "local_only"
    assert "unsupported_shortcode:code_sample" in manifest.preparation.exclusions


@pytest.mark.documents
def test_synthetic_prepared_bytes_remain_serving_equivalent_and_bind_document_version():
    from evaluation.canonical import extract_markdown, normalize
    from rag.documents import parse_document

    raw = source_bytes(
        "<!-- overview -->\n# Synthetic pods\n\n"
        'Use {{< glossary_tooltip text="containers" term_id="container" >}} with `--max-pods`.\n'
    )
    result = prepare_kubernetes_markdown(raw)
    result.verify(raw)
    assert result.data is not None
    manifest = PreparationManifest(source=citation(), preparation=result.record)
    canonical = extract_markdown(result.data, doc_id="synthetic-prepared", source=manifest.source)
    assert canonical.document.doc_version == manifest.preparation.doc_version
    assert canonical.document.doc_version != manifest.preparation.raw_sha256
    assert canonical.document.source.attribution == CHANGES_NOTICE
    assert "containers with --max-pods" in canonical.document.pages[0].text
    assert all(c.status == "mapped" for c in canonical.chunks)
    assert [c.text for c in canonical.chunks] == [
        normalize(c.text) for c in parse_document(result.data, "synthetic.md")
    ]
