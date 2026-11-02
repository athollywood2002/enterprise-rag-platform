# Development pilot protocol — proposed, not executed

**Current authorization:** offline preparation, including 20 real draft questions
for independent review and a private canonical manifest, plus #73–#74 ODP revisions
and owner-authorship exercise preparation; no annotation/execution or publication.
The owner admitted the exact
vetted **NIST SP 800-171r3** PDF for development-pilot corpus use, conditionally
permitted compliant excerpt/label publication, and **deferred SP 800-190**. This
protocol links [draft-question review metadata](pilot-question-review.json) and blank recording
fields, **no gold excerpts or labels**. PR #12 remains draft/unmerged. No timer, annotation or
helper `add` session has been run for this pilot.
The 20 question texts and review pointers are in a private review packet, not Git;
the owner/independent reviewer receives that packet through the private relay.

## 1. Decisions and approval gates

See [admission metadata](pilot-admission.json) and
[screening evidence](nist-option-a-inspection.md). Historical inspection records
retain `admission=false` as facts about screening time; the new owner decision
supersedes them **only for this named development-pilot use**, not other candidates,
final evaluation, publication or operational use. The admission record is not a
`canonical-corpus-v2` manifest and cannot be used as CLI input.

1. **Authorized preparation:** #69–#72 manifest/drafts completed; independent review
   supported the original 12 answerable and eight negative drafts. Owner then approved
   #73–#74 preparation: replace D14/D16 with numerical ODP near-misses and prepare
   six owner paraphrases plus two required/one optional scratch-written substitutes.
   Eight owner submissions are now received (D01–D07 and D09), with original and
   AI-edited candidates preserved privately. None is selected/adopted into the
   working packet; all 20 active working questions remain agent-authored. Following
   independent review, the owner approved source-grounded AI-assisted proposals for
   these eight slots and D07 retargeting to 03.03.03. Proposals await owner selection.
2. **Owner contributions and independent check:** present the proposals for owner
   selection, then request independent review. Resolve wording selection and authorship
   before finalization; do not count AI-assisted proposals as independent owner
   writing or assume past timing exists. Preserve
   original/revised wording privately, revalidate the allocation, freeze the candidate packet hash
   and order FOR REVIEW, and request Claude Code Review of ALL 20 final questions,
   category validity, ODP negatives, authorship, provenance and rights. Any revision
   requires a new hash/review. Prior review does not approve new owner wording.
   Do not fabricate wording, writing time, quality assessments, approval or support.
3. **Owner execution decision:** after that check, owner explicitly authorizes
   actual annotation/timed execution and confirms the reviewed question version,
   corpus identity, rights and recording method. No further question-writing gate
   is required for these authorized drafts, but review is NOT execution permission.
4. **After a separately authorized run:** owner reviews failures and effort forecast and
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

**#72 prerequisite completed privately:** the existing offline extractor produced
a one-document `canonical-corpus-v2` manifest from the retained exact PDF; all 120
page hashes and parser identity match the vetted inventory, zero discrepancies,
498 mapped chunks. Strict corpus reload and read-only CLI display were validated.
See [manifest verification metadata](pilot-manifest-verification.json). The actual
manifest contains canonical text, is private/uncommitted and is not a holdout or
label file. File mode 0600 is an accidental-access measure, not same-account secrecy.

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
| 07–09 | answerable | identifier | dotted | 3 |
| 10 | answerable | identifier | padded | 1 |
| 11–12 | answerable | identifier | unpadded | 2 |
| 13–16 | near_miss | semantic | none required | 4 |
| 17 | near_miss | identifier | dotted | 1 |
| 18 | near_miss | identifier | unpadded | 1 |
| 19–20 | off_topic | semantic | none required | 2 |
| Total | 12 answerable / 6 near-miss / 2 off-topic | 8 identifier / 12 semantic | 4 dotted / 1 padded / 3 unpadded | **20** |

- Required fields remain explicit: category, query type, owner-assessed difficulty
  (`easy|medium|hard`) and tags. No invented difficulty or automatic defaults to
  make the mix look balanced; record actual judgments and explain any missing levels.
