"""Tests for the typer CLI."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from paperhound import cli as cli_module
from paperhound.library import Library
from paperhound.models import Author, Paper, PaperIdentifier


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def fake_paper() -> Paper:
    return Paper(
        title="A Cool Paper",
        authors=[Author(name="Alice"), Author(name="Bob")],
        abstract="An abstract.",
        year=2024,
        venue="ICML",
        identifiers=PaperIdentifier(arxiv_id="2401.12345"),
        sources=["arxiv"],
    )


class FakeAggregator:
    def __init__(self, papers: list[Paper], lookup: Paper | None = None) -> None:
        self.papers = papers
        self.lookup = lookup

    def search(self, _query) -> list[Paper]:
        return list(self.papers)

    def get(self, _identifier: str) -> Paper | None:
        return self.lookup


def test_version(runner: CliRunner) -> None:
    result = runner.invoke(cli_module.app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip()


def test_search_table(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, fake_paper: Paper
) -> None:
    monkeypatch.setattr(
        cli_module, "_build_aggregator", lambda *args, **kwargs: FakeAggregator([fake_paper])
    )
    result = runner.invoke(cli_module.app, ["search", "transformers"])
    assert result.exit_code == 0
    assert "A Cool Paper" in result.stdout


def test_search_json(runner: CliRunner, monkeypatch: pytest.MonkeyPatch, fake_paper: Paper) -> None:
    """search --json emits JSONL: one JSON object per line."""
    monkeypatch.setattr(
        cli_module, "_build_aggregator", lambda *args, **kwargs: FakeAggregator([fake_paper])
    )
    result = runner.invoke(cli_module.app, ["search", "transformers", "--json"])
    assert result.exit_code == 0
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["title"] == "A Cool Paper"


def test_search_json_multiple_papers(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, fake_paper: Paper
) -> None:
    """search --json with multiple results emits one JSON object per line (JSONL)."""
    paper2 = Paper(
        title="Another Paper",
        authors=[Author(name="Carol")],
        year=2023,
        identifiers=PaperIdentifier(arxiv_id="2312.99999"),
        sources=["openalex"],
    )
    monkeypatch.setattr(
        cli_module,
        "_build_aggregator",
        lambda *args, **kwargs: FakeAggregator([fake_paper, paper2]),
    )
    result = runner.invoke(cli_module.app, ["search", "transformers", "--json"])
    assert result.exit_code == 0
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert len(lines) == 2
    assert json.loads(lines[0])["title"] == "A Cool Paper"
    assert json.loads(lines[1])["title"] == "Another Paper"


def test_search_json_empty_results(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    """search --json with no results exits 0 with no JSONL output."""
    monkeypatch.setattr(cli_module, "_build_aggregator", lambda *args, **kwargs: FakeAggregator([]))
    result = runner.invoke(cli_module.app, ["search", "xyz", "--json"])
    assert result.exit_code == 0
    # stdout should be empty (no output for empty results in json mode)
    assert result.stdout.strip() == ""


def test_search_json_roundtrip(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, fake_paper: Paper
) -> None:
    """Each JSONL line round-trips back to a valid Paper model."""
    from paperhound.models import Paper as PaperModel

    monkeypatch.setattr(
        cli_module, "_build_aggregator", lambda *args, **kwargs: FakeAggregator([fake_paper])
    )
    result = runner.invoke(cli_module.app, ["search", "transformers", "--json"])
    assert result.exit_code == 0
    for line in result.stdout.splitlines():
        if line.strip():
            reconstructed = PaperModel.model_validate(json.loads(line))
            assert reconstructed.title == fake_paper.title


def test_search_no_results(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_module, "_build_aggregator", lambda *args, **kwargs: FakeAggregator([]))
    result = runner.invoke(cli_module.app, ["search", "xyz"])
    assert result.exit_code == 0
    assert "No results" in result.stderr


def test_search_rejects_empty_query(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty / whitespace queries must fail before any provider is hit."""

    def boom(*_a, **_k):
        raise AssertionError("aggregator should not be built for an empty query")

    monkeypatch.setattr(cli_module, "_build_aggregator", boom)
    for q in ("", "   ", "\t\n"):
        result = runner.invoke(cli_module.app, ["search", q])
        assert result.exit_code != 0, f"expected non-zero exit for query {q!r}"
        assert "empty" in (result.stdout + result.stderr).lower()


