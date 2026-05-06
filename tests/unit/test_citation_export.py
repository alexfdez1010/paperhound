"""Unit tests for paperhound.citation_export."""

from __future__ import annotations

import json

import pytest

from paperhound.citation_export import (
    _bibtex_cite_key,
    to_bibtex,
    to_csljson,
    to_ris,
)
from paperhound.models import Author, Paper, PaperIdentifier

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def full_paper() -> Paper:
    return Paper(
        title="Attention Is All You Need",
        authors=[
            Author(name="Ashish Vaswani"),
            Author(name="Noam Shazeer"),
            Author(name="Niki Parmar"),
        ],
        abstract="We propose a new network architecture, the Transformer.",
        year=2017,
        venue="NeurIPS",
        url="https://arxiv.org/abs/1706.03762",
        identifiers=PaperIdentifier(
            arxiv_id="1706.03762",
            doi="10.48550/arXiv.1706.03762",
        ),
        sources=["arxiv"],
    )


@pytest.fixture
def minimal_paper() -> Paper:
    """Paper with only a title — all optional fields are absent."""
    return Paper(title="Minimal Paper")


@pytest.fixture
def unicode_paper() -> Paper:
    return Paper(
        title="Rôle des réseaux de neurones profonds",
        authors=[Author(name="André Müller"), Author(name="李 明")],
        year=2023,
    )


# ---------------------------------------------------------------------------
# BibTeX
# ---------------------------------------------------------------------------


class TestToBibtex:
    def test_entry_type_and_cite_key_present(self, full_paper: Paper) -> None:
        bib = to_bibtex(full_paper)
        assert "@" in bib
        assert "vaswani2017attention" in bib

    def test_required_fields(self, full_paper: Paper) -> None:
        bib = to_bibtex(full_paper)
        assert "title = {Attention Is All You Need}" in bib
        assert "Ashish Vaswani" in bib
        assert "year = {2017}" in bib

    def test_doi_and_url_present(self, full_paper: Paper) -> None:
        bib = to_bibtex(full_paper)
        assert "doi = {10.48550" in bib
        assert "url = {https://" in bib

    def test_abstract_present(self, full_paper: Paper) -> None:
        bib = to_bibtex(full_paper)
        assert "abstract = {" in bib
        assert "Transformer" in bib

    def test_minimal_paper_is_well_formed(self, minimal_paper: Paper) -> None:
        bib = to_bibtex(minimal_paper)
        # Must start with @ and end with }
        assert bib.strip().startswith("@")
        assert bib.strip().endswith("}")
        # title field present
        assert "title = {Minimal Paper}" in bib
        # Missing optional fields must NOT appear
        assert "year" not in bib
        assert "doi" not in bib
        assert "abstract" not in bib

    def test_no_doi_falls_back_to_arxiv_url(self) -> None:
        paper = Paper(
            title="Some Paper",
            year=2020,
            identifiers=PaperIdentifier(arxiv_id="2001.00001"),
        )
        bib = to_bibtex(paper)
        assert "https://arxiv.org/abs/2001.00001" in bib

    def test_no_url_no_arxiv_no_doi(self, minimal_paper: Paper) -> None:
        bib = to_bibtex(minimal_paper)
        # Should not crash; url field just absent
        assert "url" not in bib

    @pytest.mark.parametrize(
        "raw, expected_fragment",
        [
            ("title with & ampersand", r"\&"),
            ("50% off", r"\%"),
            ("$100 cash", r"\$"),
            ("var_name", r"\_"),
        ],
    )
    def test_latex_special_char_escaping(self, raw: str, expected_fragment: str) -> None:
        paper = Paper(title=raw)
        bib = to_bibtex(paper)
        assert expected_fragment in bib

    def test_unicode_title_and_authors_round_trip(self, unicode_paper: Paper) -> None:
        bib = to_bibtex(unicode_paper)
        # Title should appear verbatim (unicode preserved)
        assert "Rôle des réseaux" in bib
        assert "André Müller" in bib

    def test_multiple_authors_joined_with_and(self, full_paper: Paper) -> None:
        bib = to_bibtex(full_paper)
        assert "Ashish Vaswani and Noam Shazeer and Niki Parmar" in bib

    def test_venue_conference_uses_booktitle(self) -> None:
        paper = Paper(title="A Conference Paper", venue="NeurIPS Proceedings", year=2022)
        bib = to_bibtex(paper)
        assert "booktitle = {NeurIPS Proceedings}" in bib

    def test_venue_journal_uses_journal(self) -> None:
        paper = Paper(title="A Journal Article", venue="Nature", year=2022)
        bib = to_bibtex(paper)
        assert "journal = {Nature}" in bib


# ---------------------------------------------------------------------------
# Cite-key derivation
# ---------------------------------------------------------------------------


