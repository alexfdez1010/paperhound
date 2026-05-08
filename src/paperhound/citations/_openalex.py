"""OpenAlex implementation of ``CitationBackend``."""

from __future__ import annotations

import httpx

from paperhound.citations._base import CitationBackend
from paperhound.errors import ProviderError
from paperhound.models import Paper
from paperhound.search.openalex import (
    OPENALEX_BASE_URL,
    OpenAlexProvider,
    _payload_to_paper,
    _strip_openalex_id,
)


class OpenAlexCitationBackend(CitationBackend):
    """OpenAlex /works endpoints for references + cites filter."""

    name = "openalex"

    def __init__(self, client: httpx.Client, mailto: str | None = None) -> None:
        super().__init__(client)
        self._mailto = mailto

    def _resolve_openalex_id(self, identifier: str) -> str | None:
        provider = OpenAlexProvider(mailto=self._mailto, client=self._client)
        work = provider.get(identifier)
        if work is None:
            return None
        return work.identifiers.openalex_id or None

    def references(self, identifier: str, limit: int) -> list[Paper]:
        openalex_id = self._resolve_openalex_id(identifier)
        if not openalex_id:
            return []

        params: dict = {}
        if self._mailto:
            params["mailto"] = self._mailto
        try:
            resp = self._client.get(f"{OPENALEX_BASE_URL}/works/{openalex_id}", params=params)
        except httpx.HTTPError as exc:
            raise ProviderError(f"OpenAlex references failed: {exc}") from exc
        if resp.status_code == 404:
            return []
        if resp.status_code >= 400:
            raise ProviderError(f"OpenAlex references failed: HTTP {resp.status_code}")

        ref_ids: list[str] = [
            _strip_openalex_id(r) for r in resp.json().get("referenced_works") or [] if r
        ]
        ref_ids = [r for r in ref_ids if r][:limit]
        if not ref_ids:
            return []

        chunk = "|".join(ref_ids)
        fetch_params: dict = {
            "filter": f"ids.openalex:{chunk}",
            "per_page": min(len(ref_ids), 200),
        }
        if self._mailto:
            fetch_params["mailto"] = self._mailto
        try:
            resp2 = self._client.get(f"{OPENALEX_BASE_URL}/works", params=fetch_params)
        except httpx.HTTPError as exc:
            raise ProviderError(f"OpenAlex references bulk fetch failed: {exc}") from exc
        if resp2.status_code >= 400:
            raise ProviderError(f"OpenAlex references bulk fetch failed: HTTP {resp2.status_code}")

        results = resp2.json().get("results") or []
        return [_payload_to_paper(item) for item in results]

    def citations(self, identifier: str, limit: int) -> list[Paper]:
        openalex_id = self._resolve_openalex_id(identifier)
        if not openalex_id:
            return []

        params: dict = {
            "filter": f"cites:{openalex_id}",
            "per_page": min(limit, 200),
        }
        if self._mailto:
            params["mailto"] = self._mailto
        try:
            resp = self._client.get(f"{OPENALEX_BASE_URL}/works", params=params)
        except httpx.HTTPError as exc:
            raise ProviderError(f"OpenAlex citations failed: {exc}") from exc
        if resp.status_code >= 400:
            raise ProviderError(f"OpenAlex citations failed: HTTP {resp.status_code}")

        results = resp.json().get("results") or []
        return [_payload_to_paper(item) for item in results][:limit]
