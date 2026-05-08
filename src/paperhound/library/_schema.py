"""SQLite schema definitions and migration entry point.

Increment ``SCHEMA_VERSION`` whenever the on-disk layout changes; the library
refuses to open a database that disagrees with the current version rather
than silently operating on a stale schema.
"""

from __future__ import annotations

import sqlite3

from paperhound.errors import LibraryError

SCHEMA_VERSION = 1

DDL = """
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

# FTS5 triggers for external-content synchronisation. We use content='' so the
# index is maintained manually — these triggers handle insert / delete.
TRIGGER_INSERT = """
CREATE TRIGGER IF NOT EXISTS papers_ai
AFTER INSERT ON papers BEGIN
    INSERT INTO papers_fts(rowid, id, title, abstract, body)
    VALUES (new.rowid, new.id, new.title, COALESCE(new.abstract,''), '');
END;
"""

TRIGGER_DELETE = """
CREATE TRIGGER IF NOT EXISTS papers_ad
AFTER DELETE ON papers BEGIN
    DELETE FROM papers_fts WHERE rowid = old.rowid;
END;
"""


def ensure_schema(con: sqlite3.Connection) -> None:
    """Create tables / triggers if absent and check the schema version."""
    con.executescript(DDL)
    con.executescript(TRIGGER_INSERT)
    con.executescript(TRIGGER_DELETE)

    cur = con.execute("SELECT value FROM meta WHERE key='schema_version'")
    row = cur.fetchone()
    if row is None:
        con.execute(
            "INSERT INTO meta(key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        con.commit()
        return

    stored = int(row["value"])
    if stored != SCHEMA_VERSION:
        raise LibraryError(
            f"Library schema version mismatch: database has v{stored}, "
            f"paperhound expects v{SCHEMA_VERSION}. "
            "Please remove ~/.paperhound/library/library.db and re-add your papers."
        )
