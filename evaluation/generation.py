"""A fail-closed protocol gate before semantic evaluation, not a quality judge."""


def is_completed_generation(result: dict) -> bool:
    """Only explicit nonempty, non-limited completion can proceed to review.

    False means incomplete/unknown evidence, not a wrong semantic answer. Even
    True still needs factual, citation and negative-answer review.
    """
    evidence = result.get("generation")
    answer = result.get("answer")
    return (
        isinstance(evidence, dict)
        and evidence.get("status") == "complete"
        and evidence.get("done") is True
        and evidence.get("done_reason") == "stop"
        and evidence.get("visible_empty") is False
        and isinstance(answer, str)
        and bool(answer.strip())
    )
