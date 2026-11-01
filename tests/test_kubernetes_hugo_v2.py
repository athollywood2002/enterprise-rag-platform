"""Synthetic v2 grammar, content preservation, loss accounting and sample denominator."""

import hashlib
import json
from pathlib import Path

import pytest

from evaluation.kubernetes_hugo import (
    CHANGES_NOTICE,
    LEGACY_CHANGES_NOTICE,
    LEGACY_PREPROCESSOR_ID,
    PREPROCESSOR_ID,
    PreparationManifest,
    PreparationRecord,
    prepare_kubernetes_markdown,
)
from evaluation.kubernetes_sample import SAMPLE_PATHS, TOTAL_LIMIT, assess_fixed_sample


def raw(body):
    return ("---\ntitle: Synthetic\ncontent_type: reference\n---\n" + body).encode()


@pytest.mark.parametrize("name", ["note", "caution", "warning"])
def test_callouts_unwrap_with_exact_inner_content(name):
    content = "Keep --max-pods and `--anonymous-auth`.\n\n```yaml\na.b: AC-2(4)\n```\n"
    source = raw(f"{{{{< {name} >}}}}\n{content}{{{{< /{name} >}}}}\n")
    result = prepare_kubernetes_markdown(source)
    assert result.data == content.encode()
    assert result.record.preprocessor_id == PREPROCESSOR_ID
    assert [(c.name, c.count) for c in result.record.transform_counts] == [(f"callout:{name}", 1)]
    assert result.record.raw_sha256 == hashlib.sha256(source).hexdigest()
    assert result.record.doc_version == hashlib.sha256(content.encode()).hexdigest()
    assert result.record.changes_notice == CHANGES_NOTICE
    result.verify(source)
    assert prepare_kubernetes_markdown(source, policy=LEGACY_PREPROCESSOR_ID).data is None


def test_nested_callouts_keep_body_in_order():
    result = prepare_kubernetes_markdown(
        raw(
            "{{< note >}}\nOuter.\n{{< warning >}}\nInner.\n{{< /warning >}}\nEnd.\n{{< /note >}}\n"
        )
    )
    assert result.data == b"Outer.\nInner.\nEnd.\n"


@pytest.mark.parametrize(
    "body",
    [
        "{{< note >}}\nBody.\n",
        "{{< /note >}}\n",
        "{{< note >}}\nBody.\n{{< /warning >}}\n",
        "{{< note >}}\n{{< caution >}}\nBody.\n{{< /note >}}\n{{< /caution >}}\n",
        '{{< note title="extra" >}}\nBody.\n{{< /note >}}\n',
        "Prefix {{< note >}}\nBody.\n{{< /note >}}\n",
        "{{< note >}}Body{{< /note >}}",
        "{{% note %}}\nBody.\n{{% /note %}}\n",
    ],
)
def test_ambiguous_unbalanced_or_nonstandalone_callouts_exclude_everything(body):
    result = prepare_kubernetes_markdown(raw(body))
    assert result.data is result.record.doc_version is result.record.changes_notice is None
    assert result.record.exclusions


@pytest.mark.parametrize("key", ["synopsis", "options", "seealso", "whatsnext", "prerequisites"])
@pytest.mark.parametrize("prefix", ["", "## "])
def test_standalone_headings_are_removed_and_losses_counted(key, prefix):
    result = prepare_kubernetes_markdown(
        raw(f'{prefix}{{{{% heading "{key}" %}}}}\nKeep this text.\n')
    )
    assert result.data == b"Keep this text.\n"
    assert [(c.name, c.count) for c in result.record.transform_counts] == [(f"heading:{key}", 1)]
    assert "counted content losses" in result.record.changes_notice


@pytest.mark.parametrize(
    "token",
    [
        '{{% heading "unknown" %}}',
        '{{< heading "options" >}}',
        '{{% heading key="options" %}}',
        '{{% heading "options" "extra" %}}',
        '{{% heading "options" %}} trailing body',
        'Prefix {{% heading "options" %}}',
        '####### {{% heading "options" %}}',
        '    {{% heading "options" %}}',
    ],
)
def test_unknown_or_nonstandalone_headings_exclude(token):
    result = prepare_kubernetes_markdown(raw(token + "\nBody.\n"))
    assert result.data is None


