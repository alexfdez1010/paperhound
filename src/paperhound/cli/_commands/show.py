"""``paperhound show`` — fetch a single paper's metadata + abstract."""

from __future__ import annotations

import sys

import typer

from paperhound import cli
from paperhound.citation_export import render as render_citation
from paperhound.errors import PaperhoundError
from paperhound.output import paper_to_json_line, render_paper_detail

_VALID_FORMATS: tuple[str, ...] = ("markdown", "bibtex", "ris", "csljson")


@cli.app.command(
    epilog=(
        "Examples:\n\n\b\n"
        "  paperhound show 2401.12345\n"
        "  paperhound show 2401.12345 -s arxiv\n"
        "  paperhound show 2401.12345 --format bibtex\n"
        "  paperhound show 2401.12345 --format ris\n"
        "  paperhound show 2401.12345 --format csljson\n"
        "  paperhound show 10.48550/arXiv.2401.12345 --json"
    ),
)
def show(
    identifier: str = typer.Argument(..., help="arXiv id, DOI, Semantic Scholar id, or paper URL."),
    source: list[str] | None = typer.Option(
        None,
        "--source",
        "-s",
        help=(
            "Restrict the lookup to one or more providers. Choices: arxiv,"
            " openalex, dblp, crossref, huggingface (alias: hf),"
            " semantic_scholar (alias: s2), core. Repeatable. Useful when an"
            " upstream aggregator returns poisoned metadata for an id"
            " (e.g. ``-s arxiv`` to force the canonical arXiv record)."
        ),
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit a single compact JSON object. Overrides --format."
    ),
    fmt: str = typer.Option(
        "markdown",
        "--format",
        "-f",
        help=("Output format. One of: markdown (default, rich text), bibtex, ris, csljson."),
    ),
) -> None:
    """Fetch a paper's metadata and abstract."""
    if fmt not in _VALID_FORMATS:
        raise typer.BadParameter(
            f"Invalid format {fmt!r}. Choose from: {', '.join(_VALID_FORMATS)}."
        )

    if json_output and fmt != "markdown":
        raise typer.BadParameter(
            "--json and --format are mutually exclusive. Use --json for the Paper schema"
            " (paperhound internal) or --format for citation export formats; not both."
        )

    aggregator = cli._build_aggregator(source)
    try:
        paper = aggregator.get(identifier)
    except PaperhoundError as exc:
        cli._exit_on_error(exc)
        return

    if paper is None:
        cli.err_console.print(f"[yellow]Not found:[/yellow] {identifier}")
        raise typer.Exit(code=1)

    if json_output:
        sys.stdout.write(paper_to_json_line(paper) + "\n")
    elif fmt != "markdown":
        output = render_citation(paper, fmt)  # type: ignore[arg-type]
        sys.stdout.write(output or "")
    else:
        render_paper_detail(paper, cli.console)
