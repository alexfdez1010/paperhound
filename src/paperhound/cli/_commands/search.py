"""``paperhound search`` — fan-out search across providers + optional rerank."""

from __future__ import annotations

import sys

import typer

from paperhound import cli
from paperhound.errors import PaperhoundError, RerankError
from paperhound.filtering import parse_publication_types, parse_year_range
from paperhound.models import PEER_REVIEWED_TYPES, SearchFilters
from paperhound.output import papers_to_jsonl, render_table
from paperhound.search import SearchQuery

# Widen the candidate pool only when the reranker is going to run, so it has
# enough material to reorder. Capped to keep latency bounded.
_RERANK_CANDIDATE_MULTIPLIER = 3
_RERANK_CANDIDATE_CAP = 50


@cli.app.command(
    epilog=(
        "Examples:\n\n\b\n"
        '  paperhound search "diffusion models" -n 20\n'
        '  paperhound search "graph neural networks" -s arxiv --year 2023-\n'
        '  paperhound search "llm agents" --year 2020-2024 --min-citations 50\n'
        '  paperhound search "transformers" --venue NeurIPS --author Hinton\n'
        '  paperhound search "diffusion models" --peer-reviewed\n'
        '  paperhound search "rag" --type journal,conference\n'
        '  paperhound search "agentic workflows" --preprints-only\n'
        '  paperhound search "llm agents" --json | jq .\n'
        '  paperhound search "transformers" --no-rerank\n'
        '  paperhound search "vision language"'
        " --rerank-model sentence-transformers/all-MiniLM-L6-v2"
    ),
)
def search(
    query: str = typer.Argument(..., help='Free-text query, e.g. "vision transformers".'),
    limit: int = typer.Option(
        10, "--limit", "-n", min=1, max=100, help="Max results to return (1-100)."
    ),
    source: list[str] | None = typer.Option(
        None,
        "--source",
        "-s",
        help=(
            "Restrict to a provider. Choices: arxiv, openalex, dblp, crossref,"
            " huggingface (alias: hf), semantic_scholar (alias: s2), core."
            " Repeatable; default = arxiv + openalex + dblp + crossref +"
            " huggingface."
        ),
    ),
    year_min: int | None = typer.Option(
        None, "--year-min", help="Earliest publication year (inclusive). Prefer --year."
    ),
    year_max: int | None = typer.Option(
        None, "--year-max", help="Latest publication year (inclusive). Prefer --year."
    ),
    year: str | None = typer.Option(
        None,
        "--year",
        help=(
            "Year range filter. Accepts: YYYY (single year), YYYY-YYYY (range),"
            " YYYY- (from year), -YYYY (up to year). Inclusive on both ends."
        ),
    ),
    min_citations: int | None = typer.Option(
        None,
        "--min-citations",
        min=0,
        help="Minimum citation count (inclusive). Papers with unknown citation counts are excluded.",
    ),
    venue: str | None = typer.Option(
        None,
        "--venue",
        help="Case-insensitive substring match against the paper's venue / journal / conference.",
    ),
    author: str | None = typer.Option(
        None,
        "--author",
        help="Case-insensitive substring match against any author name.",
    ),
    pub_type: list[str] | None = typer.Option(
        None,
        "--type",
        help=(
            "Filter by publication type (repeatable / comma-separated)."
            " Allowed: journal, conference, preprint, book, other."
            " Papers with unknown type are excluded."
        ),
    ),
    peer_reviewed: bool = typer.Option(
        False,
        "--peer-reviewed",
        help=(
            "Shortcut for --type journal,conference,book. Drops preprints and"
            " papers with unknown publication type."
        ),
    ),
    preprints_only: bool = typer.Option(
        False,
        "--preprints-only",
        help="Shortcut for --type preprint.",
    ),
    timeout: float = typer.Option(
        cli.DEFAULT_TIMEOUT,
        "--timeout",
        help=(
            "Per-search budget in seconds. Providers run in parallel; ones that"
            " exceed the budget are dropped from the response."
        ),
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of a Rich table."),
    do_rerank: bool = typer.Option(
        True,
        "--rerank/--no-rerank",
        help=(
            "Rerank results by embedding similarity (query vs. title+abstract)."
            " On by default when paperhound[rerank] is installed; otherwise the"
            " merge-order ranking is used. Pass --no-rerank to skip explicitly."
        ),
    ),
    rerank_model: str = typer.Option(
        "sentence-transformers/all-MiniLM-L6-v2",
        "--rerank-model",
        help="SentenceTransformer model name used for reranking (default: all-MiniLM-L6-v2).",
    ),
) -> None:
    """Search papers across providers and print merged, deduplicated results."""
    if not query.strip():
        raise typer.BadParameter("Query must not be empty.")

    if year is not None:
        try:
            parsed_min, parsed_max = parse_year_range(year)
        except PaperhoundError as exc:
            raise typer.BadParameter(str(exc), param_hint="'--year'") from exc
        if year_min is None:
            year_min = parsed_min
        if year_max is None:
            year_max = parsed_max

    if peer_reviewed and preprints_only:
        raise typer.BadParameter("--peer-reviewed and --preprints-only are mutually exclusive.")
    try:
        types = parse_publication_types(pub_type)
    except PaperhoundError as exc:
        raise typer.BadParameter(str(exc), param_hint="'--type'") from exc
    if peer_reviewed:
        types = (types or frozenset()) | PEER_REVIEWED_TYPES
    if preprints_only:
        types = (types or frozenset()) | frozenset({"preprint"})

    filters = SearchFilters(
        year_min=year_min,
        year_max=year_max,
        min_citations=min_citations,
        venue=venue,
        author=author,
        publication_types=types,
    )
    if filters.is_empty():
        filters = None  # type: ignore[assignment]

    from paperhound import rerank as rerank_mod

    rerank_active = do_rerank and rerank_mod.is_available()
    if rerank_active:
        candidate_limit = min(limit * _RERANK_CANDIDATE_MULTIPLIER, _RERANK_CANDIDATE_CAP)
    else:
        candidate_limit = limit

    aggregator = cli._build_aggregator(source, timeout=timeout)
    try:
        papers = aggregator.search(
            SearchQuery(
                text=query,
                limit=candidate_limit,
                year_min=year_min,
                year_max=year_max,
                filters=filters,
            )
        )
    except PaperhoundError as exc:
        cli._exit_on_error(exc)
        return

    if rerank_active and papers:
        try:
            papers = rerank_mod.rerank(query, papers, rerank_model)
        except RerankError as exc:
            cli.err_console.print(f"[red]error:[/red] {exc}")
            raise typer.Exit(code=1) from exc

    papers = papers[:limit]

    if not papers:
        cli.err_console.print("[yellow]No results.[/yellow]")
        raise typer.Exit(code=0)

    if json_output:
        jsonl = papers_to_jsonl(papers)
        if jsonl:
            sys.stdout.write(jsonl + "\n")
    else:
        render_table(papers, cli.console)
