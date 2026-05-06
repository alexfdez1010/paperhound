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
        # Use a non-context-managed pool so we can return without waiting on
        # slow providers — `wait(timeout=...)` returns and we discard pending.
        pool = ThreadPoolExecutor(max_workers=self._max_workers)
        try:
            future_for = {p: pool.submit(p.search, query) for p in eligible}
            wait(list(future_for.values()), timeout=self._timeout)
            per_provider = self._collect_per_provider(future_for)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        return self._round_robin_merge(per_provider, query.limit)

    def _collect_per_provider(
        self,
        future_for: dict[SearchProvider, Future[list[Paper]]],
    ) -> list[list[Paper]]:
        """Materialize each provider's result list in the order providers were given.

        Slow providers (still pending after the budget) and failing providers
        contribute an empty list so the round-robin merge stays positional.
        """
        per_provider: list[list[Paper]] = []
        for provider, future in future_for.items():
            if not future.done():
                logger.warning(
                    "Provider %s exceeded %.1fs budget; dropping its results",
                    provider.name,
                    self._timeout,
                )
                future.cancel()
                per_provider.append([])
                continue
            try:
                per_provider.append(list(future.result()))
            except Exception as exc:
                logger.warning("Provider %s failed: %s", provider.name, exc)
                per_provider.append([])
        return per_provider

    @staticmethod
    def _round_robin_merge(per_provider: list[list[Paper]], limit: int) -> list[Paper]:
        """Interleave provider results — i-th of each, then (i+1)-th of each — and dedup.

        This preserves source diversity in the top-N: a fast provider returning
        100 rows can no longer monopolize every slot.
        """
        results: dict[str, Paper] = {}
        order: list[str] = []
        max_rows = max((len(rs) for rs in per_provider), default=0)
        for i in range(max_rows):
            for rs in per_provider:
                if i >= len(rs):
                    continue
                paper = rs[i]
                key = _dedup_key(paper)
                if key in results:
                    results[key] = results[key].merge(paper)
                else:
                    results[key] = paper
                    order.append(key)
        return [results[k] for k in order][:limit]

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
