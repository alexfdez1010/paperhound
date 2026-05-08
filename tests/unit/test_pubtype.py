"""Tests for paperhound.search._pubtype — provider type → normalized vocab."""

from __future__ import annotations

import pytest

from paperhound.search._pubtype import (
    from_crossref,
    from_dblp,
    from_openalex,
    from_semantic_scholar,
    to_openalex_filter,
    to_s2_filter,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("journal-article", "journal"),
        ("review-article", "journal"),
        ("proceedings-article", "conference"),
        ("posted-content", "preprint"),
        ("preprint", "preprint"),
        ("book", "book"),
        ("book-chapter", "book"),
        ("dataset", "other"),
        ("Journal-Article", "journal"),  # case-insensitive
        ("", None),
        (None, None),
        ("nonsense-type", None),
    ],
)
def test_from_crossref(value: str | None, expected: str | None) -> None:
    assert from_crossref(value) == expected


@pytest.mark.parametrize(
    ("work_type", "type_crossref", "source_type", "expected"),
    [
        ("preprint", None, None, "preprint"),
        ("book-chapter", None, None, "book"),
        ("article", None, "journal", "journal"),
        ("article", None, "conference", "conference"),
        ("article", "proceedings-article", None, "conference"),
        ("article", None, None, "journal"),  # default for bare "article"
        ("dataset", None, None, "other"),
        ("dissertation", None, None, "other"),
        (None, None, None, None),
    ],
)
def test_from_openalex(
    work_type: str | None,
    type_crossref: str | None,
    source_type: str | None,
    expected: str | None,
) -> None:
    assert (
        from_openalex(work_type, type_crossref=type_crossref, source_type=source_type) == expected
    )


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (["JournalArticle"], "journal"),
        (["Review"], "journal"),
        (["Conference"], "conference"),
        (["Book"], "book"),
        (["BookSection"], "book"),
        (["Dataset"], "other"),
        # First mapped wins:
        (["Unknown", "Conference"], "conference"),
        ([], None),
        (None, None),
        (["UnknownOnly"], None),
    ],
)
def test_from_semantic_scholar(values: list[str] | None, expected: str | None) -> None:
    assert from_semantic_scholar(values) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Journal Articles", "journal"),
        ("Conference and Workshop Papers", "conference"),
        ("Books and Theses", "book"),
        ("Informal Publications", "preprint"),
        ("Editorship", "other"),
        (None, None),
        ("", None),
        ("Unknown", None),
    ],
)
def test_from_dblp(value: str | None, expected: str | None) -> None:
    assert from_dblp(value) == expected


def test_to_openalex_filter_peer_reviewed_set() -> None:
    result = to_openalex_filter(frozenset({"journal", "conference", "book"}))
    assert result is not None
    parts = set(result.split("|"))
    assert {"article", "book", "book-chapter"} <= parts


def test_to_openalex_filter_preprint_only() -> None:
    assert to_openalex_filter(frozenset({"preprint"})) == "preprint"


def test_to_openalex_filter_none_passthrough() -> None:
    assert to_openalex_filter(None) is None
    assert to_openalex_filter(frozenset()) is None


def test_to_s2_filter_journal_and_conference() -> None:
    result = to_s2_filter(frozenset({"journal", "conference"}))
    assert result is not None
    parts = set(result.split(","))
    assert {"JournalArticle", "Review", "Conference"} <= parts


def test_to_s2_filter_preprint_returns_none() -> None:
    """S2 has no preprint type — push-down must abort so client-side runs."""
    assert to_s2_filter(frozenset({"preprint"})) is None
    assert to_s2_filter(frozenset({"journal", "preprint"})) is None
