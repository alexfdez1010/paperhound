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


@pytest.fixture(autouse=True)
def _stub_rerank(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend the rerank extra is installed and stub the real reranker.

    Reranking is on by default in the CLI; without this fixture every search
    test would either skip rerank (when the extra is missing in the test env)
    or try to download the SentenceTransformer model (when it is). Both states
    drift between machines. Pinning ``is_available=True`` + an identity rerank
    keeps the CLI path deterministic. Tests that exercise the rerank surface
    override these by re-monkeypatching.
    """
    import paperhound.rerank as rerank_mod

    monkeypatch.setattr(rerank_mod, "is_available", lambda: True)
    monkeypatch.setattr(
        rerank_mod, "rerank", lambda query, papers, model_name=None, **kw: list(papers)
    )


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


class FilterCapturingAggregator:
    """Fake aggregator that records the SearchQuery it received."""

    def __init__(self, papers: list[Paper]) -> None:
        self.papers = papers
        self.last_query = None

    def search(self, query) -> list[Paper]:
        self.last_query = query
        return list(self.papers)

    def get(self, _identifier: str) -> Paper | None:
        return None


def test_search_year_single_wires_through(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, fake_paper: Paper
) -> None:
    agg = FilterCapturingAggregator([fake_paper])
    monkeypatch.setattr(cli_module, "_build_aggregator", lambda *a, **kw: agg)
    result = runner.invoke(cli_module.app, ["search", "x", "--year", "2024"])
    assert result.exit_code == 0
    assert agg.last_query is not None
    assert agg.last_query.year_min == 2024
    assert agg.last_query.year_max == 2024


def test_search_year_range_wires_through(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, fake_paper: Paper
) -> None:
    agg = FilterCapturingAggregator([fake_paper])
    monkeypatch.setattr(cli_module, "_build_aggregator", lambda *a, **kw: agg)
    result = runner.invoke(cli_module.app, ["search", "x", "--year", "2023-2026"])
    assert result.exit_code == 0
    assert agg.last_query.year_min == 2023
    assert agg.last_query.year_max == 2026


def test_search_year_open_high_wires_through(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, fake_paper: Paper
) -> None:
    agg = FilterCapturingAggregator([fake_paper])
    monkeypatch.setattr(cli_module, "_build_aggregator", lambda *a, **kw: agg)
    result = runner.invoke(cli_module.app, ["search", "x", "--year", "2023-"])
    assert result.exit_code == 0
    assert agg.last_query.year_min == 2023
    assert agg.last_query.year_max is None


def test_search_min_citations_wires_through(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, fake_paper: Paper
) -> None:
    agg = FilterCapturingAggregator([fake_paper])
    monkeypatch.setattr(cli_module, "_build_aggregator", lambda *a, **kw: agg)
    result = runner.invoke(cli_module.app, ["search", "x", "--min-citations", "100"])
    assert result.exit_code == 0
    assert agg.last_query.filters is not None
    assert agg.last_query.filters.min_citations == 100


def test_search_venue_wires_through(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, fake_paper: Paper
) -> None:
    agg = FilterCapturingAggregator([fake_paper])
    monkeypatch.setattr(cli_module, "_build_aggregator", lambda *a, **kw: agg)
    result = runner.invoke(cli_module.app, ["search", "x", "--venue", "NeurIPS"])
    assert result.exit_code == 0
    assert agg.last_query.filters.venue == "NeurIPS"


def test_search_author_wires_through(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, fake_paper: Paper
) -> None:
    agg = FilterCapturingAggregator([fake_paper])
    monkeypatch.setattr(cli_module, "_build_aggregator", lambda *a, **kw: agg)
    result = runner.invoke(cli_module.app, ["search", "x", "--author", "Hinton"])
    assert result.exit_code == 0
    assert agg.last_query.filters.author == "Hinton"


def test_search_bad_year_exits_nonzero(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a, **_k):
        raise AssertionError("aggregator should not be built for bad year")

    monkeypatch.setattr(cli_module, "_build_aggregator", boom)
    result = runner.invoke(cli_module.app, ["search", "x", "--year", "not-a-year"])
    assert result.exit_code != 0
    out = result.stdout + result.stderr
    assert "year" in out.lower() or "invalid" in out.lower()


def test_search_bad_year_inverted_range_exits_nonzero(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli_module, "_build_aggregator", lambda *a, **kw: FakeAggregator([]))
    result = runner.invoke(cli_module.app, ["search", "x", "--year", "2026-2023"])
    assert result.exit_code != 0


def test_search_no_filters_leaves_filters_none(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, fake_paper: Paper
) -> None:
    """When no filter flags are passed, filters should be None (not an empty struct)."""
    agg = FilterCapturingAggregator([fake_paper])
    monkeypatch.setattr(cli_module, "_build_aggregator", lambda *a, **kw: agg)
    result = runner.invoke(cli_module.app, ["search", "x"])
    assert result.exit_code == 0
    assert agg.last_query.filters is None


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


def test_show_source_flag_passed_to_aggregator(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, fake_paper: Paper
) -> None:
    """``show -s arxiv`` must build the aggregator with only that provider."""
    captured: dict[str, object] = {}

    def fake_build(sources=None, *args, **kwargs):
        captured["sources"] = list(sources) if sources is not None else None
        return FakeAggregator([], lookup=fake_paper)

    monkeypatch.setattr(cli_module, "_build_aggregator", fake_build)
    result = runner.invoke(cli_module.app, ["show", "2401.12345", "-s", "arxiv"])
    assert result.exit_code == 0
    assert captured["sources"] == ["arxiv"]


def test_show_source_flag_rejects_unknown(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, fake_paper: Paper
) -> None:
    monkeypatch.setattr(
        cli_module,
        "_build_aggregator",
        cli_module._build_aggregator,
    )
    result = runner.invoke(cli_module.app, ["show", "2401.12345", "-s", "nope"])
    assert result.exit_code != 0
    assert "Unknown source" in (result.stdout + result.stderr) or "nope" in (
        result.stdout + result.stderr
    )


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
        cli_module,
        "convert_to_markdown",
        lambda src, output=None, options=None: "# fake markdown\n",
    )
    result = runner.invoke(cli_module.app, ["convert", "/tmp/x.pdf"])
    assert result.exit_code == 0
    assert "# fake markdown" in result.stdout


class TestConvertFlags:
    """CLI tests for the new --with-figures, --equations, --tables flags."""

    def _patch_convert(self, monkeypatch: pytest.MonkeyPatch):
        """Patch convert_to_markdown to capture the ConversionOptions passed."""
        captured: dict = {}

        def fake_convert(src, output=None, options=None):
            captured["options"] = options
            if output is not None:
                Path(output).write_text("# md\n", encoding="utf-8")
            return "# md\n"

        monkeypatch.setattr(cli_module, "convert_to_markdown", fake_convert)
        return captured

    def test_all_flags_wire_through(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        captured = self._patch_convert(monkeypatch)
        output = tmp_path / "out.md"
        result = runner.invoke(
            cli_module.app,
            [
                "convert",
                "/tmp/x.pdf",
                "-o",
                str(output),
                "--with-figures",
                "--equations",
                "latex",
                "--tables",
                "html",
            ],
        )
        assert result.exit_code == 0, result.stdout + result.stderr
        opts = captured["options"]
        assert opts is not None
        assert opts.with_figures is True
        assert opts.equations == "latex"
        assert opts.tables == "html"

    def test_defaults_are_backward_compatible(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = self._patch_convert(monkeypatch)
        result = runner.invoke(cli_module.app, ["convert", "/tmp/x.pdf"])
        assert result.exit_code == 0
        opts = captured["options"]
        assert opts is not None
        assert opts.with_figures is False
        assert opts.equations == "inline"
        assert opts.tables == "markdown"

    def test_with_figures_without_output_exits_nonzero(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_convert(monkeypatch)
        result = runner.invoke(cli_module.app, ["convert", "/tmp/x.pdf", "--with-figures"])
        assert result.exit_code != 0
        assert "output" in (result.stdout + result.stderr).lower()

    def test_invalid_equations_value_exits_nonzero(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_convert(monkeypatch)
        result = runner.invoke(cli_module.app, ["convert", "/tmp/x.pdf", "--equations", "mathml"])
        assert result.exit_code != 0

    def test_invalid_tables_value_exits_nonzero(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_convert(monkeypatch)
        result = runner.invoke(cli_module.app, ["convert", "/tmp/x.pdf", "--tables", "csv"])
        assert result.exit_code != 0


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


# ---------------------------------------------------------------------------
# --rerank flag tests
# ---------------------------------------------------------------------------


class TestSearchRerank:
    """CLI tests for the ``search --rerank`` flag."""

    def _patch_aggregator(self, monkeypatch: pytest.MonkeyPatch, papers: list[Paper]) -> None:
        monkeypatch.setattr(cli_module, "_build_aggregator", lambda *a, **k: FakeAggregator(papers))

    def test_rerank_flag_calls_rerank_function(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        fake_paper: Paper,
    ) -> None:
        """When --rerank is passed, paperhound.rerank.rerank should be called."""
        import paperhound.rerank as rerank_mod

        calls: list[dict] = []

        def fake_rerank(query, papers, model_name=None, **kwargs):
            calls.append({"query": query, "n": len(papers), "model_name": model_name})
            return list(papers)

        self._patch_aggregator(monkeypatch, [fake_paper])
        monkeypatch.setattr(rerank_mod, "rerank", fake_rerank)

        result = runner.invoke(cli_module.app, ["search", "transformers", "--rerank"])
        assert result.exit_code == 0, result.output
        assert len(calls) == 1
        assert calls[0]["query"] == "transformers"

    def test_rerank_model_forwarded(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        fake_paper: Paper,
    ) -> None:
        """--rerank-model value should be forwarded to rerank()."""
        import paperhound.rerank as rerank_mod

        calls: list[str | None] = []

        def fake_rerank(query, papers, model_name=None, **kwargs):
            calls.append(model_name)
            return list(papers)

        self._patch_aggregator(monkeypatch, [fake_paper])
        monkeypatch.setattr(rerank_mod, "rerank", fake_rerank)

        result = runner.invoke(
            cli_module.app,
            ["search", "transformers", "--rerank", "--rerank-model", "custom/model"],
        )
        assert result.exit_code == 0, result.output
        assert calls[0] == "custom/model"

    def test_no_rerank_flag_skips_rerank(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        fake_paper: Paper,
    ) -> None:
        """With --no-rerank, the rerank function must not be called."""
        import paperhound.rerank as rerank_mod

        called: list[bool] = []

        def fake_rerank(*a, **k):
            called.append(True)
            return list(a[1])

        self._patch_aggregator(monkeypatch, [fake_paper])
        monkeypatch.setattr(rerank_mod, "rerank", fake_rerank)

        result = runner.invoke(cli_module.app, ["search", "transformers", "--no-rerank"])
        assert result.exit_code == 0
        assert not called

    def test_rerank_runs_by_default(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        fake_paper: Paper,
    ) -> None:
        """No flag = rerank is called (default-on)."""
        import paperhound.rerank as rerank_mod

        called: list[bool] = []

        def fake_rerank(query, papers, model_name=None, **kw):
            called.append(True)
            return list(papers)

        self._patch_aggregator(monkeypatch, [fake_paper])
        monkeypatch.setattr(rerank_mod, "rerank", fake_rerank)

        result = runner.invoke(cli_module.app, ["search", "transformers"])
        assert result.exit_code == 0, result.output
        assert called == [True]

    def test_rerank_missing_dep_exits_nonzero_with_helpful_message(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        fake_paper: Paper,
    ) -> None:
        """When rerank() raises RerankError, the CLI exits != 0 with a clear message."""
        import paperhound.rerank as rerank_mod
        from paperhound.errors import RerankError

        def fake_rerank(*a, **k):
            raise RerankError(
                "sentence-transformers is missing — reinstall paperhound:"
                " pip install --upgrade paperhound"
            )

        self._patch_aggregator(monkeypatch, [fake_paper])
        monkeypatch.setattr(rerank_mod, "rerank", fake_rerank)

        result = runner.invoke(cli_module.app, ["search", "transformers", "--rerank"])
        assert result.exit_code != 0
        combined = result.stdout + result.stderr
        assert "sentence-transformers" in combined

    def test_rerank_wider_candidate_pool(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        fake_paper: Paper,
    ) -> None:
        """With --rerank -n 2, aggregator should be asked for more than 2 papers."""
        import paperhound.rerank as rerank_mod

        aggregator_limits: list[int] = []

        class CapturingAggregator:
            def search(self, query) -> list[Paper]:
                aggregator_limits.append(query.limit)
                return [fake_paper]

            def get(self, _id):
                return None

        monkeypatch.setattr(cli_module, "_build_aggregator", lambda *a, **k: CapturingAggregator())
        monkeypatch.setattr(
            rerank_mod, "rerank", lambda q, papers, model_name=None, **kw: list(papers)
        )

        result = runner.invoke(cli_module.app, ["search", "transformers", "--rerank", "-n", "2"])
        assert result.exit_code == 0, result.output
        assert aggregator_limits[0] > 2, (
            "aggregator should receive a wider limit when --rerank is set"
        )

    def test_rerank_result_truncated_to_limit(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """After reranking, results are sliced to --limit."""
        import paperhound.rerank as rerank_mod

        def _make_numbered_paper(i: int) -> Paper:
            return Paper(
                title=f"Paper {i}",
                abstract="Abstract",
                identifiers=PaperIdentifier(arxiv_id=f"000{i}.00000"),
                sources=["arxiv"],
            )

        papers_list = [_make_numbered_paper(i) for i in range(6)]

        class BigAggregator:
            def search(self, query) -> list[Paper]:
                return papers_list

            def get(self, _id):
                return None

        monkeypatch.setattr(cli_module, "_build_aggregator", lambda *a, **k: BigAggregator())
        monkeypatch.setattr(
            rerank_mod, "rerank", lambda q, papers, model_name=None, **kw: list(papers)
        )

        result = runner.invoke(
            cli_module.app,
            ["search", "transformers", "--rerank", "-n", "3"],
        )
        assert result.exit_code == 0, result.output
        # Table has 3 data rows: check that at most 3 paper titles appear
        # (Paper 0, Paper 1, Paper 2)
        assert "Paper 5" not in result.stdout


def test_providers_table(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("OPENALEX_MAILTO", "CROSSREF_MAILTO", "SEMANTIC_SCHOLAR_API_KEY", "CORE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    result = runner.invoke(cli_module.app, ["providers"])
    assert result.exit_code == 0, result.output
    out = result.stdout
    for name in (
        "arxiv",
        "openalex",
        "dblp",
        "crossref",
        "huggingface",
        "semantic_scholar",
        "core",
    ):
        assert name in out
    # CORE without a key surfaces the env var hint.
    assert "CORE_API_KEY" in out
    # arxiv is in the default list and reports available.
    assert "available" in out
    assert "unavailable" in out  # CORE without a key


def test_providers_json(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("OPENALEX_MAILTO", "CROSSREF_MAILTO", "SEMANTIC_SCHOLAR_API_KEY", "CORE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    result = runner.invoke(cli_module.app, ["providers", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    by_name = {row["name"]: row for row in payload}
    assert set(by_name) == {
        "arxiv",
        "openalex",
        "dblp",
        "crossref",
        "huggingface",
        "semantic_scholar",
        "core",
    }
    assert by_name["arxiv"]["default_enabled"] is True
    assert by_name["arxiv"]["available"] is True
    assert by_name["core"]["available"] is False
    assert by_name["core"]["env_vars"][0]["name"] == "CORE_API_KEY"
    assert by_name["core"]["env_vars"][0]["required"] is True
    assert by_name["core"]["fix"] is not None
