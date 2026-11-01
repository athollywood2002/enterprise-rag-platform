"""Unit tests must never reach a running database or inference service."""

import socket
from unittest.mock import Mock

import pytest


@pytest.fixture(autouse=True)
def block_service_access(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Unit tests must not access network services")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr("rag.core.QdrantClient", Mock(side_effect=forbidden))


@pytest.fixture(autouse=True)
def isolate_collection_environment(monkeypatch):
    monkeypatch.delenv("QDRANT_COLLECTION", raising=False)
    monkeypatch.delenv("qdrant_collection", raising=False)