- Tag **the form in the question**, not the gold/source form: `id-dotted`,
  `id-padded` or `id-unpadded`, exclusively for these eight slots. Examples:
  `03.01.01`, `AC-02(04)` versus `AC-2(4)`. Native dotted IDs are not padding
  variants. Mixed-form questions or a changed allocation require review.
  At one to three items per category/form cell, this is workflow coverage,
  not a statistically meaningful comparison of identifier forms (#69).
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
  The proposed run uses **prewritten, independently checked, owner-approved questions**, with their
  draft version/hash recorded separately. No unreviewed rewrite during the run;
  mark an invalid item blocked and request review.

## 4. Annotation instructions — only after execution approval

### Preparation changes #73–#74 (not annotation)

**ODP negatives:** D14 and D16 retain their proposed semantic near-miss categories.
Following #76, neutral questions about event-type and facility-access-list review
frequency replace the leading fixed-number wording. These are agent edits, not
owner contributions. The requirement contexts (physical pages 31 and 60),
discussions (31–32 and 60–61), full-corpus phrase contexts and Appendix D entries
`03.03.01.b` (116) / `03.10.01.c` (117) delegate frequency to the organization;
retained canonical and pypdf text were cross-checked. No fixed numerical day value
was identified. This is not absence of the topic: the missing fact is the requested
NIST numerical value under the original rationale. Independent review confirmed
that neutral wording permits a supported organization-defined response. The owner
approved retaining D14/D16 as `near_miss` under this explicit **pilot convention**:
the intended response states that the numeric interval is not specified / is
organization-defined; a concrete NIST-prescribed interval is unsupported. No gold
spans are created for these two items. This does not claim their source topic or
frequency clause is absent, and is not a general semantic reclassification rule.
Revisit the convention in G1(c) before baseline scoring; do not apply it silently
to D07's answerable policy-linked retention question.
Do not invent annual/90-day defaults or import outside policy.
The intended abstention disposition is **not specified; organization-defined**,
not a gold label or measured score. The existing abstention-evaluation allowlist
is UNCHANGED; any metrics addition needs separate review before a baseline.

**Owner exercise:** paraphrase D01–D06 (six answerable semantic slots); scratch-write
substitutes for D07 and D09 (answerable dotted-ID slots), optionally D12 (answerable
unpadded-ID slot). Use the private worksheet's physical-page pointers. These are
replacements, not additional slots. Read the context, put it aside, then write in
the owner's own words; do not copy source clauses or supply excerpts/answers/spans.
Record prior draft exposure honestly; no blind-authorship or lexical-leakage-removal
claim. Preserve D05's initial-training scope and independently check any changed
fact/form. If a supported substitute is not feasible, flag the slot for review.

Private provenance retains original agent wording, prior/current agent revisions,
eight verbatim owner submissions (including clarification) and nine AI-edited
variants. Owner originals have owner origin; task validity is not assumed. AI edits
are agent wording derived from owner input, not exclusively human-written. Record
prior exposure/editorial coaching and mixed-editing derivation separately; the
`agent|owner|owner-paraphrased` enum alone is insufficient for that history.
All 20 current working-packet questions remain `agent`; accepted owner replacements
are zero pending selection/support review. D12 was not attempted. Owner start/finish
timestamps are null and writing time is **NOT RECORDED**, never backfilled from the
relay timestamp or estimated. Owner approvals remain unset; implementer triage is
not an owner quality assessment or independent review.

**Owner-approved follow-up plan:** preserve the earlier implementer matrix as
history, but supersede its requirement to rewrite D07 around 03.03.02. Independent
review found the owner's retention-policy intent supported by **03.03.03.b on
physical page 33**. Retarget D07 there, still answerable / identifier / `id-dotted`,
without inventing a fixed retention duration or auditing actual configurations.
D04's authorized-media-access intent is supported by 03.08.02 on page 55; propose
that scope instead of forcing cryptography-only wording. D09's proposed question
keeps 03.08.03, without DoD/vendor obligations. D01–D06 receive source-grounded
candidate wording; D05 stays limited to initial training. All eight proposals are
AI-assisted and owner-derived, not independently owner-written. Present exact
wording and physical-page pointers privately for owner selection or edits.

Retain all eight practitioner originals and their earlier AI edits separately in a
private **potential near-miss reserve** for later development only. They are not
verified negatives, labels, holdout material, automatically admitted bulk data or
extra pilot slots. The standard/practitioner implementation gap is a source-scope
finding, not a writing failure. No reserve publication or corporate data access.
Owner choices/edits remain unset; no proposal is silently adopted or frozen.
Working-revision hashing is NOT the final candidate freeze. Source/page hashes,
conditional publication, development-only use and all execution gates are unchanged.

### Later authorized annotation

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
   retries in the minimal log and summarize unusual ambiguity in `note`. Earlier
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

Use only this **header-only template** after execution approval (#70); no real
timing records exist now:

```csv
slot,dev_id,author,start,saved,checked,retries,blocked,note
```

- `start`: begin reading/reviewing the approved question; `saved`: save confirmed;
  `checked`: post-save schema/source and human support/absence check completed, or
  the blocked/cancelled attempt closed (state that disposition in `note`, not
  a claim that the item passed validation).
  Use one clock/time zone and ISO timestamps including seconds. Leave an
  unobserved timestamp empty; never invent a save time for a blocked/cancelled item.
- `author`: actual wording provenance, `agent`, `owner` (scratch-written substitute)
  or `owner-paraphrased`; requested work does not change current authorship.
- `retries`: total rejected input/excerpt attempts for the item, including duplicate
  IDs. `blocked`: `y` or `n`. Use `note` for cancellation, pauses, unusual match
  counts, repeated source IDs, multi-span difficulty, rights flags or interruption.
  No extra mandatory per-item friction form or five-timestamp transcription.
- Session metadata once: code/runtime/parser/normalization, source/corpus hashes,
  approved draft version/order, clock/time zone, setup and familiarization effort.
  Keep question drafting and owner draft-review effort **separate** from entry
  timing; no drafting time has been measured by this preparation. Agent-assisted
  drafts do not imply zero human writing/review cost for a future dataset.
- Report `checked-start` end-to-end and `saved-start` entry/save time where observed.
  Log external interruptions in `note`; show gross time and any explicitly justified
  pause-adjusted total, not invented fine-grained phase durations. Include blocked/
  cancelled effort. Logging overhead itself is part of measured session effort.
- CLI diagnostics already show ambiguity and match counts. Any later diagnostic
  capture must stay private and be owner-approved, since it may contain canonical
  text. Do not add automatic transcript capture or a `--timing-log` feature here.

Keep the authorized owner-writing exercise in a separate private drafting record:

```csv
slot,author,start,finished,note
```

Start before reading the context for that task; finish when replacement wording is
ready. Use one clock/time zone and ISO timestamps including seconds; note pauses,
restarts, prior exposure and uncertainty. Leave unobserved times unrecorded, not
estimated. Preserve actual owner wording separately, and measure later draft-review
effort separately. The eight received submissions have no observed writing times;
do not retroactively fill this log. Human difficulty remains unassessed.

## 6. Owner debrief, limits and next decision

After a separately authorized run, report planned/attempted/saved/blocked/cancelled
counts, observed mix, gross totals and pause-adjusted totals only where pauses were
actually recorded, median and range by category/form where
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

**Next gates:** owner selects or edits the eight AI-assisted proposals (D07 now
03.03.03); preserve actual choice, wording derivation and any prospectively observed
new writing times, never backfilling first-attempt times;
then candidate hash/order freeze and independent review of ALL 20 final questions;
then a separate owner decision on annotation/timed execution/publication.
No live API/model/GPU/Docker/Qdrant actions,
downloads, merges or changes to retained source/manifest evidence. Rollback: reviewed revert of this
preparation metadata/docs; historical screening and runtime behavior stay unchanged.
