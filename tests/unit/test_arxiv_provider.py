"""Tests for the arXiv provider — uses an in-memory fake client."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

import pytest

from paperhound.errors import ProviderError
from paperhound.search.arxiv_provider import ArxivProvider, _result_to_paper
from paperhound.search.base import SearchQuery


class FakeAuthor:
    def __init__(self, name: str) -> None:
        self.name = name

    def __str__(self) -> str:
        return self.name


class FakeResult:
    def __init__(
        self,
        *,
        short_id: str = "1706.03762v3",
        title: str = "Attention Is All You Need",
        summary: str = "A transformer paper.",
        authors: Iterable[str] = ("Ashish Vaswani",),
        published: datetime = datetime(2017, 6, 12),
        entry_id: str = "http://arxiv.org/abs/1706.03762v3",
        pdf_url: str = "http://arxiv.org/pdf/1706.03762v3",
        doi: str | None = None,
    ) -> None:
        self._short_id = short_id
        self.title = title
        self.summary = summary
        self.authors = [FakeAuthor(a) for a in authors]
        self.published = published
        self.entry_id = entry_id
        self.pdf_url = pdf_url
        self.doi = doi

    def get_short_id(self) -> str:
        return self._short_id


class FakeArxivClient:
    def __init__(self, results: list[FakeResult]) -> None:
        self._results = results
        self.last_search = None

    def results(self, search):  # noqa: D401 - mimics arxiv.Client API
        self.last_search = search
        return iter(self._results)


def test_result_to_paper_normalizes_id_and_year() -> None:
    paper = _result_to_paper(FakeResult())  # type: ignore[arg-type]
    assert paper.identifiers.arxiv_id == "1706.03762"
    assert paper.year == 2017
    assert paper.pdf_url.startswith("http://arxiv.org/pdf/")
    assert paper.sources == ["arxiv"]


def test_search_returns_papers() -> None:
    client = FakeArxivClient([FakeResult()])
    provider = ArxivProvider(client=client)  # type: ignore[arg-type]
    results = provider.search(SearchQuery(text="transformers", limit=1))
    assert len(results) == 1
    assert results[0].title == "Attention Is All You Need"


def test_search_appends_year_range_filter() -> None:
    client = FakeArxivClient([])
    provider = ArxivProvider(client=client)  # type: ignore[arg-type]
    provider.search(SearchQuery(text="x", limit=1, year_min=2020, year_max=2022))
    assert "submittedDate:[20200101 TO 20221231]" in client.last_search.query


def test_get_returns_none_when_empty() -> None:
    client = FakeArxivClient([])
    provider = ArxivProvider(client=client)  # type: ignore[arg-type]
    assert provider.get("1706.03762") is None


def test_get_raises_for_invalid_id() -> None:
    client = FakeArxivClient([])
    provider = ArxivProvider(client=client)  # type: ignore[arg-type]
    with pytest.raises(ProviderError):
        provider.get("not-an-id")


def test_get_returns_paper_for_valid_id() -> None:
    client = FakeArxivClient([FakeResult()])
    provider = ArxivProvider(client=client)  # type: ignore[arg-type]
    paper = provider.get("1706.03762")
    assert paper is not None
    assert paper.identifiers.arxiv_id == "1706.03762"


def test_search_wraps_client_errors() -> None:
    class BoomClient:
        def results(self, search):
            raise RuntimeError("boom")

    provider = ArxivProvider(client=BoomClient())  # type: ignore[arg-type]
    with pytest.raises(ProviderError):
        provider.search(SearchQuery(text="x", limit=1))
