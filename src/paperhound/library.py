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

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from paperhound.errors import LibraryError
from paperhound.models import Paper

# Increment this whenever the schema changes.  On version mismatch the library
# raises LibraryError rather than silently operating on a stale schema.
SCHEMA_VERSION = 1

_DEFAULT_DIR = Path.home() / ".paperhound" / "library"


def _library_dir() -> Path:
    """Return the library root, honouring PAPERHOUND_LIBRARY_DIR."""
    env = os.environ.get("PAPERHOUND_LIBRARY_DIR")
    return Path(env) if env else _DEFAULT_DIR


# ---------------------------------------------------------------------------
# Public data-classes
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Schema SQL
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS papers (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    authors_json  TEXT NOT NULL DEFAULT '[]',
    year          INTEGER,
    abstract      TEXT,
    doi           TEXT,
    arxiv_id      TEXT,
    source        TEXT NOT NULL DEFAULT '',
    added_at      TEXT NOT NULL,
    markdown_path TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts
    USING fts5(
        id        UNINDEXED,
        title,
        abstract,
        body,
        content='',
        contentless_delete=1,
        tokenize='porter ascii'
    );
"""

# FTS5 triggers for external-content synchronisation (insert + delete).
# Because we use content='', we maintain the index manually.
_TRIGGER_INSERT = """
CREATE TRIGGER IF NOT EXISTS papers_ai
AFTER INSERT ON papers BEGIN
    INSERT INTO papers_fts(rowid, id, title, abstract, body)
    VALUES (new.rowid, new.id, new.title, COALESCE(new.abstract,''), '');
END;
"""

_TRIGGER_DELETE = """
CREATE TRIGGER IF NOT EXISTS papers_ad
AFTER DELETE ON papers BEGIN
    DELETE FROM papers_fts WHERE rowid = old.rowid;
END;
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _canonical_id(paper: Paper) -> str:
    """Derive a stable canonical id: arxiv > doi > hash(title|year)."""
    if paper.identifiers.arxiv_id:
        return paper.identifiers.arxiv_id
    if paper.identifiers.doi:
        return paper.identifiers.doi
    blob = f"{paper.title.lower().strip()}|{paper.year or ''}"
    return "hash:" + hashlib.sha1(blob.encode()).hexdigest()[:16]


def _safe_filename(paper_id: str) -> str:
    """Convert a paper id to a safe filename stem."""
    return paper_id.replace("/", "_").replace(":", "_").replace(".", "_")


def _fts_escape(query: str) -> str:
    """Wrap each whitespace-separated token in double-quotes for FTS5 MATCH.

    This prevents special FTS5 characters (*, :, ^, " etc.) from being
    interpreted as query operators, which would raise OperationalError.
    """
    tokens = query.split()
    if not tokens:
        return '""'
    return " ".join(f'"{t.replace(chr(34), "")}"' for t in tokens)


# ---------------------------------------------------------------------------
# Library class
# ---------------------------------------------------------------------------


class Library:
    """Thin wrapper around the SQLite library database.

    Parameters
    ----------
    path:
        Directory that contains (or will contain) ``library.db``.
        Defaults to the value of ``_library_dir()``.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._dir = path if path is not None else _library_dir()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._dir / "library.db"
        self._con: sqlite3.Connection = self._open()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _open(self) -> sqlite3.Connection:
        try:
            con = sqlite3.connect(self._db_path, check_same_thread=False)
        except sqlite3.Error as exc:
            raise LibraryError(f"Cannot open library database: {exc}") from exc

        # Verify FTS5 is available.
        try:
            con.execute("CREATE VIRTUAL TABLE _fts5_probe USING fts5(x)")
            con.execute("DROP TABLE _fts5_probe")
        except sqlite3.OperationalError as exc:
            raise LibraryError(
                "Your SQLite build does not include FTS5. "
                "paperhound's local library requires FTS5 support."
            ) from exc

        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA foreign_keys=ON")
        self._ensure_schema(con)
        return con

    def _ensure_schema(self, con: sqlite3.Connection) -> None:
        """Create tables / triggers if absent; check schema version."""
        con.executescript(_DDL)
        con.executescript(_TRIGGER_INSERT)
        con.executescript(_TRIGGER_DELETE)

        cur = con.execute("SELECT value FROM meta WHERE key='schema_version'")
        row = cur.fetchone()
        if row is None:
            con.execute(
                "INSERT INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            con.commit()
        else:
            stored = int(row["value"])
            if stored != SCHEMA_VERSION:
                raise LibraryError(
                    f"Library schema version mismatch: database has v{stored}, "
                    f"paperhound expects v{SCHEMA_VERSION}. "
                    "Please remove ~/.paperhound/library/library.db and re-add your papers."
                )

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._con.close()

    def __enter__(self) -> Library:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(self, paper: Paper, markdown_path: Path | None = None) -> str:
        """Insert or replace a paper entry.  Returns the canonical id.

        If the paper already exists the row is updated (idempotent re-add).
        The FTS index is updated via the delete+insert trigger pair.
        """
        from datetime import datetime, timezone

        paper_id = _canonical_id(paper)
        authors_json = json.dumps([a.name for a in paper.authors])
        added_at = datetime.now(timezone.utc).isoformat()
        md_path_str = str(markdown_path) if markdown_path else None
        source = paper.sources[0] if paper.sources else ""

        with self._con:
            # Check if row exists (to fire the delete trigger before re-insert).
            existing = self._con.execute(
                "SELECT rowid FROM papers WHERE id=?", (paper_id,)
            ).fetchone()
            if existing:
                self._con.execute("DELETE FROM papers WHERE id=?", (paper_id,))

            self._con.execute(
                """
                INSERT INTO papers
                    (id, title, authors_json, year, abstract, doi, arxiv_id,
                     source, added_at, markdown_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    paper_id,
                    paper.title,
                    authors_json,
                    paper.year,
                    paper.abstract,
                    paper.identifiers.doi,
                    paper.identifiers.arxiv_id,
                    source,
                    added_at,
                    md_path_str,
                ),
            )
        return paper_id

    def update_markdown(self, paper_id: str, markdown_path: Path) -> None:
        """Set (or overwrite) the markdown_path and refresh the FTS body."""
        body = markdown_path.read_text(encoding="utf-8", errors="replace")
        with self._con:
            # Read current row to re-index with body.
            row = self._con.execute(
                "SELECT rowid, title, abstract FROM papers WHERE id=?", (paper_id,)
            ).fetchone()
            if row is None:
                raise LibraryError(f"Paper not found in library: {paper_id!r}")
            self._con.execute(
                "UPDATE papers SET markdown_path=? WHERE id=?",
                (str(markdown_path), paper_id),
            )
            # Delete the old FTS row and insert with the new body.
            self._con.execute(
                "DELETE FROM papers_fts WHERE rowid=?",
                (row["rowid"],),
            )
            self._con.execute(
                "INSERT INTO papers_fts(rowid, id, title, abstract, body) VALUES (?, ?, ?, ?, ?)",
                (row["rowid"], paper_id, row["title"], row["abstract"] or "", body),
            )

    def list(self) -> list[LibraryEntry]:
        """Return all entries ordered by added_at descending."""
        cur = self._con.execute(
            "SELECT id, title, authors_json, year, abstract, doi, arxiv_id, "
            "       source, added_at, markdown_path "
            "FROM papers ORDER BY added_at DESC"
        )
        return [
            LibraryEntry(
                id=row["id"],
                title=row["title"],
                authors_json=row["authors_json"],
                year=row["year"],
                abstract=row["abstract"],
                doi=row["doi"],
                arxiv_id=row["arxiv_id"],
                source=row["source"],
                added_at=row["added_at"],
                markdown_path=row["markdown_path"],
            )
            for row in cur.fetchall()
        ]

    def grep(self, query: str, limit: int = 20) -> list[GrepHit]:
        """Full-text search over title + abstract + markdown body.

        Returns up to *limit* hits sorted by relevance (FTS5 rank).

        Because papers_fts is a contentless table, column values are not stored
        in the index itself.  We JOIN with the ``papers`` table via rowid to
        recover id, title, and abstract, then build a short snippet from
        whichever field matched.
        """
        escaped = _fts_escape(query)
        try:
            cur = self._con.execute(
                """
                SELECT p.id,
                       p.title,
                       p.abstract,
                       fts.rank
                FROM   papers_fts AS fts
                JOIN   papers AS p ON p.rowid = fts.rowid
                WHERE  papers_fts MATCH ?
                ORDER  BY fts.rank
                LIMIT  ?
                """,
                (escaped, limit),
            )
        except sqlite3.OperationalError as exc:
            raise LibraryError(f"FTS5 query error: {exc}") from exc

        hits: list[GrepHit] = []
        for row in cur.fetchall():
            # Build a simple snippet from the abstract (first 200 chars).
            abstract = row["abstract"] or ""
            snip = abstract[:200] + ("…" if len(abstract) > 200 else "")
            hits.append(
                GrepHit(
                    id=row["id"],
                    title=row["title"],
                    snippet=snip,
                    rank=row["rank"],
                )
            )
        return hits

    def remove(self, paper_id: str) -> Path | None:
        """Delete a paper from the library.

        Returns the markdown path (if any) so the caller can delete the file.
        Raises LibraryError if the id is not found.
        """
        row = self._con.execute(
            "SELECT markdown_path FROM papers WHERE id=?", (paper_id,)
        ).fetchone()
        if row is None:
            raise LibraryError(f"Paper not found in library: {paper_id!r}")
        md_path = Path(row["markdown_path"]) if row["markdown_path"] else None
        with self._con:
            self._con.execute("DELETE FROM papers WHERE id=?", (paper_id,))
        return md_path

    def get(self, paper_id: str) -> LibraryEntry | None:
        """Return a single entry by id, or None if not found."""
        row = self._con.execute(
            "SELECT id, title, authors_json, year, abstract, doi, arxiv_id, "
            "       source, added_at, markdown_path "
            "FROM papers WHERE id=?",
            (paper_id,),
        ).fetchone()
        if row is None:
            return None
        return LibraryEntry(
            id=row["id"],
            title=row["title"],
            authors_json=row["authors_json"],
            year=row["year"],
            abstract=row["abstract"],
            doi=row["doi"],
            arxiv_id=row["arxiv_id"],
            source=row["source"],
            added_at=row["added_at"],
            markdown_path=row["markdown_path"],
        )
