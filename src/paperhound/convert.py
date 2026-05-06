"""Convert PDFs (and other docling-supported formats) to Markdown."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

from paperhound.errors import ConversionError

logger = logging.getLogger(__name__)


class _DoclingConverter(Protocol):
    def convert(self, source: str | Path) -> object: ...


def _build_default_converter() -> _DoclingConverter:
    from docling.document_converter import DocumentConverter  # local import (heavy)

    return DocumentConverter()


def convert_to_markdown(
    source: str | Path,
    output: Path | None = None,
    *,
    converter: _DoclingConverter | None = None,
) -> str:
    """Convert ``source`` to Markdown via docling.

    ``source`` may be a local path or a remote URL (docling handles both).
    If ``output`` is provided, the Markdown is also written to that path.
    """
    return _convert(source, output=output, converter=converter)


def pdf_to_markdown(
    pdf_path: str | Path,
    output: Path | None = None,
    *,
    converter: _DoclingConverter | None = None,
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
    return _convert(path, output=output, converter=converter)


def _convert(
    source: str | Path,
    output: Path | None,
    converter: _DoclingConverter | None,
) -> str:
    converter = converter or _build_default_converter()
    try:
        result = converter.convert(source)
    except Exception as exc:
        raise ConversionError(f"docling failed to convert {source!r}: {exc}") from exc

    document = getattr(result, "document", None)
    if document is None or not hasattr(document, "export_to_markdown"):
        raise ConversionError("docling returned an unexpected result object.")
    markdown = document.export_to_markdown()

    if output is not None:
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(markdown, encoding="utf-8")
        logger.info("Wrote markdown to %s", output)

    return markdown