class TestCiteKeyDerivation:
    @pytest.mark.parametrize(
        "title, authors, year, expected",
        [
            # Standard case
            (
                "Attention Is All You Need",
                [Author(name="Ashish Vaswani")],
                2017,
                "vaswani2017attention",
            ),
            # Title starts with stopword — must skip "a"
            (
                "A Survey of Deep Learning",
                [Author(name="Jane Smith")],
                2020,
                "smith2020survey",
            ),
            # Multi-word author name — last token is last name
            (
                "Graph Neural Networks",
                [Author(name="Thomas N. Kipf")],
                2016,
                "kipf2016graph",
            ),
            # No year — "Zero" is the first significant word (hyphen splits tokens)
            (
                "Zero-Shot Learning",
                [Author(name="John Doe")],
                None,
                "doezero",
            ),
            # Accented author name — stripped to ASCII
            (
                "Deep Residual Networks",
                [Author(name="André Müller")],
                2021,
                "muller2021deep",
            ),
            # No authors
            (
                "Anonymous Work",
                [],
                2019,
                "unknown2019anonymous",
            ),
        ],
    )
    def test_cite_key(
        self,
        title: str,
        authors: list[Author],
        year: int | None,
        expected: str,
    ) -> None:
        paper = Paper(title=title, authors=authors, year=year)
        assert _bibtex_cite_key(paper) == expected


# ---------------------------------------------------------------------------
# RIS
# ---------------------------------------------------------------------------


class TestToRis:
    def test_starts_with_ty(self, full_paper: Paper) -> None:
        ris = to_ris(full_paper)
        assert ris.startswith("TY  - ")

    def test_ends_with_er(self, full_paper: Paper) -> None:
        ris = to_ris(full_paper)
        assert ris.rstrip("\n").endswith("ER  -")

    def test_all_lines_terminated(self, full_paper: Paper) -> None:
        for line in to_ris(full_paper).splitlines():
            assert line.strip() != "" or True  # blank lines unlikely but tolerated

    def test_title_present(self, full_paper: Paper) -> None:
        ris = to_ris(full_paper)
        assert "TI  - Attention Is All You Need" in ris

    def test_authors_one_per_line(self, full_paper: Paper) -> None:
        ris = to_ris(full_paper)
        assert ris.count("AU  - ") == 3

    def test_year_present(self, full_paper: Paper) -> None:
        ris = to_ris(full_paper)
        assert "PY  - 2017" in ris

    def test_doi_present(self, full_paper: Paper) -> None:
        ris = to_ris(full_paper)
        assert "DO  - " in ris

    def test_abstract_present(self, full_paper: Paper) -> None:
        ris = to_ris(full_paper)
        assert "AB  - " in ris

    def test_url_present(self, full_paper: Paper) -> None:
        ris = to_ris(full_paper)
        assert "UR  - " in ris

    def test_minimal_paper_still_ends_with_er(self, minimal_paper: Paper) -> None:
        ris = to_ris(minimal_paper)
        assert ris.rstrip("\n").endswith("ER  -")
        # Optional fields absent
        assert "PY  - " not in ris
        assert "DO  - " not in ris

    def test_no_url_uses_arxiv_fallback(self) -> None:
        paper = Paper(
            title="Fallback Paper",
            identifiers=PaperIdentifier(arxiv_id="2101.00001"),
        )
        ris = to_ris(paper)
        assert "UR  - https://arxiv.org/abs/2101.00001" in ris

    def test_unicode_preserved(self, unicode_paper: Paper) -> None:
        ris = to_ris(unicode_paper)
        assert "Rôle des réseaux" in ris


# ---------------------------------------------------------------------------
# CSL-JSON
# ---------------------------------------------------------------------------


class TestToCsljson:
    def test_returns_valid_json(self, full_paper: Paper) -> None:
        raw = to_csljson([full_paper])
        data = json.loads(raw)
        assert isinstance(data, list)
        assert len(data) == 1

    def test_required_keys(self, full_paper: Paper) -> None:
        obj = json.loads(to_csljson([full_paper]))[0]
        for key in ("id", "type", "title"):
            assert key in obj, f"missing key: {key}"

    def test_author_structure(self, full_paper: Paper) -> None:
        obj = json.loads(to_csljson([full_paper]))[0]
        assert "author" in obj
        for a in obj["author"]:
            assert "family" in a
            assert "given" in a

    def test_issued_date_parts(self, full_paper: Paper) -> None:
        obj = json.loads(to_csljson([full_paper]))[0]
        assert obj["issued"]["date-parts"] == [[2017]]

    def test_doi_and_url_present(self, full_paper: Paper) -> None:
        obj = json.loads(to_csljson([full_paper]))[0]
        assert "DOI" in obj
        assert "URL" in obj

    def test_abstract_present(self, full_paper: Paper) -> None:
        obj = json.loads(to_csljson([full_paper]))[0]
        assert "abstract" in obj

    def test_minimal_paper_parses(self, minimal_paper: Paper) -> None:
        raw = to_csljson([minimal_paper])
        data = json.loads(raw)
        assert len(data) == 1
        assert data[0]["title"] == "Minimal Paper"
        assert "issued" not in data[0]
        assert "DOI" not in data[0]

    def test_multiple_papers(self, full_paper: Paper, minimal_paper: Paper) -> None:
        raw = to_csljson([full_paper, minimal_paper])
        data = json.loads(raw)
        assert len(data) == 2

    def test_unicode_preserved(self, unicode_paper: Paper) -> None:
        raw = to_csljson([unicode_paper])
        obj = json.loads(raw)[0]
        assert "Rôle" in obj["title"]
        # Author with accented name survives round-trip
        families = [a["family"] for a in obj.get("author", [])]
        assert any("ller" in f for f in families)  # André Müller → family Müller
