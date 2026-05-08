"""Tests for the Hugging Face Papers provider."""

from __future__ import annotations

import httpx
import pytest
import respx

from paperhound.errors import ProviderError
from paperhound.search.base import SearchQuery
from paperhound.search.huggingface import HF_BASE_URL, HuggingFaceProvider


def _sample_paper() -> dict:
    return {
        "id": "1706.03762",
        "title": "Attention Is All You Need",
        "summary": "We propose a new architecture.",
        "publishedAt": "2017-06-12T00:00:00.000Z",
        "upvotes": 42,
        "authors": [
            {"name": "Ashish Vaswani"},
            {"name": "Noam Shazeer"},
        ],
    }


@respx.mock
def test_search_parses_results() -> None:
    route = respx.get(f"{HF_BASE_URL}/search").mock(
        return_value=httpx.Response(200, json=[{"paper": _sample_paper()}])
    )
    with HuggingFaceProvider() as provider:
        papers = provider.search(SearchQuery(text="transformer", limit=2))
    assert route.called
    assert len(papers) == 1
    paper = papers[0]
    assert paper.title == "Attention Is All You Need"
    assert paper.identifiers.arxiv_id == "1706.03762"
    assert paper.year == 2017
    assert paper.pdf_url == "https://arxiv.org/pdf/1706.03762.pdf"
    assert paper.citation_count == 42
    assert paper.publication_type == "preprint"


@respx.mock
def test_search_year_filter() -> None:
    respx.get(f"{HF_BASE_URL}/search").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"paper": {**_sample_paper(), "publishedAt": "2010-01-01", "title": "Old"}},
                {"paper": {**_sample_paper(), "publishedAt": "2024-01-01", "title": "New"}},
            ],
        )
    )
    with HuggingFaceProvider() as provider:
        papers = provider.search(SearchQuery(text="x", limit=10, year_min=2020))
    assert [p.title for p in papers] == ["New"]


@respx.mock
def test_get_by_arxiv() -> None:
    route = respx.get(f"{HF_BASE_URL}/1706.03762").mock(
        return_value=httpx.Response(200, json=_sample_paper())
    )
    with HuggingFaceProvider() as provider:
        paper = provider.get("1706.03762")
    assert route.called
    assert paper is not None
    assert paper.identifiers.arxiv_id == "1706.03762"


@respx.mock
def test_get_returns_none_on_404() -> None:
    respx.get(f"{HF_BASE_URL}/0000.0000").mock(return_value=httpx.Response(404))
    with HuggingFaceProvider() as provider:
        assert provider.get("0000.0000") is None


def test_get_unsupported_identifier() -> None:
    with HuggingFaceProvider() as provider:
        # DOI -> HF endpoint only takes arXiv ids; provider must short-circuit.
        assert provider.get("10.1234/x") is None


@respx.mock
def test_search_raises_on_5xx() -> None:
    respx.get(f"{HF_BASE_URL}/search").mock(return_value=httpx.Response(500))
    with HuggingFaceProvider() as provider, pytest.raises(ProviderError):
        provider.search(SearchQuery(text="x", limit=1))
