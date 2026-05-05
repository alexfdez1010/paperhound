"""Live arXiv integration tests. Always run — they hit the real arXiv API."""

from __future__ import annotations

import pytest

from paperhound.search.arxiv_provider import ArxivProvider
from paperhound.search.base import SearchQuery

pytestmark = [pytest.mark.integration]


def test_arxiv_search_returns_results() -> None:
    provider = ArxivProvider()
    results = provider.search(SearchQuery(text="attention is all you need", limit=3))
    assert results
    assert any("attention" in p.title.lower() for p in results)
    assert all(p.identifiers.arxiv_id for p in results)
    assert all(p.url for p in results)


def test_arxiv_get_returns_known_paper() -> None:
    provider = ArxivProvider()
    paper = provider.get("1706.03762")
    assert paper is not None
    assert paper.identifiers.arxiv_id == "1706.03762"
    assert paper.abstract
    assert paper.pdf_url and paper.pdf_url.startswith("http")
    assert paper.authors
    assert any("Vaswani" in a.name for a in paper.authors)


def test_arxiv_get_unknown_id_returns_none() -> None:
    provider = ArxivProvider()
    assert provider.get("0000.00000") is None
