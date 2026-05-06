"""Semantic Scholar Graph API provider."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

from paperhound.errors import ProviderError
from paperhound.identifiers import IdentifierKind, detect, to_semantic_scholar_lookup
from paperhound.models import Author, Paper, PaperIdentifier
from paperhound.search.base import SearchProvider, SearchQuery

logger = logging.getLogger(__name__)

S2_BASE_URL = "https://api.semanticscholar.org/graph/v1"
S2_FIELDS = (
    "paperId,title,abstract,year,venue,url,citationCount,"
    "externalIds,openAccessPdf,authors.name,authors.affiliations"
)

# Status codes worth retrying. 429 is rate limit; 5xx is upstream flake.
_RETRY_STATUSES = {429, 500, 502, 503, 504}


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


def _retry_after(resp: httpx.Response, attempt: int, base_delay: float, max_delay: float) -> float:
    header = resp.headers.get("Retry-After")
    if header:
        try:
            return max(0.0, min(float(header), max_delay))
        except ValueError:
            pass
    return min(base_delay * (2**attempt), max_delay)


class SemanticScholarProvider(SearchProvider):
    """Calls the public Semantic Scholar Graph API.

    An optional API key (``SEMANTIC_SCHOLAR_API_KEY`` env var or ``api_key`` argument)
    raises the rate limit. Without it the public endpoint still works but is much
    more aggressive about 429s.
    """

    name = "semantic_scholar"

    def __init__(
        self,
        api_key: str | None = None,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
        max_retries: int = 6,
        retry_base_delay: float = 5.0,
        retry_max_delay: float = 30.0,
        sleep: Any = time.sleep,
    ) -> None:
        self._api_key = api_key or os.getenv("SEMANTIC_SCHOLAR_API_KEY")
        self._client = client or httpx.Client(timeout=timeout)
        self._owns_client = client is None
        self._max_retries = max(0, max_retries)
        self._retry_base_delay = retry_base_delay
        self._retry_max_delay = retry_max_delay
        self._sleep = sleep

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

    def _request(self, op: str, url: str, params: dict[str, Any]) -> httpx.Response:
        last_resp: httpx.Response | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = self._client.get(url, params=params, headers=self._headers())
            except httpx.HTTPError as exc:
                raise ProviderError(f"Semantic Scholar {op} failed: {exc}") from exc

            if resp.status_code < 400:
                return resp
            if resp.status_code == 404:
                return resp
            if resp.status_code == 403:
                hint = (
                    " The endpoint refused the request — set SEMANTIC_SCHOLAR_API_KEY"
                    " to an authorized key or check that your IP is allowed."
                    if not self._api_key
                    else " The configured SEMANTIC_SCHOLAR_API_KEY was rejected."
                )
                raise ProviderError(f"Semantic Scholar {op} failed: 403 Forbidden.{hint}")
            if resp.status_code in _RETRY_STATUSES and attempt < self._max_retries:
                delay = _retry_after(resp, attempt, self._retry_base_delay, self._retry_max_delay)
                logger.warning(
                    "Semantic Scholar %s -> %s (attempt %d/%d). Retrying in %.1fs.",
                    op,
                    resp.status_code,
                    attempt + 1,
                    self._max_retries,
                    delay,
                )
                last_resp = resp
                self._sleep(delay)
                continue
            last_resp = resp
            break

        assert last_resp is not None
        if last_resp.status_code == 429:
            hint = (
                ""
                if self._api_key
                else (
                    " The public endpoint is shared across all unauthenticated"
                    " callers; either retry later or set SEMANTIC_SCHOLAR_API_KEY."
                )
            )
            raise ProviderError(
                f"Semantic Scholar {op} failed: rate-limited (HTTP 429) after"
                f" {self._max_retries + 1} attempts.{hint}"
            )
        raise ProviderError(
            f"Semantic Scholar {op} failed: HTTP {last_resp.status_code}"
            f" — {last_resp.text[:200] or last_resp.reason_phrase}"
        )

    def search(self, query: SearchQuery) -> list[Paper]:
        params: dict[str, Any] = {
            "query": query.text,
            "limit": max(1, min(query.limit, 100)),
            "fields": S2_FIELDS,
        }
        year_min = query.year_min or (query.filters.year_min if query.filters else None)
        year_max = query.year_max or (query.filters.year_max if query.filters else None)
        if year_min or year_max:
            lo = year_min or ""
            hi = year_max or ""
            params["year"] = f"{lo}-{hi}"
        if query.filters and query.filters.min_citations is not None:
            params["minCitationCount"] = query.filters.min_citations
        resp = self._request("search", f"{S2_BASE_URL}/paper/search", params)
        data = resp.json()
        return [_s2_to_paper(item) for item in data.get("data") or []]

    def get(self, identifier: str) -> Paper | None:
        try:
            kind, value = detect(identifier)
        except Exception:
            kind, value = IdentifierKind.SEMANTIC_SCHOLAR, identifier
        lookup = to_semantic_scholar_lookup(kind, value)
        resp = self._request("lookup", f"{S2_BASE_URL}/paper/{lookup}", {"fields": S2_FIELDS})
        if resp.status_code == 404:
            return None
        return _s2_to_paper(resp.json())
