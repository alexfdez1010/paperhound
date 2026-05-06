"""Tests for the docling Markdown converter wrapper."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from paperhound.convert import (
    ConversionOptions,
    EquationsMode,
    TablesMode,
    _build_pipeline_opts,
    convert_to_markdown,
    pdf_to_markdown,
)
from paperhound.errors import ConversionError

# ---------------------------------------------------------------------------
# Fake converter helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Backward-compatibility: existing tests still pass with defaults
# ---------------------------------------------------------------------------


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


def test_pdf_to_markdown_converts_local_file(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n% minimal stub\n")
    fake = FakeConverter("# From PDF\n")
    out = tmp_path / "paper.md"

    md = pdf_to_markdown(pdf, output=out, converter=fake)

    assert md == "# From PDF\n"
    assert out.read_text() == "# From PDF\n"
    assert fake.calls == [pdf]


def test_pdf_to_markdown_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConversionError, match="not found"):
        pdf_to_markdown(tmp_path / "nope.pdf", converter=FakeConverter())


def test_pdf_to_markdown_rejects_non_pdf_suffix(tmp_path: Path) -> None:
    txt = tmp_path / "paper.txt"
    txt.write_text("not a pdf")
    with pytest.raises(ConversionError, match=r"\.pdf"):
        pdf_to_markdown(txt, converter=FakeConverter())


# ---------------------------------------------------------------------------
# ConversionOptions dataclass validation
# ---------------------------------------------------------------------------


def test_options_defaults() -> None:
    opts = ConversionOptions()
    assert opts.with_figures is False
    assert opts.equations == "inline"
    assert opts.tables == "markdown"


@pytest.mark.parametrize("equations", ["inline", "latex"])
def test_options_valid_equations(equations: EquationsMode) -> None:
    opts = ConversionOptions(equations=equations)
    assert opts.equations == equations


@pytest.mark.parametrize("tables", ["markdown", "html"])
def test_options_valid_tables(tables: TablesMode) -> None:
    opts = ConversionOptions(tables=tables)
    assert opts.tables == tables


def test_options_invalid_equations_raises() -> None:
    with pytest.raises(ConversionError, match="equations"):
        ConversionOptions(equations="mathml")  # type: ignore[arg-type]


def test_options_invalid_tables_raises() -> None:
    with pytest.raises(ConversionError, match="tables"):
        ConversionOptions(tables="csv")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Pipeline options: verify correct docling settings are wired
# ---------------------------------------------------------------------------


def test_pipeline_opts_with_figures_sets_generate_picture_images() -> None:
    opts = ConversionOptions(with_figures=True)
    pipeline = _build_pipeline_opts(opts)
    assert pipeline.generate_picture_images is True


def test_pipeline_opts_without_figures_default_false() -> None:
    opts = ConversionOptions(with_figures=False)
    pipeline = _build_pipeline_opts(opts)
    assert pipeline.generate_picture_images is False


def test_pipeline_opts_equations_latex_sets_formula_enrichment() -> None:
    opts = ConversionOptions(equations="latex")
    pipeline = _build_pipeline_opts(opts)
    assert pipeline.do_formula_enrichment is True


def test_pipeline_opts_equations_inline_no_formula_enrichment() -> None:
    opts = ConversionOptions(equations="inline")
    pipeline = _build_pipeline_opts(opts)
    assert pipeline.do_formula_enrichment is False


# ---------------------------------------------------------------------------
# with_figures
# ---------------------------------------------------------------------------


def test_with_figures_requires_output() -> None:
    fake = FakeConverter()
    opts = ConversionOptions(with_figures=True)
    with pytest.raises(ConversionError, match="output"):
        convert_to_markdown("paper.pdf", converter=fake, options=opts)


def test_with_figures_calls_save_as_markdown_with_referenced_mode(tmp_path: Path) -> None:
    """When with_figures=True, the document's save_as_markdown is called with REFERENCED mode."""
    from docling_core.types.doc.base import ImageRefMode

    expected_md = "# With Figures\n\n![img](paper_assets/image_000000_abc.png)\n"
    output = tmp_path / "paper.md"

    # Build a fake document that records save_as_markdown calls.
    save_calls: list[dict] = []

    def fake_save_as_markdown(filename, artifacts_dir=None, image_mode=None, **kwargs):
        save_calls.append(
            {"filename": filename, "artifacts_dir": artifacts_dir, "image_mode": image_mode}
        )
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        Path(filename).write_text(expected_md, encoding="utf-8")

    fake_document = SimpleNamespace(
        export_to_markdown=lambda: "# Hello\n",
        save_as_markdown=fake_save_as_markdown,
        iterate_items=lambda: [],
    )

    class FigureConverter:
        def convert(self, _source):
            return SimpleNamespace(document=fake_document)

    opts = ConversionOptions(with_figures=True)
    md = convert_to_markdown("paper.pdf", output=output, converter=FigureConverter(), options=opts)

    assert md == expected_md
    assert len(save_calls) == 1
    assert save_calls[0]["image_mode"] == ImageRefMode.REFERENCED
    assets_dir = save_calls[0]["artifacts_dir"]
    assert assets_dir is not None
    assert "assets" in str(assets_dir)


