"""Tests for the rich-based output helpers."""

from __future__ import annotations

import io
import json

from rich.console import Console

from paperhound.models import Author, Paper, PaperIdentifier
from paperhound.output import papers_to_json, render_paper_detail, render_table


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
    assert "Transformers." in out


def test_papers_to_json_roundtrip() -> None:
    payload = papers_to_json([make_paper()])
    parsed = json.loads(payload)
    assert parsed[0]["title"] == "Attention Is All You Need"
    assert parsed[0]["identifiers"]["arxiv_id"] == "1706.03762"
