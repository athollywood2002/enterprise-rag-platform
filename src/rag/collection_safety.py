"""Non-configurable minimum safety policy for collection write targets."""

import re
from typing import Final

PROTECTED_COLLECTIONS: Final[frozenset[str]] = frozenset({"hdd_knowledge"})
_COLLECTION_NAME = re.compile(r"[a-z][a-z0-9_-]{0,127}")


class UnsafeCollectionError(ValueError):
    """The requested write target is protected, ambiguous, or an alias."""


def validate_writable_collection_name(name: str) -> str:
    """Reject unsafe names without normalizing them into a different target.

    Keep the built-in protected set in code: environment settings must not be
    able to replace or disable it. Add further protected names through review.
    """
    if not isinstance(name, str):
        raise UnsafeCollectionError("Collection name must be a string")
    if name.strip().casefold() in PROTECTED_COLLECTIONS:
        raise UnsafeCollectionError("Writes to protected Qdrant collections are forbidden")
    if not _COLLECTION_NAME.fullmatch(name):
        raise UnsafeCollectionError(
            "Collection name must be 1-128 lowercase ASCII letters, digits, underscores "
            "or hyphens, starting with a letter"
        )
    return name
