"""Tests for the search aggregator and provider fan-out."""

from __future__ import annotations

from paperhound.models import Author, Paper, PaperIdentifier
from paperhound.search.aggregator import (
    SearchAggregator,
    _dedup_key,
    _normalize_title,
    _titles_similar,
)
from paperhound.search.base import SearchProvider, SearchQuery


class FakeProvider(SearchProvider):
    def __init__(self, name: str, results: list[Paper], lookup: Paper | None = None) -> None:
        self.name = name
        self._results = results
        self._lookup = lookup
        self.calls = 0

    def search(self, query: SearchQuery) -> list[Paper]:
        self.calls += 1
        return list(self._results)

    def get(self, identifier: str) -> Paper | None:
        return self._lookup


class FailingProvider(SearchProvider):
    name = "boom"

    def search(self, query: SearchQuery) -> list[Paper]:
        raise RuntimeError("provider down")

    def get(self, identifier: str) -> Paper | None:
        raise RuntimeError("provider down")


def make_paper(title: str, *, arxiv_id: str | None = None, source: str = "arxiv") -> Paper:
    return Paper(
        title=title,
        authors=[Author(name="A")],
        identifiers=PaperIdentifier(arxiv_id=arxiv_id),
        sources=[source],
    )


def test_normalize_title_removes_punctuation_and_case() -> None:
    assert _normalize_title("Attention Is All You Need!") == "attention is all you need"


def test_dedup_key_prefers_arxiv_then_doi() -> None:
    paper = Paper(
        title="x",
        identifiers=PaperIdentifier(arxiv_id="1706.03762", doi="10.1/x"),
    )
    assert _dedup_key(paper) == "arxiv:1706.03762"


def test_dedup_key_falls_back_to_title() -> None:
    paper = Paper(title="My Cool Paper")
    assert _dedup_key(paper) == "title:my cool paper"


def test_aggregator_merges_duplicates_by_arxiv_id() -> None:
    p1 = make_paper("Title A", arxiv_id="1234.5678", source="arxiv")
    p2 = make_paper("Different Title", arxiv_id="1234.5678", source="semantic_scholar")
    p2.abstract = "Filled by S2"
    aggregator = SearchAggregator(
        [
            FakeProvider("arxiv", [p1]),
            FakeProvider("s2", [p2]),
        ]
    )
    merged = aggregator.search(SearchQuery(text="x", limit=10))
    assert len(merged) == 1
    assert merged[0].abstract == "Filled by S2"
    assert sorted(merged[0].sources) == ["arxiv", "semantic_scholar"]


def test_aggregator_dedupes_by_title_when_no_ids() -> None:
    a = make_paper("Same Paper Title")
    a.identifiers = PaperIdentifier()
    b = make_paper("same paper title!")
    b.identifiers = PaperIdentifier()
    b.sources = ["semantic_scholar"]
    aggregator = SearchAggregator([FakeProvider("a", [a]), FakeProvider("b", [b])])
    merged = aggregator.search(SearchQuery(text="x", limit=10))
    assert len(merged) == 1


def test_aggregator_survives_failing_provider() -> None:
    good = make_paper("Survivor", arxiv_id="0000.0001")
    aggregator = SearchAggregator([FakeProvider("ok", [good]), FailingProvider()])
    merged = aggregator.search(SearchQuery(text="x", limit=10))
    assert [p.title for p in merged] == ["Survivor"]


def test_aggregator_get_merges_lookup() -> None:
    arxiv_paper = make_paper("X", arxiv_id="0000.0001", source="arxiv")
    s2_paper = make_paper("X", arxiv_id="0000.0001", source="semantic_scholar")
    s2_paper.abstract = "From S2"
    aggregator = SearchAggregator(
        [
            FakeProvider("arxiv", [], lookup=arxiv_paper),
            FakeProvider("s2", [], lookup=s2_paper),
        ]
    )
    paper = aggregator.get("0000.0001")
    assert paper is not None
    assert paper.abstract == "From S2"
    assert sorted(paper.sources) == ["arxiv", "semantic_scholar"]


def test_aggregator_respects_limit() -> None:
    papers = [make_paper(f"P{i}", arxiv_id=f"0000.000{i}") for i in range(5)]
    aggregator = SearchAggregator([FakeProvider("a", papers)])
    merged = aggregator.search(SearchQuery(text="x", limit=2))
    assert len(merged) == 2


def test_aggregator_round_robin_interleaves_providers() -> None:
    """One greedy provider returning ``limit`` rows must not starve the others."""
    a = [make_paper(f"A{i}", arxiv_id=f"1000.000{i}") for i in range(5)]
    b = [make_paper(f"B{i}", arxiv_id=f"2000.000{i}") for i in range(5)]
    c = [make_paper(f"C{i}", arxiv_id=f"3000.000{i}") for i in range(5)]
    aggregator = SearchAggregator(
        [FakeProvider("a", a), FakeProvider("b", b), FakeProvider("c", c)]
    )
    merged = aggregator.search(SearchQuery(text="x", limit=6))
    assert [p.title for p in merged] == ["A0", "B0", "C0", "A1", "B1", "C1"]


