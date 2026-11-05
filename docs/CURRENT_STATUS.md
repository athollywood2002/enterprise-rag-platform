# Current status

Updated November 5, 2026. Local single-instance prototype, not a production service.

## Completed milestones

- PR #21 merged at `379d434`: Docker quickstart and manual n8n text/CSV demo.
  One real two-host manual execution ingested both fixtures and returned the correct
  ORION/NetworkOps answer with supporting citations. Shared services were preserved
  and the isolated demo stopped. Post-merge base, document and Docker CI passed.
- A separate bounded two-page PDF HTTP test at application `f20ac879` passed parsing,
  page provenance, duplicate-free reingestion, two cited answers, a metered budget
  of six embeddings/two chats and shutdown verification. The owner accepted both
  answers and closed the smoke. Earlier failed attempts remain failed and preserved.
  This private-packet result does not establish PDF support in the PR #21 image.
- Earlier authenticated text HTTP and private development A/B evidence remains
  historical. The deferred PDF follow-up is complete, not pending approval.

## Folder UI implementation (this branch)

The same-origin web interface adds browser-folder upload and bounded read-only
server-root browsing, preview, SQLite-persisted jobs, real per-file progress,
explicit retry/cancellation/restart recovery and citation inspection. TXT/CSV/text
PDF parsing uses shared backend code with pinned pypdf in Docker, independent of
optional legacy Unstructured parsing. Immutable vector revisions and a transactional
active-revision registry preserve a usable document on replacement failure.

See [operating guide](folder-library.md) for the separate managed collection, limits,
source identity semantics and n8n API integration. See [UI walkthrough](ui-walkthrough.md)
for actual browser evidence and limitations. This is reviewable branch work; it is
not an image release or a claim that the branch was deployed on AiMiniRig.

The old API/n8n demo remains supported. The new Docker parser and UI passed their own isolated container and Chromium
validation; historical PDF smoke results are not reused as proof for this
implementation. See the walkthrough for exact test scope and CI evidence. Fixture tests do not prove broad retrieval quality,
complex PDF layout support, production readiness or tenant isolation.

PRs #12 and #13 remain separate and outside this change. No retained data, private
receipts, model assets or failed runs were deleted. No registry publication or
shared-service deployment is included.

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
