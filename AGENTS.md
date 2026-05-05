# Agent guide for paperhound

Guidance for AI coding assistants working in this repository.

## What this project is

`paperhound` is a Python CLI (built with [typer](https://typer.tiangolo.com/) +
[rich](https://rich.readthedocs.io/)) for searching, downloading, and converting
academic papers. Search backends fan out in parallel:

- `paperhound.search.arxiv_provider.ArxivProvider` — wraps the `arxiv` package.
- `paperhound.search.semantic_scholar.SemanticScholarProvider` — talks to the
  Semantic Scholar Graph API over `httpx`.
- `paperhound.search.aggregator.SearchAggregator` — runs all providers
  concurrently and deduplicates by arXiv id → DOI → Semantic Scholar id →
  normalized title.

PDF → Markdown conversion goes through `paperhound.convert.convert_to_markdown`,
which is a thin wrapper around [docling](https://github.com/docling-project/docling).

## Repository layout

```
src/paperhound/
  __init__.py         # public re-exports
  __main__.py         # `python -m paperhound`
  cli.py              # typer app (entry point: `paperhound`)
  models.py           # Paper / Author / PaperIdentifier (pydantic)
  identifiers.py      # detect()/normalize_arxiv() and friends
  errors.py           # PaperhoundError hierarchy
  download.py         # resolve_pdf_url() + streaming download_pdf()
  convert.py          # docling wrapper
  output.py           # rich tables + JSON serialization
  search/
    base.py           # SearchProvider / SearchQuery
    arxiv_provider.py
    semantic_scholar.py
    aggregator.py

tests/unit/           # fast, network-free; HTTP mocked with respx
tests/integration/    # live API tests; always hit real arXiv / S2
skills/paperhound/    # SKILL.md for agents driving the CLI
.github/workflows/    # ci.yml + publish.yml (PyPI trusted publishing)
```

## Tooling

- **Package manager**: `uv` (`uv sync --extra dev`)
- **Test runner**: `pytest` — see `Makefile` for shortcuts
- **Lint/format**: `ruff` (line length 100, target `py310`)
- **Build backend**: `hatchling`
- **HTTP mocking**: `respx`

Common tasks: `make install`, `make test`, `make check`, `make build`.

## Conventions

1. **Provider-agnostic models.** All search results are normalized to
   `paperhound.models.Paper`. Add new providers by subclassing `SearchProvider`
   and emitting `Paper` objects.
2. **Errors raise `PaperhoundError` subclasses.** The CLI catches them and exits
   non-zero with a friendly message. Don't leak provider exceptions to users.
3. **Inject HTTP clients.** Every provider/downloader accepts an optional
   `httpx.Client` so tests can mock cleanly. New code should follow suit.
4. **Keep heavy deps lazy.** `docling` is imported inside
   `convert._build_default_converter` so importing the CLI is fast and tests
   that don't need docling don't pay for it.
5. **Integration tests are real.** `tests/unit/*` mocks HTTP with `respx`.
   `tests/integration/*` always hits the live arXiv / Semantic Scholar APIs —
   no env-var gate, no mocks. S2 endpoints are reachable anonymously; the
   provider retries 429s automatically.
6. **English only** in code, comments, docstrings, and tests.

## When adding features

- New CLI command? Add it in `cli.py`, return non-zero on failure via
  `_exit_on_error`, and write a unit test in `tests/unit/test_cli.py` that
  patches the dependency surface.
- New provider? Implement `SearchProvider`, add it to the aggregator factory in
  `cli._build_aggregator`, and write provider-level unit tests with `respx`.
- New identifier format? Extend `identifiers.detect()` and add parametrized
  tests to `tests/unit/test_identifiers.py`.

## Releasing

`Publish to PyPI` is wired to tag pushes (`v*`). Bump the version in
`pyproject.toml` and `paperhound/__init__.py`, tag, push. PyPI Trusted
Publishing handles the upload — no token in the repo.
