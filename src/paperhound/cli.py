"""paperhound command-line interface."""

from __future__ import annotations

import logging
import os
import sys
import warnings
from pathlib import Path

import typer
from rich.console import Console

from paperhound import __version__
from paperhound.convert import convert_to_markdown
from paperhound.download import download_pdf, resolve_pdf_url
from paperhound.errors import LibraryError, PaperhoundError
from paperhound.identifiers import IdentifierKind, detect
from paperhound.library import Library, _canonical_id, _library_dir, _safe_filename
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

# Loggers that are noisy by default — silenced unless ``--verbose``. docling
# alone emits dozens of INFO lines per PDF (page processing, model loads, OCR
# fallbacks); httpx logs every request. Stdout/stderr leakage corrupts the
# context window when the CLI is invoked from another LLM.
_NOISY_LOGGERS: tuple[str, ...] = (
    "docling",
    "docling_core",
    "docling_ibm_models",
    "docling_parse",
    "httpx",
    "httpcore",
    "urllib3",
    "PIL",
    "huggingface_hub",
    "transformers",
    "torch",
    "matplotlib",
    "filelock",
    "fsspec",
    "asyncio",
)


def _configure_logging(verbose: bool) -> None:
    """Set up logging + library output for the requested verbosity.

    Default (``verbose=False``): suppress 3rd-party logs and tqdm progress
    bars. Only ERROR-level records from paperhound itself reach stderr.

    ``--verbose``: route everything at DEBUG to stderr.
    """
    if verbose:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(levelname)s %(name)s: %(message)s",
            force=True,
        )
        for name in _NOISY_LOGGERS:
            logging.getLogger(name).setLevel(logging.NOTSET)
        return

    # tqdm checks the env var at bar instantiation. Setting it before docling
    # is imported (docling import is lazy in convert.py) silences the bars.
    os.environ.setdefault("TQDM_DISABLE", "1")
    warnings.filterwarnings("ignore")
    logging.basicConfig(
        level=logging.ERROR,
        format="%(levelname)s %(name)s: %(message)s",
        force=True,
    )
    for name in _NOISY_LOGGERS:
        lib_logger = logging.getLogger(name)
        lib_logger.setLevel(logging.CRITICAL)
        lib_logger.propagate = False


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
    "  paperhound add 2401.12345 --convert\n"
    "  paperhound list\n"
    '  paperhound grep "attention mechanism"\n'
    "  paperhound rm 2401.12345\n"
    "\n"
    "\b\n"
    "Sources:     arxiv, openalex, dblp, crossref, huggingface (alias: hf),\n"
    "             semantic_scholar (alias: s2), core. Defaults to arxiv +\n"
    "             openalex + dblp + crossref + huggingface (parallel, 10s\n"
    "             budget; round-robin merge across providers; partial\n"
    "             results returned on timeout).\n"
    "Identifiers: arXiv id (2401.12345), DOI, Semantic Scholar id, or paper URL.\n"
    "Library:     ~/.paperhound/library/ (override: PAPERHOUND_LIBRARY_DIR).\n"
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
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help=(
            "Enable verbose (DEBUG) logging from paperhound and its dependencies"
            " (docling, httpx, ...). Off by default — library logs and tqdm"
            " progress bars are suppressed so the output is safe to pipe into"
            " another tool or LLM."
        ),
    ),
    _version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show paperhound version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    _configure_logging(verbose)


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


# ---------------------------------------------------------------------------
# Local library commands
# ---------------------------------------------------------------------------


def _open_library() -> Library:
    """Open the default (or env-var-overridden) library; surface errors cleanly."""
    try:
        return Library()
    except LibraryError as exc:
        _exit_on_error(exc)
        raise  # unreachable; satisfies type checkers


