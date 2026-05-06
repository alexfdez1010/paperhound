"""Live DBLP integration tests."""

from __future__ import annotations

import pytest

from paperhound.search.base import SearchQuery
from paperhound.search.dblp import DBLPProvider

pytestmark = [pytest.mark.integration]


def test_dblp_search_returns_cs_results() -> None:
    with DBLPProvider() as provider:
        results = provider.search(SearchQuery(text="attention is all you need", limit=5))
    assert results
    assert all(p.title for p in results)
