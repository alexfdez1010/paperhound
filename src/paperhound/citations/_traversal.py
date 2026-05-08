"""Citation graph traversal — orchestrates backends + BFS hop expansion."""

from __future__ import annotations

import logging
import time
from typing import Literal

import httpx

from paperhound.citations._base import CitationBackend
from paperhound.citations._dedup import deduplicate
from paperhound.citations._openalex import OpenAlexCitationBackend
from paperhound.citations._semantic_scholar import SemanticScholarCitationBackend
from paperhound.errors import ProviderError
from paperhound.identifiers import detect
from paperhound.models import Paper

logger = logging.getLogger(__name__)

Source = Literal["openalex", "semantic_scholar"]
Mode = Literal["references", "citations"]

_DEFAULT_POLITE_SLEEP = 0.1


def _backend_call(backend: CitationBackend, mode: Mode, identifier: str, limit: int) -> list[Paper]:
    if mode == "references":
        return backend.references(identifier, limit)
    return backend.citations(identifier, limit)


def _try_backend(
    backend: CitationBackend,
    mode: Mode,
    identifier: str,
    limit: int,
    errors: list[Exception],
) -> list[Paper] | None:
    try:
        return _backend_call(backend, mode, identifier, limit)
    except (ProviderError, Exception) as exc:
        errors.append(exc)
        logger.warning("%s %s failed for %r: %s", backend.name, mode, identifier, exc)
        return None


def _fetch_one(
    identifier: str,
    mode: Mode,
    per_call_limit: int,
    source: Source | None,
    backends: dict[Source, CitationBackend],
) -> list[Paper]:
    """Fetch depth-1 references or citations for a single *identifier*.

    When *source* is set, only that backend is used. Otherwise OpenAlex is
    tried first and Semantic Scholar acts as fallback when OpenAlex returns
    nothing or raises.
    """
    errors: list[Exception] = []

    if source == "openalex":
        return _try_backend(backends["openalex"], mode, identifier, per_call_limit, errors) or []
    if source == "semantic_scholar":
        return (
            _try_backend(backends["semantic_scholar"], mode, identifier, per_call_limit, errors)
            or []
        )

    oa_result = _try_backend(backends["openalex"], mode, identifier, per_call_limit, errors)
    if oa_result:
        return oa_result
    s2_result = _try_backend(backends["semantic_scholar"], mode, identifier, per_call_limit, errors)
    return s2_result or []


def _traverse(
    identifier: str,
    mode: Mode,
    depth: int,
    limit: int,
    source: Source | None,
    backends: dict[Source, CitationBackend],
    sleep: object,
) -> list[Paper]:
    """BFS traversal up to *depth* hops; total fetched capped at limit*depth."""
    _sleep = sleep  # type: ignore[assignment]

    total_cap = limit * depth
    per_call_limit = min(limit, total_cap)

    level0 = _fetch_one(identifier, mode, per_call_limit, source, backends)
    all_papers: list[Paper] = list(level0)

    if depth >= 2 and all_papers:
        remaining = total_cap - len(all_papers)
        if remaining > 0:
            per_hop = max(1, remaining // max(1, len(all_papers)))
            for paper in all_papers[:limit]:
                if remaining <= 0:
                    break
                pid = paper.primary_id
                if not pid:
                    continue
                try:
                    _sleep(_DEFAULT_POLITE_SLEEP)
                    hop = _fetch_one(pid, mode, per_hop, source, backends)
                    all_papers.extend(hop)
                    remaining -= len(hop)
                except Exception as exc:
                    logger.debug("Depth-2 hop for %r failed: %s", pid, exc)

    return deduplicate(all_papers)[:limit]


def _build_backends(
    client: httpx.Client,
    mailto: str | None,
    api_key: str | None,
) -> dict[Source, CitationBackend]:
    return {
        "openalex": OpenAlexCitationBackend(client, mailto=mailto),
        "semantic_scholar": SemanticScholarCitationBackend(client, api_key=api_key),
    }


def _fetch(
    identifier: str,
    mode: Mode,
    depth: int,
    limit: int,
    source: Source | None,
    client: httpx.Client | None,
    mailto: str | None,
    api_key: str | None,
    sleep: object,
) -> list[Paper]:
    detect(identifier)  # validate identifier early

    depth = max(1, min(depth, 2))
    _client = client or httpx.Client(timeout=30.0)
    _owns_client = client is None
    try:
        backends = _build_backends(_client, mailto, api_key)
        return _traverse(identifier, mode, depth, limit, source, backends, sleep)
    finally:
        if _owns_client:
            _client.close()


def fetch_references(
    identifier: str,
    depth: int = 1,
    limit: int = 25,
    source: Source | None = None,
    *,
    client: httpx.Client | None = None,
    mailto: str | None = None,
    api_key: str | None = None,
    sleep: object = time.sleep,
) -> list[Paper]:
    """Return works that *identifier* cites.

    Args:
        identifier: arXiv id, DOI, Semantic Scholar id, or URL.
        depth: Traversal depth (1 or 2). Capped at 2.
        limit: Max papers to return (applied after dedup).
        source: Force a backend (``"openalex"`` or ``"semantic_scholar"``).
            ``None`` → try OpenAlex first, fall back to S2.
        client: Inject an ``httpx.Client`` (tests use respx-mocked clients).
        mailto: OpenAlex polite-pool email.
        api_key: Semantic Scholar API key.
        sleep: Injectable sleep function (default: ``time.sleep``).

    Raises:
        IdentifierError: if *identifier* cannot be parsed.
    """
    return _fetch(identifier, "references", depth, limit, source, client, mailto, api_key, sleep)


def fetch_citations(
    identifier: str,
    depth: int = 1,
    limit: int = 25,
    source: Source | None = None,
    *,
    client: httpx.Client | None = None,
    mailto: str | None = None,
    api_key: str | None = None,
    sleep: object = time.sleep,
) -> list[Paper]:
    """Return works that cite *identifier*. See :func:`fetch_references`."""
    return _fetch(identifier, "citations", depth, limit, source, client, mailto, api_key, sleep)
