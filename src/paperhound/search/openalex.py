"""OpenAlex search provider — free, no key, ~250M works."""

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

OPENALEX_BASE_URL = "https://api.openalex.org"

# Stripping the host prefix from a returned ``id`` field gives us the canonical
# OpenAlex Work id like ``W2741809807``.
_OPENALEX_HOST = "https://openalex.org/"


def _strip_doi(value: str | None) -> str | None:
    if not value:
        return None
    if value.startswith("https://doi.org/"):
        return value[len("https://doi.org/") :]
    return value


def _strip_openalex_id(value: str | None) -> str | None:
    if not value:
        return None
    if value.startswith(_OPENALEX_HOST):
        return value[len(_OPENALEX_HOST) :]
    return value


def _reconstruct_abstract(inv_idx: dict[str, list[int]] | None) -> str | None:
    """OpenAlex returns abstracts as inverted indexes; rebuild the prose."""
    if not inv_idx:
        return None
    positions: list[tuple[int, str]] = []
    for word, idxs in inv_idx.items():
        for idx in idxs:
            positions.append((idx, word))
    if not positions:
        return None
    positions.sort()
    return " ".join(word for _, word in positions)


def _payload_to_paper(payload: dict[str, Any]) -> Paper:
    ids = payload.get("ids") or {}
    primary_loc = (payload.get("primary_location") or {}) if payload else {}
    best_oa = (payload.get("best_oa_location") or {}) if payload else {}
    pdf_url = best_oa.get("pdf_url") or primary_loc.get("pdf_url")
    venue = None
    source = primary_loc.get("source") or {}
    if isinstance(source, dict):
        venue = source.get("display_name")
    authors: list[Author] = []
    for entry in payload.get("authorships") or []:
        author_block = entry.get("author") or {}
        institutions = entry.get("institutions") or []
        affiliation = institutions[0].get("display_name") if institutions else None
        name = author_block.get("display_name") or ""
        if name:
            authors.append(Author(name=name, affiliation=affiliation))
    arxiv_id = None
    raw_arxiv = ids.get("arxiv") or ids.get("ArXiv")
    if raw_arxiv:
        arxiv_id = raw_arxiv.split("/")[-1].replace("arXiv:", "").strip() or None
    return Paper(
        title=(payload.get("title") or payload.get("display_name") or "").strip(),
        authors=authors,
        abstract=_reconstruct_abstract(payload.get("abstract_inverted_index")),
        year=payload.get("publication_year"),
        venue=venue,
        url=payload.get("doi") or _strip_openalex_id(payload.get("id")),
        pdf_url=pdf_url,
        citation_count=payload.get("cited_by_count"),
        identifiers=PaperIdentifier(
            arxiv_id=arxiv_id,
            doi=_strip_doi(payload.get("doi") or ids.get("doi")),
            openalex_id=_strip_openalex_id(payload.get("id")),
        ),
        sources=["openalex"],
    )


class OpenAlexProvider(SearchProvider):
    """Calls the OpenAlex Works API.

    OpenAlex requests a ``mailto`` parameter to land in the polite pool. Reads
    ``OPENALEX_MAILTO`` from the environment if not supplied.
    """

    name = "openalex"
    capabilities = frozenset(
        {Capability.TEXT_SEARCH, Capability.ID_LOOKUP, Capability.OPEN_ACCESS_PDF}
    )

    def __init__(
        self,
        mailto: str | None = None,
        client: httpx.Client | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._mailto = mailto or os.getenv("OPENALEX_MAILTO")
        self._client = client or httpx.Client(timeout=timeout)
        self._owns_client = client is None
        self.timeout = timeout

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> OpenAlexProvider:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _params(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if self._mailto:
            params["mailto"] = self._mailto
        if extra:
            params.update(extra)
        return params

    def _request(self, op: str, url: str, params: dict[str, Any]) -> httpx.Response:
        try:
            resp = self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise ProviderError(f"OpenAlex {op} failed: {exc}") from exc
        if resp.status_code == 404:
            return resp
        if resp.status_code >= 400:
            raise ProviderError(
                f"OpenAlex {op} failed: HTTP {resp.status_code}"
                f" — {resp.text[:200] or resp.reason_phrase}"
            )
        return resp

    def search(self, query: SearchQuery) -> list[Paper]:
        params: dict[str, Any] = {
            "search": query.text,
            "per_page": max(1, min(query.limit, 50)),
        }
        filter_parts: list[str] = []
        # Year range — always pushed down when present (from query root or filters).
        year_min = query.year_min or (query.filters.year_min if query.filters else None)
        year_max = query.year_max or (query.filters.year_max if query.filters else None)
        if year_min or year_max:
            lo = year_min or 0
            hi = year_max or 9999
            filter_parts.append(f"from_publication_date:{lo}-01-01,to_publication_date:{hi}-12-31")
        # Citation count floor — OpenAlex supports cited_by_count filter.
        if query.filters and query.filters.min_citations is not None:
            filter_parts.append(f"cited_by_count:>{query.filters.min_citations - 1}")
        if filter_parts:
            params["filter"] = ",".join(filter_parts)
        # Author name — use OpenAlex search param for authorships.
        if query.filters and query.filters.author:
            params["filter"] = (
                params.get("filter", "")
                + ("," if params.get("filter") else "")
                + f"authorships.author.display_name.search:{query.filters.author}"
            )
        resp = self._request("search", f"{OPENALEX_BASE_URL}/works", self._params(params))
        data = resp.json()
        return [_payload_to_paper(item) for item in data.get("results") or []]

    def get(self, identifier: str) -> Paper | None:
        try:
            kind, value = detect(identifier)
        except Exception:
            # Try OpenAlex Work id directly (W123…).
            kind, value = None, identifier
        if kind is IdentifierKind.DOI:
            lookup = f"doi:{value}"
        elif kind is IdentifierKind.ARXIV:
            lookup = f"doi:10.48550/arXiv.{value}"
        elif value and value.upper().startswith("W"):
            lookup = value.upper()
        else:
            return None
        resp = self._request("lookup", f"{OPENALEX_BASE_URL}/works/{lookup}", self._params())
        if resp.status_code == 404:
            return None
        return _payload_to_paper(resp.json())
