"""Unit tests must never reach a running database or inference service."""

import os
import socket
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-document-tests", action="store_true", help="Run optional real parser tests"
    )


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-document-tests"):
        skip = pytest.mark.skip(
            reason="Install parser test dependencies and use --run-document-tests"
        )
        for item in items:
            if "documents" in item.keywords:
                item.add_marker(skip)


@pytest.fixture(autouse=True)
def block_service_access(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Unit tests must not access network services")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr("rag.core.QdrantClient", Mock(side_effect=forbidden))
    monkeypatch.setenv("AUTO_DOWNLOAD_NLTK", "false")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    monkeypatch.setenv(
        "NLTK_DATA", os.environ.get("NLTK_DATA", str(Path(sys.prefix) / "nltk_data"))
    )


@pytest.fixture(autouse=True)
def isolate_collection_environment(monkeypatch):
    monkeypatch.delenv("QDRANT_COLLECTION", raising=False)
    monkeypatch.delenv("qdrant_collection", raising=False)
