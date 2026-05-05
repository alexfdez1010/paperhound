"""Semantic Scholar Graph API provider."""

from __future__ import annotations

import os
from typing import Any

import httpx

from paperhound.errors import ProviderError
from paperhound.identifiers import IdentifierKind, detect, to_semantic_scholar_lookup
from paperhound.models import Author, Paper, PaperIdentifier
from paperhound.search.base import SearchProvider, SearchQuery

S2_BASE_URL = "https://api.semanticscholar.org/graph/v1"
S2_FIELDS = (
    "paperId,title,abstract,year,venue,url,citationCount,"
    "externalIds,openAccessPdf,authors.name,authors.affiliations"
)


def _s2_to_paper(payload: dict[str, Any]) -> Paper:
    external = payload.get("externalIds") or {}
    pdf_block = payload.get("openAccessPdf") or {}
    authors = []
    for a in payload.get("authors") or []:
        affiliations = a.get("affiliations") or []
        authors.append(
            Author(
                name=a.get("name") or "",
                affiliation=affiliations[0] if affiliations else None,
            )
        )
    return Paper(
        title=(payload.get("title") or "").strip(),
        authors=authors,
        abstract=payload.get("abstract"),
        year=payload.get("year"),
        venue=payload.get("venue") or None,
        url=payload.get("url"),
        pdf_url=pdf_block.get("url") or None,
        citation_count=payload.get("citationCount"),
        identifiers=PaperIdentifier(
            arxiv_id=external.get("ArXiv"),
            doi=external.get("DOI"),
            semantic_scholar_id=payload.get("paperId"),
        ),
        sources=["semantic_scholar"],
    )


class SemanticScholarProvider(SearchProvider):
    """Calls the public Semantic Scholar Graph API.

    An optional API key (``SEMANTIC_SCHOLAR_API_KEY`` env var or ``api_key`` argument)
    raises the rate limit. Without it the public endpoint still works.
    """

    name = "semantic_scholar"

    def __init__(
        self,
        api_key: str | None = None,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key or os.getenv("SEMANTIC_SCHOLAR_API_KEY")
        self._client = client or httpx.Client(timeout=timeout)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> SemanticScholarProvider:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _headers(self) -> dict[str, str]:
        headers = {"User-Agent": "paperhound/0.1"}
        if self._api_key:
            headers["x-api-key"] = self._api_key
        return headers

    def search(self, query: SearchQuery) -> list[Paper]:
        params: dict[str, Any] = {
            "query": query.text,
            "limit": max(1, min(query.limit, 100)),
            "fields": S2_FIELDS,
        }
        if query.year_min or query.year_max:
            lo = query.year_min or ""
            hi = query.year_max or ""
            params["year"] = f"{lo}-{hi}"
        try:
            resp = self._client.get(
                f"{S2_BASE_URL}/paper/search",
                params=params,
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            raise ProviderError(f"Semantic Scholar search failed: {exc}") from exc
        return [_s2_to_paper(item) for item in data.get("data") or []]

    def get(self, identifier: str) -> Paper | None:
        try:
            kind, value = detect(identifier)
        except Exception:
            kind, value = IdentifierKind.SEMANTIC_SCHOLAR, identifier
        lookup = to_semantic_scholar_lookup(kind, value)
        try:
            resp = self._client.get(
                f"{S2_BASE_URL}/paper/{lookup}",
                params={"fields": S2_FIELDS},
                headers=self._headers(),
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"Semantic Scholar lookup failed: {exc}") from exc
        return _s2_to_paper(resp.json())
