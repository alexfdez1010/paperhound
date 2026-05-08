"""``paperhound convert`` — turn a PDF / docling-supported document into Markdown."""

from __future__ import annotations

from pathlib import Path

import typer

from paperhound import cli
from paperhound.convert import ConversionOptions
from paperhound.errors import PaperhoundError


@cli.app.command(
    epilog=(
        "Examples:\n\n\b\n"
        "  paperhound convert paper.pdf -o paper.md\n"
        "  paperhound convert https://arxiv.org/pdf/2401.12345 > paper.md\n"
        "  paperhound convert paper.pdf -o paper.md --with-figures\n"
        "  paperhound convert paper.pdf -o paper.md --equations latex\n"
        "  paperhound convert paper.pdf -o paper.md --tables html"
    ),
)
def convert(
    source: str = typer.Argument(..., help="Path or URL to a PDF / docling-supported document."),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Markdown output path. Prints to stdout when omitted."
    ),
    with_figures: bool = typer.Option(
        False,
        "--with-figures",
        help=(
            "Extract embedded figures alongside the Markdown. Images are saved to"
            " <output_basename>_assets/ and referenced via Markdown image syntax."
            " Requires --output."
        ),
    ),
    equations: str = typer.Option(
        "inline",
        "--equations",
        help=(
            "Equation rendering mode. 'inline' (default): docling's default"
            " inline text representation. 'latex': enable formula enrichment so"
            " math is preserved as $...$ / $$...$$ LaTeX."
        ),
    ),
    tables: str = typer.Option(
        "markdown",
        "--tables",
        help=(
            "Table output format. 'markdown' (default): GFM pipe tables."
            " 'html': embed <table> blocks for better fidelity with irregular tables."
        ),
    ),
) -> None:
    """Convert a PDF or supported document to Markdown via docling."""
    try:
        opts = ConversionOptions(
            with_figures=with_figures,
            equations=equations,  # type: ignore[arg-type]
            tables=tables,  # type: ignore[arg-type]
        )
    except Exception as exc:
        cli.err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if with_figures and output is None:
        cli.err_console.print(
            "[red]error:[/red] --with-figures requires --output so that the"
            " assets directory can be placed alongside the Markdown file."
        )
        raise typer.Exit(code=1)

    try:
        import sys

        markdown = cli.convert_to_markdown(source, output=output, options=opts)
    except PaperhoundError as exc:
        cli._exit_on_error(exc)
        return

    if output is None:
        sys.stdout.write(markdown)
    else:
        cli.console.print(f"[green]Wrote[/green] {output}")
