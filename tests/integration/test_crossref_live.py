"""Live Crossref integration tests."""

from __future__ import annotations

import pytest

from paperhound.search.base import SearchQuery
from paperhound.search.crossref import CrossrefProvider

pytestmark = [pytest.mark.integration]


def test_crossref_search_returns_results() -> None:
    with CrossrefProvider() as provider:
        results = provider.search(SearchQuery(text="transformer attention", limit=3))
    assert results
    assert all(p.title for p in results)


def test_crossref_get_by_doi() -> None:
    with CrossrefProvider() as provider:
        paper = provider.get("10.48550/arXiv.1706.03762")
    # Crossref may or may not have arXiv DOIs; tolerate both cases but require
    # the lookup to either return a valid record or None (not raise).
    if paper is not None:
        assert paper.identifiers.doi
