"""Citation format export for ``Paper`` records.

Per-format modules implement the actual serialisation; this module exposes
the public API plus a small dispatcher.

Public API
----------
to_bibtex(paper)   -> str        single ``@article``/``@misc`` entry
to_ris(paper)      -> str        single RIS block ending with ``ER  -``
to_csljson(papers) -> str        JSON array of CSL-JSON objects
render(paper, fmt) -> str|None   dispatcher; ``None`` when ``fmt == "markdown"``
"""

from __future__ import annotations

from typing import Literal

from paperhound.citation_export._common import (
    bibtex_cite_key as _bibtex_cite_key,
)
from paperhound.citation_export.bibtex import to_bibtex
from paperhound.citation_export.csl import to_csljson
from paperhound.citation_export.ris import to_ris
from paperhound.models import Paper

ExportFormat = Literal["bibtex", "ris", "csljson", "markdown"]


def render(paper: Paper, fmt: ExportFormat) -> str | None:
    """Return *paper* serialised in *fmt*, or ``None`` for ``"markdown"``.

    Markdown rendering is handled by ``paperhound.output.render_paper_detail``.
    """
    if fmt == "bibtex":
        return to_bibtex(paper)
    if fmt == "ris":
        return to_ris(paper)
    if fmt == "csljson":
        return to_csljson([paper])
    return None


__all__ = [
    "ExportFormat",
    "_bibtex_cite_key",
    "render",
    "to_bibtex",
    "to_csljson",
    "to_ris",
]
