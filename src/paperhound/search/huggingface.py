"""Hugging Face Papers provider — AI/ML curated paper feed.

Hugging Face acquired Papers with Code in 2025 and replaced its API. This
provider hits the HF Papers JSON endpoints and is the practical successor for
AI/ML coverage in paperhound.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from paperhound.errors import ProviderError
from paperhound.identifiers import IdentifierKind, detect
from paperhound.models import Author, Paper, PaperIdentifier
from paperhound.search.base import Capability, SearchProvider, SearchQuery

logger = logging.getLogger(__name__)

HF_BASE_URL = "https://huggingface.co/api/papers"


def _payload_to_paper(payload: dict[str, Any]) -> Paper:
    arxiv_id = payload.get("id")
    authors: list[Author] = []
    for entry in payload.get("authors") or []:
        if isinstance(entry, dict):
            name = entry.get("name") or ""
            if name:
                authors.append(Author(name=name))
    published = payload.get("publishedAt")
    year = None
    if isinstance(published, str) and len(published) >= 4:
        try:
            year = int(published[:4])
        except ValueError:
            year = None
    abstract = payload.get("summary") or payload.get("ai_summary")
    return Paper(
        title=(payload.get("title") or "").strip(),
        authors=authors,
        abstract=abstract,
        year=year,
        publication_type="preprint",
        url=f"https://huggingface.co/papers/{arxiv_id}" if arxiv_id else None,
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}.pdf" if arxiv_id else None,
        citation_count=payload.get("upvotes"),
        identifiers=PaperIdentifier(arxiv_id=arxiv_id),
        sources=["huggingface"],
    )


class HuggingFaceProvider(SearchProvider):
    """Calls huggingface.co/api/papers — free, no key, AI/ML focused."""

    name = "huggingface"
    description = (
        "Hugging Face Papers — curated daily AI/ML feed (successor to Papers with"
        " Code). Best signal for trending arXiv preprints in ML."
    )
    homepage = "https://huggingface.co/papers"
    capabilities = frozenset(
        {Capability.TEXT_SEARCH, Capability.ID_LOOKUP, Capability.OPEN_ACCESS_PDF}
    )

    def __init__(
        self,
        client: httpx.Client | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._client = client or httpx.Client(timeout=timeout, follow_redirects=True)
        self._owns_client = client is None
        self.timeout = timeout

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> HuggingFaceProvider:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _request(self, op: str, url: str, params: dict[str, Any] | None) -> httpx.Response:
        try:
            resp = self._client.get(url, params=params, headers={"User-Agent": "paperhound/0.2"})
        except httpx.HTTPError as exc:
            raise ProviderError(f"HuggingFace {op} failed: {exc}") from exc
        if resp.status_code == 404:
            return resp
        if resp.status_code >= 400:
            raise ProviderError(
                f"HuggingFace {op} failed: HTTP {resp.status_code}"
                f" — {resp.text[:200] or resp.reason_phrase}"
            )
        return resp

    def search(self, query: SearchQuery) -> list[Paper]:
        params = {"q": query.text}
        resp = self._request("search", f"{HF_BASE_URL}/search", params)
        try:
            data = resp.json()
        except ValueError as exc:
            raise ProviderError(f"HuggingFace search returned non-JSON: {exc}") from exc
        if not isinstance(data, list):
            return []
        papers: list[Paper] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            block = item.get("paper") or item
            if not isinstance(block, dict):
                continue
            paper = _payload_to_paper(block)
            if not paper.title:
                continue
            if query.year_min and paper.year and paper.year < query.year_min:
                continue
            if query.year_max and paper.year and paper.year > query.year_max:
                continue
            papers.append(paper)
            if len(papers) >= query.limit:
                break
        return papers

    def get(self, identifier: str) -> Paper | None:
        try:
            kind, value = detect(identifier)
        except Exception:
            return None
        if kind is not IdentifierKind.ARXIV:
            return None
        resp = self._request("lookup", f"{HF_BASE_URL}/{value}", None)
        if resp.status_code == 404:
            return None
        try:
            data = resp.json()
        except ValueError as exc:
            raise ProviderError(f"HuggingFace lookup returned non-JSON: {exc}") from exc
        if not isinstance(data, dict):
            return None
        return _payload_to_paper(data)
