"""Tests for paperhound.citations — fetch_references / fetch_citations."""

from __future__ import annotations

import httpx
import pytest
import respx

from paperhound.citations import fetch_citations, fetch_references
from paperhound.errors import IdentifierError
from paperhound.search.openalex import OPENALEX_BASE_URL
from paperhound.search.semantic_scholar import S2_BASE_URL

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

ARXIV_ID = "1706.03762"
DOI = "10.1234/x"
OPENALEX_WID = "W2741809807"


def _oa_work(openalex_id: str = OPENALEX_WID, ref_ids: list[str] | None = None) -> dict:
    """Minimal OpenAlex work record."""
    full_id = f"https://openalex.org/{openalex_id}"
    return {
        "id": full_id,
        "doi": f"https://doi.org/{DOI}",
        "title": "Attention Is All You Need",
        "publication_year": 2017,
        "cited_by_count": 50000,
        "ids": {"arxiv": f"https://arxiv.org/abs/{ARXIV_ID}"},
        "primary_location": {"pdf_url": None, "source": {"display_name": "NeurIPS"}},
        "best_oa_location": {"pdf_url": "https://oa.example/x.pdf"},
        "abstract_inverted_index": {"hello": [0]},
        "authorships": [{"author": {"display_name": "A. Vaswani"}, "institutions": []}],
        "referenced_works": [
            f"https://openalex.org/{wid}" for wid in (ref_ids or ["W111", "W222"])
        ],
    }


def _oa_ref_work(n: int) -> dict:
    return {
        "id": f"https://openalex.org/W{n}",
        "doi": f"https://doi.org/10.{n}/x",
        "title": f"Reference Paper {n}",
        "publication_year": 2015,
        "cited_by_count": 10,
        "ids": {},
        "primary_location": {"pdf_url": None, "source": None},
        "best_oa_location": None,
        "abstract_inverted_index": None,
        "authorships": [],
        "referenced_works": [],
    }


def _s2_paper(paper_id: str, title: str = "Some Paper") -> dict:
    return {
        "paperId": paper_id,
        "title": title,
        "abstract": None,
        "year": 2020,
        "venue": None,
        "url": None,
        "citationCount": 5,
        "externalIds": {},
        "openAccessPdf": None,
        "authors": [],
    }


def _s2_ref_item(paper_id: str, title: str = "Ref Paper") -> dict:
    return {"citedPaper": _s2_paper(paper_id, title)}


def _s2_cite_item(paper_id: str, title: str = "Citing Paper") -> dict:
    return {"citingPaper": _s2_paper(paper_id, title)}


# ---------------------------------------------------------------------------
# fetch_references — happy path (OpenAlex depth=1)
# ---------------------------------------------------------------------------


@respx.mock
def test_fetch_references_openalex_depth1() -> None:
    """Happy path: refs at depth=1 from OpenAlex."""
    # Lookup route (by arXiv DOI)
    respx.get(f"{OPENALEX_BASE_URL}/works/doi:10.48550/arXiv.{ARXIV_ID}").mock(
        return_value=httpx.Response(200, json=_oa_work())
    )
    # Full work route (to get referenced_works)
    respx.get(f"{OPENALEX_BASE_URL}/works/{OPENALEX_WID}").mock(
        return_value=httpx.Response(200, json=_oa_work())
    )
    # Bulk fetch route
    respx.get(f"{OPENALEX_BASE_URL}/works").mock(
        return_value=httpx.Response(
            200,
            json={"results": [_oa_ref_work(111), _oa_ref_work(222)]},
        )
    )

    client = httpx.Client()
    papers = fetch_references(ARXIV_ID, depth=1, limit=25, source="openalex", client=client)
    client.close()

    assert len(papers) == 2
    assert papers[0].title == "Reference Paper 111"
    assert papers[1].title == "Reference Paper 222"


# ---------------------------------------------------------------------------
# fetch_citations — happy path (S2 depth=1)
# ---------------------------------------------------------------------------


@respx.mock
def test_fetch_citations_s2_depth1() -> None:
    """Happy path: cited-by at depth=1 from Semantic Scholar."""
    s2_id = "a" * 40
    respx.get(f"{S2_BASE_URL}/paper/ARXIV:{ARXIV_ID}/citations").mock(
        return_value=httpx.Response(
            200,
            json={"data": [_s2_cite_item(s2_id, "Citing Work")]},
        )
    )

    client = httpx.Client()
    papers = fetch_citations(ARXIV_ID, depth=1, limit=25, source="semantic_scholar", client=client)
    client.close()

    assert len(papers) == 1
    assert papers[0].title == "Citing Work"


