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
    DEFAULT_TIMEOUT,
    SearchAggregator,
    SearchQuery,
    build,
    names,
    resolve,
)

# Providers enabled by default. CORE is opt-in (requires CORE_API_KEY) and
# Semantic Scholar is currently rate-limited / 403 for many keys; both stay
# registered but off the default list — opt in via ``--source``.
DEFAULT_SOURCES: tuple[str, ...] = (
    "arxiv",
    "openalex",
    "dblp",
    "crossref",
    "huggingface",
)

# Click's `\b` marker (on its own line, with blank lines around the paragraph)
# tells the help formatter not to rewrap the following block — preserves
# manual line breaks in examples.
HELP_EPILOG = (
    "Examples:\n"
    "\n"
    "\b\n"
    '  paperhound search "retrieval augmented generation" -n 5\n'
    "  paperhound show 2401.12345\n"
    "  paperhound download 10.48550/arXiv.2401.12345 -o ./papers\n"
    "  paperhound convert paper.pdf -o paper.md\n"
    "  paperhound get 2401.12345 -o rag.md\n"
    "\n"
    "\b\n"
    "Sources:     arxiv, openalex, dblp, crossref, huggingface (alias: hf),\n"
    "             semantic_scholar (alias: s2), core. Defaults to arxiv +\n"
    "             openalex + dblp + crossref + huggingface (parallel, 10s\n"
    "             budget; round-robin merge across providers; partial\n"
    "             results returned on timeout).\n"
    "Identifiers: arXiv id (2401.12345), DOI, Semantic Scholar id, or paper URL.\n"
    "Docs:        https://github.com/alexfdez1010/paperhound"
)


app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode=None,
    help=(
        "Search, download, and convert academic papers from the command line.\n\n"
        "Aggregates arXiv, OpenAlex, DBLP, Crossref, Hugging Face Papers"
        " (and optionally Semantic Scholar / CORE) in parallel, then converts"
        " PDFs to Markdown via docling."
    ),
    epilog=HELP_EPILOG,
    context_settings={"help_option_names": ["-h", "--help"]},
)

console = Console()
err_console = Console(stderr=True)


def _version_callback(value: bool) -> None:
    if value:
        console.print(__version__)
        raise typer.Exit()


def _build_aggregator(
    sources: list[str] | None = None, timeout: float = DEFAULT_TIMEOUT
) -> SearchAggregator:
    requested = list(sources) if sources else list(DEFAULT_SOURCES)
    canonical: list[str] = []
    seen: set[str] = set()
    for raw in requested:
        try:
            name = resolve(raw)
        except KeyError as exc:
            valid = ", ".join(names())
            raise typer.BadParameter(f"Unknown source: {raw!r}. Valid: {valid}") from exc
        if name not in seen:
            seen.add(name)
            canonical.append(name)
    providers = [build(n) for n in canonical]
    return SearchAggregator(providers, timeout=timeout)


def _exit_on_error(exc: Exception) -> None:
    err_console.print(f"[red]error:[/red] {exc}")
    raise typer.Exit(code=1)


@app.callback()
def _root(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose (DEBUG) logging."),
    _version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show paperhound version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.ERROR,
        format="%(levelname)s %(name)s: %(message)s",
    )


@app.command()
def version() -> None:
    """Print the installed paperhound version."""
    console.print(__version__)


@app.command(
    epilog=(
        "Examples:\n\n\b\n"
        '  paperhound search "diffusion models" -n 20\n'
        '  paperhound search "graph neural networks" -s arxiv --year-min 2023\n'
        '  paperhound search "llm agents" --json | jq .'
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
        None, "--year-min", help="Earliest publication year (inclusive)."
    ),
    year_max: int | None = typer.Option(
        None, "--year-max", help="Latest publication year (inclusive)."
    ),
    timeout: float = typer.Option(
        DEFAULT_TIMEOUT,
        "--timeout",
        help=(
            "Per-search budget in seconds. Providers run in parallel; ones that"
            " exceed the budget are dropped from the response."
        ),
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of a Rich table."),
) -> None:
    """Search papers across providers and print merged, deduplicated results."""
    if not query.strip():
        raise typer.BadParameter("Query must not be empty.")
    aggregator = _build_aggregator(source, timeout=timeout)
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


@app.command(
    epilog=(
        "Examples:\n\n\b\n"
        "  paperhound show 2401.12345\n"
        "  paperhound show 10.48550/arXiv.2401.12345 --json"
    ),
)
def show(
    identifier: str = typer.Argument(..., help="arXiv id, DOI, Semantic Scholar id, or paper URL."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of formatted text."),
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


@app.command(
    epilog=(
        "Examples:\n\n\b\n"
        "  paperhound download 2401.12345\n"
        "  paperhound download 2401.12345 -o ./papers/\n"
        "  paperhound download 2401.12345 -o paper.pdf"
    ),
)
def download(
    identifier: str = typer.Argument(..., help="arXiv id, DOI, Semantic Scholar id, or paper URL."),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help=(
            "Destination file or directory. Paths with a suffix (e.g. "
            "paper.pdf) are treated as files; paths without one (./papers, "
            "./papers/) as directories — they are created if missing and the "
            "file is named after the identifier. Defaults to the current "
            "directory."
        ),
    ),
) -> Path:
    """Download a paper PDF to disk."""
    destination = output if output is not None else Path.cwd()
    try:
        url = resolve_pdf_url(identifier, lookup_pdf_url=_lookup_pdf_url)
        path = download_pdf(url, destination)
    except PaperhoundError as exc:
        _exit_on_error(exc)
        return Path()
    console.print(f"[green]Saved[/green] {path}")
    return path


@app.command(
    epilog=(
        "Examples:\n\n\b\n"
        "  paperhound convert paper.pdf -o paper.md\n"
        "  paperhound convert https://arxiv.org/pdf/2401.12345 > paper.md"
    ),
)
def convert(
    source: str = typer.Argument(..., help="Path or URL to a PDF / docling-supported document."),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Markdown output path. Prints to stdout when omitted."
    ),
) -> None:
    """Convert a PDF or supported document to Markdown via docling."""
    try:
        markdown = convert_to_markdown(source, output=output)
    except PaperhoundError as exc:
        _exit_on_error(exc)
        return

    if output is None:
        sys.stdout.write(markdown)
    else:
        console.print(f"[green]Wrote[/green] {output}")


@app.command(
    epilog=(
        "Examples:\n\n\b\n"
        "  paperhound get 2401.12345\n"
        "  paperhound get 2401.12345 -o rag.md --keep-pdf"
    ),
)
def get(
    identifier: str = typer.Argument(..., help="arXiv id, DOI, Semantic Scholar id, or paper URL."),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Markdown output path. Defaults to <id>.md in the current directory.",
    ),
    keep_pdf: bool = typer.Option(
        False, "--keep-pdf", help="Keep the downloaded PDF next to the Markdown output."
    ),
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