def test_aggregator_round_robin_skips_empty_providers() -> None:
    a = [make_paper(f"A{i}", arxiv_id=f"1000.000{i}") for i in range(3)]
    aggregator = SearchAggregator([FakeProvider("empty", []), FakeProvider("a", a)])
    merged = aggregator.search(SearchQuery(text="x", limit=3))
    assert [p.title for p in merged] == ["A0", "A1", "A2"]


def test_titles_similar_accepts_minor_punctuation() -> None:
    assert _titles_similar("Attention Is All You Need", "Attention is all you need!")


def test_titles_similar_rejects_unrelated_records() -> None:
    assert not _titles_similar(
        "Scaling Laws for Neural Language Models",
        "A clinical study of dust mite allergy in pediatric asthma",
    )


def test_aggregator_get_drops_poisoned_record_for_arxiv_id() -> None:
    """OpenAlex sometimes hijacks an arXiv id with junk metadata. Drop it."""
    arxiv_paper = Paper(
        title="Scaling Laws for Neural Language Models",
        abstract="We study empirical scaling laws.",
        identifiers=PaperIdentifier(arxiv_id="2001.08361"),
        sources=["arxiv"],
    )
    poisoned = Paper(
        title="Some completely unrelated junk paper from 1972",
        abstract="Lorem ipsum dolor sit amet.",
        identifiers=PaperIdentifier(arxiv_id="2001.08361", openalex_id="W123"),
        sources=["openalex"],
    )
    aggregator = SearchAggregator(
        [
            FakeProvider("arxiv", [], lookup=arxiv_paper),
            FakeProvider("openalex", [], lookup=poisoned),
        ]
    )
    paper = aggregator.get("2001.08361")
    assert paper is not None
    assert paper.title == "Scaling Laws for Neural Language Models"
    assert paper.abstract == "We study empirical scaling laws."
    # Poisoned record contributed neither identifier nor source.
    assert paper.sources == ["arxiv"]
    assert paper.identifiers.openalex_id is None


def test_aggregator_get_keeps_consistent_record_for_arxiv_id() -> None:
    arxiv_paper = Paper(
        title="Attention Is All You Need",
        identifiers=PaperIdentifier(arxiv_id="1706.03762"),
        sources=["arxiv"],
    )
    openalex_paper = Paper(
        title="Attention is all you need.",
        abstract="From OpenAlex.",
        identifiers=PaperIdentifier(arxiv_id="1706.03762", openalex_id="W42"),
        sources=["openalex"],
    )
    aggregator = SearchAggregator(
        [
            FakeProvider("arxiv", [], lookup=arxiv_paper),
            FakeProvider("openalex", [], lookup=openalex_paper),
        ]
    )
    paper = aggregator.get("1706.03762")
    assert paper is not None
    assert paper.abstract == "From OpenAlex."
    assert paper.identifiers.openalex_id == "W42"
    assert sorted(paper.sources) == ["arxiv", "openalex"]


def test_aggregator_get_uses_arxiv_as_base_regardless_of_completion_order() -> None:
    """Even if openalex finishes first, arxiv stays the source of truth for arxiv ids."""
    arxiv_paper = Paper(
        title="Chain-of-Thought Prompting Elicits Reasoning in Large Language Models",
        identifiers=PaperIdentifier(arxiv_id="2201.11903"),
        sources=["arxiv"],
    )
    poisoned = Paper(
        title="An unrelated dental hygiene survey",
        abstract="Junk abstract.",
        identifiers=PaperIdentifier(arxiv_id="2201.11903"),
        sources=["openalex"],
    )
    # Provider order matters for tie-breaking but the authoritative pick must
    # win regardless. Put openalex first to prove it.
    aggregator = SearchAggregator(
        [
            FakeProvider("openalex", [], lookup=poisoned),
            FakeProvider("arxiv", [], lookup=arxiv_paper),
        ]
    )
    paper = aggregator.get("2201.11903")
    assert paper is not None
    assert "Chain-of-Thought" in paper.title
    assert paper.abstract is None  # poisoned abstract dropped


def test_aggregator_round_robin_dedupes_within_round() -> None:
    """Same paper from two providers in the same round merges, doesn't duplicate."""
    a = [make_paper("Same", arxiv_id="9999.0001", source="arxiv")]
    b = [make_paper("Same", arxiv_id="9999.0001", source="openalex")]
    aggregator = SearchAggregator([FakeProvider("a", a), FakeProvider("b", b)])
    merged = aggregator.search(SearchQuery(text="x", limit=10))
    assert len(merged) == 1
    assert sorted(merged[0].sources) == ["arxiv", "openalex"]
