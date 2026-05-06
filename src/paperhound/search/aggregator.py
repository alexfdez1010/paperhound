"""Fan out searches to multiple providers and merge duplicates."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from concurrent.futures import Future, ThreadPoolExecutor, wait

from paperhound.errors import IdentifierError
from paperhound.filtering import apply_filters
from paperhound.identifiers import IdentifierKind, detect
from paperhound.models import Paper
from paperhound.search.base import Capability, SearchProvider, SearchQuery

logger = logging.getLogger(__name__)

# Default fan-out timeout. Search returns whatever providers finished within
# this budget; slower ones are dropped from the response (but their threads keep
# running in the background until they finish or the executor shuts down).
DEFAULT_TIMEOUT = 10.0

_TITLE_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")

# Jaccard threshold for deciding two titles describe the same paper. Tuned
# for OpenAlex/Crossref records that occasionally hijack a slot with junk
# metadata while keeping the requested arXiv id / DOI: in practice the
# legitimate record shares >=0.5 of its tokens with the authoritative one,
# while a hijacker shares well under 0.2.
_TITLE_SIMILARITY_THRESHOLD = 0.5

# Authoritative provider for a given identifier kind. The authoritative
# record's title/abstract is trusted; non-authoritative records whose title
# disagrees are dropped to avoid metadata poisoning across providers.
_AUTHORITATIVE_PROVIDER: dict[IdentifierKind, tuple[str, ...]] = {
    IdentifierKind.ARXIV: ("arxiv",),
    IdentifierKind.DOI: ("crossref", "openalex"),
    IdentifierKind.SEMANTIC_SCHOLAR: ("semantic_scholar",),
}


def _normalize_title(title: str) -> str:
    return _TITLE_NORMALIZE_RE.sub(" ", title.lower()).strip()


def _title_tokens(title: str) -> set[str]:
    return {tok for tok in _normalize_title(title).split() if tok}


def _titles_similar(a: str, b: str, threshold: float = _TITLE_SIMILARITY_THRESHOLD) -> bool:
    """Token-Jaccard similarity check used to detect poisoned upstream records."""
    ta, tb = _title_tokens(a), _title_tokens(b)
    if not ta or not tb:
        # Can't judge without tokens — give the upstream the benefit of the doubt.
        return True
    return len(ta & tb) / len(ta | tb) >= threshold


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
        merged = self._round_robin_merge(per_provider, query.limit)
        # Always run a client-side pass as a safety net (providers may not
        # implement push-down for all filter fields, or may ignore them silently).
        if query.filters and not query.filters.is_empty():
            merged = apply_filters(merged, query.filters)
        return merged

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
            results: dict[str, Paper] = {}
            for future in done:
                provider = futures[future]
                try:
                    found = future.result()
                except Exception as exc:
                    logger.warning("Provider %s lookup failed: %s", provider.name, exc)
                    continue
                if found is None:
                    continue
                results[provider.name] = found
            for future in not_done:
                provider = futures[future]
                logger.warning(
                    "Provider %s lookup exceeded %.1fs budget; dropping",
                    provider.name,
                    self._timeout,
                )
                future.cancel()
            return self._merge_lookups(identifier, results)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def _merge_lookups(self, identifier: str, results: dict[str, Paper]) -> Paper | None:
        """Merge per-provider lookup results, dropping records that look poisoned.

        The authoritative provider for the identifier (e.g. arXiv for an arXiv id)
        defines the canonical title. Other providers must share at least
        ``_TITLE_SIMILARITY_THRESHOLD`` token overlap or they are discarded —
        upstream aggregators occasionally serve junk records that keep the
        requested id but carry an unrelated paper's title and abstract.
        """
        if not results:
            return None
        auth_name = self._pick_authoritative(identifier, results)
        order = [p.name for p in self._providers if p.name in results]
        if auth_name is None:
            auth_name = order[0]
        base = results[auth_name]
        for name in order:
            if name == auth_name:
                continue
            other = results[name]
            if not _titles_similar(base.title, other.title):
                logger.warning(
                    "Dropping %s lookup for %s — title mismatch with %s "
                    "(%r vs %r); likely upstream metadata poisoning",
                    name,
                    identifier,
                    auth_name,
                    other.title,
                    base.title,
                )
                continue
            base = base.merge(other)
        return base

    @staticmethod
    def _pick_authoritative(identifier: str, results: dict[str, Paper]) -> str | None:
        try:
            kind, _ = detect(identifier)
        except IdentifierError:
            return None
        for candidate in _AUTHORITATIVE_PROVIDER.get(kind, ()):
            if candidate in results:
                return candidate
        return None
