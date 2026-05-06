"""Tests for the Papers with Code provider."""

from __future__ import annotations

import httpx
import pytest
import respx

from paperhound.errors import ProviderError
from paperhound.search.base import SearchQuery
from paperhound.search.paperswithcode import PWC_BASE_URL, PapersWithCodeProvider


def _sample_paper() -> dict:
    return {
        "id": "attention-is-all-you-need",
        "title": "Attention Is All You Need",
        "abstract": "We propose a new architecture.",
        "authors": ["Ashish Vaswani", "Noam Shazeer"],
        "published": "2017-06-12",
        "arxiv_id": "1706.03762",
        "doi": "10.1234/x",
        "url_pdf": "https://example.org/x.pdf",
        "url_abs": "https://arxiv.org/abs/1706.03762",
        "conference": "NeurIPS",
    }


@respx.mock
def test_search_parses_results() -> None:
    route = respx.get(f"{PWC_BASE_URL}/papers/").mock(
        return_value=httpx.Response(200, json={"results": [_sample_paper()]})
    )
    with PapersWithCodeProvider() as provider:
        papers = provider.search(SearchQuery(text="transformer", limit=2))
    assert route.called
    assert len(papers) == 1
    paper = papers[0]
    assert paper.title == "Attention Is All You Need"
    assert paper.identifiers.arxiv_id == "1706.03762"
    assert paper.identifiers.pwc_id == "attention-is-all-you-need"
    assert paper.year == 2017
    assert paper.venue == "NeurIPS"


@respx.mock
def test_search_year_filter() -> None:
    respx.get(f"{PWC_BASE_URL}/papers/").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {**_sample_paper(), "published": "2010-01-01", "title": "Old"},
                    {**_sample_paper(), "published": "2024-01-01", "title": "New"},
                ]
            },
        )
    )
    with PapersWithCodeProvider() as provider:
        papers = provider.search(SearchQuery(text="x", limit=10, year_min=2020))
    assert [p.title for p in papers] == ["New"]


@respx.mock
def test_get_by_arxiv() -> None:
    route = respx.get(f"{PWC_BASE_URL}/papers/").mock(
        return_value=httpx.Response(200, json={"results": [_sample_paper()]})
    )
    with PapersWithCodeProvider() as provider:
        paper = provider.get("1706.03762")
    assert route.called
    assert paper is not None
    assert paper.identifiers.arxiv_id == "1706.03762"


@respx.mock
def test_get_returns_none_when_no_results() -> None:
    respx.get(f"{PWC_BASE_URL}/papers/").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    with PapersWithCodeProvider() as provider:
        assert provider.get("1706.03762") is None


@respx.mock
def test_search_raises_on_error() -> None:
    respx.get(f"{PWC_BASE_URL}/papers/").mock(return_value=httpx.Response(500))
    with PapersWithCodeProvider() as provider, pytest.raises(ProviderError):
        provider.search(SearchQuery(text="x", limit=1))
