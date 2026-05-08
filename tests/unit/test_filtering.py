"""Tests for paperhound.filtering — parse_year_range and apply_filters."""

from __future__ import annotations

import pytest

from paperhound.errors import PaperhoundError
from paperhound.filtering import apply_filters, parse_publication_types, parse_year_range
from paperhound.models import Author, Paper, PaperIdentifier, SearchFilters

# ---------------------------------------------------------------------------
# parse_year_range
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("input_str", "expected"),
    [
        ("2023", (2023, 2023)),
        ("2000", (2000, 2000)),
        ("2023-2026", (2023, 2026)),
        ("2000-2000", (2000, 2000)),
        ("2023-", (2023, None)),
        ("-2026", (None, 2026)),
    ],
)
def test_parse_year_range_happy(input_str: str, expected: tuple) -> None:
    assert parse_year_range(input_str) == expected


@pytest.mark.parametrize(
    "bad_input",
    [
        "",
        "   ",
        "-",
        "abc",
        "20230",
        "202",
        "2023 2026",
        "2023/2026",
        "2026-2023",  # inverted range
    ],
)
def test_parse_year_range_invalid(bad_input: str) -> None:
    with pytest.raises(PaperhoundError):
        parse_year_range(bad_input)


def test_parse_year_range_inverted_raises() -> None:
    with pytest.raises(PaperhoundError, match="after end year"):
        parse_year_range("2026-2023")


# ---------------------------------------------------------------------------
# Helpers for apply_filters tests
# ---------------------------------------------------------------------------


def _make_paper(
    *,
    title: str = "Test Paper",
    year: int | None = 2022,
    citation_count: int | None = 10,
    venue: str | None = "NeurIPS",
    authors: list[str] | None = None,
    publication_type: str | None = None,
) -> Paper:
    if authors is None:
        authors = ["Alice Smith"]
    return Paper(
        title=title,
        authors=[Author(name=n) for n in authors],
        year=year,
        citation_count=citation_count,
        venue=venue,
        publication_type=publication_type,  # type: ignore[arg-type]
        identifiers=PaperIdentifier(),
        sources=["arxiv"],
    )


# ---------------------------------------------------------------------------
# apply_filters — individual filters
# ---------------------------------------------------------------------------


def test_apply_filters_none_filters_passthrough() -> None:
    papers = [_make_paper()]
    assert apply_filters(papers, None) == papers


def test_apply_filters_empty_filters_passthrough() -> None:
    papers = [_make_paper()]
    assert apply_filters(papers, SearchFilters()) == papers


def test_apply_filters_year_min_keeps_matching() -> None:
    paper = _make_paper(year=2023)
    assert apply_filters([paper], SearchFilters(year_min=2023)) == [paper]


def test_apply_filters_year_min_drops_too_early() -> None:
    paper = _make_paper(year=2020)
    assert apply_filters([paper], SearchFilters(year_min=2023)) == []


def test_apply_filters_year_max_keeps_matching() -> None:
    paper = _make_paper(year=2022)
    assert apply_filters([paper], SearchFilters(year_max=2024)) == [paper]


def test_apply_filters_year_max_drops_too_late() -> None:
    paper = _make_paper(year=2025)
    assert apply_filters([paper], SearchFilters(year_max=2024)) == []


def test_apply_filters_year_range_inclusive() -> None:
    papers = [_make_paper(year=y) for y in [2021, 2022, 2023, 2024, 2025]]
    filtered = apply_filters(papers, SearchFilters(year_min=2022, year_max=2024))
    assert [p.year for p in filtered] == [2022, 2023, 2024]


def test_apply_filters_year_none_on_paper_kept() -> None:
    """Papers with unknown year must NOT be excluded by year filters."""
    paper = _make_paper(year=None)
    result = apply_filters([paper], SearchFilters(year_min=2020, year_max=2024))
    assert result == [paper]


def test_apply_filters_min_citations_keeps_matching() -> None:
    paper = _make_paper(citation_count=100)
    assert apply_filters([paper], SearchFilters(min_citations=100)) == [paper]


def test_apply_filters_min_citations_drops_below() -> None:
    paper = _make_paper(citation_count=5)
    assert apply_filters([paper], SearchFilters(min_citations=10)) == []


def test_apply_filters_min_citations_none_on_paper_excluded() -> None:
    """Papers with unknown citation_count are excluded when min_citations is set."""
    paper = _make_paper(citation_count=None)
    assert apply_filters([paper], SearchFilters(min_citations=1)) == []


def test_apply_filters_venue_case_insensitive_substring() -> None:
    paper = _make_paper(venue="International Conference on Machine Learning")
    result = apply_filters([paper], SearchFilters(venue="machine learning"))
    assert result == [paper]


def test_apply_filters_venue_no_match() -> None:
    paper = _make_paper(venue="CVPR")
    assert apply_filters([paper], SearchFilters(venue="NeurIPS")) == []


def test_apply_filters_venue_none_on_paper_kept() -> None:
    """Papers with unknown venue must NOT be excluded by venue filter."""
    paper = _make_paper(venue=None)
    result = apply_filters([paper], SearchFilters(venue="NeurIPS"))
    assert result == [paper]


def test_apply_filters_author_case_insensitive_substring() -> None:
    paper = _make_paper(authors=["Geoffrey Hinton", "Yann LeCun"])
    result = apply_filters([paper], SearchFilters(author="hinton"))
    assert result == [paper]


def test_apply_filters_author_no_match() -> None:
    paper = _make_paper(authors=["Alice Smith"])
    assert apply_filters([paper], SearchFilters(author="Bengio")) == []


