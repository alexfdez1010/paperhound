"""Fan out searches to multiple providers and merge duplicates."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from concurrent.futures import Future, ThreadPoolExecutor, wait

from paperhound.models import Paper
from paperhound.search.base import Capability, SearchProvider, SearchQuery

logger = logging.getLogger(__name__)

# Default fan-out timeout. Search returns whatever providers finished within
# this budget; slower ones are dropped from the response (but their threads keep
# running in the background until they finish or the executor shuts down).
DEFAULT_TIMEOUT = 10.0

_TITLE_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


def _normalize_title(title: str) -> str:
    return _TITLE_NORMALIZE_RE.sub(" ", title.lower()).strip()


def _dedup_key(paper: Paper) -> str:
    """Pick the best key to detect duplicates across providers."""
    ids = paper.identifiers
    if ids.arxiv_id:
        return f"arxiv:{ids.arxiv_id}"
    if ids.doi:
        return f"doi:{ids.doi.lower()}"
    if ids.openalex_id:
        return f"openalex:{ids.openalex_id}"
    if ids.semantic_scholar_id:
        return f"s2:{ids.semantic_scholar_id}"
    if ids.dblp_key:
        return f"dblp:{ids.dblp_key}"
    if ids.core_id:
        return f"core:{ids.core_id}"
    if ids.pwc_id:
        return f"pwc:{ids.pwc_id}"
    return f"title:{_normalize_title(paper.title)}"


class SearchAggregator:
    """Run a query against several providers in parallel and merge the results.

    Providers run concurrently with a global ``timeout`` budget. When the budget
    elapses, providers still in flight are dropped from the response and the
    aggregator returns whatever finished. The same budget applies to ``get``.
    """

    def __init__(
        self,
        providers: Iterable[SearchProvider],
        max_workers: int | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._providers = list(providers)
        if not self._providers:
            raise ValueError("SearchAggregator requires at least one provider")
        self._max_workers = max_workers or max(1, len(self._providers))
        self._timeout = timeout

    @property
    def providers(self) -> list[SearchProvider]:
        return list(self._providers)

    @property
    def timeout(self) -> float:
        return self._timeout

    def _eligible(self, capability: Capability) -> list[SearchProvider]:
        eligible: list[SearchProvider] = []
        for provider in self._providers:
            if not provider.supports(capability):
                continue
            try:
                if not provider.available():
                    logger.debug("Provider %s reported unavailable; skipping", provider.name)
                    continue
            except Exception as exc:
                logger.warning("Provider %s availability check failed: %s", provider.name, exc)
                continue
            eligible.append(provider)
        return eligible

    def search(self, query: SearchQuery) -> list[Paper]:
        eligible = self._eligible(Capability.TEXT_SEARCH)
        if not eligible:
            return []
        results: dict[str, Paper] = {}
        order: list[str] = []
        # Use a non-context-managed pool so we can return without waiting on
        # slow providers — `wait(timeout=...)` returns and we discard pending.
        pool = ThreadPoolExecutor(max_workers=self._max_workers)
        try:
            futures = {pool.submit(p.search, query): p for p in eligible}
            collected = self._wait_all(futures)
            for _provider, papers in collected:
                for paper in papers:
                    key = _dedup_key(paper)
                    if key in results:
                        results[key] = results[key].merge(paper)
                    else:
                        results[key] = paper
                        order.append(key)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        return [results[k] for k in order][: query.limit]

    def _wait_all(
        self,
        futures: dict[Future[list[Paper]], SearchProvider],
    ) -> list[tuple[SearchProvider, list[Paper]]]:
        """Wait up to ``self._timeout`` for all futures; return finished ones."""
        done, not_done = wait(futures, timeout=self._timeout)
        out: list[tuple[SearchProvider, list[Paper]]] = []
        for future in done:
            provider = futures[future]
            try:
                out.append((provider, future.result()))
            except Exception as exc:
                logger.warning("Provider %s failed: %s", provider.name, exc)
        for future in not_done:
            provider = futures[future]
            logger.warning(
                "Provider %s exceeded %.1fs budget; dropping its results",
                provider.name,
                self._timeout,
            )
            future.cancel()
        return out

    def get(self, identifier: str) -> Paper | None:
        eligible = self._eligible(Capability.ID_LOOKUP)
        if not eligible:
            return None
        pool = ThreadPoolExecutor(max_workers=self._max_workers)
        try:
            futures = {pool.submit(p.get, identifier): p for p in eligible}
            done, not_done = wait(futures, timeout=self._timeout)
            merged: Paper | None = None
            for future in done:
                provider = futures[future]
                try:
                    found = future.result()
                except Exception as exc:
                    logger.warning("Provider %s lookup failed: %s", provider.name, exc)
                    continue
                if found is None:
                    continue
                merged = found if merged is None else merged.merge(found)
            for future in not_done:
                provider = futures[future]
                logger.warning(
                    "Provider %s lookup exceeded %.1fs budget; dropping",
                    provider.name,
                    self._timeout,
                )
                future.cancel()
            return merged
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
