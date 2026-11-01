# Offline PDF development-labeling CLI (G1(b))

This is G1(b), the labeling helper—not G1b corpus acquisition. It is proposed
for independent review before real use. Implementation/tests use synthetic
manifests and simulated keystrokes, not real annotation. It makes no network,
parser, model or database calls, and starts no listener.

## Inputs and gates

Run from the repository root in the installed development environment:

```bash
python -m evaluation.label --help
python -m evaluation.label show --corpus /owner/development/corpus.json \
  --doc-id example --doc-version SOURCE_BYTES_SHA256 --page 1
python -m evaluation.label add --corpus /owner/development/corpus.json \
  --output /owner/development/labels.json
```

Paths/IDs above are placeholders, not an approved corpus. Provide an explicitly
rights-admitted **development PDF** `canonical-corpus-v2` manifest. This stage
refuses logical/Markdown pages, even in a mixed manifest. Markdown helper support
is a separate follow-up; the merged parser/preprocessor approval does not itself
select or rights-admit a corpus. NIST/public-source acquisition, owner selection,
the timed human annotation pilot and real labels are not delivered here.

The CLI consumes supplied canonical JSON, not PDFs. It does not fetch sources,
parse new documents, infer rights, search folders, generate questions or
excerpts, split a dataset, or set up a holdout. Corpus/page hashes and exact
normalization are validated by existing loaders; drift is rejected, not repaired.
Missing schema tags, duplicate JSON keys and extra fields are rejected.

## One draft question at a time

`show` displays the normalized canonical page with document version,
physical page number and page hash. Copy **this text**, not a PDF viewer's text.
Terminal control/format characters are refused rather than rewritten, so displayed
text and code-point offsets cannot silently diverge. Page text wraps at 88 columns
for display only, without breaking words or identifiers at hyphens. A longer token
can exceed 88 columns. Copying wrapped lines is safe: excerpt normalization turns
those line breaks back into spaces. Stored canonical text, hashes and offsets do
not change.

`add` prompts for query ID, question, category, **required explicit question type**
(`identifier|semantic|mixed`), **required difficulty** (`easy|medium|hard`) and
optional unique identifier tags. No type/difficulty is silently defaulted.
Choices are case-insensitive. Invalid choices, numeric selections, IDs, questions
and tags retry in place without discarding earlier answers or echoing bad input.
Existing development output is validated before prompting. Duplicate query IDs
are rejected when entered, with a next-free `dev-NNNN` suggestion (not an automatic
assignment). Save-time validation still rejects duplicates introduced concurrently.

For `answerable`, choose an explicitly listed document/version and physical page.
The helper displays that canonical page, then accepts a pasted excerpt until a
line containing only `.`. It normalizes the paste under the corpus policy and
requires **exactly one** page-local match, including overlapping matches when
checking ambiguity. Empty/missing/ambiguous text reports status and match count
and retries **that span only**; use a longer excerpt instead of accepting an
arbitrary occurrence. Earlier fields and accepted spans are retained.
Duplicate/overlapping spans also retry in place. Oversized excerpts remain a
fail-closed session error instead of consuming unbounded input. It stores half-open code-point
offsets, normalized excerpt, source version and page hash. It never relocates
existing gold automatically. You can explicitly add more supporting spans;
duplicate/overlapping gold is rejected by the schema.

`near_miss` and `off_topic` never prompt for or create gold spans. All new records
have `review_status: draft`. Owner entry and valid offsets do **not** imply
human-reviewed semantic correctness. Promotion to human-reviewed status is outside
this helper. A final explicit `yes` saves one draft; other confirmation cancels.
EOF/Ctrl-C before saving writes no labels. If interrupted during final save, the
CLI tells the owner to inspect the output before retrying: an atomic commit may
already have happened. Do not blindly retry a query ID.

## Development-only storage and safe updates

Default output is `.local/evaluation/development-labels.json`, relative to the
current working directory. This repository ignores `/.local/evaluation/`;
other repositories may not. Prefer an explicit owner-controlled private
development path for real use, and review `git status` before committing anything.
No real development artifacts are committed by this implementation.

