"""Local library backed by SQLite FTS5.

Usage::

    lib = Library()                   # ~/.paperhound/library/
    lib = Library(Path("/tmp/test"))  # injected path (tests)
    lib.add(paper)
    lib.list()         # -> list[LibraryEntry]
    lib.grep("query")  # -> list[GrepHit]
    lib.remove("2401.12345")
"""

from __future__ import annotations

from paperhound.library._db import Library
from paperhound.library._keys import canonical_id, fts_escape, safe_filename
from paperhound.library._models import GrepHit, LibraryEntry
from paperhound.library._paths import library_dir
from paperhound.library._schema import SCHEMA_VERSION

# Backward-compatible aliases — the underscored helpers are still imported
# directly by tests and by the CLI.
_canonical_id = canonical_id
_safe_filename = safe_filename
_fts_escape = fts_escape
_library_dir = library_dir

__all__ = [
    "GrepHit",
    "Library",
    "LibraryEntry",
    "SCHEMA_VERSION",
    "_canonical_id",
    "_fts_escape",
    "_library_dir",
    "_safe_filename",
    "canonical_id",
    "fts_escape",
    "library_dir",
    "safe_filename",
]
