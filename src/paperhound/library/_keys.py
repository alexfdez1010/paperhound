"""Pure helpers for canonical ids, safe filenames, and FTS5 query escaping."""

from __future__ import annotations

import hashlib

from paperhound.models import Paper


def canonical_id(paper: Paper) -> str:
    """Derive a stable canonical id: arxiv > doi > hash(title|year)."""
    if paper.identifiers.arxiv_id:
        return paper.identifiers.arxiv_id
    if paper.identifiers.doi:
        return paper.identifiers.doi
    blob = f"{paper.title.lower().strip()}|{paper.year or ''}"
    return "hash:" + hashlib.sha1(blob.encode()).hexdigest()[:16]


def safe_filename(paper_id: str) -> str:
    """Convert a paper id to a safe filename stem."""
    return paper_id.replace("/", "_").replace(":", "_").replace(".", "_")


def fts_escape(query: str) -> str:
    """Wrap each whitespace-separated token in double-quotes for FTS5 MATCH.

    Prevents special FTS5 characters (``*``, ``:``, ``^``, ``"``, …) from
    being interpreted as query operators, which would raise OperationalError.
    """
    tokens = query.split()
    if not tokens:
        return '""'
    return " ".join(f'"{t.replace(chr(34), "")}"' for t in tokens)
