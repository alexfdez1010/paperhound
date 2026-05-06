"""Citation graph traversal — fetch references and citing works for a paper.

Supports OpenAlex and Semantic Scholar (S2). Falls back from OpenAlex to S2
when OpenAlex returns nothing or raises. Depth-2 traversal stays within a
total cap of ``limit * depth`` fetched and sleeps 0.1 s between requests to
stay in the polite pool.
"""

from __future__ import annotations

import logging
import time
from typing import Literal

import httpx

from paperhound.errors import IdentifierError, ProviderError
from paperhound.identifiers import IdentifierKind, detect, to_semantic_scholar_lookup
from paperhound.models import Paper
from paperhound.search.openalex import (
    OPENALEX_BASE_URL,
    OpenAlexProvider,
    _payload_to_paper,
    _strip_openalex_id,
)
from paperhound.search.semantic_scholar import S2_BASE_URL, S2_FIELDS, _s2_to_paper

logger = logging.getLogger(__name__)

Source = Literal["openalex", "semantic_scholar"]
_DEFAULT_POLITE_SLEEP = 0.1


# ---------------------------------------------------------------------------
# Dedup helpers (reuse same key logic as aggregator)
# ---------------------------------------------------------------------------


def _dedup_key(paper: Paper) -> str:
    ids = paper.identifiers
    if ids.arxiv_id:
        return f"arxiv:{ids.arxiv_id}"
    if ids.doi:
        return f"doi:{ids.doi.lower()}"
    if ids.openalex_id:
        return f"openalex:{ids.openalex_id}"
    if ids.semantic_scholar_id:
        return f"s2:{ids.semantic_scholar_id}"
    return f"title:{paper.title.lower().strip()}"


def _deduplicate(papers: list[Paper]) -> list[Paper]:
    seen: dict[str, Paper] = {}
    order: list[str] = []
    for paper in papers:
        key = _dedup_key(paper)
        if key in seen:
            seen[key] = seen[key].merge(paper)
        else:
            seen[key] = paper
            order.append(key)
    return [seen[k] for k in order]


# ---------------------------------------------------------------------------
# OpenAlex citation methods
# ---------------------------------------------------------------------------


def _openalex_references(
    identifier: str,
    limit: int,
    client: httpx.Client,
    mailto: str | None = None,
) -> list[Paper]:
    """Fetch works that *identifier* cites via OpenAlex referenced_works."""
    provider = OpenAlexProvider(mailto=mailto, client=client)
    # 1. Resolve the identifier to get the OpenAlex Work record.
    work = provider.get(identifier)
    if work is None:
        return []

    openalex_id = work.identifiers.openalex_id
    if not openalex_id:
        return []

    # 2. Fetch the full work to get referenced_works list.
    params: dict = {}
    if mailto:
        params["mailto"] = mailto
    try:
        resp = client.get(f"{OPENALEX_BASE_URL}/works/{openalex_id}", params=params)
    except httpx.HTTPError as exc:
        raise ProviderError(f"OpenAlex references failed: {exc}") from exc
    if resp.status_code == 404:
        return []
    if resp.status_code >= 400:
        raise ProviderError(f"OpenAlex references failed: HTTP {resp.status_code}")

    data = resp.json()
    ref_ids: list[str] = [_strip_openalex_id(r) for r in data.get("referenced_works") or [] if r]
    ref_ids = [r for r in ref_ids if r][:limit]

    if not ref_ids:
        return []

    # 3. Bulk-fetch each referenced work (filter by id in OR query).
    # OpenAlex supports filtering by openalex ids via the works?filter=ids.openalex:W1|W2 syntax.
    chunk = "|".join(ref_ids)
    fetch_params: dict = {"filter": f"ids.openalex:{chunk}", "per_page": min(len(ref_ids), 200)}
    if mailto:
        fetch_params["mailto"] = mailto
    try:
        resp2 = client.get(f"{OPENALEX_BASE_URL}/works", params=fetch_params)
    except httpx.HTTPError as exc:
        raise ProviderError(f"OpenAlex references bulk fetch failed: {exc}") from exc
    if resp2.status_code >= 400:
        raise ProviderError(f"OpenAlex references bulk fetch failed: HTTP {resp2.status_code}")

    results = resp2.json().get("results") or []
    return [_payload_to_paper(item) for item in results]


