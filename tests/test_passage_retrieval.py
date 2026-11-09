from types import SimpleNamespace

from rag.retrieval import lexical_rank, managed_candidates


def point(i, text, revision="active"):
    return SimpleNamespace(id=i, payload={"text": text, "revision": revision})


def test_answer_bearing_action_passage_outscores_same_document_timeline():
    # The relevant document alone is insufficient: discriminate its actual passages.
    timeline = point(
        1, "October 14 incident: service restored. Timeline: alerts, mitigation, recovery."
    )
    action = point(
        2,
        "Follow-up actions as of November 9: ACT-303 regional export queue-age dashboard remains open. Owner Amara. Due November 15.",
    )
    runbook = point(3, "Incident closure requires a postmortem and a follow-up review.")
    ranked = lexical_rank(
        "Which October 14 incident follow-up remained open on November 9?",
        [timeline, action, runbook],
    )
    assert ranked[0] is action


def test_lexical_candidate_can_recover_passage_absent_from_dense_results():
    answer = point(2, "Regional dashboard follow-up remains open November 9")
    dense = point(1, "Generic incident timeline")

    class DB:
        def scroll(self, **kwargs):
            assert kwargs["scroll_filter"] == "active-revisions-only"
            return [answer, dense], None

    result, evidence = managed_candidates(
        DB(),
        "library",
        "Regional dashboard follow-up open November 9",
        [dense],
        "active-revisions-only",
        2,
    )
    assert any(p.payload == answer.payload for p in result)
    assert not evidence["claim_support_verified"]
    assert not evidence["lexical_scan_truncated"]
