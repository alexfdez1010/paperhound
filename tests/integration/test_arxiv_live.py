"""Live arXiv smoke test. Skipped unless PAPERHOUND_RUN_INTEGRATION=1."""

from __future__ import annotations

import os

import pytest

from paperhound.search.arxiv_provider import ArxivProvider
from paperhound.search.base import SearchQuery

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("PAPERHOUND_RUN_INTEGRATION") != "1",
        reason="Set PAPERHOUND_RUN_INTEGRATION=1 to run live network tests.",
    ),
]


def test_arxiv_search_returns_results() -> None:
    provider = ArxivProvider()
    results = provider.search(SearchQuery(text="attention is all you need", limit=3))
    assert results
    assert any("attention" in p.title.lower() for p in results)


def test_arxiv_get_returns_known_paper() -> None:
    provider = ArxivProvider()
    paper = provider.get("1706.03762")
    assert paper is not None
    assert paper.identifiers.arxiv_id == "1706.03762"
    assert paper.abstract
