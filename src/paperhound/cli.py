"""paperhound command-line interface."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import typer
from rich.console import Console

from paperhound import __version__
from paperhound.convert import convert_to_markdown
from paperhound.download import download_pdf, resolve_pdf_url
from paperhound.errors import PaperhoundError
from paperhound.identifiers import IdentifierKind, detect
from paperhound.output import papers_to_json, render_paper_detail, render_table
from paperhound.search import (
    ArxivProvider,
    SearchAggregator,
    SearchQuery,
    SemanticScholarProvider,
)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Search, download, and convert academic papers from the command line.",
)

console = Console()
err_console = Console(stderr=True)


def _build_aggregator(sources: list[str] | None = None) -> SearchAggregator:
    chosen = {s.lower() for s in sources} if sources else {"arxiv", "semantic_scholar"}
    providers = []
    if "arxiv" in chosen:
        providers.append(ArxivProvider())
    if "semantic_scholar" in chosen or "s2" in chosen:
        providers.append(SemanticScholarProvider())
    if not providers:
        raise typer.BadParameter(f"Unknown sources: {sources!r}")
    return SearchAggregator(providers)


def _exit_on_error(exc: Exception) -> None:
    err_console.print(f"[red]error:[/red] {exc}")
    raise typer.Exit(code=1)


@app.callback()
def _root(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose logging."),
) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )


@app.command()
def version() -> None:
    """Print the installed paperhound version."""
    console.print(__version__)


@app.command()
def search(
    query: str = typer.Argument(..., help="Free-text query."),
    limit: int = typer.Option(10, "--limit", "-n", min=1, max=100),
    source: list[str] | None = typer.Option(
        None,
        "--source",
        "-s",
        help="Restrict to a provider (arxiv, semantic_scholar). Repeatable.",
    ),
    year_min: int | None = typer.Option(None, "--year-min"),
    year_max: int | None = typer.Option(None, "--year-max"),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
) -> None:
    """Search across all providers and print the merged results."""
    aggregator = _build_aggregator(source)
    try:
        papers = aggregator.search(
            SearchQuery(
                text=query,
                limit=limit,
                year_min=year_min,
                year_max=year_max,
            )
        )
    except PaperhoundError as exc:
        _exit_on_error(exc)
        return

    if not papers:
        err_console.print("[yellow]No results.[/yellow]")
        raise typer.Exit(code=0)

    if json_output:
        sys.stdout.write(papers_to_json(papers) + "\n")
    else:
        render_table(papers, console)


@app.command()
def show(
    identifier: str = typer.Argument(..., help="arXiv id, DOI, S2 id, or paper URL."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Fetch a paper's metadata and abstract."""
    aggregator = _build_aggregator()
    try:
        paper = aggregator.get(identifier)
    except PaperhoundError as exc:
        _exit_on_error(exc)
        return

    if paper is None:
        err_console.print(f"[yellow]Not found:[/yellow] {identifier}")
        raise typer.Exit(code=1)

    if json_output:
        sys.stdout.write(paper.model_dump_json(indent=2) + "\n")
    else:
        render_paper_detail(paper, console)


def _lookup_pdf_url(identifier: str) -> str | None:
    """Aggregator-backed callback used by ``download`` for non-arXiv ids."""
    aggregator = _build_aggregator()
    paper = aggregator.get(identifier)
    return paper.pdf_url if paper else None


@app.command()
def download(
    identifier: str = typer.Argument(..., help="arXiv id, DOI, S2 id, or paper URL."),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Destination file or directory. Defaults to the current directory.",
    ),
) -> Path:
    """Download a paper PDF."""
    destination = output if output is not None else Path.cwd()
    try:
        url = resolve_pdf_url(identifier, lookup_pdf_url=_lookup_pdf_url)
        path = download_pdf(url, destination)
    except PaperhoundError as exc:
        _exit_on_error(exc)
        return Path()
    console.print(f"[green]Saved[/green] {path}")
    return path


@app.command()
def convert(
    source: str = typer.Argument(..., help="Path or URL to a PDF / supported document."),
    output: Path | None = typer.Option(None, "--output", "-o"),
) -> None:
    """Convert a document to Markdown via docling."""
    try:
        markdown = convert_to_markdown(source, output=output)
    except PaperhoundError as exc:
        _exit_on_error(exc)
        return

    if output is None:
        sys.stdout.write(markdown)
    else:
        console.print(f"[green]Wrote[/green] {output}")


@app.command()
def get(
    identifier: str = typer.Argument(..., help="arXiv id, DOI, S2 id, or paper URL."),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Markdown output path. Defaults to <id>.md in the current directory.",
    ),
    keep_pdf: bool = typer.Option(False, "--keep-pdf", help="Keep the downloaded PDF."),
) -> None:
    """Download a paper and convert it to Markdown in one step."""
    try:
        kind, value = detect(identifier)
    except PaperhoundError as exc:
        _exit_on_error(exc)
        return

    md_default_stem = value.replace("/", "_") if kind is IdentifierKind.ARXIV else value
    md_path = output or Path.cwd() / f"{md_default_stem}.md"
    pdf_dest = (md_path.parent if keep_pdf else Path.cwd()) / f"{md_default_stem}.pdf"

    try:
        url = resolve_pdf_url(identifier, lookup_pdf_url=_lookup_pdf_url)
        pdf_path = download_pdf(url, pdf_dest)
        convert_to_markdown(pdf_path, output=md_path)
    except PaperhoundError as exc:
        _exit_on_error(exc)
        return
    finally:
        if not keep_pdf and pdf_dest.exists():
            try:
                pdf_dest.unlink()
            except OSError:
                pass

    console.print(f"[green]Wrote[/green] {md_path}")
