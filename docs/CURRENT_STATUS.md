# Current status

Status after PR #17 (merged 2026-11-04 UTC). This is a local-lab prototype,
not a production service.

## Main and draft work

The pre-PR #14 baseline, `82bd344`, includes authenticated text/document ingestion, page-local
document chunks, citation-bearing answers, collection write guards, and offline
canonicalization/labeling tools. The default outgoing generation request remains
unchanged; chat response metadata has changed as described below.

[PR #14](https://github.com/athollywood2002/enterprise-rag-platform/pull/14)
merged as `6000ccd0202acfaa2cfba814e6c9e5a83abc03a1` on 2026-11-03.
That merge added a [synthetic evaluation CLI](evaluation-cli.md): deterministic
offline HTTP smoke and a local approval-plan manifest. It does not add live test
execution, model evaluation, or a new ingestion default.

[PR #16](https://github.com/athollywood2002/enterprise-rag-platform/pull/16)
merged as `75b98febcabe672ad47a6ff9205a1f5fc44595ea`. It adds an optional,
default-off [generation token cap](generation-budget.md). Actual chat responses
now add a `generation` object even when uncapped; exact-two-key clients must
adapt. No-sources fallbacks retain their prior shape. Completion metadata is not
answer-quality evidence, a wall-time bound or cancellation.

[PR #17](https://github.com/athollywood2002/enterprise-rag-platform/pull/17)
merged as `ee040890c7d6042c16001cc9853078f76750b95d`. It adds an opt-in,
offline-tested [process supervisor](evaluation-supervisor.md), not a normal API
startup change. Its in-process factory alone does not count a separate API
process's model calls; explicit proxy wiring is required. Offline proxy work does
not establish live runtime isolation or authorize execution.

The following remain separate, draft and unmerged:

- [PR #12](https://github.com/athollywood2002/enterprise-rag-platform/pull/12),
  `f6f059af7127d4de5b05b4f4e25a5befda05f497`.
- [PR #13](https://github.com/athollywood2002/enterprise-rag-platform/pull/13),
  `c2caab33cda009ad34d64922412beb640d354df4`: B,
  `nist-requirement-page-v2`, a requirement-aware opt-in candidate.

Both drafts remain separate from the merged evaluation CLI. B is the owner's
preferred opt-in candidate, not the default.

## Private provisional development pilot

The completed A/B pilot used one exposed development set: 12 answerable and eight
negative questions. Evidence and labels were AI-proposed development drafts;
Claude supplied the agent judgments. All experimental launches are consumed and
experiments are stopped. No variants, probes or reruns are authorized.

| Agent judgment, answerable questions | A | B |
| --- | ---: | ---: |
| Correct | 8 | 8 |
| Content-correct with citation defect | 0 | 1 |
| Partial | 2 | 3 |
| Wrong | 2 | 0 |

The agent judged all eight negatives handled in both runs. Retrieval any-support
hits stayed 12/12, all-span hits stayed 9/12, and full union support spans improved
from 13/18 to 14/18. Full all-support questions improved from 8/12 to 9/12.

The accepted conclusion is **improved answer quality on this development set,
with no new serious regressions**, alongside minor citation/precision regressions.
This is a single-sample, agent-reviewed provisional result with a historical
control and recomputed B query vectors. It is not blind, human-gold, a deterministic
causal comparison, or a general benchmark.

Review and owner acceptance are recorded in the private coordination repository.
Private sources, prompts, labels, answers, local paths and holdout material are
excluded from public Git. The synthetic CLI does not replay those artifacts.

## Validation limits

Preservation of the private pilot evidence passed an independent read-only audit.
Supporting records remain private; this audit does not validate model quality.

No new real-service validation is claimed. The synthetic CLI covers offline code
paths with stub services. A real-service test remains separately approval-gated;
see the [evaluation CLI guide](evaluation-cli.md) and
[draft real-service test plan](real-http-validation-plan.md). The latter is a
command proposal, not an executable approval or a completed validation.
