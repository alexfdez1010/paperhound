"""Tests for the CORE provider."""

from __future__ import annotations

import httpx
import pytest
import respx

from paperhound.errors import ProviderError
from paperhound.search.base import SearchQuery
from paperhound.search.core import CORE_BASE_URL, CoreProvider


def _sample_work() -> dict:
    return {
        "id": 12345,
        "doi": "10.1234/x",
        "title": "Attention Is All You Need",
        "abstract": "We propose a new architecture.",
        "yearPublished": 2017,
        "downloadUrl": "https://example.org/x.pdf",
        "arxivId": "1706.03762",
        "authors": [{"name": "Ashish Vaswani"}, {"name": "Noam Shazeer"}],
        "journals": [{"title": "NeurIPS"}],
    }


@respx.mock
def test_search_parses_results() -> None:
    route = respx.post(f"{CORE_BASE_URL}/search/works").mock(
        return_value=httpx.Response(200, json={"results": [_sample_work()]})
    )
    with CoreProvider(api_key="k") as provider:
        papers = provider.search(SearchQuery(text="transformers", limit=2))
    assert route.called
    assert route.calls[0].request.headers["Authorization"] == "Bearer k"
    assert len(papers) == 1
    paper = papers[0]
    assert paper.title == "Attention Is All You Need"
    assert paper.identifiers.doi == "10.1234/x"
    assert paper.identifiers.arxiv_id == "1706.03762"
    assert paper.identifiers.core_id == "12345"
    assert paper.pdf_url == "https://example.org/x.pdf"
    assert paper.venue == "NeurIPS"


@respx.mock
def test_search_year_filter_appended_to_query() -> None:
    route = respx.post(f"{CORE_BASE_URL}/search/works").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    with CoreProvider(api_key="k") as provider:
        provider.search(SearchQuery(text="x", limit=1, year_min=2020, year_max=2024))
    body = route.calls[0].request.read().decode()
    assert "yearPublished>=2020" in body
    assert "yearPublished<=2024" in body


def test_provider_unavailable_without_key() -> None:
    provider = CoreProvider(api_key=None)
    assert provider.available() is False


@respx.mock
def test_get_by_doi_uses_discover() -> None:
    route = respx.post(f"{CORE_BASE_URL}/discover").mock(
        return_value=httpx.Response(200, json=_sample_work())
    )
    with CoreProvider(api_key="k") as provider:
        paper = provider.get("10.1234/x")
    assert route.called
    assert paper is not None


@respx.mock
def test_search_raises_on_auth_error() -> None:
    respx.post(f"{CORE_BASE_URL}/search/works").mock(return_value=httpx.Response(401))
    with CoreProvider(api_key="bad") as provider, pytest.raises(ProviderError) as info:
        provider.search(SearchQuery(text="x", limit=1))
    assert "CORE_API_KEY" in str(info.value)
