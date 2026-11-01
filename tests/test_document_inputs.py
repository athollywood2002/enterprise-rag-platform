"""Invalid input must be rejected before optional imports or temporary writes."""

import builtins
from unittest.mock import Mock

import pytest

from rag.documents import parse_document


@pytest.mark.parametrize(
    ("data", "filename", "message"),
    [
        (b"", "fixture.pdf", "Empty document"),
        (b"", "fixture.txt", "Empty document"),
        (b"synthetic", "fixture.exe", "Unsupported extension"),
        (b"synthetic", "fixture", "Unsupported extension"),
        (b"synthetic", "", "Unsupported extension"),
        (b"synthetic", "fixture.pdf\x00", "Invalid filename"),
    ],
)
def test_reject_before_import_or_disk_write(monkeypatch, data, filename, message):
    original_import = builtins.__import__

    def no_optional_import(name, *args, **kwargs):
        if name == "unstructured" or name.startswith("unstructured."):
            raise AssertionError("Invalid input imported the optional parser")
        return original_import(name, *args, **kwargs)

    temporary = Mock(side_effect=AssertionError("Invalid input wrote a temporary file"))
    monkeypatch.setattr(builtins, "__import__", no_optional_import)
    monkeypatch.setattr("rag.documents.TemporaryDirectory", temporary)
    with pytest.raises(ValueError, match=message):
        parse_document(data, filename)
    temporary.assert_not_called()
