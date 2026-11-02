# Development pilot protocol — proposed, not executed

**Current authorization:** offline preparation only. The owner admitted the exact
vetted **NIST SP 800-171r3** PDF for development-pilot corpus use, conditionally
permitted compliant excerpt/label publication, and **deferred SP 800-190**. This
protocol contains allocation slots and blank recording fields, **no real questions,
gold excerpts or labels**. PR #12 remains draft/unmerged. No timer, annotation or
helper `add` session has been run for this pilot.

## 1. Decisions and approval gates

See [admission metadata](pilot-admission.json) and
[screening evidence](nist-option-a-inspection.md). Historical inspection records
retain `admission=false` as facts about screening time; the new owner decision
supersedes them **only for this named development-pilot use**, not other candidates,
final evaluation, publication or operational use. The admission record is not a
`canonical-corpus-v2` manifest and cannot be used as CLI input.

1. **Now:** independent Code Review assesses this protocol, admission/publishing
   boundaries and feasibility of the proposed mix. Owner reviews the precise
   protocol and decides whether to authorize real-question writing. No agents
   generate actual questions, excerpts or labels in this preparation.
2. **After separate writing permission:** owner drafts a proposed 20-question
   allocation using admitted source material, without running the timed pilot or
   treating the draft as verified gold. Submit the actual proposed questions and
   any requested deviations for owner approval before annotation. Do not fabricate
   supporting passages to fill a quota. Record drafting effort separately, so a
   later prewritten-question entry session does not hide writing costs. Agent
   participation requires explicit scope.
3. **Before execution:** owner explicitly authorizes actual annotation and timed
   execution, confirms the reviewed question-writing plan, corpus identity, rights
   and recording method. Admission and protocol approval alone are not execution
   permission. This delivery supplies no runnable canonical corpus or label file.
4. **After execution:** owner reviews results, failures and effort forecast and
   decides go/revise/stop before bulk annotation. No automatic scale-up, baseline,
   holdout freeze or final evaluation follows.

G1(c) synthetic evaluation is separately permitted and pending. It is not needed
to time owner annotation, but must be reviewed before a measured baseline. G1(d)
remains unstarted. No downloads, models, runtime services or protected holdout work
are part of this protocol's preparation or proposed pilot workflow.

## 2. Fixed source and rights/publication boundary (#67)

Only `nist-sp800-171r3`, May 2024 final:

```text
source bytes: 1,593,213; physical pages: 120
SHA-256: 3e4631df8b5d61f40a6e542b52779ef30ddbbfff31e09214fa94ad6e6f5e6d08
parser: unstructured-pdf-fast-v1
normalization: nfc-quotes-artifacts-whitespace-v2
```

