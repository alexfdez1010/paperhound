"""Tests for the docling Markdown converter wrapper."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from paperhound.convert import convert_to_markdown
from paperhound.errors import ConversionError


class FakeConverter:
    def __init__(self, markdown: str = "# Hello\n", *, fail: bool = False) -> None:
        self._markdown = markdown
        self._fail = fail
        self.calls: list[object] = []

    def convert(self, source):
        self.calls.append(source)
        if self._fail:
            raise RuntimeError("docling boom")
        document = SimpleNamespace(export_to_markdown=lambda: self._markdown)
        return SimpleNamespace(document=document)


def test_convert_returns_markdown() -> None:
    fake = FakeConverter()
    md = convert_to_markdown("paper.pdf", converter=fake)
    assert md == "# Hello\n"
    assert fake.calls == ["paper.pdf"]


def test_convert_writes_output(tmp_path: Path) -> None:
    fake = FakeConverter("# Title\n")
    out = tmp_path / "deep" / "paper.md"
    md = convert_to_markdown("paper.pdf", output=out, converter=fake)
    assert md == "# Title\n"
    assert out.read_text() == "# Title\n"


def test_convert_wraps_docling_errors() -> None:
    fake = FakeConverter(fail=True)
    with pytest.raises(ConversionError):
        convert_to_markdown("paper.pdf", converter=fake)


def test_convert_rejects_unexpected_result_object() -> None:
    class WeirdConverter:
        def convert(self, _source):
            return SimpleNamespace(document=None)

    with pytest.raises(ConversionError):
        convert_to_markdown("paper.pdf", converter=WeirdConverter())
