# Offline abstention regression

The Phase 1 synthetic run returned “The provided excerpts do not mention …”.
Its temporary regex recognized “not mentioned” but missed “do not mention”.
Manual review established abstention; the original stopped evidence is preserved
outside this repository. This change does not change that historical result.

`evaluation/abstention.py` is an offline, standard-library-only check. It has no
connection to the API, model, retrieval code, or live ingestion scripts. It accepts
a small allowlist of complete abstention sentences, optionally followed by numeric
citations. Topic-specific forms must match the literal, caller-configured topic.
Case, whitespace and curly apostrophes are normalized. Extra claims, guesses,
quoted abstention phrases and bare negation fragments do not pass.

From the repository root, with project development dependencies installed:

```bash
python -m pytest -q tests/test_abstention.py
python -m evaluation.abstention tests/fixtures/synthetic_abstention.json
```

The fixture contains only the preserved synthetic answer and its expected topic,
not raw logs, endpoints, keys, or private system metadata. The CLI reports
`mode=offline_response_replay`, not a live E2E result. Exit codes: 0 recognized
abstention, 1 unrecognized answer, 2 invalid/unreadable fixture. Tests run under
the existing network/database-blocking fixtures.

This is intentionally conservative. Unrecognized wording needs manual review;
false negatives are possible. Passing recognizes wording only: it does not prove
the question is unanswerable, validate citations, judge factual grounding, or
protect against arbitrary adversarial text. The topic is trusted test
configuration, never extracted from a candidate answer. Generic “I don't know”
forms are accepted without judging whether they answer the right question.

No full live E2E rerun is needed for this regression. Do not reingest or change
retained test services. Review/rollback is limited to these evaluation files,
their fixture and tests; application behavior is unchanged. Broader evaluation,
metrics, benchmarks, observability and packaging remain deferred.
