"""BibTeX serialiser for ``Paper`` records."""

from __future__ import annotations

from paperhound.citation_export._common import (
    bibtex_cite_key,
    entry_type,
    fallback_url,
    latex_escape,
)
from paperhound.models import Paper


def to_bibtex(paper: Paper) -> str:
    """Serialise *paper* as a single BibTeX entry string."""
    et = entry_type(paper)
    cite_key = bibtex_cite_key(paper)

    lines: list[str] = [f"@{et}{{{cite_key},"]

    def field(name: str, value: str) -> None:
        lines.append(f"  {name} = {{{latex_escape(value)}}},")

    field("title", paper.title)

    if paper.authors:
        field("author", " and ".join(a.name for a in paper.authors))

    if paper.year:
        lines.append(f"  year = {{{paper.year}}},")

    if paper.venue:
        key = "booktitle" if et == "inproceedings" else "journal"
        field(key, paper.venue)

    if paper.identifiers.doi:
        field("doi", paper.identifiers.doi)

    url = fallback_url(paper)
    if url:
        field("url", url)

    if paper.abstract:
        field("abstract", paper.abstract)

    if lines[-1].endswith(","):
        lines[-1] = lines[-1][:-1]
    lines.append("}")

    return "\n".join(lines) + "\n"
