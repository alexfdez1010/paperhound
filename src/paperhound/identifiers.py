"""Parse and detect paper identifiers (arXiv, DOI, Semantic Scholar)."""

from __future__ import annotations

import re
from enum import Enum

from paperhound.errors import IdentifierError

# arXiv identifier formats:
#   - new style: 2401.12345 or 2401.12345v2 (4 digits . 4-5 digits)
#   - old style: cs.AI/0301001 or hep-th/9901001
ARXIV_NEW_RE = re.compile(r"^(\d{4}\.\d{4,5})(v\d+)?$")
ARXIV_OLD_RE = re.compile(r"^([a-z\-]+(?:\.[A-Z]{2})?/\d{7})(v\d+)?$")
ARXIV_URL_RE = re.compile(
    r"arxiv\.org/(?:abs|pdf|html)/([a-z\-]+(?:\.[A-Z]{2})?/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?",
    re.IGNORECASE,
)

# DOI: 10.xxxx/yyyy
DOI_RE = re.compile(r"^10\.\d{4,9}/[\-._;()/:A-Za-z0-9]+$")
DOI_URL_RE = re.compile(r"(?:doi\.org/|dx\.doi\.org/)(10\.\d{4,9}/[\-._;()/:A-Za-z0-9]+)")

# Semantic Scholar paperId is a 40-char lowercase hex string (sha-1).
S2_RE = re.compile(r"^[0-9a-f]{40}$")
S2_URL_RE = re.compile(r"semanticscholar\.org/paper/(?:[^/]+/)?([0-9a-f]{40})")


class IdentifierKind(str, Enum):
    ARXIV = "arxiv"
    DOI = "doi"
    SEMANTIC_SCHOLAR = "semantic_scholar"


def normalize_arxiv(value: str) -> str:
    """Strip the version suffix from an arXiv id (e.g. 2401.12345v3 -> 2401.12345)."""
    value = value.strip()
    m = ARXIV_NEW_RE.match(value)
    if m:
        return m.group(1)
    m = ARXIV_OLD_RE.match(value)
    if m:
        return m.group(1)
    raise IdentifierError(f"Not an arXiv id: {value!r}")


def detect(value: str) -> tuple[IdentifierKind, str]:
    """Detect the kind of identifier and return its canonical form.

    Accepts bare ids or URLs (arxiv.org, doi.org, semanticscholar.org).
    """
    if not value:
        raise IdentifierError("Empty identifier.")
    raw = value.strip()

    # Try URL extractors first.
    m = ARXIV_URL_RE.search(raw)
    if m:
        return IdentifierKind.ARXIV, m.group(1)

    m = DOI_URL_RE.search(raw)
    if m:
        return IdentifierKind.DOI, m.group(1)

    m = S2_URL_RE.search(raw)
    if m:
        return IdentifierKind.SEMANTIC_SCHOLAR, m.group(1)

    # Strip the common "arXiv:" / "doi:" prefixes.
    lowered = raw.lower()
    if lowered.startswith("arxiv:"):
        return IdentifierKind.ARXIV, normalize_arxiv(raw.split(":", 1)[1])
    if lowered.startswith("doi:"):
        candidate = raw.split(":", 1)[1].strip()
        if DOI_RE.match(candidate):
            return IdentifierKind.DOI, candidate

    if ARXIV_NEW_RE.match(raw) or ARXIV_OLD_RE.match(raw):
        return IdentifierKind.ARXIV, normalize_arxiv(raw)

    if DOI_RE.match(raw):
        return IdentifierKind.DOI, raw

    if S2_RE.match(raw):
        return IdentifierKind.SEMANTIC_SCHOLAR, raw

    raise IdentifierError(f"Unrecognized paper identifier: {value!r}")


def to_semantic_scholar_lookup(kind: IdentifierKind, value: str) -> str:
    """Convert a detected identifier to the form Semantic Scholar's API accepts."""
    if kind is IdentifierKind.ARXIV:
        return f"ARXIV:{value}"
    if kind is IdentifierKind.DOI:
        return f"DOI:{value}"
    return value


def arxiv_pdf_url(arxiv_id: str, version: str | None = None) -> str:
    suffix = version or ""
    return f"https://arxiv.org/pdf/{arxiv_id}{suffix}.pdf"
