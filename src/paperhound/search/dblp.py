"""DBLP search provider — CS-focused publication index."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from paperhound.errors import ProviderError
from paperhound.models import Author, Paper, PaperIdentifier
from paperhound.search._pubtype import from_dblp as _pubtype_from_dblp
from paperhound.search.base import Capability, SearchProvider, SearchQuery

logger = logging.getLogger(__name__)

DBLP_BASE_URL = "https://dblp.org/search/publ/api"


def _as_list(value: Any) -> list[Any]:
    """DBLP collapses single-element lists; normalize to a list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _payload_to_paper(hit: dict[str, Any]) -> Paper:
    info = hit.get("info") or {}
    raw_authors = (info.get("authors") or {}).get("author")
    authors: list[Author] = []
    for entry in _as_list(raw_authors):
        if isinstance(entry, dict):
            name = entry.get("text") or ""
        else:
            name = str(entry)
        if name:
            authors.append(Author(name=name))
    year = info.get("year")
    try:
        year_int = int(year) if year is not None else None
    except (TypeError, ValueError):
        year_int = None
    doi = info.get("doi")
    arxiv_id = None
    ee = info.get("ee")
    if isinstance(ee, str) and "arxiv.org/abs/" in ee.lower():
        arxiv_id = ee.lower().split("arxiv.org/abs/", 1)[1].split("?")[0].strip("/")
    return Paper(
        title=(info.get("title") or "").strip(),
        authors=authors,
        year=year_int,
        venue=info.get("venue"),
        publication_type=_pubtype_from_dblp(info.get("type")),
        url=info.get("url") or ee,
        identifiers=PaperIdentifier(
            arxiv_id=arxiv_id,
            doi=doi,
            dblp_key=info.get("key"),
        ),
        sources=["dblp"],
    )


class DBLPProvider(SearchProvider):
    """Free, no-key CS publication search via the DBLP JSON API."""

    name = "dblp"
    description = (
        "DBLP — computer-science bibliography. Strong venue / author coverage for"
        " CS conferences and journals. Text search only (no id lookup)."
    )
    homepage = "https://dblp.org/"
    capabilities = frozenset({Capability.TEXT_SEARCH})

    def __init__(
        self,
        client: httpx.Client | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._client = client or httpx.Client(timeout=timeout)
        self._owns_client = client is None
        self.timeout = timeout

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> DBLPProvider:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def search(self, query: SearchQuery) -> list[Paper]:
        params = {
            "q": query.text,
            "format": "json",
            "h": max(1, min(query.limit, 1000)),
        }
        try:
            resp = self._client.get(DBLP_BASE_URL, params=params)
        except httpx.HTTPError as exc:
            raise ProviderError(f"DBLP search failed: {exc}") from exc
        if resp.status_code >= 400:
            raise ProviderError(
                f"DBLP search failed: HTTP {resp.status_code}"
                f" — {resp.text[:200] or resp.reason_phrase}"
            )
        data = resp.json()
        hits_block = (data.get("result") or {}).get("hits") or {}
        papers: list[Paper] = []
        for hit in _as_list(hits_block.get("hit")):
            if not isinstance(hit, dict):
                continue
            paper = _payload_to_paper(hit)
            if not paper.title:
                continue
            if query.year_min and paper.year and paper.year < query.year_min:
                continue
            if query.year_max and paper.year and paper.year > query.year_max:
                continue
            papers.append(paper)
        return papers

    def get(self, identifier: str) -> Paper | None:
        # DBLP has no direct lookup endpoint that maps DOI/arXiv -> publication;
        # the search endpoint is the only public surface, so lookup is omitted.
        return None
