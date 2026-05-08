"""Typer CLI entry point.

The ``app`` object is registered piecewise: helpers + the root callback live
here; each command lives in :mod:`paperhound.cli._commands`. Importing this
module triggers command registration via ``_commands.register_all``.

Helper functions and the third-party callables that command bodies depend on
(``resolve_pdf_url``, ``download_pdf``, ``convert_to_markdown``) are exposed
as attributes of this package so that tests can ``monkeypatch.setattr`` them
without reaching into individual command modules.
"""

from __future__ import annotations

import typer
from rich.console import Console

from paperhound import __version__
from paperhound.cli._help import ROOT_EPILOG, ROOT_HELP
from paperhound.cli._logging import NOISY_LOGGERS, configure_logging
from paperhound.convert import convert_to_markdown  # re-export for tests
from paperhound.download import download_pdf, resolve_pdf_url  # re-export for tests
from paperhound.errors import LibraryError, PaperhoundError
from paperhound.library import Library
from paperhound.search import (
    DEFAULT_TIMEOUT,
    SearchAggregator,
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

# Backward-compatible aliases — tests monkeypatch / read these names.
_NOISY_LOGGERS = NOISY_LOGGERS


def _configure_logging(verbose: bool) -> None:
    """Backward-compatible alias for :func:`paperhound.cli._logging.configure_logging`."""
    configure_logging(verbose)


console = Console()
err_console = Console(stderr=True)


app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode=None,
    help=ROOT_HELP,
    epilog=ROOT_EPILOG,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _version_callback(value: bool) -> None:
    if value:
        console.print(__version__)
        raise typer.Exit()


def _build_aggregator(
    sources: list[str] | None = None, timeout: float = DEFAULT_TIMEOUT
) -> SearchAggregator:
    """Build a :class:`SearchAggregator` for the given sources (defaults applied)."""
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


def _open_library() -> Library:
    """Open the default (or env-var-overridden) library; surface errors cleanly."""
    try:
        return Library()
    except LibraryError as exc:
        _exit_on_error(exc)
        raise  # unreachable; satisfies type checkers


def _lookup_pdf_url(identifier: str) -> str | None:
    """Aggregator-backed callback used by ``download`` for non-arXiv ids."""
    aggregator = _build_aggregator()
    paper = aggregator.get(identifier)
    return paper.pdf_url if paper else None


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


# Importing the command modules registers their @app.command decorators with
# the typer app. Done last so all helpers/aliases above are already in the
# package namespace when commands look them up via ``paperhound.cli``.
from paperhound.cli._commands import register_all  # noqa: E402

register_all()


__all__ = [
    "DEFAULT_SOURCES",
    "DEFAULT_TIMEOUT",
    "PaperhoundError",
    "app",
    "console",
    "convert_to_markdown",
    "download_pdf",
    "err_console",
    "resolve_pdf_url",
]
