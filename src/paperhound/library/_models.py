"""Read-side data classes returned by the :class:`Library`."""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class LibraryEntry:
    """One row from the ``papers`` table."""

    id: str
    title: str
    authors_json: str  # JSON array of author name strings
    year: int | None
    abstract: str | None
    doi: str | None
    arxiv_id: str | None
    source: str  # originating provider (first seen)
    added_at: str  # ISO-8601
    markdown_path: str | None

    @property
    def first_author(self) -> str:
        names: list[str] = json.loads(self.authors_json) if self.authors_json else []
        if not names:
            return "-"
        if len(names) == 1:
            return names[0]
        return f"{names[0]} et al."


@dataclass
class GrepHit:
    """One FTS5 match result."""

    id: str
    title: str
    snippet: str
    rank: float = field(default=0.0)
