"""Conservative abstention wording check, not a semantic groundedness judge."""

import argparse
import json
import re
from pathlib import Path


def _normalize(text: str) -> str:
    return " ".join(text.replace("’", "'").casefold().split())


def is_abstention(answer: str, *, topic: str) -> bool:
    """Match a small allowlist of whole answers, rejecting extra factual clauses.

    Topic is trusted evaluation configuration, not text inferred from the answer.
    Unsupported paraphrases fail closed and need manual review. Trailing positive
    numeric citations are allowed syntactically, but their grounding is NOT checked.
    """
    subject = _normalize(topic)
    if not subject:
        return False
    subject = re.escape(subject)
    context = r"(?:the )?(?:provided )?(?:excerpts|sources|context)"
    patterns = (
        rf"{subject} is not (?:mentioned|specified|provided|stated|available) in {context}",
        (
            rf"{context} (?:do not|don't|does not|doesn't) "
            rf"(?:mention|specify|state|provide|contain) {subject}"
        ),
        r"i (?:do not|don't) know(?: the answer)?",
        r"i don't know based on the available documents",
        rf"i (?:cannot|can't) determine the answer from {context}",
        rf"there is insufficient information in {context} to answer",
    )
    # Full-match is deliberate: a negation keyword within a hallucinated answer
    # or an abstention followed by a guess must not earn a pass.
    return any(
        re.fullmatch(pattern + r"\.?(?:\s*\[[1-9]\d*\])*", _normalize(answer)) is not None
        for pattern in patterns
    )


def main() -> int:
    """Replay a local {answer, topic} fixture without loading services or secrets."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    args = parser.parse_args()
    try:
        case = json.loads(args.fixture.read_text())
        if not isinstance(case, dict) or not all(
            isinstance(case.get(key), str) for key in ("answer", "topic")
        ):
            raise ValueError("Invalid fixture")
        passed = is_abstention(case["answer"], topic=case["topic"])
    except (OSError, ValueError):
        print("Invalid local fixture; expected JSON string fields answer and topic")
        return 2
    print(json.dumps({"mode": "offline_response_replay", "abstention_detected": passed}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
