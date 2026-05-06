"""Unit tests for paperhound.library — all offline, no network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperhound.errors import LibraryError
from paperhound.library import Library, _canonical_id, _fts_escape, _safe_filename
from paperhound.models import Author, Paper, PaperIdentifier

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def lib(tmp_path: Path) -> Library:
    """A fresh library in a temp directory."""
    return Library(path=tmp_path)


@pytest.fixture()
def arxiv_paper() -> Paper:
    return Paper(
        title="Attention Is All You Need",
        authors=[Author(name="Vaswani"), Author(name="Shazeer"), Author(name="Parmar")],
        abstract="The dominant sequence transduction models are based on complex recurrent networks.",
        year=2017,
        venue="NeurIPS",
        identifiers=PaperIdentifier(arxiv_id="1706.03762", doi="10.5555/3295222.3295349"),
        sources=["arxiv"],
    )


@pytest.fixture()
def doi_only_paper() -> Paper:
    return Paper(
        title="Nature paper without arXiv",
        authors=[Author(name="Smith")],
        abstract="Some abstract.",
        year=2020,
        identifiers=PaperIdentifier(doi="10.1038/s41586-020-0001-0"),
        sources=["crossref"],
    )


@pytest.fixture()
def no_id_paper() -> Paper:
    return Paper(
        title="A Paper With No Standard Id",
        authors=[Author(name="Unknown")],
        year=2021,
        sources=["dblp"],
    )


# ---------------------------------------------------------------------------
# _canonical_id
# ---------------------------------------------------------------------------


def test_canonical_id_prefers_arxiv(arxiv_paper: Paper) -> None:
    assert _canonical_id(arxiv_paper) == "1706.03762"


def test_canonical_id_falls_back_to_doi(doi_only_paper: Paper) -> None:
    assert _canonical_id(doi_only_paper) == "10.1038/s41586-020-0001-0"


def test_canonical_id_hashes_title_year(no_id_paper: Paper) -> None:
    cid = _canonical_id(no_id_paper)
    assert cid.startswith("hash:")
    assert len(cid) == len("hash:") + 16


def test_canonical_id_same_paper_same_hash(no_id_paper: Paper) -> None:
    assert _canonical_id(no_id_paper) == _canonical_id(no_id_paper)


# ---------------------------------------------------------------------------
# _fts_escape
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("attention", '"attention"'),
        ("attention mechanism", '"attention" "mechanism"'),
        # Special FTS5 chars are stripped from within quoted tokens
        ('at*ten:tion "test"', '"at*ten:tion" "test"'),
        # Empty query returns empty quoted token
        ("", '""'),
        # Multiple spaces collapsed
        ("a  b", '"a" "b"'),
    ],
)
def test_fts_escape(raw: str, expected: str) -> None:
    assert _fts_escape(raw) == expected


# ---------------------------------------------------------------------------
# _safe_filename
# ---------------------------------------------------------------------------


def test_safe_filename_arxiv() -> None:
    assert _safe_filename("1706.03762") == "1706_03762"


def test_safe_filename_doi() -> None:
    assert _safe_filename("10.1038/s41586-020-0001-0") == "10_1038_s41586-020-0001-0"


def test_safe_filename_hash() -> None:
    assert _safe_filename("hash:abc123") == "hash_abc123"


# ---------------------------------------------------------------------------
# Happy path: add → list → grep → rm
# ---------------------------------------------------------------------------


def test_add_list_grep_rm(lib: Library, arxiv_paper: Paper) -> None:
    # add
    paper_id = lib.add(arxiv_paper)
    assert paper_id == "1706.03762"

    # list
    entries = lib.list()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.id == "1706.03762"
    assert entry.title == arxiv_paper.title
    assert entry.year == 2017
    assert "Vaswani" in entry.first_author

    # grep
    hits = lib.grep("sequence transduction")
    assert len(hits) >= 1
    assert hits[0].id == "1706.03762"

    # rm
    lib.remove("1706.03762")
    assert lib.list() == []


# ---------------------------------------------------------------------------
# Idempotent re-add (updated fields)
# ---------------------------------------------------------------------------


def test_idempotent_readd(lib: Library, arxiv_paper: Paper) -> None:
    lib.add(arxiv_paper)

    updated = arxiv_paper.model_copy(deep=True)
    updated.title = "Attention Is All You Need (Updated Title)"
    updated.year = 2018
    lib.add(updated)

    entries = lib.list()
    assert len(entries) == 1, "Re-add must not duplicate the row"
    assert entries[0].title == "Attention Is All You Need (Updated Title)"
    assert entries[0].year == 2018


# ---------------------------------------------------------------------------
# FTS5 special characters in query (sanitization)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_query",
    [
        "attention*",
        "title:attention",
        "attention^2",
        '"quoted phrase"',
        "NOT attention",
    ],
)
def test_grep_special_chars_do_not_raise(lib: Library, arxiv_paper: Paper, bad_query: str) -> None:
    """FTS5 special chars are sanitized; no OperationalError should be raised."""
    lib.add(arxiv_paper)
    # Should not raise — result may be empty but must not error.
    hits = lib.grep(bad_query)
    assert isinstance(hits, list)


# ---------------------------------------------------------------------------
# Empty library
# ---------------------------------------------------------------------------


def test_list_empty(lib: Library) -> None:
    assert lib.list() == []


def test_grep_empty(lib: Library) -> None:
    hits = lib.grep("anything")
    assert hits == []


# ---------------------------------------------------------------------------
# rm of non-existent id → LibraryError
# ---------------------------------------------------------------------------


def test_rm_not_found(lib: Library) -> None:
    with pytest.raises(LibraryError, match="not found"):
        lib.remove("nonexistent-id")


# ---------------------------------------------------------------------------
# PAPERHOUND_LIBRARY_DIR env var is honoured
# ---------------------------------------------------------------------------


def test_env_var_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom_dir = tmp_path / "custom_lib"
    monkeypatch.setenv("PAPERHOUND_LIBRARY_DIR", str(custom_dir))

    from paperhound.library import _library_dir

    result = _library_dir()
    assert result == custom_dir


def test_library_uses_env_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arxiv_paper: Paper
) -> None:
    custom_dir = tmp_path / "mylib"
    monkeypatch.setenv("PAPERHOUND_LIBRARY_DIR", str(custom_dir))

    lib = Library()  # should pick up env var
    lib.add(arxiv_paper)
    entries = lib.list()
    assert len(entries) == 1
    assert (custom_dir / "library.db").exists()


# ---------------------------------------------------------------------------
# Markdown body searchable when present
# ---------------------------------------------------------------------------


def test_markdown_body_searchable(lib: Library, arxiv_paper: Paper, tmp_path: Path) -> None:
    paper_id = lib.add(arxiv_paper)

    md_file = tmp_path / "paper.md"
    md_file.write_text(
        "# Attention Is All You Need\n\nThis paper introduces the Transformer architecture "
        "with multi-head self-attention layers.",
        encoding="utf-8",
    )
    lib.update_markdown(paper_id, md_file)

    hits = lib.grep("Transformer architecture")
    assert len(hits) >= 1
    assert hits[0].id == paper_id


# ---------------------------------------------------------------------------
# Schema version mismatch raises LibraryError
# ---------------------------------------------------------------------------


def test_schema_version_mismatch(tmp_path: Path) -> None:
    # Create a valid library, then manually change the schema version.
    lib = Library(path=tmp_path)
    lib._con.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
    lib._con.commit()
    lib.close()

    with pytest.raises(LibraryError, match="schema version mismatch"):
        Library(path=tmp_path)


# ---------------------------------------------------------------------------
# Multiple papers: list ordering and grep precision
# ---------------------------------------------------------------------------


def test_multiple_papers(lib: Library) -> None:
    p1 = Paper(
        title="First Paper on Graph Neural Networks",
        authors=[Author(name="Alice")],
        abstract="We study graph neural networks for node classification.",
        year=2019,
        identifiers=PaperIdentifier(arxiv_id="1901.00001"),
        sources=["arxiv"],
    )
    p2 = Paper(
        title="Second Paper on Diffusion Models",
        authors=[Author(name="Bob")],
        abstract="Diffusion models generate high-quality images.",
        year=2021,
        identifiers=PaperIdentifier(arxiv_id="2101.00002"),
        sources=["arxiv"],
    )
    lib.add(p1)
    lib.add(p2)

    entries = lib.list()
    assert len(entries) == 2

    # grep should find only the diffusion paper
    hits = lib.grep("diffusion images")
    ids = [h.id for h in hits]
    assert "2101.00002" in ids
    assert "1901.00001" not in ids


# ---------------------------------------------------------------------------
# Authors JSON round-trips correctly
# ---------------------------------------------------------------------------


def test_authors_json_round_trip(lib: Library, arxiv_paper: Paper) -> None:
    lib.add(arxiv_paper)
    entry = lib.get("1706.03762")
    assert entry is not None
    names = json.loads(entry.authors_json)
    assert names == ["Vaswani", "Shazeer", "Parmar"]
    assert entry.first_author == "Vaswani et al."


def test_single_author_no_et_al(lib: Library, doi_only_paper: Paper) -> None:
    lib.add(doi_only_paper)
    entry = lib.get("10.1038/s41586-020-0001-0")
    assert entry is not None
    assert entry.first_author == "Smith"


# ---------------------------------------------------------------------------
# get() returns None for unknown id
# ---------------------------------------------------------------------------


def test_get_unknown(lib: Library) -> None:
    assert lib.get("does-not-exist") is None


# ---------------------------------------------------------------------------
# update_markdown on unknown paper raises LibraryError
# ---------------------------------------------------------------------------


def test_update_markdown_unknown(lib: Library, tmp_path: Path) -> None:
    md = tmp_path / "x.md"
    md.write_text("hello")
    with pytest.raises(LibraryError, match="not found"):
        lib.update_markdown("ghost-id", md)
