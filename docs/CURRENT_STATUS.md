# Current status

As of 2026-11-03. This is a local-lab prototype, not a production service.

## Main and draft work

`main` at `82bd344` includes authenticated text/document ingestion, page-local
document chunks, citation-bearing answers, collection write guards, and offline
canonicalization/labeling tools. The default serving behavior has not changed in
this reproducibility work.

This change adds a [synthetic evaluation CLI](evaluation-cli.md): deterministic
offline HTTP smoke and a local approval-plan manifest. It does not add live test
execution, model evaluation, or a new ingestion default.

The following remain separate, draft and unmerged:

- [PR #12](https://github.com/athollywood2002/enterprise-rag-platform/pull/12),
  `f6f059af7127d4de5b05b4f4e25a5befda05f497`.
- [PR #13](https://github.com/athollywood2002/enterprise-rag-platform/pull/13),
  `c2caab33cda009ad34d64922412beb640d354df4`: B,
  `nist-requirement-page-v2`, a requirement-aware opt-in candidate.

Neither draft is rebased, merged or edited by this change. B is the owner's
preferred opt-in candidate, not the default.

## Private provisional MacBook pilot

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

Review and owner acceptance are recorded in the
[coordination relay](https://github.com/athollywood2002/ai-architect-workspace/issues/3#issuecomment-6598215400)
and [phase authorization](https://github.com/athollywood2002/ai-architect-workspace/issues/3#issuecomment-6610883119).
Private sources, prompts, labels, answers, local paths and holdout material are
excluded from public Git. The synthetic CLI does not replay those artifacts.

## Preservation and remaining gates

Original A/B outputs, frozen inputs, provenance, both earlier snapshots and the
failed snapshot are preserved. A fresh same-Mac snapshot passed byte verification
for 153 data files / 15,142,641 bytes plus two controls in a collision-safe
namespace. Independent read-only backup audit is requested and **pending**.
Same-disk copies are not off-device recovery; restore remains untested.

No new real-service validation is claimed. AiMiniRig availability does not
authorize SSH, Docker, inference or database writes. A later synthetic FastAPI
test needs separate approval naming the machine, services, isolated storage and
collection, model/version pins and exact commands. Never use `hdd_knowledge`.
