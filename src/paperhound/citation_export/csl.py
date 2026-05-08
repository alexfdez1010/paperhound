"""CSL-JSON serialiser for ``Paper`` records."""

from __future__ import annotations

import json

from paperhound.citation_export._common import (
    bibtex_cite_key,
    entry_type,
    fallback_url,
)
from paperhound.models import Paper

_CSL_TYPE_MAP = {
    "article": "article-journal",
    "inproceedings": "paper-conference",
    "misc": "article",
}


def _split_name(full_name: str) -> dict[str, str]:
    """Split ``"Given Family"`` into ``{"family": ..., "given": ...}``."""
    parts = full_name.strip().split()
    if len(parts) == 1:
        return {"family": parts[0], "given": ""}
    family = parts[-1]
    given = " ".join(parts[:-1])
    return {"family": family, "given": given}


def _paper_to_csl(paper: Paper) -> dict:
    et = entry_type(paper)
    csl_type = _CSL_TYPE_MAP.get(et, "article")

    obj: dict = {
        "id": bibtex_cite_key(paper),
        "type": csl_type,
        "title": paper.title,
    }

    if paper.authors:
        obj["author"] = [_split_name(a.name) for a in paper.authors]

    if paper.year:
        obj["issued"] = {"date-parts": [[paper.year]]}

    if paper.abstract:
        obj["abstract"] = paper.abstract

    if paper.identifiers.doi:
        obj["DOI"] = paper.identifiers.doi

    url = fallback_url(paper)
    if url:
        obj["URL"] = url

    if paper.venue:
        key = "container-title" if et == "article" else "event"
        obj[key] = paper.venue

    return obj


def to_csljson(papers: list[Paper]) -> str:
    """Serialise *papers* as a JSON-encoded CSL-JSON array."""
    items = [_paper_to_csl(p) for p in papers]
    return json.dumps(items, ensure_ascii=False, indent=2)
