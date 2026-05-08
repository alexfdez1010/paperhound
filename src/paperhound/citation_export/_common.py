"""Shared helpers used by every citation export backend.

Pure-text utilities — no I/O, no Paper-specific logic beyond reading already
attached metadata. Kept private so backends can evolve their public surface
independently from this layer.
"""

from __future__ import annotations

import re
import unicodedata

from paperhound.models import Paper

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

_CONFERENCE_KEYWORDS: tuple[str, ...] = (
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


def strip_accents(s: str) -> str:
    """Decompose accented characters and keep only ASCII letters/digits."""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def latex_escape(s: str) -> str:
    """Escape BibTeX special characters in *s*."""
    return s.translate(_LATEX_SPECIAL)


def first_author_last_name(paper: Paper) -> str:
    """Return the ASCII-safe last name of the first author, lowercased."""
    if not paper.authors:
        return "unknown"
    name = paper.authors[0].name.strip()
    parts = name.split()
    last = parts[-1] if parts else name
    ascii_last = strip_accents(last)
    return re.sub(r"[^a-z0-9]", "", ascii_last.lower())


def first_significant_title_word(paper: Paper) -> str:
    """Return the first non-stopword token from the title, lowercased ASCII."""
    words = re.findall(r"[A-Za-z0-9]+", paper.title)
    for w in words:
        lower = w.lower()
        if lower not in _STOPWORDS:
            ascii_w = strip_accents(lower)
            return re.sub(r"[^a-z0-9]", "", ascii_w)
    if words:
        return re.sub(r"[^a-z0-9]", "", strip_accents(words[0].lower()))
    return "paper"


def bibtex_cite_key(paper: Paper) -> str:
    """Deterministic cite key: ``<lastNameLower><year><firstSignificantWord>``."""
    author = first_author_last_name(paper)
    year = str(paper.year) if paper.year else ""
    word = first_significant_title_word(paper)
    return f"{author}{year}{word}"


def entry_type(paper: Paper) -> str:
    """Heuristically choose @article, @inproceedings, or @misc."""
    if paper.identifiers.arxiv_id and not paper.venue:
        return "misc"
    venue = (paper.venue or "").lower()
    if any(kw in venue for kw in _CONFERENCE_KEYWORDS):
        return "inproceedings"
    if venue:
        return "article"
    return "misc"


def fallback_url(paper: Paper) -> str | None:
    """URL preference: explicit ``paper.url`` then synthesized arXiv abs URL."""
    if paper.url:
        return paper.url
    if paper.identifiers.arxiv_id:
        return f"https://arxiv.org/abs/{paper.identifiers.arxiv_id}"
    return None
