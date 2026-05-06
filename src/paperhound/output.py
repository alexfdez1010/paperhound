"""Render Paper objects for terminal and machine-readable output."""

from __future__ import annotations

import json
from collections.abc import Iterable

from rich.console import Console
from rich.table import Table

from paperhound.models import Paper


def render_table(papers: Iterable[Paper], console: Console) -> None:
    table = Table(show_lines=False, header_style="bold cyan")
    table.add_column("#", style="dim", width=3)
    table.add_column("Title", overflow="fold")
    table.add_column("Authors", overflow="fold")
    table.add_column("Year", justify="right")
    table.add_column("ID")
    table.add_column("Sources")

    for i, paper in enumerate(papers, start=1):
        authors = ", ".join(paper.author_names()[:3])
        if len(paper.authors) > 3:
            authors += f", +{len(paper.authors) - 3}"
        table.add_row(
            str(i),
            paper.title,
            authors or "-",
            str(paper.year) if paper.year else "-",
            paper.primary_id or "-",
            ",".join(paper.sources),
        )
    console.print(table)


def render_paper_detail(paper: Paper, console: Console) -> None:
    console.print(f"[bold]{paper.title}[/bold]")
    if paper.authors:
        console.print("[dim]Authors:[/dim] " + ", ".join(paper.author_names()))
    meta = []
    if paper.year:
        meta.append(f"year={paper.year}")
    if paper.venue:
        meta.append(f"venue={paper.venue}")
    if paper.citation_count is not None:
        meta.append(f"citations={paper.citation_count}")
    if meta:
        console.print("[dim]" + " | ".join(meta) + "[/dim]")
    if paper.identifiers.arxiv_id:
        console.print(f"[dim]arXiv:[/dim] {paper.identifiers.arxiv_id}")
    if paper.identifiers.doi:
        console.print(f"[dim]DOI:[/dim] {paper.identifiers.doi}")
    if paper.identifiers.semantic_scholar_id:
        console.print(f"[dim]S2:[/dim] {paper.identifiers.semantic_scholar_id}")
    if paper.url:
        console.print(f"[dim]URL:[/dim] {paper.url}")
    if paper.pdf_url:
        console.print(f"[dim]PDF:[/dim] {paper.pdf_url}")
    if paper.abstract:
        console.print()
        console.print("[bold]Abstract[/bold]")
        console.print(paper.abstract)


def papers_to_json(papers: Iterable[Paper]) -> str:
    return json.dumps([p.model_dump(mode="json") for p in papers], indent=2)