def test_configure_logging_default_silences_libraries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default mode: noisy libs are pinned to CRITICAL and tqdm is disabled."""
    import logging

    monkeypatch.delenv("TQDM_DISABLE", raising=False)
    cli_module._configure_logging(verbose=False)

    assert logging.getLogger().level == logging.ERROR
    for name in cli_module._NOISY_LOGGERS:
        lib = logging.getLogger(name)
        assert lib.level == logging.CRITICAL, name
        assert lib.propagate is False, name
    assert os.environ.get("TQDM_DISABLE") == "1"


def test_configure_logging_verbose_enables_debug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--verbose`` resets noisy loggers to NOTSET so DEBUG records flow."""
    import logging

    monkeypatch.delenv("TQDM_DISABLE", raising=False)
    # Pre-pin one library so we can prove verbose actually unpins it.
    logging.getLogger("docling").setLevel(logging.CRITICAL)

    cli_module._configure_logging(verbose=True)

    assert logging.getLogger().level == logging.DEBUG
    for name in cli_module._NOISY_LOGGERS:
        assert logging.getLogger(name).level == logging.NOTSET, name
    assert os.environ.get("TQDM_DISABLE") is None


def test_root_invokes_configure_logging(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    """The Typer root callback should delegate to ``_configure_logging``."""
    calls: list[bool] = []
    monkeypatch.setattr(cli_module, "_configure_logging", lambda verbose: calls.append(verbose))

    runner.invoke(cli_module.app, ["version"])
    runner.invoke(cli_module.app, ["--verbose", "version"])
    runner.invoke(cli_module.app, ["-v", "version"])

    assert calls == [False, True, True]


def test_library_log_emitted_under_default_is_filtered(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, fake_paper: Paper
) -> None:
    """Real-world regression: a docling-style INFO log must not reach stderr."""
    import logging

    def search_with_log(_query):
        logging.getLogger("docling.document_converter").info("Going to convert document...")
        logging.getLogger("httpx").info("HTTP Request: GET /v1/papers")
        return [fake_paper]

    fake = FakeAggregator([fake_paper])
    fake.search = search_with_log  # type: ignore[assignment]
    monkeypatch.setattr(cli_module, "_build_aggregator", lambda *a, **k: fake)

    result = runner.invoke(cli_module.app, ["search", "transformers"])
    assert result.exit_code == 0
    assert "Going to convert" not in result.stderr
    assert "HTTP Request" not in result.stderr


def test_show_prints_abstract(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, fake_paper: Paper
) -> None:
    monkeypatch.setattr(
        cli_module,
        "_build_aggregator",
        lambda *args, **kwargs: FakeAggregator([], lookup=fake_paper),
    )
    result = runner.invoke(cli_module.app, ["show", "2401.12345"])
    assert result.exit_code == 0
    assert "Abstract" in result.stdout
    assert "An abstract." in result.stdout


def test_show_not_found(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli_module, "_build_aggregator", lambda *args, **kwargs: FakeAggregator([], lookup=None)
    )
    result = runner.invoke(cli_module.app, ["show", "2401.12345"])
    assert result.exit_code == 1


def test_show_json(runner: CliRunner, monkeypatch: pytest.MonkeyPatch, fake_paper: Paper) -> None:
    """show --json emits a single compact JSON object on one line."""
    monkeypatch.setattr(
        cli_module,
        "_build_aggregator",
        lambda *args, **kwargs: FakeAggregator([], lookup=fake_paper),
    )
    result = runner.invoke(cli_module.app, ["show", "2401.12345", "--json"])
    assert result.exit_code == 0
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1, "show --json should emit exactly one line"
    obj = json.loads(lines[0])
    assert obj["title"] == "A Cool Paper"
    assert obj["year"] == 2024


def test_show_json_roundtrip(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, fake_paper: Paper
) -> None:
    """show --json output round-trips back to a valid Paper model."""
    from paperhound.models import Paper as PaperModel

    monkeypatch.setattr(
        cli_module,
        "_build_aggregator",
        lambda *args, **kwargs: FakeAggregator([], lookup=fake_paper),
    )
    result = runner.invoke(cli_module.app, ["show", "2401.12345", "--json"])
    assert result.exit_code == 0
    reconstructed = PaperModel.model_validate(json.loads(result.stdout.strip()))
    assert reconstructed.title == fake_paper.title
    assert reconstructed.identifiers.arxiv_id == "2401.12345"


def test_show_json_and_format_mutually_exclusive(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, fake_paper: Paper
) -> None:
    """Passing both --json and --format on show must exit non-zero with a clear error."""
    monkeypatch.setattr(
        cli_module,
        "_build_aggregator",
        lambda *args, **kwargs: FakeAggregator([], lookup=fake_paper),
    )
    for fmt in ("bibtex", "ris", "csljson"):
        result = runner.invoke(cli_module.app, ["show", "2401.12345", "--json", "--format", fmt])
        assert result.exit_code != 0, f"expected non-zero exit for --json --format {fmt}"
        msg = (result.stdout + result.stderr).lower()
        assert "mutually exclusive" in msg or "json" in msg


class TestShowFormat:
    """CLI tests for ``paperhound show --format``."""

    def _patch(self, monkeypatch: pytest.MonkeyPatch, paper: Paper) -> None:
        monkeypatch.setattr(
            cli_module,
            "_build_aggregator",
            lambda *args, **kwargs: FakeAggregator([], lookup=paper),
        )

    def test_format_bibtex_exits_zero_and_contains_at(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch, fake_paper: Paper
    ) -> None:
        self._patch(monkeypatch, fake_paper)
        result = runner.invoke(cli_module.app, ["show", "2401.12345", "--format", "bibtex"])
        assert result.exit_code == 0, result.output
        assert "@" in result.stdout

    def test_format_ris_contains_ty_and_er(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch, fake_paper: Paper
    ) -> None:
        self._patch(monkeypatch, fake_paper)
        result = runner.invoke(cli_module.app, ["show", "2401.12345", "--format", "ris"])
        assert result.exit_code == 0, result.output
        assert "TY  - " in result.stdout
        assert "ER  -" in result.stdout

    def test_format_csljson_parses_as_json(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch, fake_paper: Paper
    ) -> None:
        self._patch(monkeypatch, fake_paper)
        result = runner.invoke(cli_module.app, ["show", "2401.12345", "--format", "csljson"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        assert len(data) == 1

    def test_format_markdown_is_default(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch, fake_paper: Paper
    ) -> None:
        self._patch(monkeypatch, fake_paper)
        result = runner.invoke(cli_module.app, ["show", "2401.12345"])
        assert result.exit_code == 0
        assert "Abstract" in result.stdout

    def test_invalid_format_exits_nonzero(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch, fake_paper: Paper
    ) -> None:
        self._patch(monkeypatch, fake_paper)
        result = runner.invoke(cli_module.app, ["show", "2401.12345", "--format", "endnote"])
        assert result.exit_code != 0
        msg = (result.stdout + result.stderr).lower()
        assert "invalid" in msg or "format" in msg or "choose" in msg


def test_download_invokes_helpers(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict = {}

    def fake_resolve(identifier: str, *, lookup_pdf_url=None) -> str:
        captured["identifier"] = identifier
        return "https://example.org/x.pdf"

    def fake_download(url: str, dest: Path, **_) -> Path:
        captured["url"] = url
        target = dest if dest.suffix else dest / "x.pdf"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"%PDF")
        return target

    monkeypatch.setattr(cli_module, "resolve_pdf_url", fake_resolve)
    monkeypatch.setattr(cli_module, "download_pdf", fake_download)

    result = runner.invoke(
        cli_module.app, ["download", "2401.12345", "-o", str(tmp_path / "out.pdf")]
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert captured["identifier"] == "2401.12345"
    assert (tmp_path / "out.pdf").exists()


def test_convert_writes_to_stdout(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli_module, "convert_to_markdown", lambda src, output=None: "# fake markdown\n"
    )
    result = runner.invoke(cli_module.app, ["convert", "/tmp/x.pdf"])
    assert result.exit_code == 0
    assert "# fake markdown" in result.stdout


def test_get_pipeline_writes_markdown(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    md_path = tmp_path / "out.md"

    def fake_resolve(identifier: str, *, lookup_pdf_url=None) -> str:
        return "https://example.org/x.pdf"

    def fake_download(url: str, dest: Path, **_) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"%PDF")
        return dest

    def fake_convert(source, output=None):
        if output is not None:
            Path(output).write_text("# md\n")
        return "# md\n"

    monkeypatch.setattr(cli_module, "resolve_pdf_url", fake_resolve)
    monkeypatch.setattr(cli_module, "download_pdf", fake_download)
    monkeypatch.setattr(cli_module, "convert_to_markdown", fake_convert)

    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli_module.app, ["get", "2401.12345", "-o", str(md_path)])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert md_path.read_text() == "# md\n"
    # PDF removed by default
    assert not (tmp_path / "2401.12345.pdf").exists()


# ---------------------------------------------------------------------------
# Library command tests
# ---------------------------------------------------------------------------


def _make_library(tmp_path: Path) -> Library:
    """Helper: create an isolated Library for testing."""
    return Library(path=tmp_path)


def _patch_library(monkeypatch: pytest.MonkeyPatch, lib: Library) -> None:
    """Patch _open_library in the CLI module to return a pre-built Library."""
    monkeypatch.setattr(cli_module, "_open_library", lambda: lib)


class TestLibraryAdd:
    def test_add_happy_path(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        fake_paper: Paper,
        tmp_path: Path,
    ) -> None:
        lib = _make_library(tmp_path)
        _patch_library(monkeypatch, lib)
        monkeypatch.setattr(
            cli_module,
            "_build_aggregator",
            lambda *a, **k: FakeAggregator([], lookup=fake_paper),
        )

        result = runner.invoke(cli_module.app, ["add", "2401.12345"])
        assert result.exit_code == 0, result.stdout + result.stderr
        assert "Added" in result.stdout

        entries = lib.list()
        assert len(entries) == 1
        assert entries[0].title == "A Cool Paper"

    def test_add_not_found(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        lib = _make_library(tmp_path)
        _patch_library(monkeypatch, lib)
        monkeypatch.setattr(
            cli_module,
            "_build_aggregator",
            lambda *a, **k: FakeAggregator([], lookup=None),
        )

        result = runner.invoke(cli_module.app, ["add", "2401.12345"])
        assert result.exit_code == 1

    def test_add_with_convert(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        fake_paper: Paper,
        tmp_path: Path,
    ) -> None:
        lib = _make_library(tmp_path)
        _patch_library(monkeypatch, lib)
        monkeypatch.setattr(
            cli_module,
            "_build_aggregator",
            lambda *a, **k: FakeAggregator([], lookup=fake_paper),
        )

        def fake_resolve(identifier: str, *, lookup_pdf_url=None) -> str:
            return "https://example.org/paper.pdf"

        def fake_download(url: str, dest: Path, **_) -> Path:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"%PDF")
            return dest

        def fake_convert(source, output=None):
            if output is not None:
                Path(output).write_text("# Paper\n\nSome content.\n")
            return "# Paper\n\nSome content.\n"

        monkeypatch.setattr(cli_module, "resolve_pdf_url", fake_resolve)
        monkeypatch.setattr(cli_module, "download_pdf", fake_download)
        monkeypatch.setattr(cli_module, "convert_to_markdown", fake_convert)

        result = runner.invoke(cli_module.app, ["add", "2401.12345", "--convert"])
        assert result.exit_code == 0, result.stdout + result.stderr
        assert "Added" in result.stdout
        assert "Markdown" in result.stdout

        entries = lib.list()
        assert len(entries) == 1
        assert entries[0].markdown_path is not None

    def test_add_idempotent(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        fake_paper: Paper,
        tmp_path: Path,
    ) -> None:
        lib = _make_library(tmp_path)
        _patch_library(monkeypatch, lib)
        monkeypatch.setattr(
            cli_module,
            "_build_aggregator",
            lambda *a, **k: FakeAggregator([], lookup=fake_paper),
        )

        runner.invoke(cli_module.app, ["add", "2401.12345"])
        runner.invoke(cli_module.app, ["add", "2401.12345"])
        assert len(lib.list()) == 1, "Duplicate add must not create two rows"


class TestLibraryList:
    def test_list_empty(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        lib = _make_library(tmp_path)
        _patch_library(monkeypatch, lib)

        result = runner.invoke(cli_module.app, ["list"])
        assert result.exit_code == 0
        assert "empty" in result.stdout.lower()

    def test_list_shows_entries(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        fake_paper: Paper,
        tmp_path: Path,
    ) -> None:
        lib = _make_library(tmp_path)
        lib.add(fake_paper)
        _patch_library(monkeypatch, lib)

        result = runner.invoke(cli_module.app, ["list"])
        assert result.exit_code == 0
        assert "A Cool Paper" in result.stdout


class TestLibraryGrep:
    def test_grep_hit(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        fake_paper: Paper,
        tmp_path: Path,
    ) -> None:
        lib = _make_library(tmp_path)
        lib.add(fake_paper)
        _patch_library(monkeypatch, lib)

        result = runner.invoke(cli_module.app, ["grep", "abstract"])
        assert result.exit_code == 0
        assert "2401.12345" in result.stdout

    def test_grep_no_hits(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        lib = _make_library(tmp_path)
        _patch_library(monkeypatch, lib)

        result = runner.invoke(cli_module.app, ["grep", "quantum entanglement"])
        assert result.exit_code == 0
        assert "No hits" in result.stdout

    def test_grep_empty_query(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        lib = _make_library(tmp_path)
        _patch_library(monkeypatch, lib)

        result = runner.invoke(cli_module.app, ["grep", "   "])
        assert result.exit_code != 0

    def test_grep_fts_special_chars(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        fake_paper: Paper,
        tmp_path: Path,
    ) -> None:
        """FTS5 special characters in query must not crash the command."""
        lib = _make_library(tmp_path)
        lib.add(fake_paper)
        _patch_library(monkeypatch, lib)

        result = runner.invoke(cli_module.app, ["grep", "title:abstract*"])
        assert result.exit_code == 0


class TestLibraryRm:
    def test_rm_existing(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        fake_paper: Paper,
        tmp_path: Path,
    ) -> None:
        lib = _make_library(tmp_path)
        lib.add(fake_paper)
        _patch_library(monkeypatch, lib)

        result = runner.invoke(cli_module.app, ["rm", "--yes", "2401.12345"])
        assert result.exit_code == 0, result.stdout + result.stderr
        assert "Removed" in result.stdout
        assert lib.list() == []

    def test_rm_not_found(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        lib = _make_library(tmp_path)
        _patch_library(monkeypatch, lib)

        result = runner.invoke(cli_module.app, ["rm", "--yes", "does-not-exist"])
        assert result.exit_code == 1

    def test_rm_deletes_markdown_file(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        fake_paper: Paper,
        tmp_path: Path,
    ) -> None:
        lib = _make_library(tmp_path)
        md_file = tmp_path / "paper.md"
        md_file.write_text("# Paper")
        lib.add(fake_paper, markdown_path=md_file)
        lib.update_markdown("2401.12345", md_file)
        _patch_library(monkeypatch, lib)

        result = runner.invoke(cli_module.app, ["rm", "--yes", "2401.12345"])
        assert result.exit_code == 0
        assert not md_file.exists(), "Markdown file should be deleted on rm"


# ---------------------------------------------------------------------------
# Citation graph commands: refs and cited-by
# ---------------------------------------------------------------------------


class TestCitationCommands:
    """CLI tests for 'refs' and 'cited-by' commands."""

    def _patch_fetch(
        self,
        monkeypatch: pytest.MonkeyPatch,
        papers: list[Paper],
        error: Exception | None = None,
    ) -> None:
        """Monkeypatch both fetch_references and fetch_citations in cli module."""
        import paperhound.citations as cit_module

        def fake_fetch(*args, **kwargs) -> list[Paper]:
            if error is not None:
                raise error
            return papers

        monkeypatch.setattr(cit_module, "fetch_references", fake_fetch)
        monkeypatch.setattr(cit_module, "fetch_citations", fake_fetch)

    def test_refs_table_output(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        fake_paper: Paper,
    ) -> None:
        """refs command prints a Rich table with paper titles."""
        import paperhound.citations as cit_module

        monkeypatch.setattr(cit_module, "fetch_references", lambda *a, **k: [fake_paper])
        result = runner.invoke(cli_module.app, ["refs", "1706.03762"])
        assert result.exit_code == 0, result.output
        assert "A Cool Paper" in result.output

    def test_refs_json_output(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        fake_paper: Paper,
    ) -> None:
        """refs --json emits valid JSON list."""
        import paperhound.citations as cit_module

        monkeypatch.setattr(cit_module, "fetch_references", lambda *a, **k: [fake_paper])
        result = runner.invoke(cli_module.app, ["refs", "1706.03762", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data[0]["title"] == "A Cool Paper"

    def test_cited_by_table_output(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        fake_paper: Paper,
    ) -> None:
        """cited-by command prints a Rich table."""
        import paperhound.citations as cit_module

        monkeypatch.setattr(cit_module, "fetch_citations", lambda *a, **k: [fake_paper])
        result = runner.invoke(cli_module.app, ["cited-by", "1706.03762"])
        assert result.exit_code == 0, result.output
        assert "A Cool Paper" in result.output

    def test_cited_by_json_output(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        fake_paper: Paper,
    ) -> None:
        """cited-by --json emits valid JSON list."""
        import paperhound.citations as cit_module

        monkeypatch.setattr(cit_module, "fetch_citations", lambda *a, **k: [fake_paper])
        result = runner.invoke(cli_module.app, ["cited-by", "1706.03762", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)

    def test_refs_no_results(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Empty result set prints a 'No results' message."""
        import paperhound.citations as cit_module

        monkeypatch.setattr(cit_module, "fetch_references", lambda *a, **k: [])
        result = runner.invoke(cli_module.app, ["refs", "1706.03762"])
        assert result.exit_code == 0
        assert "No results" in result.stderr

    def test_cited_by_no_results(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import paperhound.citations as cit_module

        monkeypatch.setattr(cit_module, "fetch_citations", lambda *a, **k: [])
        result = runner.invoke(cli_module.app, ["cited-by", "1706.03762"])
        assert result.exit_code == 0
        assert "No results" in result.stderr

    def test_refs_invalid_source(
        self,
        runner: CliRunner,
    ) -> None:
        """Unknown --source should exit with error."""
        result = runner.invoke(cli_module.app, ["refs", "1706.03762", "--source", "bogus"])
        assert result.exit_code != 0

    def test_refs_source_semantic_scholar(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        fake_paper: Paper,
    ) -> None:
        """--source semantic_scholar (alias s2) is accepted."""
        import paperhound.citations as cit_module

        calls: list[dict] = []

        def capture(*args, **kwargs) -> list[Paper]:
            calls.append(kwargs)
            return [fake_paper]

        monkeypatch.setattr(cit_module, "fetch_references", capture)
        result = runner.invoke(
            cli_module.app, ["refs", "1706.03762", "--source", "semantic_scholar"]
        )
        assert result.exit_code == 0, result.output
        assert calls[0].get("source") == "semantic_scholar"

    def test_refs_source_openalex(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        fake_paper: Paper,
    ) -> None:
        """--source openalex is accepted."""
        import paperhound.citations as cit_module

        calls: list[dict] = []

        def capture(*args, **kwargs) -> list[Paper]:
            calls.append(kwargs)
            return [fake_paper]

        monkeypatch.setattr(cit_module, "fetch_references", capture)
        result = runner.invoke(cli_module.app, ["refs", "1706.03762", "--source", "openalex"])
        assert result.exit_code == 0, result.output
        assert calls[0].get("source") == "openalex"

    def test_refs_depth_and_limit_passed_through(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        fake_paper: Paper,
    ) -> None:
        """depth and limit options are forwarded to fetch_references."""
        import paperhound.citations as cit_module

        calls: list[dict] = []

        def capture(*args, **kwargs) -> list[Paper]:
            calls.append({"depth": kwargs.get("depth"), "limit": kwargs.get("limit")})
            return [fake_paper]

        monkeypatch.setattr(cit_module, "fetch_references", capture)
        result = runner.invoke(
            cli_module.app, ["refs", "1706.03762", "--depth", "2", "--limit", "7"]
        )
        assert result.exit_code == 0, result.output
        assert calls[0]["depth"] == 2
        assert calls[0]["limit"] == 7

    def test_refs_provider_error_exits_nonzero(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """ProviderError from fetch_references must cause non-zero exit."""
        import paperhound.citations as cit_module
        from paperhound.errors import ProviderError

        monkeypatch.setattr(
            cit_module,
            "fetch_references",
            lambda *a, **k: (_ for _ in ()).throw(ProviderError("boom")),
        )
        result = runner.invoke(cli_module.app, ["refs", "1706.03762"])
        assert result.exit_code != 0
