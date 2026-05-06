"""Tests for the rich-based output helpers."""

from __future__ import annotations

import io
import json

import pytest
from rich.console import Console

from paperhound.models import Author, Paper, PaperIdentifier
from paperhound.output import (
    paper_to_json_line,
    papers_to_json,
    papers_to_jsonl,
    render_paper_detail,
    render_table,
)


def make_paper() -> Paper:
    return Paper(
        title="Attention Is All You Need",
        authors=[Author(name="Ashish Vaswani"), Author(name="Noam Shazeer")],
        abstract="Transformers.",
        year=2017,
        venue="NeurIPS",
        identifiers=PaperIdentifier(arxiv_id="1706.03762", doi="10.1/x"),
        sources=["arxiv", "semantic_scholar"],
    )


def _capture(fn) -> str:
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, color_system=None, width=200)
    fn(console)
    return buf.getvalue()


def test_render_table_includes_title_and_id() -> None:
    out = _capture(lambda c: render_table([make_paper()], c))
    assert "Attention Is All You Need" in out
    assert "1706.03762" in out


def test_render_paper_detail_has_abstract_and_ids() -> None:
    out = _capture(lambda c: render_paper_detail(make_paper(), c))
    assert "Attention Is All You Need" in out
    assert "Ashish Vaswani" in out
    assert "1706.03762" in out
    assert "Abstract" in out
    assert "Transformers." in out


def test_render_paper_detail_skips_abstract_header_when_empty() -> None:
    paper = make_paper().model_copy(update={"abstract": None})
    out = _capture(lambda c: render_paper_detail(paper, c))
    assert "Abstract" not in out


def test_papers_to_json_roundtrip() -> None:
    payload = papers_to_json([make_paper()])
    parsed = json.loads(payload)
    assert parsed[0]["title"] == "Attention Is All You Need"
    assert parsed[0]["identifiers"]["arxiv_id"] == "1706.03762"


# ---------------------------------------------------------------------------
# JSONL helpers
# ---------------------------------------------------------------------------


def test_paper_to_json_line_is_parseable() -> None:
    line = paper_to_json_line(make_paper())
    obj = json.loads(line)
    assert obj["title"] == "Attention Is All You Need"
    assert obj["identifiers"]["arxiv_id"] == "1706.03762"


def test_paper_to_json_line_is_single_line() -> None:
    """The result must contain no newlines (compact, not pretty-printed)."""
    line = paper_to_json_line(make_paper())
    assert "\n" not in line


def test_paper_to_json_line_roundtrip() -> None:
    """Parsed line round-trips back to an equivalent Paper model."""
    paper = make_paper()
    reconstructed = Paper.model_validate(json.loads(paper_to_json_line(paper)))
    assert reconstructed.title == paper.title
    assert reconstructed.year == paper.year
    assert reconstructed.identifiers.arxiv_id == paper.identifiers.arxiv_id


def test_paper_to_json_line_unicode() -> None:
    """Non-ASCII characters must be preserved (ensure_ascii=False)."""
    paper = Paper(
        title="Ünïcödé tïtle",
        authors=[Author(name="François Müller")],
        year=2024,
        sources=[],
    )
    line = paper_to_json_line(paper)
    # Verify the character is not escaped
    assert "Ünïcödé" in line
    assert "François" in line


def test_paper_to_json_line_optional_fields_null() -> None:
    """Optional fields absent from the model appear as null in JSON."""
    paper = Paper(title="Minimal", sources=[])
    obj = json.loads(paper_to_json_line(paper))
    assert obj["abstract"] is None
    assert obj["year"] is None
    assert obj["venue"] is None


def test_papers_to_jsonl_empty() -> None:
    """Empty iterable yields an empty string."""
    assert papers_to_jsonl([]) == ""


def test_papers_to_jsonl_single() -> None:
    """Single paper yields exactly one JSON line."""
    result = papers_to_jsonl([make_paper()])
    lines = result.splitlines()
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["title"] == "Attention Is All You Need"


def test_papers_to_jsonl_multiple() -> None:
    """Multiple papers yield one line per paper, each individually parseable."""
    paper1 = make_paper()
    paper2 = Paper(
        title="BERT: Pre-training",
        authors=[Author(name="Jacob Devlin")],
        year=2018,
        sources=["arxiv"],
    )
    result = papers_to_jsonl([paper1, paper2])
    lines = result.splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["title"] == "Attention Is All You Need"
    assert json.loads(lines[1])["title"] == "BERT: Pre-training"


@pytest.mark.parametrize(
    "title,expected",
    [
        ("", ""),
        ("A" * 500, "A" * 500),
        ("Special: <>&\"'", "Special: <>&\"'"),
        ("Unicode: 中文 العربية Ελληνικά", "Unicode: 中文 العربية Ελληνικά"),
        # Embedded newlines are normalized at the model layer (provider feeds
        # often wrap long titles); the JSON line must reflect that.
        ("Newline\nin\ntitle", "Newline in title"),
    ],
)
def test_paper_to_json_line_edge_case_titles(title: str, expected: str) -> None:
    """Edge-case titles must serialise and round-trip without error."""
    paper = Paper(title=title, sources=[])
    line = paper_to_json_line(paper)
    assert "\n" not in line  # still a single line
    assert json.loads(line)["title"] == expected
