"""Citation graph traversal — fetch references and citing works for a paper.

Backends live under ``paperhound.citations._openalex`` and
``paperhound.citations._semantic_scholar``; the public entry points are the
``fetch_references`` / ``fetch_citations`` functions plus the ``Source``
literal alias.

The legacy ``_openalex_*`` / ``_s2_*`` module-level helpers remain importable
as thin shims for tests that pin to those names.
"""

from __future__ import annotations

import httpx

from paperhound.citations._dedup import dedup_key as _dedup_key
from paperhound.citations._dedup import deduplicate as _deduplicate
from paperhound.citations._openalex import OpenAlexCitationBackend
from paperhound.citations._semantic_scholar import (
    SemanticScholarCitationBackend,
    _s2_lookup,
)
from paperhound.citations._traversal import (
    Source,
    fetch_citations,
    fetch_references,
)

__all__ = [
    "OpenAlexCitationBackend",
    "SemanticScholarCitationBackend",
    "Source",
    "_dedup_key",
    "_deduplicate",
    "_openalex_citations",
    "_openalex_references",
    "_s2_citations",
    "_s2_lookup",
    "_s2_references",
    "fetch_citations",
    "fetch_references",
]
from paperhound.models import Paper


def _openalex_references(
    identifier: str,
    limit: int,
    client: httpx.Client,
    mailto: str | None = None,
) -> list[Paper]:
    """Backward-compatible shim around :class:`OpenAlexCitationBackend`."""
    return OpenAlexCitationBackend(client, mailto=mailto).references(identifier, limit)


def _openalex_citations(
    identifier: str,
    limit: int,
    client: httpx.Client,
    mailto: str | None = None,
) -> list[Paper]:
    """Backward-compatible shim around :class:`OpenAlexCitationBackend`."""
    return OpenAlexCitationBackend(client, mailto=mailto).citations(identifier, limit)


def _s2_references(
    identifier: str,
    limit: int,
    client: httpx.Client,
    api_key: str | None = None,
) -> list[Paper]:
    """Backward-compatible shim around :class:`SemanticScholarCitationBackend`."""
    return SemanticScholarCitationBackend(client, api_key=api_key).references(identifier, limit)


def _s2_citations(
    identifier: str,
    limit: int,
    client: httpx.Client,
    api_key: str | None = None,
) -> list[Paper]:
    """Backward-compatible shim around :class:`SemanticScholarCitationBackend`."""
    return SemanticScholarCitationBackend(client, api_key=api_key).citations(identifier, limit)