def _openalex_citations(
    identifier: str,
    limit: int,
    client: httpx.Client,
    mailto: str | None = None,
) -> list[Paper]:
    """Fetch works that cite *identifier* using OpenAlex cites filter."""
    provider = OpenAlexProvider(mailto=mailto, client=client)
    work = provider.get(identifier)
    if work is None:
        return []

    openalex_id = work.identifiers.openalex_id
    if not openalex_id:
        return []

    params: dict = {
        "filter": f"cites:{openalex_id}",
        "per_page": min(limit, 200),
    }
    if mailto:
        params["mailto"] = mailto
    try:
        resp = client.get(f"{OPENALEX_BASE_URL}/works", params=params)
    except httpx.HTTPError as exc:
        raise ProviderError(f"OpenAlex citations failed: {exc}") from exc
    if resp.status_code >= 400:
        raise ProviderError(f"OpenAlex citations failed: HTTP {resp.status_code}")

    results = resp.json().get("results") or []
    return [_payload_to_paper(item) for item in results][:limit]


# ---------------------------------------------------------------------------
# Semantic Scholar citation methods
# ---------------------------------------------------------------------------


def _s2_lookup(identifier: str) -> str:
    """Convert a user-supplied identifier to the S2 lookup key."""
    try:
        kind, value = detect(identifier)
    except IdentifierError:
        kind, value = IdentifierKind.SEMANTIC_SCHOLAR, identifier
    return to_semantic_scholar_lookup(kind, value)


def _s2_references(
    identifier: str,
    limit: int,
    client: httpx.Client,
    api_key: str | None = None,
) -> list[Paper]:
    """Fetch works that *identifier* cites via S2 /paper/{id}/references."""
    lookup = _s2_lookup(identifier)
    headers = {"User-Agent": "paperhound/0.1"}
    if api_key:
        headers["x-api-key"] = api_key
    params = {"fields": S2_FIELDS, "limit": min(limit, 500)}
    try:
        resp = client.get(
            f"{S2_BASE_URL}/paper/{lookup}/references",
            params=params,
            headers=headers,
        )
    except httpx.HTTPError as exc:
        raise ProviderError(f"Semantic Scholar references failed: {exc}") from exc
    if resp.status_code == 404:
        return []
    if resp.status_code >= 400:
        raise ProviderError(f"Semantic Scholar references failed: HTTP {resp.status_code}")

    data = resp.json()
    papers = []
    for item in (data.get("data") or [])[:limit]:
        cited = item.get("citedPaper")
        if cited:
            papers.append(_s2_to_paper(cited))
    return papers


