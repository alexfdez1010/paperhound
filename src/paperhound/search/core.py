"""CORE search provider — open-access aggregator with PDF links."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from paperhound.errors import ProviderError
from paperhound.identifiers import IdentifierKind, detect
from paperhound.models import Author, Paper, PaperIdentifier
from paperhound.search.base import Capability, SearchProvider, SearchQuery

logger = logging.getLogger(__name__)

CORE_BASE_URL = "https://api.core.ac.uk/v3"


def _payload_to_paper(payload: dict[str, Any]) -> Paper:
    authors: list[Author] = []
    for entry in payload.get("authors") or []:
        if isinstance(entry, dict):
            name = entry.get("name") or ""
        else:
            name = str(entry)
        if name:
            authors.append(Author(name=name))
    year = payload.get("yearPublished")
    venue = None
    journals = payload.get("journals") or []
    if journals and isinstance(journals, list):
        first = journals[0]
        if isinstance(first, dict):
            venue = first.get("title")
    pdf_url = payload.get("downloadUrl")
    arxiv_id = None
    arxiv_block = payload.get("arxivId")
    if isinstance(arxiv_block, str):
        arxiv_id = arxiv_block.replace("arXiv:", "").strip() or None
    return Paper(
        title=(payload.get("title") or "").strip(),
        authors=authors,
        abstract=payload.get("abstract"),
        year=year if isinstance(year, int) else None,
        venue=venue,
        url=payload.get("doi") and f"https://doi.org/{payload['doi']}",
        pdf_url=pdf_url,
        identifiers=PaperIdentifier(
            arxiv_id=arxiv_id,
            doi=payload.get("doi"),
            core_id=str(payload["id"]) if payload.get("id") is not None else None,
        ),
        sources=["core"],
    )


class CoreProvider(SearchProvider):
    """Calls api.core.ac.uk v3. Requires ``CORE_API_KEY`` env var.

    Without a key the provider reports unavailable and the aggregator skips it,
    so installs without a key still run cleanly.
    """

    name = "core"
    capabilities = frozenset(
        {Capability.TEXT_SEARCH, Capability.ID_LOOKUP, Capability.OPEN_ACCESS_PDF}
    )

    def __init__(
        self,
        api_key: str | None = None,
        client: httpx.Client | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._api_key = api_key or os.getenv("CORE_API_KEY")
        self._client = client or httpx.Client(timeout=timeout)
        self._owns_client = client is None
        self.timeout = timeout

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> CoreProvider:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def available(self) -> bool:
        return bool(self._api_key)

    def _headers(self) -> dict[str, str]:
        headers = {"User-Agent": "paperhound/0.2"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _request(self, op: str, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            resp = self._client.request(method, url, headers=self._headers(), **kwargs)
        except httpx.HTTPError as exc:
            raise ProviderError(f"CORE {op} failed: {exc}") from exc
        if resp.status_code == 404:
            return resp
        if resp.status_code in (401, 403):
            raise ProviderError(f"CORE {op} failed: HTTP {resp.status_code} — check CORE_API_KEY.")
        if resp.status_code >= 400:
            raise ProviderError(
                f"CORE {op} failed: HTTP {resp.status_code}"
                f" — {resp.text[:200] or resp.reason_phrase}"
            )
        return resp

    def search(self, query: SearchQuery) -> list[Paper]:
        text = query.text
        if query.year_min:
            text = f"({text}) AND yearPublished>={query.year_min}"
        if query.year_max:
            text = f"({text}) AND yearPublished<={query.year_max}"
        body = {"q": text, "limit": max(1, min(query.limit, 100))}
        resp = self._request("search", "POST", f"{CORE_BASE_URL}/search/works", json=body)
        data = resp.json()
        return [_payload_to_paper(i) for i in data.get("results") or []]

    def get(self, identifier: str) -> Paper | None:
        try:
            kind, value = detect(identifier)
        except Exception:
            kind, value = None, identifier
        if kind is IdentifierKind.DOI:
            url = f"{CORE_BASE_URL}/discover"
            resp = self._request("lookup", "POST", url, json={"doi": value})
            if resp.status_code == 404:
                return None
            data = resp.json() or {}
            if not data:
                return None
            return _payload_to_paper(data)
        if value and value.isdigit():
            resp = self._request("lookup", "GET", f"{CORE_BASE_URL}/works/{value}")
            if resp.status_code == 404:
                return None
            return _payload_to_paper(resp.json())
        return None
