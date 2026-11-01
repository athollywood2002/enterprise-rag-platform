"""Fixed pre-selection coverage sample for Hugo v2; no acquisition side effects."""

import re
from collections import Counter
from collections.abc import Mapping

from evaluation.kubernetes_hugo import (
    LEGACY_PREPROCESSOR_ID,
    PREPROCESSOR_ID,
    prepare_kubernetes_markdown,
)

KUBERNETES_REVISION = "f4ec4968d939d533ecc82b7a352155caed3c932d"
SAMPLE_PATHS = (
    "content/en/docs/reference/command-line-tools-reference/kubelet.md",
    "content/en/docs/reference/command-line-tools-reference/kube-apiserver.md",
    "content/en/docs/reference/kubectl/quick-reference.md",
    "content/en/docs/concepts/overview/components.md",
    "content/en/docs/concepts/configuration/configmap.md",
    "content/en/docs/concepts/services-networking/service.md",
    "content/en/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes.md",
    "content/en/docs/reference/access-authn-authz/rbac.md",
    "content/en/docs/concepts/workloads/pods/_index.md",
    "content/en/docs/concepts/architecture/nodes.md",
)
IDENTIFIER_PROBES = ("--max-pods", "--anonymous-auth", "kube-apiserver", "kubectl", "AC-2(4)")
PER_FILE_LIMIT = 131_072
TOTAL_LIMIT = 1_048_576


def assess_fixed_sample(sources: Mapping[str, bytes]) -> dict[str, object]:
    """Assess all ten rows, including missing/excluded ones, without corpus selection.

    Retention is measured in prepared Markdown bytes only, not canonical parsing,
    embedding, retrieval, rendered webpage completeness or licensing approval.
    """
    if set(sources) - set(SAMPLE_PATHS):
        raise ValueError("Unexpected paths outside the fixed sample")
    if sum(len(raw) for raw in sources.values()) > TOTAL_LIMIT:
        raise ValueError("Fixed sample aggregate byte limit exceeded")
    rows = []
    flag_pattern = re.compile(r"(?<![A-Za-z0-9-])--[A-Za-z0-9][A-Za-z0-9-]*")
    for path in SAMPLE_PATHS:
        if path not in sources:
            rows.append({"path": path, "status": "not_acquired"})
            continue
        raw = sources[path]
        legacy = prepare_kubernetes_markdown(raw, policy=LEGACY_PREPROCESSOR_ID)
        current = prepare_kubernetes_markdown(raw)
        current.verify(raw)
        original = raw.decode("utf-8", errors="replace")
        lines = original.replace("\r\n", "\n").splitlines(keepends=True)
        closing = next((i for i in range(1, len(lines)) if lines[i].rstrip("\n") == "---"), None)
        body = (
            "".join(lines[closing + 1 :])
            if lines and lines[0] == "---\n" and closing is not None
            else None
        )
        prepared = current.data.decode("utf-8") if current.data is not None else None
        original_flags = Counter(flag_pattern.findall(original))
        prepared_flags = Counter(flag_pattern.findall(prepared)) if prepared is not None else None
        rows.append(
            {
                "path": path,
                "bytes": len(raw),
                "status": current.record.status,
                "v1_status": legacy.record.status,
                "v1_exclusions": list(legacy.record.exclusions),
                "preparation": current.record.model_dump(mode="json"),
                "raw_flag_occurrences": sum(original_flags.values()),
                "raw_distinct_flags": len(original_flags),
                "missing_flag_occurrences": (
                    dict(sorted((original_flags - prepared_flags).items()))
                    if prepared_flags is not None
                    else None
                ),
                "identifier_probes": {
                    probe: {
                        "raw_occurrences": original.count(probe),
                        "body_occurrences": body.count(probe) if body is not None else None,
                        "frontmatter_occurrences": original.count(probe) - body.count(probe)
                        if body is not None
                        else None,
                        "prepared_occurrences": prepared.count(probe)
                        if prepared is not None
                        else None,
                    }
                    for probe in IDENTIFIER_PROBES
                },
            }
        )
    return {
        "schema_version": "k8s-hugo-coverage-v1",
        "revision": KUBERNETES_REVISION,
        "policy": PREPROCESSOR_ID,
        "sample_size": len(SAMPLE_PATHS),
        "accepted": sum(row["status"] == "accepted" for row in rows),
        "excluded": sum(row["status"] == "excluded" for row in rows),
        "not_acquired": sum(row["status"] == "not_acquired" for row in rows),
        "v1_accepted": sum(row.get("v1_status") == "accepted" for row in rows),
        "rows": rows,
    }
