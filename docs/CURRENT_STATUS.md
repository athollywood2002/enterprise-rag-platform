# Current status

Updated 2026-11-04 UTC after PR #19 and the accepted live text HTTP smoke.
This is a local-lab prototype, not a production service.

## Latest verified milestone

The merged application at [`4051ca5`](https://github.com/athollywood2002/enterprise-rag-platform/commit/4051ca5468f20f54080366fadc61e4207db433db)
passed one scoped synthetic text test through the real route:
**authenticated HTTP API → budget proxy → dedicated owned Ollama and native Qdrant**.

| Check | Observed result |
| --- | --- |
| Authorization | Unauthorized ingestion and question requests returned 401. |
| Idempotent ingestion | Ingesting the same text twice left one point with the same ID and payload; it remained unchanged after the question. |
| Answer and citation | One question returned the correct synthetic fact with a matching source and citation. |
| Model budget | Exactly three embedding calls and one chat call; generation completed with an explicit 1,536-token cap. |
| Resource controls | The test cgroup reported a 400% CPU quota, 24 GiB memory limit, zero swap and a 512-task limit. |
| Shutdown | All captured owned process identities and their GPU entries disappeared within the single 15-second observation window; acceptance occurred after about 0.425 seconds. |
| Final checks | Shared model-service identity remained unchanged at the observations, test ports closed, supervisor evidence finalized without errors and the exact test cgroup was absent. |

The first shutdown sample still contained a matching zombie process and its GPU
entry. That sample did not pass; acceptance required actual disappearance in a
later sample. An earlier run failed its shutdown checkpoint despite passing the
HTTP sequence. That failure remains recorded, with its cause unconfirmed.

The test used Qwen3:8b, nomic-embed-text, Qdrant server 1.17.0 and qdrant-client
1.17.1 with frozen runtime/model/dependency pins. Review checked the private
captures and all 24 returned receipt hashes and contents. Raw receipts,
operational paths, credentials and deployment-specific pins remain private.
These are saved run observations, not a current host-health claim.

## What is available on main

- Authenticated text/document ingestion, page-local document chunks,
  citation-bearing answers and collection write guards.
- Offline canonicalization, development labeling and the
  [synthetic evaluation CLI](evaluation-cli.md) from
  [PR #14](https://github.com/athollywood2002/enterprise-rag-platform/pull/14).
  The CLI uses stub services; it does not execute the private live test.
- An optional, default-off [generation token cap](generation-budget.md) from
  [PR #16](https://github.com/athollywood2002/enterprise-rag-platform/pull/16).
  Actual chat responses include generation metadata even when uncapped;
  no-sources fallbacks retain their prior shape.
- An opt-in [process supervisor and separate-API budget proxy](evaluation-supervisor.md)
  from [PR #17](https://github.com/athollywood2002/enterprise-rag-platform/pull/17)
  and [PR #18](https://github.com/athollywood2002/enterprise-rag-platform/pull/18).
- [PR #19](https://github.com/athollywood2002/enterprise-rag-platform/pull/19)
  rejects equivalent proxy/upstream ports and validates upstream JSON before
  recording success.

Normal API startup does not enable the supervisor or proxy. The successful live
test used a separately reviewed private launcher, including its shutdown
observation window; that launcher is not a new public CLI mode or part of the
merged supervisor library. The [validation guide](real-http-validation-plan.md)
describes the test contract, not a ready-to-run deployment package or permission
to repeat the run.

## Scope and next work

This milestone validates one tiny plain-text HTTP integration path. It does not
validate document/PDF parsing through this supervised route, parser resource
limits, retrieval selectivity, comparative answer quality or a general benchmark.
It does not demonstrate host/network containment or an enforceable VRAM cap.
The public automated tests remain offline; they do not contact live model or
database services.

Next work is a separately scoped document/PDF HTTP validation covering parsing,
page provenance, collection isolation and cited retrieval. Reusable public live
execution tooling remains a reproducibility gap. Neither that future test nor
the earlier A/B pilot is executed by the synthetic evaluation CLI.

The following remain separate, draft and unmerged:

- [PR #12](https://github.com/athollywood2002/enterprise-rag-platform/pull/12),
  `f6f059af7127d4de5b05b4f4e25a5befda05f497`.
- [PR #13](https://github.com/athollywood2002/enterprise-rag-platform/pull/13),
  `c2caab33cda009ad34d64922412beb640d354df4`: B,
  `nist-requirement-page-v2`, a requirement-aware opt-in candidate.

B remains the owner's preferred opt-in candidate, not the default. This text
smoke neither tests B nor changes the provisional pilot conclusions below.

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

Preservation of the private pilot evidence passed an independent read-only audit.
Supporting records remain private; that audit does not validate model quality.
