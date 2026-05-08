"""Semantic Scholar implementation of ``CitationBackend``."""

from __future__ import annotations

import httpx

from paperhound.citations._base import CitationBackend
from paperhound.errors import IdentifierError, ProviderError
from paperhound.identifiers import IdentifierKind, detect, to_semantic_scholar_lookup
from paperhound.models import Paper
from paperhound.search.semantic_scholar import S2_BASE_URL, S2_FIELDS, _s2_to_paper


def _s2_lookup(identifier: str) -> str:
    """Convert a user-supplied identifier to the S2 lookup key."""
    try:
        kind, value = detect(identifier)
    except IdentifierError:
        kind, value = IdentifierKind.SEMANTIC_SCHOLAR, identifier
    return to_semantic_scholar_lookup(kind, value)


class SemanticScholarCitationBackend(CitationBackend):
    """Semantic Scholar /paper/{id}/(references|citations) endpoints."""

    name = "semantic_scholar"

    def __init__(self, client: httpx.Client, api_key: str | None = None) -> None:
        super().__init__(client)
        self._api_key = api_key

    def _request(self, lookup: str, leg: str, limit: int) -> dict:
        headers = {"User-Agent": "paperhound/0.1"}
        if self._api_key:
            headers["x-api-key"] = self._api_key
        params = {"fields": S2_FIELDS, "limit": min(limit, 500)}
        try:
            resp = self._client.get(
                f"{S2_BASE_URL}/paper/{lookup}/{leg}",
                params=params,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"Semantic Scholar {leg} failed: {exc}") from exc
        if resp.status_code == 404:
            return {"data": []}
        if resp.status_code >= 400:
            raise ProviderError(f"Semantic Scholar {leg} failed: HTTP {resp.status_code}")
        return resp.json()

    def references(self, identifier: str, limit: int) -> list[Paper]:
        data = self._request(_s2_lookup(identifier), "references", limit)
        papers: list[Paper] = []
        for item in (data.get("data") or [])[:limit]:
            cited = item.get("citedPaper")
            if cited:
                papers.append(_s2_to_paper(cited))
        return papers

    def citations(self, identifier: str, limit: int) -> list[Paper]:
        data = self._request(_s2_lookup(identifier), "citations", limit)
        papers: list[Paper] = []
        for item in (data.get("data") or [])[:limit]:
            citing = item.get("citingPaper")
            if citing:
                papers.append(_s2_to_paper(citing))
        return papers
