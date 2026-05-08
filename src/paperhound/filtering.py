"""Client-side filtering utilities for search results.

Pure functions — no I/O, no network.
"""

from __future__ import annotations

import re

from paperhound.errors import PaperhoundError
from paperhound.models import Paper, SearchFilters

_YEAR_RANGE_RE = re.compile(r"^(?:(?P<single>\d{4})|(?P<lo>\d{4})?-(?P<hi>\d{4})?)$")


def parse_year_range(s: str) -> tuple[int | None, int | None]:
    """Parse a year range string into (year_min, year_max).

    Accepted forms:
    - ``"2023"``       → (2023, 2023)
    - ``"2023-2026"``  → (2023, 2026)
    - ``"2023-"``      → (2023, None)
    - ``"-2026"``      → (None, 2026)

    Raises :exc:`paperhound.errors.PaperhoundError` on invalid input.
    """
    if not s or not s.strip():
        raise PaperhoundError("Year range must not be empty.")
    s = s.strip()
    m = _YEAR_RANGE_RE.match(s)
    if not m:
        raise PaperhoundError(f"Invalid year range {s!r}. Use YYYY, YYYY-YYYY, YYYY-, or -YYYY.")
    if m.group("single"):
        y = int(m.group("single"))
        return y, y
    lo = int(m.group("lo")) if m.group("lo") else None
    hi = int(m.group("hi")) if m.group("hi") else None
    if lo is None and hi is None:
        raise PaperhoundError(f"Invalid year range {s!r}. At least one year must be given.")
    if lo is not None and hi is not None and lo > hi:
        raise PaperhoundError(f"Invalid year range {s!r}: start year {lo} is after end year {hi}.")
    return lo, hi


def apply_filters(papers: list[Paper], filters: SearchFilters | None) -> list[Paper]:
    """Apply *filters* to *papers* client-side and return the surviving subset.

    The function is intentionally lenient about missing fields:
    - ``year_min`` / ``year_max``: a paper with ``year=None`` is **kept**
      (we have no data to reject it).
    - ``min_citations``: a paper with ``citation_count=None`` is **excluded**
      (we cannot verify the citation floor; this is safer for users who explicitly
      asked for a minimum).
    - ``venue``: a paper with ``venue=None`` is **kept**.
    - ``author``: a paper with no authors is **kept**.
    - ``publication_types``: a paper with ``publication_type=None`` is
      **excluded** when the filter is set — when the user asks for a specific
      type (e.g. peer-reviewed only), an unlabeled record is treated the same
      way as a missing citation count.

    All string comparisons are case-insensitive substring matches.
    """
    if filters is None or filters.is_empty():
        return list(papers)

    out: list[Paper] = []
    for paper in papers:
        if filters.year_min is not None and paper.year is not None:
            if paper.year < filters.year_min:
                continue
        if filters.year_max is not None and paper.year is not None:
            if paper.year > filters.year_max:
                continue
        if filters.min_citations is not None:
            if paper.citation_count is None or paper.citation_count < filters.min_citations:
                continue
        if filters.venue is not None and paper.venue is not None:
            if filters.venue.lower() not in paper.venue.lower():
                continue
        if filters.author is not None and paper.authors:
            needle = filters.author.lower()
            if not any(needle in a.name.lower() for a in paper.authors):
                continue
        if filters.publication_types is not None:
            if paper.publication_type is None:
                continue
            if paper.publication_type not in filters.publication_types:
                continue
        out.append(paper)
    return out


def parse_publication_types(values: list[str] | None) -> frozenset[str] | None:
    """Parse repeated/comma-separated ``--type`` values into a normalized set.

    Returns ``None`` when *values* is empty so callers can leave
    ``SearchFilters.publication_types`` unset.

    Raises :exc:`paperhound.errors.PaperhoundError` on unknown types.
    """
    from paperhound.models import PUBLICATION_TYPES

    if not values:
        return None
    out: set[str] = set()
    for raw in values:
        for piece in raw.split(","):
            token = piece.strip().lower()
            if not token:
                continue
            if token not in PUBLICATION_TYPES:
                allowed = ", ".join(sorted(PUBLICATION_TYPES))
                raise PaperhoundError(f"Unknown publication type {token!r}. Allowed: {allowed}.")
            out.add(token)
    return frozenset(out) if out else None
