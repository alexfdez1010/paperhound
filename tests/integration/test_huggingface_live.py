"""Live Hugging Face Papers integration tests."""

from __future__ import annotations

import pytest

from paperhound.search.base import SearchQuery
from paperhound.search.huggingface import HuggingFaceProvider

pytestmark = [pytest.mark.integration]


def test_huggingface_search_returns_results() -> None:
    with HuggingFaceProvider() as provider:
        results = provider.search(SearchQuery(text="attention transformer", limit=3))
    assert results
    assert all(p.title for p in results)


def test_huggingface_get_by_arxiv() -> None:
    with HuggingFaceProvider() as provider:
        paper = provider.get("1706.03762")
    assert paper is not None
    assert paper.identifiers.arxiv_id == "1706.03762"
