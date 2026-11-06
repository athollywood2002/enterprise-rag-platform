# Current status

Updated November 6, 2026. The browser library and manual n8n workflow are available for community setup and workflow review. Both use the same API service with separate collections. Start with the [Docker browser quickstart](../README.md#docker-browser-quickstart) or [see the interface](ui-walkthrough.md).

## Completed demonstrations

| Demonstration | Observed outcome |
| --- | --- |
| Docker and n8n (PR #21, `379d434`) | One manual two-host run read the public TXT and CSV fixtures, ingested both through the legacy API, and returned ORION and NetworkOps with citations to both files. The isolated demo stopped. |
| Separate two-page text-PDF HTTP smoke (`f20ac879`) | Parsing preserved pages, identical reingestion kept the point count stable, and the maintainer accepted both cited answers. The test metered six embedding calls and two chats and verified shutdown. Its scope was this HTTP stack and fixture. |
| Real browser-folder workflow (attempt 3) | A browser upload ingested one TXT, one CSV and one two-page text PDF. Three documents yielded four indexed chunks. After refresh and reconnect, the saved job reopened. The maintainer accepted all four answers below. |

### What the real browser run answered

The following are summaries of the retained real-model answers. The chat model was `qwen3:8b` and the embedding model was `nomic-embed-text:latest`.

| Question about the live fixtures | Accepted result | Source shown |
| --- | --- | --- |
| What is ORION's recovery code? | LANTERN | `runbook.txt` |
| Who owns ORION and where is it located? | NetworkOps, Room 7 | `inventory.csv` |
| When does maintenance start, and what must be checked before it ends? | Start at 21:15 UTC. Verify the blue indicator before ending maintenance. | `procedure.pdf`, pages 1 and 2 respectively |
| What is ORION's purchase price? | The supplied excerpts give no price. | Answer referred to all four retrieved excerpts. |

**Formal attempt 3 outcome: `FAILED_INCOMPLETE`.** The harness captured only part of the required service logs. Shutdown was verified. The maintainer's acceptance closes the four answer reviews. Eight embeddings and four chats were expected; the run had no enforced budget or independently verified call totals.

The public quickstart uses different fixtures: ORION is the recovery **code** for `demo-router-01`. In the live test ORION was the **asset**. The [walkthrough screenshots](ui-walkthrough.md) illustrate the UI using synthetic responses.

## Implementation and test history

- PR #22 (`fb1cb26`) added the managed library, read-only server roots, shared TXT/CSV/text-PDF parsing, persistent jobs and revision-safe replacement. Post-merge Python, document, Docker and Chromium checks passed. The container and browser checks used synthetic model services. [Operating guide](folder-library.md)
- PR #23 fixed out-of-order job selection, aligned actions with the displayed job, and separated API authentication from model and database readiness. A deployment label identifies configured mode. Model tags and database metadata can be checked before asking a question. [Historical live procedure](live-folder-ui-test-plan.md)
- Earlier scoped API, parser and synthetic checks are described in the [developer reference](developer-reference.md).

## Following task

Test retrieval with a modest set of competing documents. Include plausible distractors so the result limit excludes some chunks, then inspect which supporting excerpts are retrieved and cited. This task is pending. The completed four-chunk live demo used `top_k=5`, so every chunk could reach the model.

## Earlier development-set evaluation


The completed A/B pilot used one exposed development set: 12 answerable and eight
negative questions. Evidence and labels were AI-proposed development drafts;
Claude supplied the agent judgments. The pilot is closed.

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