def test_apply_filters_author_no_authors_on_paper_kept() -> None:
    """Papers with no author list must NOT be excluded by author filter."""
    paper = _make_paper(authors=[])
    result = apply_filters([paper], SearchFilters(author="Hinton"))
    assert result == [paper]


# ---------------------------------------------------------------------------
# apply_filters — publication_type
# ---------------------------------------------------------------------------


def test_apply_filters_publication_types_keeps_matching() -> None:
    paper = _make_paper(publication_type="journal")
    filters = SearchFilters(publication_types=frozenset({"journal", "conference"}))
    assert apply_filters([paper], filters) == [paper]


def test_apply_filters_publication_types_drops_non_matching() -> None:
    paper = _make_paper(publication_type="preprint")
    filters = SearchFilters(publication_types=frozenset({"journal", "conference"}))
    assert apply_filters([paper], filters) == []


def test_apply_filters_publication_types_drops_unknown() -> None:
    """Papers with publication_type=None are excluded when filter is set."""
    paper = _make_paper(publication_type=None)
    filters = SearchFilters(publication_types=frozenset({"journal"}))
    assert apply_filters([paper], filters) == []


def test_apply_filters_peer_reviewed_drops_preprint_and_unknown() -> None:
    journal = _make_paper(title="J", publication_type="journal")
    conference = _make_paper(title="C", publication_type="conference")
    book = _make_paper(title="B", publication_type="book")
    preprint = _make_paper(title="P", publication_type="preprint")
    untagged = _make_paper(title="U", publication_type=None)
    filters = SearchFilters(publication_types=frozenset({"journal", "conference", "book"}))
    result = apply_filters([journal, conference, book, preprint, untagged], filters)
    assert [p.title for p in result] == ["J", "C", "B"]


# ---------------------------------------------------------------------------
# parse_publication_types
# ---------------------------------------------------------------------------


def test_parse_publication_types_none_returns_none() -> None:
    assert parse_publication_types(None) is None
    assert parse_publication_types([]) is None


def test_parse_publication_types_single_value() -> None:
    assert parse_publication_types(["journal"]) == frozenset({"journal"})


def test_parse_publication_types_comma_separated() -> None:
    assert parse_publication_types(["journal,conference"]) == frozenset({"journal", "conference"})


def test_parse_publication_types_repeatable_and_case_insensitive() -> None:
    assert parse_publication_types(["JOURNAL", "Conference,Book"]) == frozenset(
        {"journal", "conference", "book"}
    )


def test_parse_publication_types_unknown_raises() -> None:
    with pytest.raises(PaperhoundError, match="workshop"):
        parse_publication_types(["workshop"])


# ---------------------------------------------------------------------------
# apply_filters — combined filters
# ---------------------------------------------------------------------------


def test_apply_filters_combined_all_pass() -> None:
    paper = _make_paper(
        year=2023,
        citation_count=200,
        venue="NeurIPS",
        authors=["Geoffrey Hinton"],
    )
    filters = SearchFilters(
        year_min=2020,
        year_max=2024,
        min_citations=100,
        venue="neurips",
        author="Hinton",
    )
    assert apply_filters([paper], filters) == [paper]


def test_apply_filters_combined_one_fails() -> None:
    paper = _make_paper(
        year=2023,
        citation_count=5,  # below min_citations
        venue="NeurIPS",
        authors=["Geoffrey Hinton"],
    )
    filters = SearchFilters(
        year_min=2020,
        year_max=2024,
        min_citations=100,
        venue="neurips",
        author="Hinton",
    )
    assert apply_filters([paper], filters) == []


def test_apply_filters_mixed_batch() -> None:
    papers = [
        _make_paper(title="A", year=2018, citation_count=50),
        _make_paper(title="B", year=2022, citation_count=150),
        _make_paper(title="C", year=2023, citation_count=200),
        _make_paper(title="D", year=2025, citation_count=300),
    ]
    filtered = apply_filters(papers, SearchFilters(year_min=2020, year_max=2024, min_citations=100))
    assert [p.title for p in filtered] == ["B", "C"]


# ---------------------------------------------------------------------------
# Regression seed — the exact scenario that motivated the feature
# ---------------------------------------------------------------------------


def test_regression_neurips_hinton_2023() -> None:
    """User searches NeurIPS 2023 papers by Hinton with >=50 citations.

    Papers outside the year range, with too few citations, or by other
    authors should be dropped; a matching paper is kept.
    """
    matching = _make_paper(
        title="Matching Paper",
        year=2023,
        citation_count=100,
        venue="NeurIPS 2023",
        authors=["Geoffrey Hinton", "Co Author"],
    )
    wrong_year = _make_paper(
        title="Wrong Year",
        year=2020,
        citation_count=100,
        venue="NeurIPS",
        authors=["Geoffrey Hinton"],
    )
    too_few_cites = _make_paper(
        title="Too Few Cites",
        year=2023,
        citation_count=10,
        venue="NeurIPS",
        authors=["Geoffrey Hinton"],
    )
    wrong_author = _make_paper(
        title="Wrong Author",
        year=2023,
        citation_count=100,
        venue="NeurIPS",
        authors=["Someone Else"],
    )
    papers = [matching, wrong_year, too_few_cites, wrong_author]
    result = apply_filters(
        papers,
        SearchFilters(
            year_min=2023, year_max=2023, min_citations=50, venue="neurips", author="hinton"
        ),
    )
    assert result == [matching]