# ---------------------------------------------------------------------------
# --limit honored
# ---------------------------------------------------------------------------


@respx.mock
def test_fetch_references_limit_honored() -> None:
    """Only the first N results up to --limit are returned."""
    s2_ids = [f"{'a' * 39}{i}" for i in range(5)]
    respx.get(f"{S2_BASE_URL}/paper/ARXIV:{ARXIV_ID}/references").mock(
        return_value=httpx.Response(
            200,
            json={"data": [_s2_ref_item(sid, f"Paper {i}") for i, sid in enumerate(s2_ids)]},
        )
    )

    client = httpx.Client()
    papers = fetch_references(ARXIV_ID, depth=1, limit=3, source="semantic_scholar", client=client)
    client.close()

    assert len(papers) == 3


# ---------------------------------------------------------------------------
# Fallback: OpenAlex empty → S2 used
# ---------------------------------------------------------------------------


@respx.mock
def test_fallback_openalex_empty_uses_s2() -> None:
    """When OpenAlex returns nothing (404 on lookup), S2 is tried."""
    # OpenAlex lookup 404
    respx.get(f"{OPENALEX_BASE_URL}/works/doi:10.48550/arXiv.{ARXIV_ID}").mock(
        return_value=httpx.Response(404)
    )
    # S2 references succeed
    s2_id = "b" * 40
    respx.get(f"{S2_BASE_URL}/paper/ARXIV:{ARXIV_ID}/references").mock(
        return_value=httpx.Response(
            200,
            json={"data": [_s2_ref_item(s2_id, "Fallback Paper")]},
        )
    )

    client = httpx.Client()
    papers = fetch_references(ARXIV_ID, depth=1, limit=25, source=None, client=client)
    client.close()

    assert len(papers) == 1
    assert papers[0].title == "Fallback Paper"


# ---------------------------------------------------------------------------
# Both empty → empty list (no error)
# ---------------------------------------------------------------------------


@respx.mock
def test_fetch_references_both_empty() -> None:
    """When both providers return nothing, result is an empty list."""
    respx.get(f"{OPENALEX_BASE_URL}/works/doi:10.48550/arXiv.{ARXIV_ID}").mock(
        return_value=httpx.Response(404)
    )
    respx.get(f"{S2_BASE_URL}/paper/ARXIV:{ARXIV_ID}/references").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    client = httpx.Client()
    papers = fetch_references(ARXIV_ID, depth=1, limit=25, client=client)
    client.close()

    assert papers == []


# ---------------------------------------------------------------------------
# Bad identifier → IdentifierError
# ---------------------------------------------------------------------------


def test_fetch_references_bad_identifier() -> None:
    with pytest.raises(IdentifierError):
        fetch_references("not-a-real-identifier-xyz!!!")


def test_fetch_citations_bad_identifier() -> None:
    with pytest.raises(IdentifierError):
        fetch_citations("not-a-real-identifier-xyz!!!")


# ---------------------------------------------------------------------------
# Depth=2 stays within total cap and deduplicates
# ---------------------------------------------------------------------------


@respx.mock
def test_depth2_stays_within_cap_and_dedupes() -> None:
    """Depth-2 traversal must cap total results to limit*2 and deduplicate."""
    sleeps: list[float] = []
    limit = 2

    s2_id_a = "a" * 40
    s2_id_b = "b" * 40
    # Root: returns [a, b]
    respx.get(f"{S2_BASE_URL}/paper/ARXIV:{ARXIV_ID}/references").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    _s2_ref_item(s2_id_a, "Paper A"),
                    _s2_ref_item(s2_id_b, "Paper B"),
                ]
            },
        )
    )
    # Depth-2 hop for paper A → returns [a] again (duplicate) + [c]
    s2_id_c = "c" * 40
    respx.get(f"{S2_BASE_URL}/paper/{s2_id_a}/references").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    _s2_ref_item(s2_id_a, "Paper A"),  # dup
                    _s2_ref_item(s2_id_c, "Paper C"),
                ]
            },
        )
    )
    # Depth-2 hop for paper B → returns [d]
    s2_id_d = "d" * 40
    respx.get(f"{S2_BASE_URL}/paper/{s2_id_b}/references").mock(
        return_value=httpx.Response(
            200,
            json={"data": [_s2_ref_item(s2_id_d, "Paper D")]},
        )
    )

    client = httpx.Client()
    papers = fetch_references(
        ARXIV_ID,
        depth=2,
        limit=limit,
        source="semantic_scholar",
        client=client,
        sleep=sleeps.append,
    )
    client.close()

    # Titles must be unique (deduplication)
    titles = [p.title for p in papers]
    assert len(titles) == len(set(titles)), f"Duplicates found: {titles}"
    # Result length must not exceed limit
    assert len(papers) <= limit
    # At least one sleep happened (polite traversal)
    assert len(sleeps) >= 1


