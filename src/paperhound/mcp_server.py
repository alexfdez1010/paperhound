"""MCP server for paperhound — exposes search/show/download/library as tools.

Run with:  paperhound mcp

The server communicates over stdio using the MCP protocol.  Requires the
optional ``mcp`` extra:  pip install 'paperhound[mcp]'

Design notes
------------
* Lazy-import ``mcp`` so that the rest of the package (and unit tests of
  unrelated code) never pull in the optional dependency.
* All handler functions are plain sync/async Python; the MCP decorators are
  applied at ``run()``-time, after the import guard.  This lets unit tests call
  the handlers directly without ``mcp`` installed.
* Structured dicts (not Pydantic objects) are returned at the MCP boundary so
  the SDK can serialise them as JSON content.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from paperhound.errors import LibraryError, PaperhoundError
from paperhound.library import Library, _canonical_id, _safe_filename
from paperhound.models import Paper

# ---------------------------------------------------------------------------
# Internal helpers (re-use CLI wiring patterns)
# ---------------------------------------------------------------------------

_DEFAULT_SOURCES: tuple[str, ...] = (
    "arxiv",
    "openalex",
    "dblp",
    "crossref",
    "huggingface",
)


def _build_aggregator(sources: list[str] | None = None):  # type: ignore[return]
    """Build a SearchAggregator, resolving source aliases."""
    from paperhound.search import DEFAULT_TIMEOUT, SearchAggregator, build, names, resolve

    requested = list(sources) if sources else list(_DEFAULT_SOURCES)
    canonical: list[str] = []
    seen: set[str] = set()
    for raw in requested:
        try:
            name = resolve(raw)
        except KeyError:
            valid = ", ".join(names())
            raise ValueError(f"Unknown source: {raw!r}. Valid: {valid}") from None
        if name not in seen:
            seen.add(name)
            canonical.append(name)
    providers = [build(n) for n in canonical]
    return SearchAggregator(providers, timeout=DEFAULT_TIMEOUT)


def _paper_to_dict(paper: Paper) -> dict[str, Any]:
    """Convert a Paper model to a plain dict suitable for MCP JSON content."""
    return {
        "title": paper.title,
        "authors": [{"name": a.name, "affiliation": a.affiliation} for a in paper.authors],
        "abstract": paper.abstract,
        "year": paper.year,
        "venue": paper.venue,
        "url": paper.url,
        "pdf_url": paper.pdf_url,
        "citation_count": paper.citation_count,
        "identifiers": {
            "arxiv_id": paper.identifiers.arxiv_id,
            "doi": paper.identifiers.doi,
            "semantic_scholar_id": paper.identifiers.semantic_scholar_id,
            "openalex_id": paper.identifiers.openalex_id,
            "dblp_key": paper.identifiers.dblp_key,
            "core_id": paper.identifiers.core_id,
        },
        "sources": paper.sources,
    }


def _open_library(path: Path | None = None) -> Library:
    """Open the default (or injected) library."""
    try:
        return Library(path=path)
    except LibraryError as exc:
        raise RuntimeError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Handler functions — pure Python, no mcp dependency needed for unit tests
# ---------------------------------------------------------------------------


def handle_search(
    query: str,
    limit: int = 10,
    sources: list[str] | None = None,
    *,
    _aggregator=None,  # injection point for tests
) -> list[dict[str, Any]]:
    """Search papers across providers."""
    from paperhound.search import SearchQuery

    if not query.strip():
        raise ValueError("Query must not be empty.")

    aggregator = _aggregator if _aggregator is not None else _build_aggregator(sources)
    try:
        papers = aggregator.search(SearchQuery(text=query, limit=limit))
    except PaperhoundError as exc:
        raise RuntimeError(str(exc)) from exc
    return [_paper_to_dict(p) for p in papers]


def handle_show(
    identifier: str,
    *,
    _aggregator=None,  # injection point for tests
) -> dict[str, Any]:
    """Fetch metadata and abstract for a single paper."""
    aggregator = _aggregator if _aggregator is not None else _build_aggregator()
    try:
        paper = aggregator.get(identifier)
    except PaperhoundError as exc:
        raise RuntimeError(str(exc)) from exc
    if paper is None:
        raise ValueError(f"Paper not found: {identifier!r}")
    return _paper_to_dict(paper)


def handle_download(
    identifier: str,
    dest: str | None = None,
    *,
    _aggregator=None,  # injection point for tests
    _resolve_fn=None,  # injection point for tests
    _download_fn=None,  # injection point for tests
) -> dict[str, Any]:
    """Download a paper PDF and return the path."""
    from paperhound.download import download_pdf, resolve_pdf_url

    resolve_fn = _resolve_fn if _resolve_fn is not None else resolve_pdf_url
    download_fn = _download_fn if _download_fn is not None else download_pdf

    aggregator = _aggregator if _aggregator is not None else _build_aggregator()

    def _lookup(id_: str) -> str | None:
        p = aggregator.get(id_)
        return p.pdf_url if p else None

    destination = Path(dest) if dest else Path.cwd()
    try:
        url = resolve_fn(identifier, lookup_pdf_url=_lookup)
        path = download_fn(url, destination)
    except PaperhoundError as exc:
        raise RuntimeError(str(exc)) from exc
    return {"path": str(path)}


def handle_convert(
    identifier: str,
    dest: str | None = None,
    *,
    _convert_fn=None,  # injection point for tests
) -> dict[str, Any]:
    """Convert a PDF or supported document to Markdown."""
    from paperhound.convert import convert_to_markdown

    convert_fn = _convert_fn if _convert_fn is not None else convert_to_markdown

    output = Path(dest) if dest else None
    try:
        markdown = convert_fn(identifier, output=output)
    except PaperhoundError as exc:
        raise RuntimeError(str(exc)) from exc

    result: dict[str, Any] = {}
    if output is not None:
        result["path"] = str(output)
    else:
        result["markdown"] = markdown
    return result


def handle_library_add(
    identifier: str,
    convert: bool = False,
    *,
    _aggregator=None,
    _library_path: Path | None = None,
    _resolve_fn=None,
    _download_fn=None,
    _convert_fn=None,
) -> dict[str, Any]:
    """Fetch metadata and add a paper to the local library."""
    from paperhound.convert import convert_to_markdown
    from paperhound.download import download_pdf, resolve_pdf_url

    resolve_fn = _resolve_fn if _resolve_fn is not None else resolve_pdf_url
    download_fn = _download_fn if _download_fn is not None else download_pdf
    convert_fn = _convert_fn if _convert_fn is not None else convert_to_markdown

    aggregator = _aggregator if _aggregator is not None else _build_aggregator()

    try:
        paper = aggregator.get(identifier)
    except PaperhoundError as exc:
        raise RuntimeError(str(exc)) from exc

    if paper is None:
        raise ValueError(f"Paper not found: {identifier!r}")

    lib = _open_library(_library_path)
    paper_id = _canonical_id(paper)

    md_path: Path | None = None
    if convert:
        safe = _safe_filename(paper_id)
        actual_lib_dir = lib._dir
        md_path = actual_lib_dir / f"{safe}.md"
        tmp_pdf = actual_lib_dir / f"{safe}.pdf"

        def _lookup(id_: str) -> str | None:
            p = aggregator.get(id_)
            return p.pdf_url if p else None

        try:
            url = resolve_fn(identifier, lookup_pdf_url=_lookup)
            download_fn(url, tmp_pdf)
            convert_fn(tmp_pdf, output=md_path)
        except PaperhoundError as exc:
            raise RuntimeError(str(exc)) from exc
        finally:
            if tmp_pdf.exists():
                try:
                    tmp_pdf.unlink()
                except OSError:
                    pass

    try:
        paper_id = lib.add(paper, markdown_path=md_path)
        if md_path is not None:
            lib.update_markdown(paper_id, md_path)
    except LibraryError as exc:
        raise RuntimeError(str(exc)) from exc

    result = _paper_to_dict(paper)
    result["library_id"] = paper_id
    if md_path:
        result["markdown_path"] = str(md_path)
    return result


def handle_library_list(
    *,
    _library_path: Path | None = None,
) -> list[dict[str, Any]]:
    """List all papers in the local library."""
    lib = _open_library(_library_path)
    try:
        entries = lib.list()
    except LibraryError as exc:
        raise RuntimeError(str(exc)) from exc

    return [
        {
            "id": e.id,
            "title": e.title,
            "authors": json.loads(e.authors_json) if e.authors_json else [],
            "year": e.year,
            "abstract": e.abstract,
            "doi": e.doi,
            "arxiv_id": e.arxiv_id,
            "source": e.source,
            "added_at": e.added_at,
            "markdown_path": e.markdown_path,
        }
        for e in entries
    ]


def handle_library_grep(
    query: str,
    limit: int = 20,
    *,
    _library_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Full-text search the local library."""
    if not query.strip():
        raise ValueError("Query must not be empty.")

    lib = _open_library(_library_path)
    try:
        hits = lib.grep(query, limit=limit)
    except LibraryError as exc:
        raise RuntimeError(str(exc)) from exc

    return [
        {
            "id": h.id,
            "title": h.title,
            "snippet": h.snippet,
            "rank": h.rank,
        }
        for h in hits
    ]