def _s2_citations(
    identifier: str,
    limit: int,
    client: httpx.Client,
    api_key: str | None = None,
) -> list[Paper]:
    """Fetch works that cite *identifier* via S2 /paper/{id}/citations."""
    lookup = _s2_lookup(identifier)
    headers = {"User-Agent": "paperhound/0.1"}
    if api_key:
        headers["x-api-key"] = api_key
    params = {"fields": S2_FIELDS, "limit": min(limit, 500)}
    try:
        resp = client.get(
            f"{S2_BASE_URL}/paper/{lookup}/citations",
            params=params,
            headers=headers,
        )
    except httpx.HTTPError as exc:
        raise ProviderError(f"Semantic Scholar citations failed: {exc}") from exc
    if resp.status_code == 404:
        return []
    if resp.status_code >= 400:
        raise ProviderError(f"Semantic Scholar citations failed: HTTP {resp.status_code}")

    data = resp.json()
    papers = []
    for item in (data.get("data") or [])[:limit]:
        citing = item.get("citingPaper")
        if citing:
            papers.append(_s2_to_paper(citing))
    return papers


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


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
        source: Force a provider (``"openalex"`` or ``"semantic_scholar"``).
            ``None`` → try OpenAlex first, fall back to S2 if empty or errored.
        client: Inject an ``httpx.Client`` (tests use respx-mocked clients).
        mailto: OpenAlex polite-pool email.
        api_key: Semantic Scholar API key.
        sleep: Injectable sleep function (default: ``time.sleep``).

    Returns:
        Flat, deduplicated list of ``Paper`` objects (up to *limit*).

    Raises:
        IdentifierError: if *identifier* cannot be parsed.
    """
    # Validate the identifier early so we surface IdentifierError.
    detect(identifier)

    depth = max(1, min(depth, 2))
    _client = client or httpx.Client(timeout=30.0)
    _owns_client = client is None

    try:
        return _traverse(
            identifier=identifier,
            mode="references",
            depth=depth,
            limit=limit,
            source=source,
            client=_client,
            mailto=mailto,
            api_key=api_key,
            sleep=sleep,  # type: ignore[arg-type]
        )
    finally:
        if _owns_client:
            _client.close()


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
    """Return works that cite *identifier*.

    Same parameters as :func:`fetch_references`.
    """
    detect(identifier)

    depth = max(1, min(depth, 2))
    _client = client or httpx.Client(timeout=30.0)
    _owns_client = client is None

    try:
        return _traverse(
            identifier=identifier,
            mode="citations",
            depth=depth,
            limit=limit,
            source=source,
            client=_client,
            mailto=mailto,
            api_key=api_key,
            sleep=sleep,  # type: ignore[arg-type]
        )
    finally:
        if _owns_client:
            _client.close()


# ---------------------------------------------------------------------------
# Internal traversal
# ---------------------------------------------------------------------------

_FetchFn = object  # callable


def _fetch_one(
    identifier: str,
    mode: Literal["references", "citations"],
    per_call_limit: int,
    source: Source | None,
    client: httpx.Client,
    mailto: str | None,
    api_key: str | None,
) -> list[Paper]:
    """Fetch depth-1 references or citations for a single *identifier*."""
    errors: list[Exception] = []

    def try_openalex() -> list[Paper] | None:
        try:
            if mode == "references":
                return _openalex_references(identifier, per_call_limit, client, mailto)
            return _openalex_citations(identifier, per_call_limit, client, mailto)
        except (ProviderError, Exception) as exc:
            errors.append(exc)
            logger.warning("OpenAlex %s failed for %r: %s", mode, identifier, exc)
            return None

    def try_s2() -> list[Paper] | None:
        try:
            if mode == "references":
                return _s2_references(identifier, per_call_limit, client, api_key)
            return _s2_citations(identifier, per_call_limit, client, api_key)
        except (ProviderError, Exception) as exc:
            errors.append(exc)
            logger.warning("S2 %s failed for %r: %s", mode, identifier, exc)
            return None

    if source == "openalex":
        result = try_openalex()
        return result or []
    if source == "semantic_scholar":
        result = try_s2()
        return result or []

    # Default: try OpenAlex, fall back to S2.
    oa_result = try_openalex()
    if oa_result:
        return oa_result
    s2_result = try_s2()
    return s2_result or []


def _traverse(
    identifier: str,
    mode: Literal["references", "citations"],
    depth: int,
    limit: int,
    source: Source | None,
    client: httpx.Client,
    mailto: str | None,
    api_key: str | None,
    sleep: object,
) -> list[Paper]:
    """BFS traversal up to *depth* hops; total fetched capped at limit*depth."""
    _sleep = sleep  # type: ignore[assignment]

    total_cap = limit * depth
    per_call_limit = min(limit, total_cap)

    # Level 0: seed identifier.
    level0 = _fetch_one(identifier, mode, per_call_limit, source, client, mailto, api_key)

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
                    hop = _fetch_one(pid, mode, per_hop, source, client, mailto, api_key)
                    all_papers.extend(hop)
                    remaining -= len(hop)
                except Exception as exc:
                    logger.debug("Depth-2 hop for %r failed: %s", pid, exc)

    deduped = _deduplicate(all_papers)
    return deduped[:limit]
