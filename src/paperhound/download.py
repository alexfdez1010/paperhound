"""Download paper PDFs given an identifier or URL."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import httpx

from paperhound.errors import DownloadError, IdentifierError
from paperhound.identifiers import IdentifierKind, arxiv_pdf_url, detect

logger = logging.getLogger(__name__)


def _safe_filename(stem: str) -> str:
    keep = "".join(c if c.isalnum() or c in "-._" else "_" for c in stem)
    return keep.strip("._") or "paper"


def resolve_pdf_url(
    identifier: str, *, lookup_pdf_url: Callable[[str], str | None] | None = None
) -> str:
    """Map an identifier (arXiv id, DOI, S2 id, or URL) to a PDF URL.

    For arXiv ids the URL is constructed directly. For DOIs / Semantic Scholar ids
    the caller must pass ``lookup_pdf_url`` — typically ``Aggregator.get`` followed
    by reading ``paper.pdf_url`` — because no deterministic URL exists.
    """
    raw = identifier.strip()
    if raw.lower().startswith(("http://", "https://")):
        return raw
    kind, value = detect(raw)
    if kind is IdentifierKind.ARXIV:
        return arxiv_pdf_url(value)
    if lookup_pdf_url is None:
        raise IdentifierError(
            f"Cannot resolve PDF URL for {kind.value} id {value!r} without a lookup callback."
        )
    url = lookup_pdf_url(raw)
    if not url:
        raise DownloadError(f"No open-access PDF found for {raw!r}.")
    return url


def download_pdf(
    url: str,
    destination: Path,
    *,
    client: httpx.Client | None = None,
    chunk_size: int = 64 * 1024,
    timeout: float = 60.0,
) -> Path:
    """Stream the PDF at ``url`` to ``destination`` and return the final path."""
    destination = Path(destination)
    # Treat extension-less missing paths as directories so `-o ./papers`
    # creates `./papers/<id>.pdf` instead of a binary file literally named
    # `papers`. Paths with a suffix (e.g. `paper.pdf`) keep file semantics.
    if not destination.exists() and not destination.suffix:
        destination.mkdir(parents=True, exist_ok=True)
    if destination.is_dir():
        destination = destination / f"{_safe_filename(Path(url).stem)}.pdf"
    destination.parent.mkdir(parents=True, exist_ok=True)

    own_client = client is None
    http = client or httpx.Client(timeout=timeout, follow_redirects=True)
    try:
        with http.stream("GET", url) as resp:
            if resp.status_code >= 400:
                raise DownloadError(f"Download failed ({resp.status_code}) for {url}")
            with destination.open("wb") as fh:
                for chunk in resp.iter_bytes(chunk_size):
                    fh.write(chunk)
    except httpx.HTTPError as exc:
        raise DownloadError(f"Network error while downloading {url}: {exc}") from exc
    finally:
        if own_client:
            http.close()
    logger.info("Downloaded %s -> %s", url, destination)
    return destination
