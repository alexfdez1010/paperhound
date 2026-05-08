"""SQLite-backed library implementation.

Wraps a single connection and exposes a small CRUD + FTS surface used by the
CLI. The connection is opened in WAL mode and FTS5 availability is verified
at open time so we surface a clear error on hostile environments.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from paperhound.errors import LibraryError
from paperhound.library._keys import canonical_id, fts_escape
from paperhound.library._models import GrepHit, LibraryEntry
from paperhound.library._paths import library_dir
from paperhound.library._schema import ensure_schema
from paperhound.models import Paper

_ENTRY_COLUMNS = (
    "id, title, authors_json, year, abstract, doi, arxiv_id, source, added_at, markdown_path"
)


def _row_to_entry(row: sqlite3.Row) -> LibraryEntry:
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


class Library:
    """Thin wrapper around the SQLite library database.

    Parameters
    ----------
    path:
        Directory that contains (or will contain) ``library.db``. Defaults to
        ``library_dir()`` (``~/.paperhound/library`` unless overridden by
        ``PAPERHOUND_LIBRARY_DIR``).
    """

    def __init__(self, path: Path | None = None) -> None:
        self._dir = path if path is not None else library_dir()
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

        # FTS5 probe — fails fast on builds without it.
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
        ensure_schema(con)
        return con

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._con.close()

    def __enter__(self) -> Library:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add(self, paper: Paper, markdown_path: Path | None = None) -> str:
        """Insert or replace a paper entry; returns the canonical id.

        Re-adding an existing entry updates its row (idempotent). The FTS
        index is refreshed via the delete + insert trigger pair.
        """
        from datetime import datetime, timezone

        paper_id = canonical_id(paper)
        authors_json = json.dumps([a.name for a in paper.authors])
        added_at = datetime.now(timezone.utc).isoformat()
        md_path_str = str(markdown_path) if markdown_path else None
        source = paper.sources[0] if paper.sources else ""

        with self._con:
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
        """Set (or overwrite) ``markdown_path`` and refresh the FTS body."""
        body = markdown_path.read_text(encoding="utf-8", errors="replace")
        with self._con:
            row = self._con.execute(
                "SELECT rowid, title, abstract FROM papers WHERE id=?", (paper_id,)
            ).fetchone()
            if row is None:
                raise LibraryError(f"Paper not found in library: {paper_id!r}")
            self._con.execute(
                "UPDATE papers SET markdown_path=? WHERE id=?",
                (str(markdown_path), paper_id),
            )
            self._con.execute(
                "DELETE FROM papers_fts WHERE rowid=?",
                (row["rowid"],),
            )
            self._con.execute(
                "INSERT INTO papers_fts(rowid, id, title, abstract, body) VALUES (?, ?, ?, ?, ?)",
                (row["rowid"], paper_id, row["title"], row["abstract"] or "", body),
            )

    def list(self) -> list[LibraryEntry]:
        """Return all entries ordered by ``added_at`` descending."""
        cur = self._con.execute(f"SELECT {_ENTRY_COLUMNS} FROM papers ORDER BY added_at DESC")
        return [_row_to_entry(row) for row in cur.fetchall()]

    def grep(self, query: str, limit: int = 20) -> list[GrepHit]:
        """Full-text search over title + abstract + markdown body."""
        escaped = fts_escape(query)
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
        """Delete a paper and return its markdown path (if any) for cleanup."""
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
        """Return a single entry by id, or ``None`` when missing."""
        row = self._con.execute(
            f"SELECT {_ENTRY_COLUMNS} FROM papers WHERE id=?",
            (paper_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_entry(row)