# ---------------------------------------------------------------------------
# OpenAlex references/citations endpoint tests (extend test_openalex.py style)
# ---------------------------------------------------------------------------


@respx.mock
def test_openalex_references_returns_papers() -> None:
    """Direct OpenAlex reference fetch: resolve + bulk-fetch returns Paper list."""
    respx.get(f"{OPENALEX_BASE_URL}/works/doi:10.48550/arXiv.{ARXIV_ID}").mock(
        return_value=httpx.Response(200, json=_oa_work())
    )
    respx.get(f"{OPENALEX_BASE_URL}/works/{OPENALEX_WID}").mock(
        return_value=httpx.Response(200, json=_oa_work())
    )
    respx.get(f"{OPENALEX_BASE_URL}/works").mock(
        return_value=httpx.Response(200, json={"results": [_oa_ref_work(999)]})
    )

    from paperhound.citations import _openalex_references

    client = httpx.Client()
    papers = _openalex_references(ARXIV_ID, 25, client)
    client.close()

    assert len(papers) == 1
    assert papers[0].title == "Reference Paper 999"


@respx.mock
def test_openalex_citations_uses_cites_filter() -> None:
    """cited-by via OpenAlex uses cites:<id> filter."""
    respx.get(f"{OPENALEX_BASE_URL}/works/doi:10.48550/arXiv.{ARXIV_ID}").mock(
        return_value=httpx.Response(200, json=_oa_work())
    )
    route = respx.get(f"{OPENALEX_BASE_URL}/works").mock(
        return_value=httpx.Response(200, json={"results": [_oa_ref_work(42)]})
    )

    from paperhound.citations import _openalex_citations

    client = httpx.Client()
    papers = _openalex_citations(ARXIV_ID, 10, client)
    client.close()

    assert len(papers) == 1
    assert "cites" in route.calls[0].request.url.params.get("filter", "")


# ---------------------------------------------------------------------------
# Semantic Scholar references/citations endpoint tests
# ---------------------------------------------------------------------------


@respx.mock
def test_s2_references_parses_citedPaper() -> None:
    """S2 /references returns items with citedPaper; we extract those."""
    s2_id = "f" * 40
    respx.get(f"{S2_BASE_URL}/paper/ARXIV:{ARXIV_ID}/references").mock(
        return_value=httpx.Response(200, json={"data": [_s2_ref_item(s2_id, "Referenced")]})
    )

    from paperhound.citations import _s2_references

    client = httpx.Client()
    papers = _s2_references(ARXIV_ID, 10, client)
    client.close()

    assert len(papers) == 1
    assert papers[0].title == "Referenced"
    assert papers[0].identifiers.semantic_scholar_id == s2_id


@respx.mock
def test_s2_citations_parses_citingPaper() -> None:
    """S2 /citations returns items with citingPaper; we extract those."""
    s2_id = "e" * 40
    respx.get(f"{S2_BASE_URL}/paper/ARXIV:{ARXIV_ID}/citations").mock(
        return_value=httpx.Response(200, json={"data": [_s2_cite_item(s2_id, "Citing")]})
    )

    from paperhound.citations import _s2_citations

    client = httpx.Client()
    papers = _s2_citations(ARXIV_ID, 10, client)
    client.close()

    assert len(papers) == 1
    assert papers[0].title == "Citing"


@respx.mock
def test_s2_references_returns_empty_on_404() -> None:
    respx.get(f"{S2_BASE_URL}/paper/ARXIV:{ARXIV_ID}/references").mock(
        return_value=httpx.Response(404)
    )

    from paperhound.citations import _s2_references

    client = httpx.Client()
    papers = _s2_references(ARXIV_ID, 10, client)
    client.close()

    assert papers == []
