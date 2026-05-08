"""``paperhound get`` — download a paper and convert it to Markdown in one step."""

from __future__ import annotations

from pathlib import Path

import typer

from paperhound import cli
from paperhound.errors import PaperhoundError
from paperhound.identifiers import IdentifierKind, detect


@cli.app.command(
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
        cli._exit_on_error(exc)
        return

    md_default_stem = value.replace("/", "_") if kind is IdentifierKind.ARXIV else value
    md_path = output or Path.cwd() / f"{md_default_stem}.md"
    pdf_dest = (md_path.parent if keep_pdf else Path.cwd()) / f"{md_default_stem}.pdf"

    try:
        url = cli.resolve_pdf_url(identifier, lookup_pdf_url=cli._lookup_pdf_url)
        pdf_path = cli.download_pdf(url, pdf_dest)
        cli.convert_to_markdown(pdf_path, output=md_path)
    except PaperhoundError as exc:
        cli._exit_on_error(exc)
        return
    finally:
        if not keep_pdf and pdf_dest.exists():
            try:
                pdf_dest.unlink()
            except OSError:
                pass

    cli.console.print(f"[green]Wrote[/green] {md_path}")
