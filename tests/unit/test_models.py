"""Tests for the Paper / PaperIdentifier models."""

from __future__ import annotations

from paperhound.models import Author, Paper, PaperIdentifier


def make_paper(**overrides) -> Paper:
    base = dict(
        title="Attention Is All You Need",
        authors=[Author(name="Ashish Vaswani"), Author(name="Noam Shazeer")],
        abstract="A new architecture.",
        year=2017,
        venue="NeurIPS",
        identifiers=PaperIdentifier(arxiv_id="1706.03762"),
        sources=["arxiv"],
    )
    base.update(overrides)
    return Paper(**base)


def test_primary_identifier_prefers_arxiv() -> None:
    paper = make_paper(
        identifiers=PaperIdentifier(
            arxiv_id="1706.03762", doi="10.1/x", semantic_scholar_id="a" * 40
        )
    )
    assert paper.primary_id == "1706.03762"


def test_primary_identifier_falls_back() -> None:
    paper = make_paper(identifiers=PaperIdentifier(doi="10.1/x"))
    assert paper.primary_id == "10.1/x"


def test_paper_identifier_is_empty() -> None:
    assert PaperIdentifier().is_empty()
    assert not PaperIdentifier(arxiv_id="1706.03762").is_empty()


def test_merge_combines_fields() -> None:
    a = make_paper(abstract=None, citation_count=None, sources=["arxiv"])
    b = make_paper(
        abstract="Filled in by S2.",
        citation_count=12345,
        identifiers=PaperIdentifier(arxiv_id="1706.03762", semantic_scholar_id="z" * 40),
        sources=["semantic_scholar"],
    )
    merged = a.merge(b)
    assert merged.abstract == "Filled in by S2."
    assert merged.citation_count == 12345
    assert merged.identifiers.semantic_scholar_id == "z" * 40
    assert merged.sources == ["arxiv", "semantic_scholar"]


def test_merge_prefers_existing_values() -> None:
    a = make_paper(abstract="First", year=2017)
    b = make_paper(abstract="Second", year=2099)
    merged = a.merge(b)
    assert merged.abstract == "First"
    assert merged.year == 2017


def test_author_names() -> None:
    paper = make_paper()
    assert paper.author_names() == ["Ashish Vaswani", "Noam Shazeer"]
