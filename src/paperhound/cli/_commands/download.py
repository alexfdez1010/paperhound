"""``paperhound download`` — fetch a paper's PDF to disk."""

from __future__ import annotations

from pathlib import Path

import typer

from paperhound import cli
from paperhound.errors import PaperhoundError


@cli.app.command(
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
        url = cli.resolve_pdf_url(identifier, lookup_pdf_url=cli._lookup_pdf_url)
        path = cli.download_pdf(url, destination)
    except PaperhoundError as exc:
        cli._exit_on_error(exc)
        return Path()
    cli.console.print(f"[green]Saved[/green] {path}")
    return path
