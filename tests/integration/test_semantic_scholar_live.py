"""Live Semantic Scholar smoke test. Skipped unless PAPERHOUND_RUN_INTEGRATION=1."""

from __future__ import annotations

import os

import pytest

from paperhound.search.base import SearchQuery
from paperhound.search.semantic_scholar import SemanticScholarProvider

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("PAPERHOUND_RUN_INTEGRATION") != "1",
        reason="Set PAPERHOUND_RUN_INTEGRATION=1 to run live network tests.",
    ),
]


def test_s2_search_returns_results() -> None:
    with SemanticScholarProvider() as provider:
        results = provider.search(SearchQuery(text="transformer attention", limit=3))
    assert results


def test_s2_get_by_arxiv_id() -> None:
    with SemanticScholarProvider() as provider:
        paper = provider.get("1706.03762")
    assert paper is not None
    assert paper.identifiers.arxiv_id == "1706.03762"
