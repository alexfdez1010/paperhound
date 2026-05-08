"""Tests for the Crossref provider."""

from __future__ import annotations

import httpx
import pytest
import respx

from paperhound.errors import ProviderError
from paperhound.models import SearchFilters
from paperhound.search.base import SearchQuery
from paperhound.search.crossref import CROSSREF_BASE_URL, CrossrefProvider


def _sample_item() -> dict:
    return {
        "DOI": "10.1234/x",
        "title": ["Attention Is All You Need"],
        "container-title": ["NeurIPS"],
        "type": "proceedings-article",
        "issued": {"date-parts": [[2017, 6, 12]]},
        "is-referenced-by-count": 100000,
        "URL": "https://doi.org/10.1234/x",
        "author": [
            {"given": "Ashish", "family": "Vaswani", "affiliation": [{"name": "Google"}]},
            {"given": "Noam", "family": "Shazeer", "affiliation": []},
        ],
        "link": [
            {"URL": "https://example.org/x.pdf", "content-type": "application/pdf"},
        ],
        "abstract": "<p>We propose a new architecture.</p>",
    }


@respx.mock
def test_search_parses_results() -> None:
    route = respx.get(f"{CROSSREF_BASE_URL}/works").mock(
        return_value=httpx.Response(200, json={"message": {"items": [_sample_item()]}})
    )
    with CrossrefProvider() as provider:
        papers = provider.search(SearchQuery(text="transformers", limit=2))
    assert route.called
    assert len(papers) == 1
    paper = papers[0]
    assert paper.title == "Attention Is All You Need"
    assert paper.identifiers.doi == "10.1234/x"
    assert paper.year == 2017
    assert paper.venue == "NeurIPS"
    assert paper.pdf_url == "https://example.org/x.pdf"
    assert paper.authors[0].name == "Ashish Vaswani"
    assert paper.authors[0].affiliation == "Google"
    assert paper.citation_count == 100000
    assert paper.publication_type == "conference"


@respx.mock
def test_search_passes_year_filter() -> None:
    route = respx.get(f"{CROSSREF_BASE_URL}/works").mock(
        return_value=httpx.Response(200, json={"message": {"items": []}})
    )
    with CrossrefProvider() as provider:
        provider.search(SearchQuery(text="x", limit=2, year_min=2020, year_max=2024))
    assert route.calls[0].request.url.params["filter"].startswith("from-pub-date:2020")


@respx.mock
def test_get_by_doi() -> None:
    route = respx.get(f"{CROSSREF_BASE_URL}/works/10.1234/x").mock(
        return_value=httpx.Response(200, json={"message": _sample_item()})
    )
    with CrossrefProvider() as provider:
        paper = provider.get("10.1234/x")
    assert route.called
    assert paper is not None
    assert paper.identifiers.doi == "10.1234/x"


@respx.mock
def test_get_returns_none_on_404() -> None:
    respx.get(f"{CROSSREF_BASE_URL}/works/10.1/missing").mock(return_value=httpx.Response(404))
    with CrossrefProvider() as provider:
        assert provider.get("10.1/missing") is None


def test_get_unsupported_identifier() -> None:
    with CrossrefProvider() as provider:
        # Random S2-shaped id that isn't a DOI -> None, no network call.
        assert provider.get("a" * 40) is None


@respx.mock
def test_search_raises_on_error() -> None:
    respx.get(f"{CROSSREF_BASE_URL}/works").mock(return_value=httpx.Response(500))
    with CrossrefProvider() as provider, pytest.raises(ProviderError):
        provider.search(SearchQuery(text="x", limit=1))


@respx.mock
def test_search_unescapes_html_entities_in_title_and_abstract() -> None:
    item = _sample_item()
    item["title"] = ["Foo &amp; Bar &lt;baz&gt;"]
    item["abstract"] = "<jats:p>Alpha &amp; Beta</jats:p>"
    respx.get(f"{CROSSREF_BASE_URL}/works").mock(
        return_value=httpx.Response(200, json={"message": {"items": [item]}})
    )
    with CrossrefProvider() as provider:
        papers = provider.search(SearchQuery(text="x", limit=1))
    assert papers[0].title == "Foo & Bar <baz>"
    assert "&amp;" not in (papers[0].abstract or "")
    assert "Alpha & Beta" in (papers[0].abstract or "")


@respx.mock
def test_user_agent_includes_mailto() -> None:
    route = respx.get(f"{CROSSREF_BASE_URL}/works").mock(
        return_value=httpx.Response(200, json={"message": {"items": []}})
    )
    with CrossrefProvider(mailto="me@example.com") as provider:
        provider.search(SearchQuery(text="x", limit=1))
    assert "mailto:me@example.com" in route.calls[0].request.headers["User-Agent"]


@respx.mock
def test_search_pushes_down_author_filter() -> None:
    route = respx.get(f"{CROSSREF_BASE_URL}/works").mock(
        return_value=httpx.Response(200, json={"message": {"items": []}})
    )
    filters = SearchFilters(author="Hinton")
    with CrossrefProvider() as provider:
        provider.search(SearchQuery(text="x", limit=2, filters=filters))
    assert route.calls[0].request.url.params["query.author"] == "Hinton"


@respx.mock
def test_search_pushes_down_year_from_filters_when_query_root_empty() -> None:
    """year_min/year_max from SearchFilters are pushed down even when not set on query root."""
    route = respx.get(f"{CROSSREF_BASE_URL}/works").mock(
        return_value=httpx.Response(200, json={"message": {"items": []}})
    )
    filters = SearchFilters(year_min=2021, year_max=2023)
    with CrossrefProvider() as provider:
        provider.search(SearchQuery(text="x", limit=2, filters=filters))
    filter_param = route.calls[0].request.url.params["filter"]
    assert "from-pub-date:2021" in filter_param
    assert "until-pub-date:2023" in filter_param
