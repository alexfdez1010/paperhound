"""Tests for the DBLP provider."""

from __future__ import annotations

import httpx
import pytest
import respx

from paperhound.errors import ProviderError
from paperhound.search.base import SearchQuery
from paperhound.search.dblp import DBLP_BASE_URL, DBLPProvider


def _hit(title: str, year: str = "2020", arxiv: str | None = None) -> dict:
    info: dict = {
        "title": title,
        "year": year,
        "venue": "NeurIPS",
        "key": "conf/nips/x",
        "doi": "10.1234/x",
        "url": "https://dblp.org/x",
        "authors": {"author": [{"text": "Alice"}, {"text": "Bob"}]},
    }
    if arxiv:
        info["ee"] = f"https://arxiv.org/abs/{arxiv}"
    return {"info": info}


@respx.mock
def test_search_parses_hits() -> None:
    route = respx.get(DBLP_BASE_URL).mock(
        return_value=httpx.Response(
            200,
            json={"result": {"hits": {"hit": [_hit("Paper A", arxiv="2401.12345")]}}},
        )
    )
    with DBLPProvider() as provider:
        papers = provider.search(SearchQuery(text="x", limit=3))
    assert route.called
    assert len(papers) == 1
    paper = papers[0]
    assert paper.title == "Paper A"
    assert paper.year == 2020
    assert paper.identifiers.dblp_key == "conf/nips/x"
    assert paper.identifiers.doi == "10.1234/x"
    assert paper.identifiers.arxiv_id == "2401.12345"
    assert [a.name for a in paper.authors] == ["Alice", "Bob"]


@respx.mock
def test_search_handles_single_hit_dict() -> None:
    # DBLP returns a single hit as a dict (not list); we must accept both.
    respx.get(DBLP_BASE_URL).mock(
        return_value=httpx.Response(200, json={"result": {"hits": {"hit": _hit("Solo")}}})
    )
    with DBLPProvider() as provider:
        papers = provider.search(SearchQuery(text="x", limit=1))
    assert [p.title for p in papers] == ["Solo"]


@respx.mock
def test_search_handles_no_hits() -> None:
    respx.get(DBLP_BASE_URL).mock(return_value=httpx.Response(200, json={"result": {"hits": {}}}))
    with DBLPProvider() as provider:
        papers = provider.search(SearchQuery(text="x", limit=1))
    assert papers == []


@respx.mock
def test_search_filters_by_year() -> None:
    respx.get(DBLP_BASE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "result": {
                    "hits": {
                        "hit": [
                            _hit("Old", year="2010"),
                            _hit("New", year="2024"),
                        ]
                    }
                }
            },
        )
    )
    with DBLPProvider() as provider:
        papers = provider.search(SearchQuery(text="x", limit=10, year_min=2020))
    assert [p.title for p in papers] == ["New"]


@respx.mock
def test_search_raises_on_error() -> None:
    respx.get(DBLP_BASE_URL).mock(return_value=httpx.Response(500))
    with DBLPProvider() as provider, pytest.raises(ProviderError):
        provider.search(SearchQuery(text="x", limit=1))


def test_get_returns_none() -> None:
    # DBLP has no lookup endpoint; the provider declares no ID_LOOKUP.
    with DBLPProvider() as provider:
        assert provider.get("10.1234/x") is None
