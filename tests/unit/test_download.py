"""Tests for download helpers."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from paperhound.download import download_pdf, resolve_pdf_url
from paperhound.errors import DownloadError, IdentifierError


def test_resolve_pdf_url_for_arxiv_id() -> None:
    assert resolve_pdf_url("2401.12345") == "https://arxiv.org/pdf/2401.12345.pdf"


def test_resolve_pdf_url_for_https_url_passthrough() -> None:
    url = "https://example.org/paper.pdf"
    assert resolve_pdf_url(url) == url


def test_resolve_pdf_url_for_doi_requires_lookup() -> None:
    with pytest.raises(IdentifierError):
        resolve_pdf_url("10.1234/foo.bar")


def test_resolve_pdf_url_uses_lookup_callback() -> None:
    url = resolve_pdf_url(
        "10.1234/foo.bar",
        lookup_pdf_url=lambda _id: "https://example.org/paper.pdf",
    )
    assert url == "https://example.org/paper.pdf"


def test_resolve_pdf_url_raises_when_lookup_returns_none() -> None:
    with pytest.raises(DownloadError):
        resolve_pdf_url("10.1234/foo.bar", lookup_pdf_url=lambda _id: None)


@respx.mock
def test_download_pdf_streams_to_file(tmp_path: Path) -> None:
    respx.get("https://arxiv.org/pdf/2401.12345.pdf").mock(
        return_value=httpx.Response(200, content=b"%PDF-1.4 ...")
    )
    target = tmp_path / "paper.pdf"
    result = download_pdf("https://arxiv.org/pdf/2401.12345.pdf", target)
    assert result == target
    assert target.read_bytes().startswith(b"%PDF")


@respx.mock
def test_download_pdf_chooses_filename_when_directory(tmp_path: Path) -> None:
    respx.get("https://arxiv.org/pdf/2401.12345.pdf").mock(
        return_value=httpx.Response(200, content=b"%PDF")
    )
    result = download_pdf("https://arxiv.org/pdf/2401.12345.pdf", tmp_path)
    assert result.parent == tmp_path
    assert result.suffix == ".pdf"


@respx.mock
def test_download_pdf_raises_on_http_error(tmp_path: Path) -> None:
    respx.get("https://arxiv.org/pdf/missing.pdf").mock(return_value=httpx.Response(404))
    with pytest.raises(DownloadError):
        download_pdf("https://arxiv.org/pdf/missing.pdf", tmp_path / "x.pdf")
