"""RIS serialiser for ``Paper`` records."""

from __future__ import annotations

from paperhound.citation_export._common import entry_type, fallback_url
from paperhound.models import Paper

_RIS_TYPE_MAP = {
    "article": "JOUR",
    "inproceedings": "CONF",
    "misc": "GENERIC",
}


def to_ris(paper: Paper) -> str:
    """Serialise *paper* as a single RIS block.

    Lines are ``TAG  - value\\n``-formatted; the block ends with ``ER  -``.
    """
    et = entry_type(paper)
    ris_type = _RIS_TYPE_MAP.get(et, "GENERIC")

    lines: list[str] = []

    def tag(t: str, value: str) -> None:
        lines.append(f"{t}  - {value}\n")

    tag("TY", ris_type)
    tag("TI", paper.title)

    for author in paper.authors:
        tag("AU", author.name)

    if paper.abstract:
        tag("AB", paper.abstract)

    if paper.year:
        tag("PY", str(paper.year))

    if paper.venue:
        key = "BT" if et == "inproceedings" else "JO"
        tag(key, paper.venue)

    if paper.identifiers.doi:
        tag("DO", paper.identifiers.doi)

    url = fallback_url(paper)
    if url:
        tag("UR", url)

    lines.append("ER  -\n")

    return "".join(lines)
