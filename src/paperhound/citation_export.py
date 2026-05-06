"""Citation format export for Paper objects.

Provides pure functions to serialise a ``Paper`` (or a list of papers) to
BibTeX, RIS, and CSL-JSON.  No third-party dependencies — stdlib ``json`` only.

Public API
----------
to_bibtex(paper)   -> str        -- single ``@article``/``@misc`` entry
to_ris(paper)      -> str        -- single RIS block, newline-terminated, ends with ER
to_csljson(papers) -> str        -- JSON-serialised list of CSL-JSON objects
render(paper, fmt) -> str        -- dispatcher; fmt in bibtex|ris|csljson|markdown
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Literal

from paperhound.models import Paper

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LATEX_SPECIAL = str.maketrans(
    {
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "_": r"\_",
        "#": r"\#",
        "^": r"\^{}",
        "~": r"\~{}",
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
    }
)

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "of",
        "in",
        "on",
        "at",
        "to",
        "for",
        "and",
        "or",
        "but",
        "with",
        "is",
        "are",
        "was",
        "by",
        "from",
        "via",
        "into",
        "as",
        "be",
        "this",
        "that",
        "its",
    }
)


def _strip_accents(s: str) -> str:
    """Decompose accented characters and keep only ASCII letters/digits."""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _latex_escape(s: str) -> str:
    """Escape BibTeX special characters in *s*."""
    return s.translate(_LATEX_SPECIAL)


def _first_author_last_name(paper: Paper) -> str:
    """Return the ASCII-safe last name of the first author, lowercased."""
    if not paper.authors:
        return "unknown"
    name = paper.authors[0].name.strip()
    # Try to extract the last token as the surname.
    parts = name.split()
    last = parts[-1] if parts else name
    ascii_last = _strip_accents(last)
    # Keep only alphanumeric characters.
    return re.sub(r"[^a-z0-9]", "", ascii_last.lower())


def _first_significant_title_word(paper: Paper) -> str:
    """Return the first non-stopword token from the title, lowercased ASCII."""
    words = re.findall(r"[A-Za-z0-9]+", paper.title)
    for w in words:
        lower = w.lower()
        if lower not in _STOPWORDS:
            ascii_w = _strip_accents(lower)
            return re.sub(r"[^a-z0-9]", "", ascii_w)
    # Fallback: use the first word regardless.
    if words:
        return re.sub(r"[^a-z0-9]", "", _strip_accents(words[0].lower()))
    return "paper"


def _bibtex_cite_key(paper: Paper) -> str:
    """Deterministic cite key: ``<lastNameLower><year><firstSignificantWord>``."""
    author = _first_author_last_name(paper)
    year = str(paper.year) if paper.year else ""
    word = _first_significant_title_word(paper)
    return f"{author}{year}{word}"


def _entry_type(paper: Paper) -> str:
    """Heuristically choose @article, @inproceedings, or @misc."""
    if paper.identifiers.arxiv_id and not paper.venue:
        return "misc"
    venue = (paper.venue or "").lower()
    if any(
        kw in venue
        for kw in (
            "workshop",
            "conf",
            "proceedings",
            "symposium",
            "icml",
            "nips",
            "neurips",
            "iclr",
            "cvpr",
            "eccv",
            "iccv",
            "acl",
            "emnlp",
            "naacl",
            "aaai",
        )
    ):
        return "inproceedings"
    if venue:
        return "article"
    return "misc"


# ---------------------------------------------------------------------------
# BibTeX
# ---------------------------------------------------------------------------


def to_bibtex(paper: Paper) -> str:
    """Serialise *paper* as a single BibTeX entry string."""
    entry_type = _entry_type(paper)
    cite_key = _bibtex_cite_key(paper)

    lines: list[str] = [f"@{entry_type}{{{cite_key},"]

    def field(name: str, value: str) -> None:
        escaped = _latex_escape(value)
        lines.append(f"  {name} = {{{escaped}}},")

    field("title", paper.title)

    if paper.authors:
        author_str = " and ".join(a.name for a in paper.authors)
        field("author", author_str)

    if paper.year:
        lines.append(f"  year = {{{paper.year}}},")

    if paper.venue:
        key = "booktitle" if entry_type == "inproceedings" else "journal"
        field(key, paper.venue)

    if paper.identifiers.doi:
        field("doi", paper.identifiers.doi)

    if paper.url:
        field("url", paper.url)
    elif paper.identifiers.arxiv_id:
        field("url", f"https://arxiv.org/abs/{paper.identifiers.arxiv_id}")

    if paper.abstract:
        field("abstract", paper.abstract)

    # Remove trailing comma from last field and close.
    if lines[-1].endswith(","):
        lines[-1] = lines[-1][:-1]
    lines.append("}")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# RIS
# ---------------------------------------------------------------------------

_RIS_TYPE_MAP = {
    "article": "JOUR",
    "inproceedings": "CONF",
    "misc": "GENERIC",
}


def to_ris(paper: Paper) -> str:
    """Serialise *paper* as a single RIS block.

    Lines are ``TAG  - value\n``-formatted.  The block ends with ``ER  -``.
    """
    entry_type = _entry_type(paper)
    ris_type = _RIS_TYPE_MAP.get(entry_type, "GENERIC")

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
        key = "BT" if entry_type == "inproceedings" else "JO"
        tag(key, paper.venue)

    if paper.identifiers.doi:
        tag("DO", paper.identifiers.doi)

    url = paper.url
    if not url and paper.identifiers.arxiv_id:
        url = f"https://arxiv.org/abs/{paper.identifiers.arxiv_id}"
    if url:
        tag("UR", url)

    lines.append("ER  -\n")

    return "".join(lines)


# ---------------------------------------------------------------------------
# CSL-JSON
# ---------------------------------------------------------------------------


def _split_name(full_name: str) -> dict[str, str]:
    """Split ``"Given Family"`` into ``{"family": ..., "given": ...}``."""
    parts = full_name.strip().split()
    if len(parts) == 1:
        return {"family": parts[0], "given": ""}
    family = parts[-1]
    given = " ".join(parts[:-1])
    return {"family": family, "given": given}


def to_csljson(papers: list[Paper]) -> str:
    """Serialise *papers* as a JSON-encoded CSL-JSON array."""
    items: list[dict] = []
    for paper in papers:
        entry_type = _entry_type(paper)
        csl_type = {
            "article": "article-journal",
            "inproceedings": "paper-conference",
            "misc": "article",
        }.get(entry_type, "article")

        obj: dict = {
            "id": _bibtex_cite_key(paper),
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

        url = paper.url
        if not url and paper.identifiers.arxiv_id:
            url = f"https://arxiv.org/abs/{paper.identifiers.arxiv_id}"
        if url:
            obj["URL"] = url

        if paper.venue:
            key = "container-title" if entry_type == "article" else "event"
            obj[key] = paper.venue

        items.append(obj)

    return json.dumps(items, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

ExportFormat = Literal["bibtex", "ris", "csljson", "markdown"]


def render(paper: Paper, fmt: ExportFormat) -> str | None:
    """Return the paper serialised in *fmt*, or ``None`` for ``"markdown"``
    (caller should use ``output.render_paper_detail`` for that path).
    """
    if fmt == "bibtex":
        return to_bibtex(paper)
    if fmt == "ris":
        return to_ris(paper)
    if fmt == "csljson":
        return to_csljson([paper])
    # fmt == "markdown" — caller handles this
    return None