@pytest.mark.parametrize(
    "attrs",
    [
        'state="stable" for_k8s_version="v1.27"',
        'for_k8s_version="v1.33" state="deprecated"',
        'feature_gate_name="ExampleGate"',
        'feature_gate_name="ExampleGate" state="beta" for_k8s_version="v1.36"',
    ],
)
def test_supported_standalone_badges_are_removed_and_counted(attrs):
    result = prepare_kubernetes_markdown(raw(f"{{{{< feature-state {attrs} >}}}}\nKeep content.\n"))
    assert result.data == b"Keep content.\n"
    assert [(c.name, c.count) for c in result.record.transform_counts] == [("feature-state", 1)]


@pytest.mark.parametrize(
    "token",
    [
        "{{< feature-state >}}",
        '{{< feature-state state="stable" >}}',
        '{{< feature-state state="stable" for_k8s_version="latest" >}}',
        '{{< feature-state state="unknown" for_k8s_version="v1.2" >}}',
        '{{< feature-state feature_gate_name="../file" >}}',
        '{{< feature-state feature_gate_name="Example" extra="ignored" >}}',
        '{{< feature-state feature_gate_name="Example" feature_gate_name="Other" >}}',
        '{{% feature-state feature_gate_name="Example" %}}',
        'Prefix {{< feature-state feature_gate_name="Example" >}}',
    ],
)
def test_unsupported_badges_exclude(token):
    assert prepare_kubernetes_markdown(raw(token + "\nBody.\n")).data is None


@pytest.mark.parametrize(
    "token",
    [
        '{{% code_sample file="elsewhere.yaml" %}}',
        '{{< include "elsewhere.md" >}}',
        "{{< tabs >}}",
        "{{< tab >}}",
        '{{< api-reference page="core/pod" >}}',
        '{{< param "version" >}}',
        "{{< skew currentVersion >}}",
        "{{< glossary_definition >}}",
        '{{< figure src="image.svg" >}}',
        "{{< thirdparty-content >}}",
        '{{< glossary_tooltip term_id="node" >}}',
    ],
)
def test_external_or_unreliable_templates_stay_excluded_under_v2(token):
    result = prepare_kubernetes_markdown(raw("{{< note >}}\nSafe.\n" + token + "\n{{< /note >}}\n"))
    assert result.data is None


def test_v1_stays_replayable_and_v2_provenance_is_explicit():
    source = raw('{{< glossary_tooltip text="node" term_id="node" >}}\n')
    first = prepare_kubernetes_markdown(source, policy=LEGACY_PREPROCESSOR_ID)
    second = prepare_kubernetes_markdown(source)
    first.verify(source)
    second.verify(source)
    assert first.data == second.data
    assert first.record.raw_sha256 == second.record.raw_sha256
    assert first.record.doc_version == second.record.doc_version
    assert first.record.preprocessor_id != second.record.preprocessor_id
    assert first.record.changes_notice != second.record.changes_notice
    assert first.record.model_dump_json() != second.record.model_dump_json()
    with pytest.raises(ValueError, match="Unsupported preprocessing policy"):
        prepare_kubernetes_markdown(source, policy="unknown")


def test_sample_denominator_includes_missing_and_excluded_documents():
    report = assess_fixed_sample(
        {
            SAMPLE_PATHS[0]: raw('## {{% heading "options" %}}\n--max-pods\n'),
            SAMPLE_PATHS[1]: raw('{{< include "unknown" >}}\n'),
        }
    )
    assert report["sample_size"] == 10
    assert (report["accepted"], report["excluded"], report["not_acquired"]) == (1, 1, 8)
    assert report["v1_accepted"] == 0
    assert report["rows"][0]["missing_flag_occurrences"] == {}
    assert report["rows"][0]["identifier_probes"]["--max-pods"] == {
        "raw_occurrences": 1,
        "body_occurrences": 1,
        "frontmatter_occurrences": 0,
        "prepared_occurrences": 1,
    }
    assert report["rows"][1]["missing_flag_occurrences"] is None
    assert [row["path"] for row in report["rows"]] == list(SAMPLE_PATHS)
    with pytest.raises(ValueError, match="Unexpected paths"):
        assess_fixed_sample({"another-page.md": raw("Body")})
    with pytest.raises(ValueError, match="aggregate byte limit"):
        assess_fixed_sample({SAMPLE_PATHS[0]: b"x" * (TOTAL_LIMIT + 1)})


