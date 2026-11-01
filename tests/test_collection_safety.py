"""Synthetic fixtures and mocked clients only; no Qdrant/Ollama installation."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from qdrant_client import QdrantClient

from rag.collection_safety import (
    PROTECTED_COLLECTIONS,
    UnsafeCollectionError,
    validate_writable_collection_name,
)
from rag.config import Settings
from rag.core import Chunk, RagEngine
from rag.documents import DocumentChunk

SAFE_NAME = "rag_portfolio_e2e_test_v1"
PROTECTED_VARIANTS = ["hdd_knowledge", "HDD_KNOWLEDGE", " hdd_knowledge ", "hdd_knowledge\n"]
AMBIGUOUS_NAMES = [
    "",
    "safe name",
    "SafeName",
    "../hdd_knowledge",
    "hdd%5fknowledge",
    "hdd_knowledge/",
    "hdd_knowledge\x00",
    "hdd_knowledge\u200b",
    "ｈｄｄ_knowledge",
    "hdd_knowledgе",
    "a" * 129,
    "safe\n",
]


def settings(**overrides) -> Settings:
    return Settings(
        _env_file=None,
        api_key="synthetic-unit-test-only",
        qdrant_url="http://qdrant.invalid:6333",
        ollama_url="http://ollama.invalid:11434",
        **overrides,
    )


def make_engine(name: str = SAFE_NAME) -> tuple[RagEngine, Mock]:
    db = Mock(spec=QdrantClient)
    db.get_aliases.return_value = SimpleNamespace(aliases=[])
    db.collection_exists.return_value = False
    db.get_collection.return_value = SimpleNamespace(
        config=SimpleNamespace(params=SimpleNamespace(vectors=SimpleNamespace(size=3)))
    )
    engine = RagEngine(settings(qdrant_collection=name), qdrant=db)
    engine.embed = Mock(return_value=[1.0, 0.0, 0.0])
    return engine, db


def alias_response(target: str = "hdd_knowledge") -> SimpleNamespace:
    return SimpleNamespace(aliases=[SimpleNamespace(alias_name=SAFE_NAME, collection_name=target)])


@pytest.mark.parametrize("name", sorted(PROTECTED_COLLECTIONS))
def test_every_builtin_protected_name_is_rejected(name):
    with pytest.raises(UnsafeCollectionError, match="protected"):
        validate_writable_collection_name(name)


@pytest.mark.parametrize("name", PROTECTED_VARIANTS + AMBIGUOUS_NAMES)
def test_explicit_settings_reject_protected_and_ambiguous_names(name):
    with pytest.raises(ValidationError):
        settings(qdrant_collection=name)


@pytest.mark.parametrize(
    "name", [name for name in PROTECTED_VARIANTS + AMBIGUOUS_NAMES if "\x00" not in name]
)
@pytest.mark.parametrize("variable", ["QDRANT_COLLECTION", "qdrant_collection"])
def test_environment_cannot_select_unsafe_target(monkeypatch, variable, name):
    monkeypatch.setenv(variable, name)
    with pytest.raises(ValidationError):
        settings()


@pytest.mark.parametrize("name", [None, 0, False, [], {}])
def test_non_string_names_fail_closed(name):
    with pytest.raises(UnsafeCollectionError, match="string"):
        validate_writable_collection_name(name)


@pytest.mark.parametrize("variable", ["PROTECTED_COLLECTIONS", "QDRANT_PROTECTED_COLLECTIONS"])
def test_environment_cannot_clear_builtin_protection(monkeypatch, variable):
    monkeypatch.setenv(variable, "[]")
    monkeypatch.setenv("QDRANT_COLLECTION", "hdd_knowledge")
    with pytest.raises(ValidationError, match="protected"):
        settings()


def test_dotenv_cannot_select_protected_target(tmp_path):
    dotenv = tmp_path / "synthetic.env"
    dotenv.write_text("QDRANT_COLLECTION=hdd_knowledge\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="protected"):
        Settings(_env_file=dotenv, api_key="synthetic-unit-test-only")


@pytest.mark.parametrize("name", [SAFE_NAME, "rag_unit_test", "rag-test-2", "rag_documents_v1"])
def test_permitted_names_are_not_rewritten(name, monkeypatch):
    assert validate_writable_collection_name(name) == name
    monkeypatch.setenv("QDRANT_COLLECTION", name)
    assert settings().qdrant_collection == name


def test_default_collection_remains_permitted():
    assert settings().qdrant_collection == "rag_documents_v1"


def test_assignment_validation_rejects_protected_target():
    config = settings(qdrant_collection=SAFE_NAME)
    with pytest.raises(ValidationError, match="protected"):
        config.qdrant_collection = "hdd_knowledge"
    assert config.qdrant_collection == SAFE_NAME


@pytest.mark.parametrize("bypass", ["model_construct", "model_copy"])
def test_engine_constructor_revalidates_unvalidated_settings(bypass, monkeypatch):
    if bypass == "model_construct":
        config = Settings.model_construct(qdrant_collection="hdd_knowledge")
    else:
        config = settings().model_copy(update={"qdrant_collection": "hdd_knowledge"})
    factory = Mock()
    monkeypatch.setattr("rag.core.QdrantClient", factory)
    with pytest.raises(UnsafeCollectionError, match="protected"):
        RagEngine(config)
    factory.assert_not_called()


@pytest.mark.parametrize("name", PROTECTED_VARIANTS)
@pytest.mark.parametrize("entrypoint", ["ensure", "text", "document", "empty"])
def test_write_entrypoints_reject_tampered_settings_without_service_calls(name, entrypoint):
    engine, db = make_engine()
    # Deliberately bypass Pydantic assignment validation, like an unsafe caller.
    engine.config.__dict__["qdrant_collection"] = name
    with pytest.raises(UnsafeCollectionError, match="protected"):
        if entrypoint == "ensure":
            engine.ensure_collection(3)
        elif entrypoint == "text":
            engine.ingest("Synthetic fact.", "fixture.txt")
        elif entrypoint == "document":
            engine.ingest_chunks([DocumentChunk("Synthetic fact.", "fixture.pdf", 0, 1)])
        else:
            engine.ingest_chunks([])
    assert db.mock_calls == []
    engine.embed.assert_not_called()


def test_explicit_ensure_target_cannot_bypass_guard():
    engine, db = make_engine()
    with pytest.raises(UnsafeCollectionError, match="protected"):
        engine.ensure_collection(3, collection_name="hdd_knowledge")
    assert db.mock_calls == []


@pytest.mark.parametrize("exists", [False, True])
@pytest.mark.parametrize("name", [SAFE_NAME, "rag_unit_test", "rag-test-2"])
@pytest.mark.parametrize("chunk_type", [Chunk, DocumentChunk])
def test_permitted_ingestion_writes_only_to_selected_collection(exists, name, chunk_type):
    engine, db = make_engine(name)
    db.collection_exists.return_value = exists
    assert engine.ingest_chunks([chunk_type("Synthetic fact.", "fixture.txt", 0)]) == 1
    db.collection_exists.assert_called_once_with(name)
    if exists:
        db.create_collection.assert_not_called()
        db.get_collection.assert_called_once_with(name)
    else:
        assert db.create_collection.call_args.kwargs["collection_name"] == name
        db.get_collection.assert_not_called()
    db.upsert.assert_called_once()
    assert db.upsert.call_args.kwargs["collection_name"] == name
    assert db.upsert.call_args.kwargs["wait"] is True


def test_permitted_text_ingestion():
    engine, db = make_engine()
    assert engine.ingest("Synthetic fact.", "fixture.txt") == 1
    assert db.upsert.call_args.kwargs["collection_name"] == SAFE_NAME


@pytest.mark.parametrize("chunks", [[], iter(())])
def test_empty_permitted_ingestion_does_not_touch_database(chunks):
    engine, db = make_engine()
    assert engine.ingest_chunks(chunks) == 0
    assert db.mock_calls == []


@pytest.mark.parametrize("stage", ["embed", "collection_exists"])
def test_mid_ingestion_config_mutation_cannot_redirect_write(stage):
    engine, db = make_engine()

    def tamper(*args, **kwargs):
        engine.config.__dict__["qdrant_collection"] = "hdd_knowledge"
        return [1.0, 0.0, 0.0] if stage == "embed" else False

    if stage == "embed":
        engine.embed.side_effect = tamper
    else:
        db.collection_exists.side_effect = tamper
    assert engine.ingest("Synthetic fact.", "fixture.txt") == 1
    db.collection_exists.assert_called_once_with(SAFE_NAME)
    assert db.create_collection.call_args.kwargs["collection_name"] == SAFE_NAME
    assert db.upsert.call_args.kwargs["collection_name"] == SAFE_NAME


@pytest.mark.parametrize("target", ["hdd_knowledge", "rag_other_test"])
def test_aliases_are_rejected_even_when_their_destination_looks_safe(target):
    engine, db = make_engine()
    db.get_aliases.return_value = alias_response(target)
    with pytest.raises(UnsafeCollectionError, match="aliases"):
        engine.ingest("Synthetic fact.", "fixture.txt")
    db.collection_exists.assert_not_called()
    db.create_collection.assert_not_called()
    db.upsert.assert_not_called()


def test_alias_is_rechecked_immediately_before_creation():
    engine, db = make_engine()
    db.get_aliases.side_effect = [SimpleNamespace(aliases=[]), alias_response()]
    with pytest.raises(UnsafeCollectionError, match="aliases"):
        engine.ensure_collection(3)
    db.create_collection.assert_not_called()
    db.upsert.assert_not_called()


def test_alias_is_rechecked_immediately_before_upsert():
    engine, db = make_engine()
    db.collection_exists.return_value = True
    db.get_aliases.side_effect = [SimpleNamespace(aliases=[]), alias_response()]
    with pytest.raises(UnsafeCollectionError, match="aliases"):
        engine.ingest("Synthetic fact.", "fixture.txt")
    db.create_collection.assert_not_called()
    db.upsert.assert_not_called()


def test_overriding_ensure_collection_does_not_bypass_upsert_guard(monkeypatch):
    engine, db = make_engine()
    monkeypatch.setattr(engine, "ensure_collection", lambda *args, **kwargs: None)
    db.get_aliases.return_value = alias_response()
    with pytest.raises(UnsafeCollectionError, match="aliases"):
        engine.ingest("Synthetic fact.", "fixture.txt")
    db.create_collection.assert_not_called()
    db.upsert.assert_not_called()


@pytest.mark.parametrize("stage", ["ensure", "upsert"])
def test_alias_lookup_failure_blocks_writes(stage):
    engine, db = make_engine()
    if stage == "ensure":
        db.get_aliases.side_effect = RuntimeError("Synthetic alias lookup failure")
    else:
        db.collection_exists.return_value = True
        db.get_aliases.side_effect = [
            SimpleNamespace(aliases=[]),
            RuntimeError("Synthetic alias lookup failure"),
        ]
    with pytest.raises(RuntimeError, match="Synthetic alias lookup failure"):
        engine.ingest("Synthetic fact.", "fixture.txt")
    db.create_collection.assert_not_called()
    db.upsert.assert_not_called()
