"""Fan out searches to multiple providers and merge duplicates."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed

from paperhound.models import Paper
from paperhound.search.base import SearchProvider, SearchQuery

logger = logging.getLogger(__name__)

_TITLE_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


def _normalize_title(title: str) -> str:
    return _TITLE_NORMALIZE_RE.sub(" ", title.lower()).strip()


def _dedup_key(paper: Paper) -> str:
    """Pick the best key to detect duplicates across providers."""
    if paper.identifiers.arxiv_id:
        return f"arxiv:{paper.identifiers.arxiv_id}"
    if paper.identifiers.doi:
        return f"doi:{paper.identifiers.doi.lower()}"
    if paper.identifiers.semantic_scholar_id:
        return f"s2:{paper.identifiers.semantic_scholar_id}"
    return f"title:{_normalize_title(paper.title)}"


class SearchAggregator:
    """Run a query against several providers in parallel and merge the results."""

    def __init__(
        self,
        providers: Iterable[SearchProvider],
        max_workers: int | None = None,
    ) -> None:
        self._providers = list(providers)
        if not self._providers:
            raise ValueError("SearchAggregator requires at least one provider")
        self._max_workers = max_workers or max(1, len(self._providers))

    @property
    def providers(self) -> list[SearchProvider]:
        return list(self._providers)

    def search(self, query: SearchQuery) -> list[Paper]:
        results: dict[str, Paper] = {}
        order: list[str] = []
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures = {
                pool.submit(provider.search, query): provider for provider in self._providers
            }
            for future in as_completed(futures):
                provider = futures[future]
                try:
                    papers = future.result()
                except Exception as exc:
                    logger.warning("Provider %s failed: %s", provider.name, exc)
                    continue
                for paper in papers:
                    key = _dedup_key(paper)
                    if key in results:
                        results[key] = results[key].merge(paper)
                    else:
                        results[key] = paper
                        order.append(key)
        return [results[k] for k in order][: query.limit]

    def get(self, identifier: str) -> Paper | None:
        merged: Paper | None = None
        for provider in self._providers:
            try:
                found = provider.get(identifier)
            except Exception as exc:
                logger.warning("Provider %s lookup failed: %s", provider.name, exc)
                continue
            if found is None:
                continue
            merged = found if merged is None else merged.merge(found)
        return merged
