"""Tests for the Semantic Scholar provider."""

from __future__ import annotations

import httpx
import pytest
import respx

from paperhound.errors import ProviderError
from paperhound.search.base import SearchQuery
from paperhound.search.semantic_scholar import S2_BASE_URL, SemanticScholarProvider


def _sample_payload() -> dict:
    return {
        "paperId": "f" * 40,
        "title": "Attention Is All You Need",
        "abstract": "We propose a new architecture.",
        "year": 2017,
        "venue": "NeurIPS",
        "url": "https://www.semanticscholar.org/paper/abc",
        "citationCount": 100000,
        "externalIds": {"ArXiv": "1706.03762", "DOI": "10.1/x"},
        "openAccessPdf": {"url": "https://arxiv.org/pdf/1706.03762.pdf"},
        "authors": [
            {"name": "Ashish Vaswani", "affiliations": ["Google"]},
            {"name": "Noam Shazeer", "affiliations": []},
        ],
    }


@respx.mock
def test_search_parses_results() -> None:
    route = respx.get(f"{S2_BASE_URL}/paper/search").mock(
        return_value=httpx.Response(200, json={"data": [_sample_payload()]})
    )
    with SemanticScholarProvider() as provider:
        results = provider.search(SearchQuery(text="transformers", limit=5))
    assert route.called
    assert len(results) == 1
    paper = results[0]
    assert paper.title == "Attention Is All You Need"
    assert paper.identifiers.arxiv_id == "1706.03762"
    assert paper.identifiers.doi == "10.1/x"
    assert paper.pdf_url == "https://arxiv.org/pdf/1706.03762.pdf"
    assert paper.authors[0].affiliation == "Google"
    assert paper.sources == ["semantic_scholar"]


@respx.mock
def test_search_passes_year_range() -> None:
    route = respx.get(f"{S2_BASE_URL}/paper/search").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    with SemanticScholarProvider() as provider:
        provider.search(SearchQuery(text="x", limit=3, year_min=2015, year_max=2018))
    assert route.calls[0].request.url.params["year"] == "2015-2018"


@respx.mock
def test_search_raises_provider_error_on_5xx() -> None:
    respx.get(f"{S2_BASE_URL}/paper/search").mock(return_value=httpx.Response(500))
    with SemanticScholarProvider() as provider, pytest.raises(ProviderError):
        provider.search(SearchQuery(text="x", limit=1))


@respx.mock
def test_get_by_arxiv_id_uses_lookup_prefix() -> None:
    route = respx.get(f"{S2_BASE_URL}/paper/ARXIV:1706.03762").mock(
        return_value=httpx.Response(200, json=_sample_payload())
    )
    with SemanticScholarProvider() as provider:
        paper = provider.get("1706.03762")
    assert route.called
    assert paper is not None
    assert paper.identifiers.arxiv_id == "1706.03762"


@respx.mock
def test_get_returns_none_on_404() -> None:
    respx.get(f"{S2_BASE_URL}/paper/ARXIV:0000.0000").mock(return_value=httpx.Response(404))
    with SemanticScholarProvider() as provider:
        assert provider.get("0000.0000") is None


@respx.mock
def test_api_key_sent_when_provided() -> None:
    route = respx.get(f"{S2_BASE_URL}/paper/search").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    with SemanticScholarProvider(api_key="secret") as provider:
        provider.search(SearchQuery(text="x", limit=1))
    assert route.calls[0].request.headers["x-api-key"] == "secret"


@respx.mock
def test_search_raises_clear_error_on_403() -> None:
    respx.get(f"{S2_BASE_URL}/paper/search").mock(return_value=httpx.Response(403))
    with SemanticScholarProvider(max_retries=0) as provider:
        with pytest.raises(ProviderError) as info:
            provider.search(SearchQuery(text="x", limit=1))
    msg = str(info.value)
    assert "403" in msg
    assert "SEMANTIC_SCHOLAR_API_KEY" in msg


@respx.mock
def test_search_retries_on_429_then_succeeds() -> None:
    sleeps: list[float] = []
    route = respx.get(f"{S2_BASE_URL}/paper/search").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json={"data": [_sample_payload()]}),
        ]
    )
    with SemanticScholarProvider(
        max_retries=3, retry_base_delay=0.0, sleep=sleeps.append
    ) as provider:
        results = provider.search(SearchQuery(text="x", limit=1))
    assert route.call_count == 3
    assert len(results) == 1
    assert len(sleeps) == 2


@respx.mock
def test_search_raises_rate_limit_after_retries_exhausted() -> None:
    respx.get(f"{S2_BASE_URL}/paper/search").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "0"})
    )
    with SemanticScholarProvider(max_retries=2, retry_base_delay=0.0, sleep=lambda _: None) as p:
        with pytest.raises(ProviderError) as info:
            p.search(SearchQuery(text="x", limit=1))
    assert "rate-limited" in str(info.value)
