"""Papers with Code search provider — AI/ML-focused index."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from paperhound.errors import ProviderError
from paperhound.identifiers import IdentifierKind, detect
from paperhound.models import Author, Paper, PaperIdentifier
from paperhound.search.base import Capability, SearchProvider, SearchQuery

logger = logging.getLogger(__name__)

PWC_BASE_URL = "https://paperswithcode.com/api/v1"


def _payload_to_paper(payload: dict[str, Any]) -> Paper:
    authors = [Author(name=str(a)) for a in payload.get("authors") or [] if a]
    arxiv_id = payload.get("arxiv_id")
    pdf_url = payload.get("url_pdf")
    abs_url = payload.get("url_abs")
    return Paper(
        title=(payload.get("title") or "").strip(),
        authors=authors,
        abstract=payload.get("abstract"),
        year=_year_from_published(payload.get("published")),
        venue=payload.get("conference") or payload.get("proceeding"),
        url=abs_url,
        pdf_url=pdf_url,
        identifiers=PaperIdentifier(
            arxiv_id=arxiv_id,
            doi=payload.get("doi"),
            pwc_id=payload.get("id"),
        ),
        sources=["paperswithcode"],
    )


def _year_from_published(value: Any) -> int | None:
    if not value or not isinstance(value, str):
        return None
    head = value[:4]
    try:
        return int(head)
    except ValueError:
        return None


class PapersWithCodeProvider(SearchProvider):
    """Defunct — paperswithcode.com/api was decommissioned in 2025 and now
    302-redirects to huggingface.co/papers. Use ``HuggingFaceProvider`` instead.

    The class is kept (and registered) so existing scripts referencing the
    ``paperswithcode`` source name fail loudly via ``available()`` rather than
    raising mid-search.
    """

    name = "paperswithcode"
    capabilities = frozenset(
        {Capability.TEXT_SEARCH, Capability.ID_LOOKUP, Capability.OPEN_ACCESS_PDF}
    )

    def __init__(
        self,
        client: httpx.Client | None = None,
        timeout: float = 10.0,
        force_enabled: bool = False,
    ) -> None:
        self._client = client or httpx.Client(timeout=timeout)
        self._owns_client = client is None
        self.timeout = timeout
        self._force_enabled = force_enabled

    def available(self) -> bool:
        return self._force_enabled

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> PapersWithCodeProvider:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _request(self, op: str, url: str, params: dict[str, Any] | None) -> httpx.Response:
        try:
            resp = self._client.get(url, params=params, headers={"User-Agent": "paperhound/0.2"})
        except httpx.HTTPError as exc:
            raise ProviderError(f"PapersWithCode {op} failed: {exc}") from exc
        if resp.status_code == 404:
            return resp
        if resp.status_code >= 400:
            raise ProviderError(
                f"PapersWithCode {op} failed: HTTP {resp.status_code}"
                f" — {resp.text[:200] or resp.reason_phrase}"
            )
        return resp

    def search(self, query: SearchQuery) -> list[Paper]:
        params = {
            "q": query.text,
            "items_per_page": max(1, min(query.limit, 50)),
        }
        resp = self._request("search", f"{PWC_BASE_URL}/papers/", params)
        data = resp.json()
        results = data.get("results") or []
        papers: list[Paper] = []
        for item in results:
            paper = _payload_to_paper(item)
            if not paper.title:
                continue
            if query.year_min and paper.year and paper.year < query.year_min:
                continue
            if query.year_max and paper.year and paper.year > query.year_max:
                continue
            papers.append(paper)
        return papers

    def get(self, identifier: str) -> Paper | None:
        try:
            kind, value = detect(identifier)
        except Exception:
            return None
        if kind is IdentifierKind.ARXIV:
            params = {"arxiv_id": value, "items_per_page": 1}
        elif kind is IdentifierKind.DOI:
            params = {"doi": value, "items_per_page": 1}
        else:
            return None
        resp = self._request("lookup", f"{PWC_BASE_URL}/papers/", params)
        data = resp.json()
        results = data.get("results") or []
        if not results:
            return None
        return _payload_to_paper(results[0])
