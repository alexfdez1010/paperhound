"""Tests for identifier parsing."""

from __future__ import annotations

import pytest

from paperhound.errors import IdentifierError
from paperhound.identifiers import (
    IdentifierKind,
    arxiv_pdf_url,
    detect,
    normalize_arxiv,
    to_semantic_scholar_lookup,
)


class TestDetect:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("2401.12345", "2401.12345"),
            ("2401.12345v3", "2401.12345"),
            ("arxiv:2401.12345", "2401.12345"),
            ("ArXiv:2401.12345v2", "2401.12345"),
            ("https://arxiv.org/abs/2401.12345", "2401.12345"),
            ("https://arxiv.org/pdf/2401.12345v2.pdf", "2401.12345"),
            ("cs.AI/0301001", "cs.AI/0301001"),
            ("hep-th/9901001", "hep-th/9901001"),
        ],
    )
    def test_arxiv(self, value: str, expected: str) -> None:
        kind, parsed = detect(value)
        assert kind is IdentifierKind.ARXIV
        assert parsed == expected

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("10.1234/foo.bar", "10.1234/foo.bar"),
            ("doi:10.1234/foo.bar", "10.1234/foo.bar"),
            ("https://doi.org/10.1038/s41586-020-2649-2", "10.1038/s41586-020-2649-2"),
        ],
    )
    def test_doi(self, value: str, expected: str) -> None:
        kind, parsed = detect(value)
        assert kind is IdentifierKind.DOI
        assert parsed == expected

    def test_s2_paper_id(self) -> None:
        s2_id = "0" * 40
        kind, parsed = detect(s2_id)
        assert kind is IdentifierKind.SEMANTIC_SCHOLAR
        assert parsed == s2_id

    def test_s2_url(self) -> None:
        s2_id = "a" * 40
        kind, parsed = detect(f"https://www.semanticscholar.org/paper/Title/{s2_id}")
        assert kind is IdentifierKind.SEMANTIC_SCHOLAR
        assert parsed == s2_id

    @pytest.mark.parametrize("value", ["", "not-a-real-id", "12345"])
    def test_invalid(self, value: str) -> None:
        with pytest.raises(IdentifierError):
            detect(value)


class TestNormalizeArxiv:
    def test_strips_version(self) -> None:
        assert normalize_arxiv("2401.12345v9") == "2401.12345"

    def test_keeps_old_format(self) -> None:
        assert normalize_arxiv("hep-th/9901001v2") == "hep-th/9901001"


def test_to_semantic_scholar_lookup() -> None:
    assert to_semantic_scholar_lookup(IdentifierKind.ARXIV, "2401.12345") == "ARXIV:2401.12345"
    assert to_semantic_scholar_lookup(IdentifierKind.DOI, "10.1/x") == "DOI:10.1/x"
    s2 = "f" * 40
    assert to_semantic_scholar_lookup(IdentifierKind.SEMANTIC_SCHOLAR, s2) == s2


def test_arxiv_pdf_url() -> None:
    assert arxiv_pdf_url("2401.12345") == "https://arxiv.org/pdf/2401.12345.pdf"
    assert arxiv_pdf_url("2401.12345", "v2") == "https://arxiv.org/pdf/2401.12345v2.pdf"