def test_with_figures_assets_dir_named_after_output_stem(tmp_path: Path) -> None:
    """Assets directory is <output_stem>_assets/ next to the output file."""
    output = tmp_path / "my_paper.md"
    captured: dict = {}

    def fake_save(filename, artifacts_dir=None, image_mode=None, **kwargs):
        captured["artifacts_dir"] = artifacts_dir
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        Path(filename).write_text("# md\n", encoding="utf-8")

    fake_document = SimpleNamespace(
        export_to_markdown=lambda: "# md\n",
        save_as_markdown=fake_save,
    )

    class _Conv:
        def convert(self, _s):
            return SimpleNamespace(document=fake_document)

    opts = ConversionOptions(with_figures=True)
    convert_to_markdown("p.pdf", output=output, converter=_Conv(), options=opts)

    expected_assets = tmp_path / "my_paper_assets"
    assert captured["artifacts_dir"] == expected_assets


# ---------------------------------------------------------------------------
# tables=html post-processing
# ---------------------------------------------------------------------------


def test_tables_html_replaces_gfm_with_html() -> None:
    """tables='html' must replace GFM pipe tables with HTML <table> blocks."""
    gfm_table = "| A | B |\n|---|---|\n| 1 | 2 |\n"
    html_table = "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
    full_markdown = f"# Title\n\n{gfm_table}\n\nSome text.\n"

    from docling_core.types.doc.document import TableItem

    # Fake TableItem that returns known markdown and html.
    fake_table_item = MagicMock(spec=TableItem)
    fake_table_item.export_to_markdown.return_value = gfm_table
    fake_table_item.export_to_html.return_value = html_table

    # Make iterate_items yield (fake_table_item, 0).
    fake_document = SimpleNamespace(
        export_to_markdown=lambda: full_markdown,
        iterate_items=lambda: [(fake_table_item, 0)],
    )

    class _Conv:
        def convert(self, _s):
            return SimpleNamespace(document=fake_document)

    opts = ConversionOptions(tables="html")
    result = convert_to_markdown("x.pdf", converter=_Conv(), options=opts)

    assert html_table in result
    assert gfm_table not in result


def test_tables_markdown_default_unchanged() -> None:
    """tables='markdown' (default) must not alter the output at all."""
    gfm_table = "| A | B |\n|---|---|\n| 1 | 2 |\n"
    full_markdown = f"# Title\n\n{gfm_table}\n"

    fake_document = SimpleNamespace(export_to_markdown=lambda: full_markdown)

    class _Conv:
        def convert(self, _s):
            return SimpleNamespace(document=fake_document)

    result = convert_to_markdown("x.pdf", converter=_Conv())
    assert result == full_markdown


def test_tables_html_non_table_items_skipped() -> None:
    """Non-TableItem items yielded by iterate_items must be ignored gracefully."""
    from docling_core.types.doc.document import TableItem

    gfm_table = "| X | Y |\n|---|---|\n| a | b |\n"
    html_table = "<table><tr><th>X</th><th>Y</th></tr></table>"
    full_markdown = f"# Doc\n\n{gfm_table}\n"

    non_table_item = SimpleNamespace()  # not a TableItem instance

    fake_table_item = MagicMock(spec=TableItem)
    fake_table_item.export_to_markdown.return_value = gfm_table
    fake_table_item.export_to_html.return_value = html_table

    fake_document = SimpleNamespace(
        export_to_markdown=lambda: full_markdown,
        iterate_items=lambda: [(non_table_item, 0), (fake_table_item, 0)],
    )

    class _Conv:
        def convert(self, _s):
            return SimpleNamespace(document=fake_document)

    opts = ConversionOptions(tables="html")
    result = convert_to_markdown("x.pdf", converter=_Conv(), options=opts)

    # Table should still be replaced; non-table item was silently skipped.
    assert html_table in result
    assert gfm_table not in result


# ---------------------------------------------------------------------------
# Conversion error path
# ---------------------------------------------------------------------------


def test_conversion_error_wraps_docling_exception() -> None:
    """Any exception from docling.convert() must be wrapped in ConversionError."""
    fake = FakeConverter(fail=True)
    with pytest.raises(ConversionError, match="docling failed"):
        convert_to_markdown("x.pdf", converter=fake)


def test_conversion_error_on_missing_document_attr() -> None:
    class BadResult:
        pass  # no .document attribute

    class BadConverter:
        def convert(self, _s):
            return BadResult()

    with pytest.raises(ConversionError, match="unexpected result"):
        convert_to_markdown("x.pdf", converter=BadConverter())
