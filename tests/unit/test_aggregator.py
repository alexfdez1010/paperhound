"""Tests for the search aggregator and provider fan-out."""

from __future__ import annotations

from paperhound.models import Author, Paper, PaperIdentifier
from paperhound.search.aggregator import SearchAggregator, _dedup_key, _normalize_title
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
