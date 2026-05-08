"""Library commands: ``add``, ``list``, ``grep``, ``rm``."""

from __future__ import annotations

from pathlib import Path

import typer

from paperhound import cli
from paperhound.errors import LibraryError, PaperhoundError
from paperhound.library import _canonical_id, _safe_filename


@cli.app.command(
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
    aggregator = cli._build_aggregator()
    try:
        paper = aggregator.get(identifier)
    except PaperhoundError as exc:
        cli._exit_on_error(exc)
        return

    if paper is None:
        cli.err_console.print(f"[yellow]Not found:[/yellow] {identifier}")
        raise typer.Exit(code=1)

    lib = cli._open_library()
    paper_id = _canonical_id(paper)

    md_path: Path | None = None
    if convert_flag:
        safe = _safe_filename(paper_id)
        actual_lib_dir = lib._dir
        md_path = actual_lib_dir / f"{safe}.md"
        tmp_pdf = actual_lib_dir / f"{safe}.pdf"
        try:
            url = cli.resolve_pdf_url(identifier, lookup_pdf_url=cli._lookup_pdf_url)
            cli.download_pdf(url, tmp_pdf)
            cli.convert_to_markdown(tmp_pdf, output=md_path)
        except PaperhoundError as exc:
            cli._exit_on_error(exc)
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
        cli._exit_on_error(exc)
        return

    cli.console.print(f"[green]Added[/green] {paper_id}")
    if md_path:
        cli.console.print(f"[green]Markdown[/green] {md_path}")


@cli.app.command(
    name="list",
    epilog="Examples:\n\n\b\n  paperhound list",
)
def library_list() -> None:
    """List all papers in the local library."""
    lib = cli._open_library()
    try:
        entries = lib.list()
    except LibraryError as exc:
        cli._exit_on_error(exc)
        return

    if not entries:
        cli.console.print("[dim]Library is empty.[/dim]")
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
    cli.console.print(table)


@cli.app.command(
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

    lib = cli._open_library()
    try:
        hits = lib.grep(query, limit=limit)
    except LibraryError as exc:
        cli._exit_on_error(exc)
        return

    if not hits:
        cli.console.print("[dim]No hits.[/dim]")
        return

    for hit in hits:
        cli.console.print(f"[bold]{hit.id}[/bold]  {hit.title}")
        cli.console.print(f"  [dim]{hit.snippet}[/dim]")
        cli.console.print()


@cli.app.command(
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
    lib = cli._open_library()
    try:
        entry = lib.get(identifier)
        if entry is None:
            cli.err_console.print(f"[yellow]Not in library:[/yellow] {identifier}")
            raise typer.Exit(code=1)

        if not yes:
            typer.confirm(f"Remove {identifier!r} from library?", abort=True)

        md_path = lib.remove(identifier)
    except LibraryError as exc:
        cli._exit_on_error(exc)
        return

    if md_path and md_path.exists():
        try:
            md_path.unlink()
            cli.console.print(f"[dim]Deleted markdown:[/dim] {md_path}")
        except OSError as exc:
            cli.err_console.print(f"[yellow]Could not delete markdown file:[/yellow] {exc}")

    cli.console.print(f"[green]Removed[/green] {identifier}")