# ---------------------------------------------------------------------------
# MCP server entry point
# ---------------------------------------------------------------------------


def run() -> None:
    """Start the MCP server over stdio.  Requires the ``mcp`` extra."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        import sys

        print(
            "MCP support not installed. Install with: pip install 'paperhound[mcp]'",
            file=sys.stderr,
        )
        sys.exit(1)

    mcp = FastMCP(
        "paperhound",
        instructions=(
            "paperhound: search, show, download and convert academic papers "
            "(arXiv, OpenAlex, DBLP, Crossref, Hugging Face Papers, Semantic Scholar, CORE) "
            "and manage a local offline library."
        ),
    )

    @mcp.tool()
    def search(
        query: str,
        limit: int = 10,
        sources: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Search papers across providers and return merged, deduplicated results.

        Args:
            query: Free-text query, e.g. "vision transformers".
            limit: Max results (1-100, default 10).
            sources: Optional list of provider names to restrict the search.
                     Valid values: arxiv, openalex, dblp, crossref, huggingface,
                     semantic_scholar, core. Defaults to all five main providers.
        """
        return handle_search(query, limit=limit, sources=sources)

    @mcp.tool()
    def show(identifier: str) -> dict[str, Any]:
        """Fetch metadata and abstract for a single paper.

        Args:
            identifier: arXiv id (2401.12345), DOI, Semantic Scholar id, or paper URL.
        """
        return handle_show(identifier)

    @mcp.tool()
    def download(identifier: str, dest: str | None = None) -> dict[str, Any]:
        """Download a paper PDF to disk and return the file path.

        Args:
            identifier: arXiv id, DOI, Semantic Scholar id, or paper URL.
            dest: Destination directory or file path. Defaults to current directory.
        """
        return handle_download(identifier, dest=dest)

    @mcp.tool()
    def convert(identifier: str, dest: str | None = None) -> dict[str, Any]:
        """Convert a PDF or supported document to Markdown.

        Args:
            identifier: Path or URL to a PDF or docling-supported document.
            dest: Output Markdown file path. If omitted, the Markdown is returned inline.
        """
        return handle_convert(identifier, dest=dest)

    @mcp.tool()
    def library_add(identifier: str, convert: bool = False) -> dict[str, Any]:
        """Fetch metadata and add a paper to the local library.

        Re-adding an existing entry updates its metadata (idempotent).

        Args:
            identifier: arXiv id, DOI, Semantic Scholar id, or paper URL.
            convert: Also fetch and convert the PDF to Markdown, stored in the library.
        """
        return handle_library_add(identifier, convert=convert)

    @mcp.tool()
    def library_list() -> list[dict[str, Any]]:
        """List all papers saved in the local library."""
        return handle_library_list()

    @mcp.tool()
    def library_grep(query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Full-text search the local library (title + abstract + Markdown body).

        Args:
            query: Full-text search query.
            limit: Max hits (default 20).
        """
        return handle_library_grep(query, limit=limit)

    mcp.run(transport="stdio")