The supplied corpus is reloaded and its identity checked before saving; changes
during the prompt session abort. Existing output must be valid `span-labels-v2`, **development** split, matching
the supplied corpus identity. The helper preserves existing questions and appends
one new draft. Duplicate query IDs, schema violations, old gold drift, foreign
corpus identities, heldout markers or unrelated file content abort without replacing
that label file. Nested models are serialized/revalidated before writing.

POSIX/macOS/Linux only: use a cooperative nonblocking `flock` on an adjacent
`.lock` file; write a same-directory private staging file, flush/fsync, then
atomically replace output. New output/staging/lock files use mode 0600; a newly
created leaf output directory uses 0700. Existing directories/ACLs are not explicitly
modified; replaced output takes staging-file metadata, so prior file ACLs are not
promised to be retained. Modes alone are not proof of confidentiality.
The helper removes only its own staging file on failure; the lock file can remain.
Label-file errors do not guarantee zero filesystem side effects (e.g. a newly
created directory/lock). No background process or listener remains.

Do not edit the same output concurrently with external tools. Cooperating CLI
writers are locked and detected external content changes abort before replacement,
but noncooperating races/hostile same-account processes are **not** protected.
Atomic replacement is not a backup, anti-tampering control or power-loss durability
claim. Back up valuable development labels under an owner-approved workflow;
this task does not authorize backup/cleanup of existing artifacts.

Require explicit `.json` input/output, bounded regular files (16 MiB), reject
symlink paths/components, Git metadata paths and names suggesting holdout storage.
Final data-file opens use `O_NOFOLLOW`; parent checks are accidental-use guards,
not an adversarial filesystem sandbox. Invalid payloads are not echoed in errors.

## Holdout is not implemented

Only `--split development` exists. `holdout`, `heldout`, `test` or any other split
is rejected by argument parsing **before file I/O**, including repo/worktree output
requests. Holdout-named input/output paths are also refused. Tests simulate both
normal repositories and linked worktrees; they do not create real holdout data.

Filename/schema checks, `.gitignore`, file modes and paths under the same OS user
do **not** establish secrecy from an agent or another process with that user's
access. A neutral filename can still contain sensitive data. Do not point this
helper or an agent session at holdout data, encrypted files, keys or unrelated
private files. Real holdout requires owner-controlled encryption/key custody
outside the agent session or a separate account/machine, with separate approval
for final evaluation. No key/passphrase, encryption/decryption, holdout output,
commitment creation or hidden-file discovery is provided here.

## Separate follow-ups (not implemented)

- #61: optional batch-entry loop; still one question per invocation.
- #62: count Unicode `Cf` characters per page during any separately approved NIST
  canonicalization. Direction marks/word joiners may block terminal display.
  Decide any normalization-v3 or placeholder policy before real labeling through
  dedicated review; this change does not alter normalization or the control guard.
- #63: macOS `/tmp` and `/var` are symlink aliases and are refused by path guards.
  Use an explicit non-symlink physical path (e.g. under `/private/...`) instead;
  do not relax the guard or infer holdout secrecy from that path.
- Optional excerpt `find`/context search is outside this correction.

## Verification and rollback

```bash
python -m pytest -q tests/test_label_cli.py
python -m pytest -q --run-document-tests
python -m ruff check .
python -m ruff format --check .
```

Tests use authored synthetic manifests and simulated owner input under existing
network/database guards. They cover exact display/Unicode spans, multispans,
explicit strata, ambiguity, cancellation, draft-only updates, existing-data/drift
preservation, safe paths, simulated lock/replace failures and interruption after
commit. They do not prove holdout isolation or label quality.

Decision: plain CLI and development-only schema; no web/notebook, automatic corpus
discovery, generated gold or real holdout workflow. Keep PDF-only scope until its
own review. G1(c) metrics/splits, #52 chunk-map work, #55 Markdown partitioner
guard and G1(d) Compose remain separate. Rollback by reviewed revert of helper,
tests/docs and dedicated ignore rule; no serving, storage or index migration.
