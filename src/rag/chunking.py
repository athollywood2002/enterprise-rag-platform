"""Immutable shared title-chunking configuration; no parser imports."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ChunkingPolicy:
    max_characters: int = 1200
    new_after_n_chars: int = 1000
    combine_text_under_n_chars: int = 200
    multipage_sections: bool = False

    @property
    def policy_id(self) -> str:
        return (
            f"unstructured-title-page-local-v1:max={self.max_characters}:"
            f"new={self.new_after_n_chars}:combine={self.combine_text_under_n_chars}:"
            f"multipage={str(self.multipage_sections).lower()}"
        )


TITLE_CHUNKING = ChunkingPolicy()
