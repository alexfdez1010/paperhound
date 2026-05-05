"""Live Semantic Scholar integration tests. Always run.

All endpoints used here are reachable anonymously. The provider retries 429s
with backoff so the suite tolerates the shared public quota; setting
``SEMANTIC_SCHOLAR_API_KEY`` makes the runs faster but is not required.
"""

from __future__ import annotations

import pytest

from paperhound.search.base import SearchQuery
from paperhound.search.semantic_scholar import SemanticScholarProvider

pytestmark = [pytest.mark.integration]


def test_s2_search_returns_results() -> None:
    with SemanticScholarProvider() as provider:
        results = provider.search(SearchQuery(text="transformer attention", limit=3))
    assert results
    assert all(p.title for p in results)
    assert any(p.identifiers.semantic_scholar_id for p in results)


def test_s2_get_by_arxiv_id() -> None:
    with SemanticScholarProvider() as provider:
        paper = provider.get("1706.03762")
    assert paper is not None
    assert paper.identifiers.arxiv_id == "1706.03762"
    assert paper.title.lower().startswith("attention")


def test_s2_returns_none_for_unknown_doi() -> None:
    with SemanticScholarProvider() as provider:
        paper = provider.get("10.1234/this-doi-does-not-exist-paperhound-test")
    assert paper is None