Retain exact title/revision/source URL, source hash, parser package/Unicode identity,
canonical corpus hash and every physical page's canonical hash. Compare all 120 page
hashes with the vetted inventory under its recorded runtime before future annotation.
Stop on drift; no silent re-extraction repair, source replacement or offset migration.
The existing vetted runtime found raw-partition Cf and canonical Cf/Cc = zero (#62).
That finding is file/runtime-specific, not permission to skip future validation.

Citation to retain with any approved exported excerpts/labels:

> Ross R, Pillitteri V (2024), *Protecting Controlled Unclassified Information in
> Nonfederal Systems and Organizations*, NIST SP 800-171r3, National Institute of
> Standards and Technology, Gaithersburg, MD.
> https://doi.org/10.6028/NIST.SP.800-171r3 (accessed 2026-11-02).
> Republished courtesy of the National Institute of Standards and Technology.

Physical page 3 states no copyright in the United States and requests attribution.
Owner permits excerpts/labels **only insofar as compliant with applicable rights
and attribution**. This is not a worldwide/CC0 or all-included-material grant.
Flag independently owned or unclear third-party material; do not publish or use
uncleared material as gold pending review. Source-use admission is distinct from
per-record publication eligibility and from approval to actually publish anything.
Record a separate publication-review decision for each eventual question/span:
`pending`, `eligible-with-attribution`, or `withheld-for-rights-review`, with reason.
These are sidecar fields, not new fields added to the strict label schema.

No raw PDFs, diagrams, screenshots, future labels or timing logs are committed by
this preparation. Private retention is not proof of secrecy. Do not add SP 800-190
or a fallback: its 61-page margin noise, missing figure labels and rights review
remain deferred. #68 noise detection and any versioned serving/evaluation noise
policy are separate future review items, not silent preprocessing.

## 3. Proposed 20-slot allocation (#66)

The following is a **design target for owner review**, not an annotated dataset.
Slot ranges are ordering placeholders, not query IDs or real question records.

| Slots | Category | Query type | Question identifier form | Count |
| --- | --- | --- | --- | ---: |
| 01–06 | answerable | semantic | none required | 6 |
| 07–09 | answerable | identifier | padded | 3 |
| 10–12 | answerable | identifier | unpadded | 3 |
| 13–16 | near_miss | semantic | none required | 4 |
| 17 | near_miss | identifier | padded | 1 |
| 18 | near_miss | identifier | unpadded | 1 |
| 19–20 | off_topic | semantic | none required | 2 |
| Total | 12 answerable / 6 near-miss / 2 off-topic | 8 identifier / 12 semantic | 4 padded / 4 unpadded | **20** |

- Required fields remain explicit: category, query type, owner-assessed difficulty
  (`easy|medium|hard`) and tags. No invented difficulty or automatic defaults to
  make the mix look balanced; record actual judgments and explain any missing levels.
- Tag **the form in the question**, not the gold/source form: `id-padded` or
  `id-unpadded`, exclusively for these eight slots. Examples of notation only:
  `AC-02(04)` versus `AC-2(4)`. Dotted requirement notation such as `03.01.01`
  is distinct; do not mislabel it padded/unpadded. If dotted-only or mixed-form
  slots are wanted, propose a revised allocation/tag rule for owner approval first.
- Do not rewrite canonical source, excerpts or questions through an automatic ID
  normalizer. Correspondence between forms must be checked by the owner, not
  inferred from string stripping. Query-time normalization is a later P2-B variant.
- **A spelling/padding difference alone never makes a near-miss.** A genuine
  near-miss concerns a related subject but a specific unsupported fact. Check the
  whole admitted corpus and alternate identifier forms before calling it absent.
  Off-topic means no relevant subject in the admitted corpus, not merely a failed
  search or absent literal token. Do not consult other documents to manufacture gold.
- Spread answerable candidates across at least four requirement families and six
  physical pages where feasible; prefer prose with independently verifiable support.
  Do not cluster 20 prompts on one paragraph or count repeated/cross-referenced IDs
  as independent facts. Record source reuse. Use different facts across ID forms
  where possible; if same-fact pairs are approved, flag them and report familiarity
  effects instead of claiming independent difficulty or form superiority.
- Feasibility is a review gate: some control IDs occur only in flattened appendix
  tables. Do not invent prose support or row relationships to satisfy the six
  answerable form slots. If support depends solely on an unreliable table mapping,
  mark the slot blocked and request a mix/source decision before timing. This plan
  does not promise every slot can be filled from the current extraction.
- Freeze the approved slot order before execution, interleaving categories/forms
  rather than completing easy items first. Record the chosen permutation and any
  departure. No post-hoc replacements or order changes to improve timing results.
  The proposed run uses **owner-prewritten, owner-approved questions**, with their
  draft version/hash recorded separately. No unreviewed rewrite during the run;
  mark an invalid item blocked and request review.

## 4. Annotation instructions — only after execution approval

Use the merged PDF-only helper as documented in [labeling-cli.md](labeling-cli.md).
It displays wrapped canonical page text, writes uniquely matched normalized spans
and saves **development drafts**, not human-review claims. Do not run `add` now.

For each authorized question:

1. Use the approved development manifest and private development output path,
   distinct from source and Git metadata. Record reviewed code commit, corpus hash
   and question reference in the separate timing/publication sidecar. Never use a
   holdout path or mark pilot records as held-out. Avoid symlink aliases on macOS.
2. Owner supplies ID, actual question, explicit category/type/difficulty and tags.
   Use a unique owner-assigned development ID. The CLI checks duplicates early,
   suggests an unused ID and repeats save-time checks; do not bypass them.
3. For answerable items select exact document/version and **physical** page.
   Copy from canonical display, not PDF-viewer layout. Wrapped newlines normalize
   safely; identifiers must not be manually repaired. Select minimal sufficient
   supporting text, not a whole-page excerpt to avoid ambiguity.
4. An ambiguous/missing/empty match retries only the current span. Record reported
   match count, retry count, why a longer excerpt was needed and time spent. Earlier
   fields/spans are retained. Do not pick the first repeated ID arbitrarily; verify
   the actual prose location. Multiple disjoint spans are allowed where genuinely
   necessary; overlapping/duplicate spans are rejected. Record multi-span friction.
5. Verify stored source hash, page hash, half-open Unicode code-point bounds and
   normalized excerpt agreement using existing development loaders after saving.
   Location correctness is not semantic support: owner separately checks that the
   passage actually answers the question. The CLI does not set `human_reviewed`.
6. Near-miss/off-topic records have **no gold spans**. Record the owner's absence
   check scope, alternate forms checked and rationale separately; no fabricated
   negative excerpt or claim that the CLI proves unanswerability.
7. Confirm save explicitly. On interruption during save, inspect the output before
   retrying because an atomic commit may have happened. Count interrupted/abandoned
   attempts and their time; never silently drop them. No automated promotion to
   human-reviewed status, cleanup or publication is part of the helper/pilot plan.

Known limitations (#58) remain measurement inputs: Table 3 physical page 103
flattens columns; source ID/title and later clauses can occupy different chunks.
Gold is canonical-page location, not a chunk ID. Do not alter source/chunking to
make a question easier or infer row-based facts from flattened text. If ambiguity,
format controls, rights uncertainty, hash drift or semantic loss prevents valid
labeling, stop that item and log a blocker; request review rather than silently
replacing or misclassifying it. No real retrieval/inference is needed to time this.

## 5. Timing and friction record template

Record manually with a stopwatch/clock and a private text sidecar; no new service,
background timer or browser/model tool. This blank field list is **not** a label
file and contains no populated question or span. Define one clock source/time zone
and units (seconds), and preserve wall time and interruption time separately.

| Field | Record after authorization |
| --- | --- |
| Session | date, code commit, parser/normalization/runtime, corpus SHA-256, source SHA-256, approved order, tool/output setup |
| Slot/reference | approved slot, owner-assigned development ID, category/type/difficulty, form tags, source-family/page reuse flags |
| Preparation time | session setup/synthetic familiarization and earlier authorized question drafting separately |
| t0 | begin reading/reviewing the prewritten, approved question |
| t1 | question/category/type/difficulty finalized for entry |
| t2 | first canonical page opened or negative-corpus verification begun |
| t3 | save confirmed (or cancellation/blocker recorded) |
| t4 | post-save schema/source and human support/absence check completed |
| Pauses | interruption seconds/reason; keep gross wall time as well as net active time |
| Friction | choice/number retries, duplicate-ID rejection, excerpt match counts/retries, repeated source IDs, page navigation, multi-span attempts, lock/save/interruption errors |
| Outcome | saved-draft / cancelled / blocked; sidecar publication eligibility and rights reason; owner semantic-check status, not automatic human-review promotion |

Use `t4-t0` gross end-to-end time, minus explicitly recorded external interruption
seconds for active time. Report `t1-t0` question review, `t3-t1` verification/entry/
save and `t4-t3` post-save check, plus separate session overhead. If drafts were
prepared outside the timed entry session, include that drafting time separately in the effort
forecast; do not compare a prewritten-question entry time with a full writing and
labeling budget. No zero/blank timing value should be invented when a stage is not
observed. Record terminal work within entry time; a session or item blocked before
save still consumes effort.

## 6. Owner debrief, limits and next decision

After a separately authorized run, report planned/attempted/saved/blocked/cancelled
counts, observed mix, wall/active totals, median and range by category/form where
sample size permits, retry/ambiguity and validation failures, repeated-fact effects
and rights-withheld items. All durations and counts remain **not measured** now.
Twenty convenience items from one source are a usability/effort pilot, not a
retrieval benchmark, statistically powered identifier comparison or independent
quality sample. A single annotator and correlated questions are explicit limits.

Reforecast bulk work as fixed overhead plus observed per-stratum active time times
the proposed remaining stratum counts, including separately measured drafting,
verification, retries and later grading/audit effort. Show sensitivity to slow/blocked
items and unknown work; do not promise a lower budget or extrapolate a precise
confidence interval from 20 items. Generation grading is not measured in this pilot.

Owner decides go/revise/stop after reviewing friction and correctness. Require no
unresolved source/hash/schema/rights/semantic-support failures before scale-up;
budget tolerance and any revised mix need owner approval. Do not turn failed slots
into successful annotations or fix normalization without dedicated review.

All pilot questions are development data. This source/revision family is exposed
for development and must not later be split into a supposedly blind holdout group.
A single admitted document does not solve the final grouped/stratified dataset or
cluster-bootstrap requirements. No holdout files, paths, keys or commitments are
created, inspected or requested. Later blind self-relabel audit and final evaluation
need separate owner-controlled workflows; no secrecy claim from same-account paths.

**Next gate:** independent Code Review plus owner decision on this protocol and
permission for actual question writing. No source/API/model/GPU/Docker/Qdrant actions,
downloads, merges or retained-artifact changes. Rollback: reviewed revert of this
preparation metadata/docs; historical screening and runtime behavior stay unchanged.
