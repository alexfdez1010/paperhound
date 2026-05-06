"""Live OpenAlex integration tests."""

from __future__ import annotations

import pytest

from paperhound.search.base import SearchQuery
from paperhound.search.openalex import OpenAlexProvider

pytestmark = [pytest.mark.integration]


def test_openalex_search_returns_results() -> None:
    with OpenAlexProvider() as provider:
        results = provider.search(SearchQuery(text="transformer attention", limit=3))
    assert results
    assert all(p.title for p in results)


def test_openalex_get_by_doi() -> None:
    with OpenAlexProvider() as provider:
        paper = provider.get("10.48550/arXiv.1706.03762")
    assert paper is not None
    assert paper.title.lower().startswith("attention")