@app.command(
    name="add",
    epilog=("Examples:\n\n\b\n  paperhound add 2401.12345\n  paperhound add 2401.12345 --convert"),
)
def library_add(
    identifier: str = typer.Argument(..., help="arXiv id, DOI, Semantic Scholar id, or paper URL."),
    convert_flag: bool = typer.Option(
        False,
        "--convert",
        help="Also fetch and convert the PDF to Markdown and store it in the library.",
    ),
) -> None:
    """Fetch a paper's metadata and add it to the local library.

    Re-adding an existing entry updates its metadata (idempotent).
    Pass --convert to also store a Markdown version of the PDF.
    """
    aggregator = _build_aggregator()
    try:
        paper = aggregator.get(identifier)
    except PaperhoundError as exc:
        _exit_on_error(exc)
        return

    if paper is None:
        err_console.print(f"[yellow]Not found:[/yellow] {identifier}")
        raise typer.Exit(code=1)

    lib = _open_library()
    paper_id = _canonical_id(paper)

    md_path: Path | None = None
    if convert_flag:
        safe = _safe_filename(paper_id)
        md_path = _library_dir() / f"{safe}.md"
        # Resolve the library dir the same way the Library object does.
        actual_lib_dir = lib._dir
        md_path = actual_lib_dir / f"{safe}.md"
        tmp_pdf = actual_lib_dir / f"{safe}.pdf"
        try:
            url = resolve_pdf_url(identifier, lookup_pdf_url=_lookup_pdf_url)
            download_pdf(url, tmp_pdf)
            convert_to_markdown(tmp_pdf, output=md_path)
        except PaperhoundError as exc:
            _exit_on_error(exc)
            return
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
        _exit_on_error(exc)
        return

    console.print(f"[green]Added[/green] {paper_id}")
    if md_path:
        console.print(f"[green]Markdown[/green] {md_path}")


@app.command(
    name="list",
    epilog="Examples:\n\n\b\n  paperhound list",
)
def library_list() -> None:
    """List all papers in the local library."""
    lib = _open_library()
    try:
        entries = lib.list()
    except LibraryError as exc:
        _exit_on_error(exc)
        return

    if not entries:
        console.print("[dim]Library is empty.[/dim]")
        return

    from rich.table import Table

    table = Table(show_lines=False, header_style="bold cyan")
    table.add_column("ID")
    table.add_column("Title", overflow="fold")
    table.add_column("Authors", overflow="fold")
    table.add_column("Year", justify="right")
    table.add_column("MD", justify="center")

    for entry in entries:
        table.add_row(
            entry.id,
            entry.title,
            entry.first_author,
            str(entry.year) if entry.year else "-",
            "yes" if entry.markdown_path else "-",
        )
    console.print(table)


@app.command(
    name="grep",
    epilog=(
        "Examples:\n\n\b\n"
        '  paperhound grep "attention mechanism"\n'
        '  paperhound grep "diffusion" --limit 5'
    ),
)
def library_grep(
    query: str = typer.Argument(..., help="Full-text search query."),
    limit: int = typer.Option(20, "--limit", "-n", min=1, max=200, help="Max hits (default 20)."),
) -> None:
    """Full-text search the local library (title + abstract + Markdown body)."""
    if not query.strip():
        raise typer.BadParameter("Query must not be empty.")

    lib = _open_library()
    try:
        hits = lib.grep(query, limit=limit)
    except LibraryError as exc:
        _exit_on_error(exc)
        return

    if not hits:
        console.print("[dim]No hits.[/dim]")
        return

    for hit in hits:
        console.print(f"[bold]{hit.id}[/bold]  {hit.title}")
        console.print(f"  [dim]{hit.snippet}[/dim]")
        console.print()


@app.command(
    name="rm",
    epilog="Examples:\n\n\b\n  paperhound rm 2401.12345",
)
def library_rm(
    identifier: str = typer.Argument(..., help="Library id of the paper to remove."),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip the confirmation prompt.",
    ),
) -> None:
    """Remove a paper from the local library (and its Markdown file, if any)."""
    lib = _open_library()
    try:
        entry = lib.get(identifier)
        if entry is None:
            err_console.print(f"[yellow]Not in library:[/yellow] {identifier}")
            raise typer.Exit(code=1)

        if not yes:
            typer.confirm(f"Remove {identifier!r} from library?", abort=True)

        md_path = lib.remove(identifier)
    except LibraryError as exc:
        _exit_on_error(exc)
        return

    if md_path and md_path.exists():
        try:
            md_path.unlink()
            console.print(f"[dim]Deleted markdown:[/dim] {md_path}")
        except OSError as exc:
            err_console.print(f"[yellow]Could not delete markdown file:[/yellow] {exc}")

    console.print(f"[green]Removed[/green] {identifier}")
