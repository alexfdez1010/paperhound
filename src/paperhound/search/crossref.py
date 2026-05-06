"""Crossref search provider — authoritative DOI metadata."""

from __future__ import annotations

import html
import logging
import os
from typing import Any

import httpx

from paperhound.errors import ProviderError
from paperhound.identifiers import IdentifierKind, detect
from paperhound.models import Author, Paper, PaperIdentifier
from paperhound.search.base import Capability, SearchProvider, SearchQuery

logger = logging.getLogger(__name__)

CROSSREF_BASE_URL = "https://api.crossref.org"


def _join_title(value: Any) -> str:
    # Crossref returns titles with raw HTML entities (`&amp;`, `&lt;`, JATS).
    if isinstance(value, list):
        joined = " ".join(part for part in value if part).strip()
    else:
        joined = str(value or "").strip()
    return html.unescape(joined)


def _clean_abstract(value: Any) -> str | None:
    if value is None:
        return None
    return html.unescape(str(value))


def _year_from_issued(issued: dict[str, Any] | None) -> int | None:
    if not issued:
        return None
    parts = issued.get("date-parts") or []
    if parts and isinstance(parts, list) and parts[0]:
        first = parts[0][0]
        try:
            return int(first)
        except (TypeError, ValueError):
            return None
    return None


def _pdf_link(item: dict[str, Any]) -> str | None:
    for entry in item.get("link") or []:
        if not isinstance(entry, dict):
            continue
        if (entry.get("content-type") or "").lower() == "application/pdf":
            url = entry.get("URL")
            if url:
                return url
    return None


def _payload_to_paper(item: dict[str, Any]) -> Paper:
    authors: list[Author] = []
    for entry in item.get("author") or []:
        given = (entry.get("given") or "").strip()
        family = (entry.get("family") or "").strip()
        name = (f"{given} {family}").strip() or entry.get("name") or ""
        affiliations = entry.get("affiliation") or []
        affiliation = None
        if affiliations and isinstance(affiliations, list):
            first = affiliations[0]
            if isinstance(first, dict):
                affiliation = first.get("name")
        if name:
            authors.append(Author(name=name, affiliation=affiliation))
    venue = _join_title(item.get("container-title")) or None
    return Paper(
        title=_join_title(item.get("title")),
        authors=authors,
        abstract=_clean_abstract(item.get("abstract")),
        year=_year_from_issued(item.get("issued")),
        venue=venue,
        url=item.get("URL"),
        pdf_url=_pdf_link(item),
        citation_count=item.get("is-referenced-by-count"),
        identifiers=PaperIdentifier(doi=item.get("DOI")),
        sources=["crossref"],
    )


class CrossrefProvider(SearchProvider):
    """Calls api.crossref.org. Reads ``CROSSREF_MAILTO`` for the polite pool."""

    name = "crossref"
    capabilities = frozenset({Capability.TEXT_SEARCH, Capability.ID_LOOKUP})

    def __init__(
        self,
        mailto: str | None = None,
        client: httpx.Client | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._mailto = mailto or os.getenv("CROSSREF_MAILTO")
        self._client = client or httpx.Client(timeout=timeout)
        self._owns_client = client is None
        self.timeout = timeout

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> CrossrefProvider:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _headers(self) -> dict[str, str]:
        ua = "paperhound/0.2"
        if self._mailto:
            ua = f"{ua} (mailto:{self._mailto})"
        return {"User-Agent": ua}

    def _request(self, op: str, url: str, params: dict[str, Any] | None) -> httpx.Response:
        try:
            resp = self._client.get(url, params=params, headers=self._headers())
        except httpx.HTTPError as exc:
            raise ProviderError(f"Crossref {op} failed: {exc}") from exc
        if resp.status_code == 404:
            return resp
        if resp.status_code >= 400:
            raise ProviderError(
                f"Crossref {op} failed: HTTP {resp.status_code}"
                f" — {resp.text[:200] or resp.reason_phrase}"
            )
        return resp

    def search(self, query: SearchQuery) -> list[Paper]:
        params: dict[str, Any] = {
            "query": query.text,
            "rows": max(1, min(query.limit, 100)),
        }
        filters: list[str] = []
        if query.year_min:
            filters.append(f"from-pub-date:{query.year_min}")
        if query.year_max:
            filters.append(f"until-pub-date:{query.year_max}")
        if filters:
            params["filter"] = ",".join(filters)
        resp = self._request("search", f"{CROSSREF_BASE_URL}/works", params)
        data = resp.json()
        items = (data.get("message") or {}).get("items") or []
        return [_payload_to_paper(i) for i in items]

    def get(self, identifier: str) -> Paper | None:
        try:
            kind, value = detect(identifier)
        except Exception:
            return None
        if kind is IdentifierKind.DOI:
            doi = value
        elif kind is IdentifierKind.ARXIV:
            doi = f"10.48550/arXiv.{value}"
        else:
            return None
        resp = self._request("lookup", f"{CROSSREF_BASE_URL}/works/{doi}", None)
        if resp.status_code == 404:
            return None
        message = (resp.json() or {}).get("message")
        if not message:
            return None
        return _payload_to_paper(message)
