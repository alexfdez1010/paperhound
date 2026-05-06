"""Unit tests for paperhound.mcp_server — all offline, no network, no mcp dep."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from paperhound import cli as cli_module
from paperhound.errors import PaperhoundError
from paperhound.library import Library
from paperhound.mcp_server import (
    _paper_to_dict,
    handle_convert,
    handle_download,
    handle_library_add,
    handle_library_grep,
    handle_library_list,
    handle_search,
    handle_show,
)
from paperhound.models import Author, Paper, PaperIdentifier

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_paper() -> Paper:
    return Paper(
        title="Attention Is All You Need",
        authors=[Author(name="Vaswani"), Author(name="Shazeer")],
        abstract="We propose the Transformer, a novel architecture based solely on attention.",
        year=2017,
        venue="NeurIPS",
        url="https://arxiv.org/abs/1706.03762",
        pdf_url="https://arxiv.org/pdf/1706.03762",
        citation_count=100000,
        identifiers=PaperIdentifier(arxiv_id="1706.03762", doi="10.5555/3295222.3295349"),
        sources=["arxiv"],
    )


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class FakeAggregator:
    def __init__(self, papers: list[Paper], lookup: Paper | None = None) -> None:
        self.papers = papers
        self.lookup = lookup

    def search(self, _query) -> list[Paper]:
        return list(self.papers)

    def get(self, _identifier: str) -> Paper | None:
        return self.lookup


# ---------------------------------------------------------------------------
# _paper_to_dict
# ---------------------------------------------------------------------------


def test_paper_to_dict_structure(fake_paper: Paper) -> None:
    d = _paper_to_dict(fake_paper)
    assert d["title"] == "Attention Is All You Need"
    assert d["year"] == 2017
    assert d["authors"][0]["name"] == "Vaswani"
    assert d["identifiers"]["arxiv_id"] == "1706.03762"
    assert d["sources"] == ["arxiv"]


def test_paper_to_dict_optional_none() -> None:
    minimal = Paper(title="Minimal Paper", sources=["dblp"])
    d = _paper_to_dict(minimal)
    assert d["abstract"] is None
    assert d["year"] is None
    assert d["identifiers"]["arxiv_id"] is None


# ---------------------------------------------------------------------------
# handle_search
# ---------------------------------------------------------------------------


def test_handle_search_happy_path(fake_paper: Paper) -> None:
    agg = FakeAggregator([fake_paper])
    results = handle_search("attention", _aggregator=agg)
    assert len(results) == 1
    assert results[0]["title"] == "Attention Is All You Need"


def test_handle_search_empty_results(fake_paper: Paper) -> None:
    agg = FakeAggregator([])
    results = handle_search("nothing", _aggregator=agg)
    assert results == []


def test_handle_search_empty_query_raises(fake_paper: Paper) -> None:
    agg = FakeAggregator([fake_paper])
    with pytest.raises(ValueError, match="empty"):
        handle_search("   ", _aggregator=agg)


def test_handle_search_whitespace_query_raises() -> None:
    agg = FakeAggregator([])
    with pytest.raises(ValueError, match="empty"):
        handle_search("\t\n", _aggregator=agg)


def test_handle_search_with_limit(fake_paper: Paper) -> None:
    agg = FakeAggregator([fake_paper, fake_paper])
    results = handle_search("attention", limit=5, _aggregator=agg)
    # Both returned by fake aggregator (it ignores limit) — just check no error
    assert isinstance(results, list)


def test_handle_search_provider_error_raises(fake_paper: Paper) -> None:
    class ErrorAggregator:
        def search(self, _q):
            raise PaperhoundError("provider down")

        def get(self, _id):
            return None

    with pytest.raises(RuntimeError, match="provider down"):
        handle_search("query", _aggregator=ErrorAggregator())


# ---------------------------------------------------------------------------
# handle_show
# ---------------------------------------------------------------------------


def test_handle_show_happy_path(fake_paper: Paper) -> None:
    agg = FakeAggregator([], lookup=fake_paper)
    result = handle_show("1706.03762", _aggregator=agg)
    assert result["title"] == "Attention Is All You Need"
    assert result["abstract"] is not None


def test_handle_show_not_found_raises() -> None:
    agg = FakeAggregator([], lookup=None)
    with pytest.raises(ValueError, match="not found"):
        handle_show("9999.99999", _aggregator=agg)


def test_handle_show_provider_error_raises() -> None:
    class ErrorAggregator:
        def get(self, _id):
            raise PaperhoundError("timeout")

        def search(self, _q):
            return []

    with pytest.raises(RuntimeError, match="timeout"):
        handle_show("bad-id", _aggregator=ErrorAggregator())


# ---------------------------------------------------------------------------
# handle_download
# ---------------------------------------------------------------------------


def test_handle_download_happy_path(fake_paper: Paper, tmp_path: Path) -> None:
    agg = FakeAggregator([], lookup=fake_paper)

    def fake_resolve(identifier, *, lookup_pdf_url=None):
        return "https://arxiv.org/pdf/1706.03762"

    def fake_download(url, dest):
        target = dest if dest.suffix else dest / "1706.03762.pdf"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"%PDF")
        return target

    result = handle_download(
        "1706.03762",
        dest=str(tmp_path),
        _aggregator=agg,
        _resolve_fn=fake_resolve,
        _download_fn=fake_download,
    )
    assert "path" in result
    assert result["path"].endswith(".pdf")


def test_handle_download_error_raises(fake_paper: Paper, tmp_path: Path) -> None:
    agg = FakeAggregator([], lookup=fake_paper)

    def bad_resolve(identifier, *, lookup_pdf_url=None):
        from paperhound.errors import DownloadError

        raise DownloadError("no PDF available")

    with pytest.raises(RuntimeError, match="no PDF"):
        handle_download(
            "1706.03762",
            dest=str(tmp_path),
            _aggregator=agg,
            _resolve_fn=bad_resolve,
        )


# ---------------------------------------------------------------------------
# handle_convert
# ---------------------------------------------------------------------------


def test_handle_convert_returns_markdown() -> None:
    def fake_convert(src, output=None):
        return "# Paper\n\nContent."

    result = handle_convert("/tmp/x.pdf", _convert_fn=fake_convert)
    assert result["markdown"] == "# Paper\n\nContent."


def test_handle_convert_with_dest(tmp_path: Path) -> None:
    dest = tmp_path / "out.md"

    def fake_convert(src, output=None):
        if output:
            Path(output).write_text("# Paper")
        return "# Paper"

    result = handle_convert("/tmp/x.pdf", dest=str(dest), _convert_fn=fake_convert)
    assert result["path"] == str(dest)


def test_handle_convert_error_raises() -> None:
    from paperhound.errors import ConversionError

    def bad_convert(src, output=None):
        raise ConversionError("bad file")

    with pytest.raises(RuntimeError, match="bad file"):
        handle_convert("/tmp/x.pdf", _convert_fn=bad_convert)


# ---------------------------------------------------------------------------
# handle_library_add
# ---------------------------------------------------------------------------


def test_handle_library_add_happy_path(fake_paper: Paper, tmp_path: Path) -> None:
    agg = FakeAggregator([], lookup=fake_paper)
    result = handle_library_add("1706.03762", _aggregator=agg, _library_path=tmp_path)
    assert result["title"] == "Attention Is All You Need"
    assert result["library_id"] == "1706.03762"

    # Verify it's actually in the library
    lib = Library(path=tmp_path)
    entries = lib.list()
    assert len(entries) == 1
    assert entries[0].id == "1706.03762"


def test_handle_library_add_not_found_raises(tmp_path: Path) -> None:
    agg = FakeAggregator([], lookup=None)
    with pytest.raises(ValueError, match="not found"):
        handle_library_add("9999.99999", _aggregator=agg, _library_path=tmp_path)


def test_handle_library_add_idempotent(fake_paper: Paper, tmp_path: Path) -> None:
    agg = FakeAggregator([], lookup=fake_paper)
    handle_library_add("1706.03762", _aggregator=agg, _library_path=tmp_path)
    handle_library_add("1706.03762", _aggregator=agg, _library_path=tmp_path)

    lib = Library(path=tmp_path)
    assert len(lib.list()) == 1


def test_handle_library_add_with_convert(fake_paper: Paper, tmp_path: Path) -> None:
    agg = FakeAggregator([], lookup=fake_paper)

    def fake_resolve(identifier, *, lookup_pdf_url=None):
        return "https://arxiv.org/pdf/1706.03762"

    def fake_download(url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"%PDF")
        return dest

    def fake_convert(src, output=None):
        if output:
            Path(output).write_text("# Attention Is All You Need\n\nContent.")
        return "# Attention Is All You Need\n\nContent."

    result = handle_library_add(
        "1706.03762",
        convert=True,
        _aggregator=agg,
        _library_path=tmp_path,
        _resolve_fn=fake_resolve,
        _download_fn=fake_download,
        _convert_fn=fake_convert,
    )
    assert "markdown_path" in result

    lib = Library(path=tmp_path)
    entries = lib.list()
    assert len(entries) == 1
    assert entries[0].markdown_path is not None


# ---------------------------------------------------------------------------
# handle_library_list
# ---------------------------------------------------------------------------


def test_handle_library_list_empty(tmp_path: Path) -> None:
    result = handle_library_list(_library_path=tmp_path)
    assert result == []


def test_handle_library_list_with_entries(fake_paper: Paper, tmp_path: Path) -> None:
    lib = Library(path=tmp_path)
    lib.add(fake_paper)

    result = handle_library_list(_library_path=tmp_path)
    assert len(result) == 1
    assert result[0]["title"] == "Attention Is All You Need"
    assert result[0]["id"] == "1706.03762"
    assert "added_at" in result[0]


def test_handle_library_list_multiple(tmp_path: Path) -> None:
    lib = Library(path=tmp_path)
    p1 = Paper(
        title="Paper One",
        identifiers=PaperIdentifier(arxiv_id="0001.00001"),
        sources=["arxiv"],
    )
    p2 = Paper(
        title="Paper Two",
        identifiers=PaperIdentifier(arxiv_id="0002.00002"),
        sources=["arxiv"],
    )
    lib.add(p1)
    lib.add(p2)

    result = handle_library_list(_library_path=tmp_path)
    assert len(result) == 2
    titles = [r["title"] for r in result]
    assert "Paper One" in titles
    assert "Paper Two" in titles


# ---------------------------------------------------------------------------
# handle_library_grep
# ---------------------------------------------------------------------------


def test_handle_library_grep_hit(fake_paper: Paper, tmp_path: Path) -> None:
    lib = Library(path=tmp_path)
    lib.add(fake_paper)

    results = handle_library_grep("attention", _library_path=tmp_path)
    assert len(results) >= 1
    assert results[0]["id"] == "1706.03762"
    assert "snippet" in results[0]
    assert "rank" in results[0]


def test_handle_library_grep_no_hits(tmp_path: Path) -> None:
    Library(path=tmp_path)  # initialize the DB
    results = handle_library_grep("quantum entanglement", _library_path=tmp_path)
    assert results == []


def test_handle_library_grep_empty_query_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="empty"):
        handle_library_grep("   ", _library_path=tmp_path)


@pytest.mark.parametrize(
    "bad_query",
    ["title:foo*", '"quoted"', "NOT something", "term^2"],
)
def test_handle_library_grep_special_chars_no_error(
    fake_paper: Paper, tmp_path: Path, bad_query: str
) -> None:
    lib = Library(path=tmp_path)
    lib.add(fake_paper)
    # Should not raise
    results = handle_library_grep(bad_query, _library_path=tmp_path)
    assert isinstance(results, list)


# ---------------------------------------------------------------------------
# CLI: mcp subcommand registration
# ---------------------------------------------------------------------------


def test_mcp_subcommand_in_help(runner: CliRunner) -> None:
    result = runner.invoke(cli_module.app, ["--help"])
    assert result.exit_code == 0
    assert "mcp" in result.stdout


def test_mcp_command_help(runner: CliRunner) -> None:
    result = runner.invoke(cli_module.app, ["mcp", "--help"])
    assert result.exit_code == 0
    assert "MCP" in result.stdout or "mcp" in result.stdout.lower()


def test_mcp_missing_dep_exits_with_message(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the mcp package is not installed, the command exits non-zero with a helpful message."""
    import builtins

    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "mcp" or name.startswith("mcp."):
            raise ImportError("No module named 'mcp'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)

    result = runner.invoke(cli_module.app, ["mcp"])
    assert result.exit_code != 0
    combined = result.stdout + (result.stderr or "")
    assert "paperhound[mcp]" in combined or "MCP support not installed" in combined
