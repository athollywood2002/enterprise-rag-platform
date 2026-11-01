"""Real pinned Markdown parser/chunker on authored synthetic text only."""

from itertools import pairwise
from unittest.mock import Mock

import pytest

from evaluation.canonical import MARKDOWN_PINS, extract_document, normalize, text_sha256
from evaluation.corpus import (
    CorpusManifest,
    GoldSpan,
    SourceRecord,
    load_corpus,
    validate_gold,
)
from evaluation.spans import chunk_relevant, span_coverage
from rag.chunking import TITLE_CHUNKING

pytestmark = pytest.mark.documents


@pytest.fixture
def source():
    return SourceRecord(
        title="Authored synthetic Markdown",
        canonical_url="urn:synthetic:markdown",
        revision="1",
        license_id="MIT",
        attribution="Repository test authors",
        redistribution="redistributable",
    )


def test_markdown_single_partition_identifiers_and_serving_parity(monkeypatch, source):
    from rag import documents

    raw = b"""# Synthetic node configuration

Use `--max-pods=110` for `kube-apiserver`, and inspect `AC-2(4)` with `a.b`.

```sh
kubectl get pods --all-namespaces
kubectl get nodes -o wide
```

```yaml
maxPods: 110
apiVersion: v1
featureGates:
  ExampleGate: true
```

A **bold** explanation and [link label](https://example.org/reference).

<!-- synthetic hidden comment -->
"""
    partition = Mock(wraps=documents._partition_document)
    monkeypatch.setattr(documents, "_partition_document", partition)
    result = extract_document(raw, filename="fixture.md", doc_id="markdown", source=source)
    partition.assert_called_once()
    text = result.document.pages[0].text
    assert text == (
        "Synthetic node configuration Use --max-pods=110 for kube-apiserver, and inspect "
        "AC-2(4) with a.b. kubectl get pods --all-namespaces kubectl get nodes -o wide "
        "maxPods: 110 apiVersion: v1 featureGates: ExampleGate: true A bold explanation and link label."
    )
    assert result.document.page_kind == "logical"
    assert result.document.pages[0].sha256 == text_sha256(text)
    assert all(
        c.page_kind == "logical" and c.page == 1 and c.status == "mapped" for c in result.chunks
    )
    assert tuple((p.name, p.version) for p in result.document.parser.packages) == MARKDOWN_PINS
    serving = documents.parse_document(raw, "fixture.md")
    assert [c.text for c in result.chunks] == [normalize(c.text) for c in serving]
    assert all(c.page_number is None for c in serving)  # Serving is not relabeled as physical.
    assert result.chunking_policy == TITLE_CHUNKING.policy_id
    # Rendering intentionally loses markup, link targets and comments. Canonical
    # whitespace normalization also loses YAML indentation; never execute it.
    for absent in ("```", "**", "https://example.org/reference", "synthetic hidden comment"):
        assert absent not in text
    assert load_corpus(
        CorpusManifest(documents=(result.document,)).model_dump_json()
    ).documents == (result.document,)
    assert result == extract_document(raw, filename="fixture.md", doc_id="markdown", source=source)


def test_large_markdown_has_bounded_ordered_chunks_and_nontrivial_gold_coverage(source):
    from rag.documents import parse_document

    sections = []
    for i in range(40):
        sections.append(
            f"## Synthetic node pool {i:03d}\n\n"
            f"Pool pool-{i:03d} is an authored fixture, not operational guidance. "
            + (
                "The node configuration limits pod density and reserves system resources. "
                "Review the scheduling requirements before changing the configuration. "
            )
            * 2
            + f"\n\n```sh\nkubectl get nodes -l pool=pool-{i:03d} --show-labels\n```\n\n"
        )
    raw = (
        "# Synthetic Kubernetes-style guide\n\n"
        + "\n".join(sections)
        + "\nUse `--node-labels=pilot.final=true` for the final synthetic pool.\n"
    ).encode()
    assert len(raw) > 10_000
    result = extract_document(raw, filename="long.md", doc_id="long-md", source=source)
    assert len(result.chunks) > 10
    assert result.mapping_counts == {"mapped": len(result.chunks)}
    assert all(0 < len(c.text) <= TITLE_CHUNKING.max_characters for c in result.chunks)
    assert all(a.end <= b.start for a, b in pairwise(result.chunks))
    assert result.chunks[0].start == 0
    page = result.document.pages[0]
    assert result.chunks[-1].end == len(page.text)
    serving = parse_document(raw, "long.md")
    assert all(0 < len(c.text) <= TITLE_CHUNKING.max_characters for c in serving)
    assert [c.text for c in result.chunks] == [normalize(c.text) for c in serving]
    excerpt = "--node-labels=pilot.final=true"
    start = page.text.index(excerpt)
    assert start > 10_000
    span = GoldSpan(
        doc_id="long-md",
        doc_version=result.document.doc_version,
        page=1,
        page_kind="logical",
        page_sha256=page.sha256,
        start=start,
        end=start + len(excerpt),
        excerpt=excerpt,
    )
    corpus = CorpusManifest(documents=(result.document,))
    assert not chunk_relevant(span, result.chunks[0], corpus)
    assert span_coverage(span, (result.chunks[0],), corpus) == 0
    assert chunk_relevant(span, result.chunks[-1], corpus)
    assert sum(chunk_relevant(span, c, corpus) for c in result.chunks) == 1
    wrong = GoldSpan(**{**span.model_dump(), "page_kind": "physical"})
    with pytest.raises(ValueError, match="page kind"):
        validate_gold(wrong, corpus)


def test_markdown_canonical_separator_comes_from_actual_elements(monkeypatch, source):
    from rag import documents

    partition = Mock(wraps=documents._partition_document)
    # Record elements without reparsing to independently reconstruct canonical text.
    captured = []

    def record(path, suffix):
        elements = partition(path, suffix)
        captured.extend(elements)
        return elements

    monkeypatch.setattr(documents, "_partition_document", record)
    result = extract_document(
        b"# Heading\n\nFirst paragraph.\n\n`--max-pods`",
        filename="parts.md",
        doc_id="parts",
        source=source,
    )
    partition.assert_called_once()
    assert result.document.pages[0].text == normalize(
        "\n\n".join(str(e) for e in captured if str(e).strip())
    )


def test_markdown_rejects_invented_physical_pages(monkeypatch, source):
    from unstructured.documents.elements import ElementMetadata, Text

    monkeypatch.setattr(
        "rag.documents._partition_document",
        lambda *args: [
            Text("Synthetic", metadata=ElementMetadata(page_number=1)),
        ],
    )
    with pytest.raises(ValueError, match="Unexpected physical Markdown pages"):
        extract_document(b"# Synthetic", filename="bad.md", doc_id="bad", source=source)


def test_markdown_unicode_and_escaped_identifier_punctuation(source):
    raw = "# Café\n\nUse `--max-pods` – node 😀 and `AC-2(4)` with `a.b`.\n".encode()
    result = extract_document(raw, filename="unicode.md", doc_id="unicode", source=source)
    assert result.document.pages[0].text == "Café Use --max-pods – node 😀 and AC-2(4) with a.b."
    assert result.mapping_counts == {"mapped": 1}
