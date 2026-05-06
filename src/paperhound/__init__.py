"""paperhound — search, download, and convert academic papers.

Use the high-level helpers re-exported here for the common cases:

    from paperhound import search_papers, get_paper, convert_to_markdown, Library

For finer control, drop into the underlying modules
(``paperhound.search``, ``paperhound.download``, ``paperhound.convert``,
``paperhound.citations``, ``paperhound.rerank``).
"""

from importlib.metadata import PackageNotFoundError, version

from paperhound.convert import convert_to_markdown, pdf_to_markdown
from paperhound.library import Library
from paperhound.models import Author, Paper, PaperIdentifier, SearchFilters

try:
    __version__ = version("paperhound")
except PackageNotFoundError:  # editable install without metadata, tests, etc.
    __version__ = "0.0.0+unknown"


# Default provider set used by ``search_papers`` and ``get_paper`` — mirrors
# the CLI default (CORE / Semantic Scholar are opt-in).
_DEFAULT_SOURCES: tuple[str, ...] = (
    "arxiv",
    "openalex",
    "dblp",
    "crossref",
    "huggingface",
)


def _build_default_aggregator(
    sources: list[str] | None = None,
    timeout: float | None = None,
):
    """Lazy-build a SearchAggregator with the default provider set."""
    from paperhound.search import (
        DEFAULT_TIMEOUT,
        SearchAggregator,
        build,
        resolve,
    )

    requested = list(sources) if sources else list(_DEFAULT_SOURCES)
    canonical: list[str] = []
    seen: set[str] = set()
    for raw in requested:
        name = resolve(raw)
        if name not in seen:
            seen.add(name)
            canonical.append(name)
    providers = [build(n) for n in canonical]
    return SearchAggregator(providers, timeout=timeout if timeout is not None else DEFAULT_TIMEOUT)


def search_papers(
    query: str,
    *,
    limit: int = 10,
    sources: list[str] | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    min_citations: int | None = None,
    venue: str | None = None,
    author: str | None = None,
    timeout: float | None = None,
) -> list[Paper]:
    """Search across providers and return merged, deduplicated papers.

    Parameters mirror the CLI (`paperhound search`). Filters are pushed down
    to providers that support them and applied client-side after the merge.

    Returns
    -------
    list[Paper]
        Up to *limit* papers, sorted by the round-robin merge order.
    """
    from paperhound.search import SearchQuery

    filters = SearchFilters(
        year_min=year_min,
        year_max=year_max,
        min_citations=min_citations,
        venue=venue,
        author=author,
    )
    aggregator = _build_default_aggregator(sources, timeout=timeout)
    return aggregator.search(
        SearchQuery(
            text=query,
            limit=limit,
            year_min=year_min,
            year_max=year_max,
            filters=None if filters.is_empty() else filters,
        )
    )


def get_paper(identifier: str, *, sources: list[str] | None = None) -> Paper | None:
    """Resolve an arXiv id, DOI, Semantic Scholar id, or paper URL to a Paper.

    Returns ``None`` when no provider knows the identifier.
    """
    aggregator = _build_default_aggregator(sources)
    return aggregator.get(identifier)


__all__ = [
    "Author",
    "Library",
    "Paper",
    "PaperIdentifier",
    "SearchFilters",
    "__version__",
    "convert_to_markdown",
    "get_paper",
    "pdf_to_markdown",
    "search_papers",
]
