"""Helpers to normalize provider-native publication-type fields.

Each provider exposes its own taxonomy (Crossref ``type``, OpenAlex ``type`` /
``type_crossref``, Semantic Scholar ``publicationTypes`` list, …). These
helpers map them onto the small shared vocabulary in
:mod:`paperhound.models` so the user-facing filter has consistent semantics.
"""

from __future__ import annotations

from paperhound.models import PublicationType

# Crossref / OpenAlex ``type`` (or ``type_crossref``) → normalized.
# https://api.crossref.org/types
_CROSSREF_TYPE: dict[str, PublicationType] = {
    "journal-article": "journal",
    "journal-issue": "journal",
    "journal-volume": "journal",
    "journal": "journal",
    "review-article": "journal",
    "proceedings-article": "conference",
    "proceedings": "conference",
    "conference-paper": "conference",
    "posted-content": "preprint",
    "preprint": "preprint",
    "book": "book",
    "book-chapter": "book",
    "book-section": "book",
    "edited-book": "book",
    "monograph": "book",
    "reference-book": "book",
    "report": "other",
    "report-component": "other",
    "dataset": "other",
    "dissertation": "other",
    "thesis": "other",
    "standard": "other",
    "other": "other",
    "component": "other",
    "peer-review": "other",
    "grant": "other",
}

# OpenAlex source.type (the venue host) → normalized. Used when ``type`` is the
# generic ``article`` and we need to disambiguate journal vs conference.
_OPENALEX_SOURCE_TYPE: dict[str, PublicationType] = {
    "journal": "journal",
    "conference": "conference",
    "book series": "book",
    "book": "book",
    "ebook platform": "book",
}

# Semantic Scholar ``publicationTypes`` entries → normalized. The first entry
# in the list that maps wins.
_S2_TYPE: dict[str, PublicationType] = {
    "JournalArticle": "journal",
    "Review": "journal",
    "Conference": "conference",
    "Book": "book",
    "BookSection": "book",
    "Editorial": "journal",
    "LettersAndComments": "journal",
    "MetaAnalysis": "journal",
    "CaseReport": "journal",
    "ClinicalTrial": "journal",
    "News": "other",
    "Study": "other",
    "Dataset": "other",
}

# DBLP ``type`` (i.e. the bibtex-ish entry kind) → normalized.
_DBLP_TYPE: dict[str, PublicationType] = {
    "Journal Articles": "journal",
    "Conference and Workshop Papers": "conference",
    "Books and Theses": "book",
    "Books": "book",
    "Parts in Books or Collections": "book",
    "Editorship": "other",
    "Informal Publications": "preprint",
    "Informal and Other Publications": "preprint",
    "Reference Works": "other",
    "Data and Artifacts": "other",
}


def from_crossref(value: str | None) -> PublicationType | None:
    """Map a Crossref-style ``type`` string to the normalized vocabulary."""
    if not value:
        return None
    return _CROSSREF_TYPE.get(value.strip().lower())


def from_openalex(
    work_type: str | None,
    type_crossref: str | None = None,
    source_type: str | None = None,
) -> PublicationType | None:
    """Map OpenAlex's two type fields + the source type onto the vocabulary.

    ``work_type`` is the OpenAlex-native value (e.g. ``"article"``,
    ``"preprint"``, ``"book-chapter"``, ``"dataset"``). When it is the generic
    ``"article"`` and a Crossref or source type is present, those are used to
    pick journal vs conference more accurately.
    """
    work = (work_type or "").strip().lower()
    if work == "preprint":
        return "preprint"
    if work in _CROSSREF_TYPE:
        mapped = _CROSSREF_TYPE[work]
        if mapped != "journal" or work != "article":
            return mapped
    if work == "article":
        # Disambiguate via source venue first (more reliable), fall back to
        # type_crossref. If neither helps, default to journal — OpenAlex's
        # ``article`` overwhelmingly means journal article.
        src = (source_type or "").strip().lower()
        if src in _OPENALEX_SOURCE_TYPE:
            return _OPENALEX_SOURCE_TYPE[src]
        cr = from_crossref(type_crossref)
        if cr is not None:
            return cr
        return "journal"
    return None


def from_semantic_scholar(values: list[str] | None) -> PublicationType | None:
    """Map an S2 ``publicationTypes`` list to the first known normalized type."""
    if not values:
        return None
    for value in values:
        if not isinstance(value, str):
            continue
        mapped = _S2_TYPE.get(value)
        if mapped is not None:
            return mapped
    return None


def from_dblp(value: str | None) -> PublicationType | None:
    """Map a DBLP type (``info.type``) to the normalized vocabulary."""
    if not value:
        return None
    return _DBLP_TYPE.get(value.strip())


# Reverse mappings used to push the publication-type filter down to providers
# that support it. Empty list means we cannot push the filter (client-side
# filtering still applies as a safety net).
_OPENALEX_PUSHDOWN: dict[str, tuple[str, ...]] = {
    "journal": ("article",),
    "conference": ("article",),
    "preprint": ("preprint",),
    "book": ("book", "book-chapter"),
    "other": (
        "dataset",
        "dissertation",
        "report",
        "standard",
        "editorial",
        "letter",
        "erratum",
        "review",
        "paratext",
        "other",
    ),
}

_S2_PUSHDOWN: dict[str, tuple[str, ...]] = {
    "journal": ("JournalArticle", "Review"),
    "conference": ("Conference",),
    "preprint": (),  # S2 has no preprint type — fall back to client-side.
    "book": ("Book", "BookSection"),
    "other": ("Editorial", "Dataset", "News", "Study"),
}


def to_openalex_filter(types: frozenset[str] | None) -> str | None:
    """Build an OpenAlex ``type:`` filter value for the given normalized set.

    Returns ``None`` when push-down is not safe (e.g. ``preprint`` is in the
    set but OpenAlex's "article" already overlaps with peer-reviewed work).
    """
    if not types:
        return None
    out: set[str] = set()
    for t in types:
        mapped = _OPENALEX_PUSHDOWN.get(t)
        if not mapped:
            return None
        out.update(mapped)
    return "|".join(sorted(out)) if out else None


def to_s2_filter(types: frozenset[str] | None) -> str | None:
    """Build a Semantic Scholar ``publicationTypes`` filter value.

    Returns ``None`` when at least one requested type cannot be expressed in
    S2's vocabulary (notably ``preprint``) — the caller falls back to the
    client-side filter.
    """
    if not types:
        return None
    out: set[str] = set()
    for t in types:
        mapped = _S2_PUSHDOWN.get(t)
        if not mapped:
            return None
        out.update(mapped)
    return ",".join(sorted(out)) if out else None
