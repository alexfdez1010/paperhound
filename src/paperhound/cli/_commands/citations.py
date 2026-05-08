"""Citation graph commands: ``refs`` and ``cited-by``."""

from __future__ import annotations

import sys

import typer

from paperhound import citations as _citations  # late-bound for test monkeypatching
from paperhound import cli
from paperhound.citations import Source
from paperhound.errors import PaperhoundError
from paperhound.output import papers_to_json, render_table

_CITATION_SOURCE_HELP = (
    "Citation provider: openalex or semantic_scholar. Default: try OpenAlex"
    " first, fall back to Semantic Scholar if OpenAlex returns nothing."
)


def _resolve_source(source: str | None) -> Source | None:
    if source is None:
        return None
    lower = source.lower().replace("-", "_")
    if lower in ("openalex", "oa"):
        return "openalex"
    if lower in ("semantic_scholar", "s2"):
        return "semantic_scholar"
    raise typer.BadParameter(f"Unknown --source {source!r}. Use 'openalex' or 'semantic_scholar'.")


def _run(
    identifier: str, depth: int, limit: int, source: str | None, json_output: bool, mode: str
) -> None:
    """Shared logic for ``refs`` and ``cited-by``."""
    if depth < 1 or depth > 2:
        raise typer.BadParameter("--depth must be 1 or 2.")
    if limit < 1:
        raise typer.BadParameter("--limit must be >= 1.")

    resolved = _resolve_source(source)

    try:
        if mode == "refs":
            papers = _citations.fetch_references(
                identifier, depth=depth, limit=limit, source=resolved
            )
        else:
            papers = _citations.fetch_citations(
                identifier, depth=depth, limit=limit, source=resolved
            )
    except PaperhoundError as exc:
        cli._exit_on_error(exc)
        return

    if not papers:
        cli.err_console.print("[yellow]No results.[/yellow]")
        raise typer.Exit(code=0)

    if json_output:
        sys.stdout.write(papers_to_json(papers) + "\n")
    else:
        render_table(papers, cli.console)


@cli.app.command(
    name="refs",
    epilog=(
        "Examples:\n\n\b\n"
        "  paperhound refs 1706.03762\n"
        "  paperhound refs 1706.03762 --depth 2 --limit 50\n"
        "  paperhound refs 1706.03762 --source semantic_scholar --json"
    ),
)
def refs(
    identifier: str = typer.Argument(..., help="arXiv id, DOI, Semantic Scholar id, or paper URL."),
    depth: int = typer.Option(1, "--depth", "-d", min=1, max=2, help="Traversal depth (1 or 2)."),
    limit: int = typer.Option(25, "--limit", "-n", min=1, help="Max papers to return."),
    source: str | None = typer.Option(None, "--source", "-s", help=_CITATION_SOURCE_HELP),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of a Rich table."),
) -> None:
    """List works that a paper cites (its reference list).

    Queries OpenAlex (default) or Semantic Scholar for the paper's reference
    list. Use --depth 2 to include references-of-references (deduped, capped
    at limit*2 fetched). Results use the same Paper format as 'search'.
    """
    _run(identifier, depth, limit, source, json_output, mode="refs")


@cli.app.command(
    name="cited-by",
    epilog=(
        "Examples:\n\n\b\n"
        "  paperhound cited-by 1706.03762\n"
        "  paperhound cited-by 1706.03762 --depth 2 --limit 50\n"
        "  paperhound cited-by 1706.03762 --source openalex --json"
    ),
)
def cited_by(
    identifier: str = typer.Argument(..., help="arXiv id, DOI, Semantic Scholar id, or paper URL."),
    depth: int = typer.Option(1, "--depth", "-d", min=1, max=2, help="Traversal depth (1 or 2)."),
    limit: int = typer.Option(25, "--limit", "-n", min=1, help="Max papers to return."),
    source: str | None = typer.Option(None, "--source", "-s", help=_CITATION_SOURCE_HELP),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of a Rich table."),
) -> None:
    """List works that cite a paper.

    Queries OpenAlex (default) or Semantic Scholar for papers that have cited
    the given work. Use --depth 2 to also fetch works citing those citing papers
    (deduped, capped at limit*2 fetched). Results use the same Paper format as
    'search'.
    """
    _run(identifier, depth, limit, source, json_output, mode="cited-by")
