import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from evaluation.abstention import is_abstention, main
from rag.config import Settings
from rag.core import RagEngine

TOPIC = "the color of the Helios team's uniform"


@pytest.mark.parametrize(
    "answer",
    [
        f"{TOPIC} is not mentioned in the provided excerpts.",
        f"{TOPIC} is not specified in the context. [1]",
        f"{TOPIC} is not provided in the provided sources.",
        f"The provided excerpts do not mention {TOPIC}. [1][2]",
        f"The excerpts don't specify {TOPIC}.",
        f"The provided sources do not state {TOPIC}.",
        f"The context does not provide {TOPIC}.",
        "I do not know.",
        "I don't know the answer.",
        "I cannot determine the answer from the provided excerpts.",
        "There is insufficient information in the provided excerpts to answer.",
        "  I DON'T KNOW.  [1] [2]  ",
        "I don’t know.",
        "I don't know based on the available documents.",
    ],
)
def test_clear_abstentions(answer):
    assert is_abstention(answer, topic=TOPIC)


@pytest.mark.parametrize(
    "answer",
    [
        "",
        "   ",
        "[1][2]",
        "The uniform is blue. [1]",
        "The answer is 23 minutes.",
        "Blue",
        "Not mentioned",
        "I know the answer.",
        "The provided excerpts mention the color is blue.",
        f"The excerpts do not mention {TOPIC}, but it is blue.",
        f"The excerpts do not mention {TOPIC}. It is blue.",
        f"The uniform is blue. The excerpts do not mention {TOPIC}.",
        "I don't know. My guess is blue.",
        "I don't know whether it is blue.",
        "It is not mentioned that the uniform is blue, but it is green.",
        "The provided excerpts do not mention the station location.",
        'The phrase "I do not know" appears in the text. The uniform is blue.',
        "<think>I don't know.</think>The uniform is blue.",
        "I don't know. [0]",
        "I don't know. [x]",
        "I don't know based on the available documents. The uniform is blue.",
        "The uniform is blue. I don't know based on the available documents.",
        "I don't know based on the available documents, but my guess is blue.",
    ],
)
def test_non_abstentions_and_mixed_claims_fail(answer):
    assert not is_abstention(answer, topic=TOPIC)


def test_topic_is_literal_not_regex():
    assert not is_abstention("The context does not mention anything.", topic=".*")


def test_empty_topic_fails_closed():
    assert not is_abstention("I don't know.", topic=" ")


@pytest.mark.parametrize("collection_exists", [False, True])
def test_application_fallback_stays_recognized(collection_exists):
    """Exercise both actual fallback branches so evaluator wording cannot drift."""
    database = Mock()
    database.collection_exists.return_value = collection_exists
    database.query_points.return_value = Mock(points=[])
    engine = RagEngine(
        Settings(
            _env_file=None,
            api_key="synthetic-unit-test-only",
            qdrant_collection="synthetic_abstention_unit_test",
        ),
        qdrant=database,
    )
    engine.embed = Mock(return_value=[0.1, 0.2])
    result = engine.ask("What color is the synthetic uniform?")
    assert result == {
        "answer": "I don't know based on the available documents.",
        "sources": [],
    }
    assert is_abstention(result["answer"], topic=TOPIC)
    if collection_exists:
        database.query_points.assert_called_once()
    else:
        database.query_points.assert_not_called()


def test_preserved_synthetic_response_replay():
    fixture = Path(__file__).parent / "fixtures/synthetic_abstention.json"
    case = json.loads(fixture.read_text())
    assert is_abstention(case["answer"], topic=case["topic"])


@pytest.mark.parametrize(
    ("contents", "expected"),
    [
        (json.dumps({"answer": "I don't know.", "topic": TOPIC}), 0),
        (json.dumps({"answer": "Blue.", "topic": TOPIC}), 1),
        ("not json", 2),
        ("[]", 2),
        ('{"answer": null, "topic": "color"}', 2),
    ],
)
def test_replay_cli(tmp_path, monkeypatch, capsys, contents, expected):
    fixture = tmp_path / "case.json"
    fixture.write_text(contents)
    monkeypatch.setattr("sys.argv", ["abstention", str(fixture)])
    assert main() == expected
    output = capsys.readouterr().out
    if expected != 2:
        assert json.loads(output) == {
            "mode": "offline_response_replay",
            "abstention_detected": expected == 0,
        }


def test_replay_missing_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["abstention", str(tmp_path / "missing.json")])
    assert main() == 2
    assert "Invalid local fixture" in capsys.readouterr().out
