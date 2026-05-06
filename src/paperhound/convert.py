"""Convert PDFs (and other docling-supported formats) to Markdown."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from paperhound.errors import ConversionError

logger = logging.getLogger(__name__)

# Valid literal values for the conversion options.
EquationsMode = Literal["inline", "latex"]
TablesMode = Literal["markdown", "html"]


@dataclass
class ConversionOptions:
    """Options controlling how a document is converted to Markdown.

    ``with_figures``:
        Extract embedded images alongside the Markdown. When *True* the caller
        must also pass ``output`` to :func:`convert_to_markdown` (or
        :func:`pdf_to_markdown`) so that the assets directory can be placed next
        to the output file.  Images are saved to
        ``<output_basename>_assets/imageNNNNNN_<hash>.png`` and referenced via
        standard Markdown image syntax in the output.

        Requires docling ``PdfPipelineOptions.generate_picture_images=True``.

    ``equations``:
        ``"inline"`` (default) — use docling's default inline representation.
        ``"latex"``  — enable formula enrichment (``do_formula_enrichment=True``)
        so that mathematical expressions are preserved as LaTeX ``$...$`` /
        ``$$...$$`` in the output.

    ``tables``:
        ``"markdown"`` (default) — GFM pipe tables.
        ``"html"``     — embed ``<table>`` blocks instead of GFM syntax.  This
        uses :meth:`docling_core.types.doc.document.TableItem.export_to_html`
        on each table item and splices the result into the Markdown string.
    """

    with_figures: bool = False
    equations: EquationsMode = "inline"
    tables: TablesMode = "markdown"

    def __post_init__(self) -> None:
        if self.equations not in ("inline", "latex"):
            raise ConversionError(
                f"Invalid equations mode {self.equations!r}. Choose 'inline' or 'latex'."
            )
        if self.tables not in ("markdown", "html"):
            raise ConversionError(
                f"Invalid tables mode {self.tables!r}. Choose 'markdown' or 'html'."
            )


_DEFAULT_OPTIONS = ConversionOptions()


class _DoclingConverter(Protocol):
    def convert(self, source: str | Path) -> object: ...


def _build_pipeline_opts(options: ConversionOptions):
    """Create a PdfPipelineOptions configured from *options*.

    Separated so unit tests can call it directly and inspect the result without
    needing a real DocumentConverter.
    """
    from docling.datamodel.pipeline_options import PdfPipelineOptions  # noqa: PLC0415

    pipeline_opts = PdfPipelineOptions()

    # Figure extraction — generate per-picture PNG images during pipeline run.
    if options.with_figures:
        pipeline_opts.generate_picture_images = True

    # Equation mode — enable the formula-enrichment VLM when latex is requested.
    if options.equations == "latex":
        pipeline_opts.do_formula_enrichment = True

    return pipeline_opts


def _build_default_converter(options: ConversionOptions) -> _DoclingConverter:
    from docling.document_converter import (  # noqa: PLC0415
        DocumentConverter,
        PdfFormatOption,
    )

    pipeline_opts = _build_pipeline_opts(options)

    return DocumentConverter(
        format_options={
            "pdf": PdfFormatOption(pipeline_options=pipeline_opts),
        }
    )


def convert_to_markdown(
    source: str | Path,
    output: Path | None = None,
    *,
    converter: _DoclingConverter | None = None,
    options: ConversionOptions | None = None,
) -> str:
    """Convert ``source`` to Markdown via docling.

    ``source`` may be a local path or a remote URL (docling handles both).
    If ``output`` is provided, the Markdown is also written to that path.
    Pass a :class:`ConversionOptions` to enable figure extraction, LaTeX
    equations, or HTML table output.
    """
    return _convert(source, output=output, converter=converter, options=options)


def pdf_to_markdown(
    pdf_path: str | Path,
    output: Path | None = None,
    *,
    converter: _DoclingConverter | None = None,
    options: ConversionOptions | None = None,
) -> str:
    """Convert a local PDF file to Markdown via docling.

    Stricter than :func:`convert_to_markdown`: requires an existing local file
    with a ``.pdf`` suffix. Use :func:`convert_to_markdown` for URLs or other
    docling-supported formats.
    """
    path = Path(pdf_path)
    if not path.exists():
        raise ConversionError(f"PDF not found: {path}")
    if not path.is_file():
        raise ConversionError(f"Not a file: {path}")
    if path.suffix.lower() != ".pdf":
        raise ConversionError(f"Expected a .pdf file, got: {path.name}")
    return _convert(path, output=output, converter=converter, options=options)


def _convert(
    source: str | Path,
    output: Path | None,
    converter: _DoclingConverter | None,
    options: ConversionOptions | None,
) -> str:
    opts = options or _DEFAULT_OPTIONS

    # Validate options eagerly (raises ConversionError on bad values).
    # Re-creating the dataclass would validate __post_init__; but since the
    # caller may have built it manually, we just call __post_init__ here.
    opts.__post_init__()

    if opts.with_figures and output is None:
        raise ConversionError(
            "--with-figures requires an output path so that the assets directory"
            " can be placed alongside the Markdown file."
        )

    converter = converter or _build_default_converter(opts)
    try:
        result = converter.convert(source)
    except Exception as exc:
        raise ConversionError(f"docling failed to convert {source!r}: {exc}") from exc

    document = getattr(result, "document", None)
    if document is None or not hasattr(document, "export_to_markdown"):
        raise ConversionError("docling returned an unexpected result object.")

    # --- figure extraction ---
    if opts.with_figures and output is not None:
        output = Path(output)
        assets_dir = output.parent / f"{output.stem}_assets"
        return _export_with_figures(document, output, assets_dir)

    # --- plain markdown export ---
    markdown = document.export_to_markdown()

    # --- HTML tables post-processing ---
    if opts.tables == "html":
        markdown = _replace_tables_with_html(document, markdown)

    if output is not None:
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(markdown, encoding="utf-8")
        logger.info("Wrote markdown to %s", output)

    return markdown


def _export_with_figures(document: object, output: Path, assets_dir: Path) -> str:
    """Save the document as Markdown with referenced figure images.

    Uses :meth:`DoclingDocument.save_as_markdown` with
    ``image_mode=ImageRefMode.REFERENCED`` so that picture data is written to
    *assets_dir* and the Markdown contains proper ``![...](...)`` references.
    """
    try:
        from docling_core.types.doc.base import ImageRefMode

        output.parent.mkdir(parents=True, exist_ok=True)
        document.save_as_markdown(  # type: ignore[union-attr]
            filename=output,
            artifacts_dir=assets_dir,
            image_mode=ImageRefMode.REFERENCED,
        )
        markdown = output.read_text(encoding="utf-8")
        logger.info("Wrote markdown (with figures) to %s", output)
        logger.info("Figure assets written to %s", assets_dir)
        return markdown
    except Exception as exc:
        raise ConversionError(f"Failed to export document with figures: {exc}") from exc


def _replace_tables_with_html(document: object, markdown: str) -> str:
    """Replace GFM table blocks in *markdown* with HTML <table> exports.

    Iterates the document's items looking for TableItem instances, generates the
    HTML representation of each table, and splices it into the Markdown string
    in place of the corresponding GFM pipe-table block.

    If a table's GFM form cannot be found in the Markdown (e.g. the table was
    rendered differently), the original Markdown is left unchanged for that
    table (best-effort, no crash).
    """
    try:
        from docling_core.types.doc.document import TableItem
    except ImportError:
        # Old docling_core without TableItem — skip silently.
        return markdown

    result = markdown
    try:
        for item, _level in document.iterate_items():  # type: ignore[union-attr]
            if not isinstance(item, TableItem):
                continue
            try:
                md_table = item.export_to_markdown(doc=document)  # type: ignore[arg-type]
                html_table = item.export_to_html(doc=document)  # type: ignore[arg-type]
            except Exception:
                continue  # best-effort: skip tables that fail to export

            if md_table and html_table and md_table in result:
                result = result.replace(md_table, html_table, 1)
    except Exception:
        # If document iteration fails for any reason, return unchanged markdown.
        pass

    return result