def test_v2_accepted_manifest_requires_v2_change_notice():
    from evaluation.corpus import SourceRecord

    result = prepare_kubernetes_markdown(raw('## {{% heading "options" %}}\n--max-pods\n'))
    citation = SourceRecord(
        title="Synthetic",
        canonical_url="urn:synthetic:v2",
        revision="1",
        license_id="MIT",
        attribution=CHANGES_NOTICE,
        redistribution="redistributable",
    )
    manifest = PreparationManifest(source=citation, preparation=result.record)
    assert manifest.preparation.preprocessor_id == PREPROCESSOR_ID
    assert PreparationManifest.model_validate_json(manifest.model_dump_json()) == manifest
    with pytest.raises(ValueError, match="Attribution"):
        PreparationManifest(
            source=SourceRecord(**{**citation.model_dump(), "attribution": LEGACY_CHANGES_NOTICE}),
            preparation=result.record,
        )
    with pytest.raises(ValueError, match="Changes notice"):
        PreparationRecord(**{**result.record.model_dump(), "changes_notice": LEGACY_CHANGES_NOTICE})


@pytest.mark.parametrize(
    "body",
    [
        '```text\n## {{% heading "options" %}}\nBody.\n```\n',
        '~~~text\n{{< feature-state feature_gate_name="Example" >}}\nBody.\n~~~\n',
        "```text\n{{< note >}}\nBody.\n{{< /note >}}\n```\n",
        '`{{% heading "options" %}}`\nBody.\n',
    ],
)
def test_v2_does_not_admit_rewritten_code_examples(body):
    result = prepare_kubernetes_markdown(raw(body))
    assert result.data is None
    assert "template_or_marker_in_code_context" in result.record.exclusions


def test_fixed_sample_evidence_keeps_all_rows_and_qualifies_retention():
    path = Path(__file__).resolve().parents[1] / "docs/kubernetes-v2-coverage.json"
    evidence = json.loads(path.read_text())
    assert [row["path"] for row in evidence["rows"]] == list(SAMPLE_PATHS)
    assert (
        evidence["sample_size"],
        evidence["v1_accepted"],
        evidence["accepted"],
        evidence["excluded"],
        evidence["not_acquired"],
    ) == (10, 0, 2, 8, 0)
    for i, row in enumerate(evidence["rows"]):
        record = PreparationRecord.model_validate_json(json.dumps(row["preparation"]))
        assert record.preprocessor_id == PREPROCESSOR_ID
        if i < 2:
            assert record.status == "accepted"
            assert row["missing_flag_occurrences"] == {}
            assert row["raw_flag_occurrences"] > 200
            assert (
                row["identifier_probes"]["--max-pods" if i == 0 else "--anonymous-auth"][
                    "raw_occurrences"
                ]
                > 0
            )
            assert all(
                p["body_occurrences"] == p["prepared_occurrences"]
                for p in row["identifier_probes"].values()
            )
        else:
            assert record.status == "excluded" and record.doc_version is None
            assert row["missing_flag_occurrences"] is None
    assert evidence["acquisition_summary"]["canonicalization_or_labeling_performed"] is False
    api_probe = evidence["rows"][1]["identifier_probes"]["kube-apiserver"]
    assert api_probe == {
        "raw_occurrences": 15,
        "body_occurrences": 14,
        "frontmatter_occurrences": 1,
        "prepared_occurrences": 14,
    }
    assert evidence["rows"][1]["preparation"]["title"] == "kube-apiserver"
