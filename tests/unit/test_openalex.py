"""Tests for the OpenAlex provider."""

from __future__ import annotations

import httpx
import pytest
import respx

from paperhound.errors import ProviderError
from paperhound.search.base import SearchQuery
from paperhound.search.openalex import OPENALEX_BASE_URL, OpenAlexProvider


def _sample_work() -> dict:
    return {
        "id": "https://openalex.org/W2741809807",
        "doi": "https://doi.org/10.1234/x",
        "title": "Attention Is All You Need",
        "publication_year": 2017,
        "cited_by_count": 100000,
        "ids": {"arxiv": "https://arxiv.org/abs/1706.03762"},
        "primary_location": {
            "pdf_url": "https://example.org/x.pdf",
            "source": {"display_name": "NeurIPS"},
        },
        "best_oa_location": {"pdf_url": "https://oa.example/x.pdf"},
        "abstract_inverted_index": {"Hello": [0], "world": [1]},
        "authorships": [
            {
                "author": {"display_name": "Ashish Vaswani"},
                "institutions": [{"display_name": "Google"}],
            },
            {
                "author": {"display_name": "Noam Shazeer"},
                "institutions": [],
            },
        ],
    }


@respx.mock
def test_search_parses_results() -> None:
    route = respx.get(f"{OPENALEX_BASE_URL}/works").mock(
        return_value=httpx.Response(200, json={"results": [_sample_work()]})
    )
    with OpenAlexProvider() as provider:
        papers = provider.search(SearchQuery(text="transformers", limit=3))
    assert route.called
    assert len(papers) == 1
    paper = papers[0]
    assert paper.title == "Attention Is All You Need"
    assert paper.identifiers.openalex_id == "W2741809807"
    assert paper.identifiers.doi == "10.1234/x"
    assert paper.identifiers.arxiv_id == "1706.03762"
    assert paper.pdf_url == "https://oa.example/x.pdf"
    assert paper.venue == "NeurIPS"
    assert paper.abstract == "Hello world"
    assert paper.authors[0].affiliation == "Google"
    assert paper.sources == ["openalex"]


@respx.mock
def test_search_passes_year_filter() -> None:
    route = respx.get(f"{OPENALEX_BASE_URL}/works").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    with OpenAlexProvider() as provider:
        provider.search(SearchQuery(text="x", limit=2, year_min=2020, year_max=2024))
    assert (
        route.calls[0].request.url.params["filter"].startswith("from_publication_date:2020-01-01")
    )


@respx.mock
def test_get_by_doi_uses_doi_prefix() -> None:
    route = respx.get(f"{OPENALEX_BASE_URL}/works/doi:10.1234/x").mock(
        return_value=httpx.Response(200, json=_sample_work())
    )
    with OpenAlexProvider() as provider:
        paper = provider.get("10.1234/x")
    assert route.called
    assert paper is not None
    assert paper.identifiers.doi == "10.1234/x"


@respx.mock
def test_get_by_arxiv_translates_to_doi() -> None:
    route = respx.get(f"{OPENALEX_BASE_URL}/works/doi:10.48550/arXiv.1706.03762").mock(
        return_value=httpx.Response(200, json=_sample_work())
    )
    with OpenAlexProvider() as provider:
        paper = provider.get("1706.03762")
    assert route.called
    assert paper is not None


@respx.mock
def test_get_returns_none_on_404() -> None:
    respx.get(f"{OPENALEX_BASE_URL}/works/doi:10.1/missing").mock(return_value=httpx.Response(404))
    with OpenAlexProvider() as provider:
        assert provider.get("10.1/missing") is None


@respx.mock
def test_search_raises_on_5xx() -> None:
    respx.get(f"{OPENALEX_BASE_URL}/works").mock(return_value=httpx.Response(500))
    with OpenAlexProvider() as provider, pytest.raises(ProviderError):
        provider.search(SearchQuery(text="x", limit=1))


@respx.mock
def test_mailto_passed_when_provided() -> None:
    route = respx.get(f"{OPENALEX_BASE_URL}/works").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    with OpenAlexProvider(mailto="me@example.com") as provider:
        provider.search(SearchQuery(text="x", limit=1))
    assert route.calls[0].request.url.params["mailto"] == "me@example.com"
