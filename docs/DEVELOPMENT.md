# 🛠️ Development

## Setup

```bash
make install            # uv sync --extra dev
```

## Test & lint

```bash
make test               # unit tests (network-free, respx-mocked)
make test-integration   # live API tests — always live, no env-var gate
make test-all           # unit + integration
make check              # lint + format check + unit tests (run before pushing)
```

Unit tests use `respx` to mock HTTP, so they never touch the network.
Integration tests under `tests/integration/` always hit the real provider
APIs (arXiv, OpenAlex, DBLP, Crossref, Hugging Face Papers, Semantic
Scholar) — no env-var gate, no mocks. The `SemanticScholarProvider`
retries 429s with exponential backoff; export
`SEMANTIC_SCHOLAR_API_KEY` only if you want faster runs.

See [`docs/TESTING.md`](TESTING.md) for the standardized post-publish
smoke procedure.

## Releasing to PyPI

1. Bump `version` in `pyproject.toml`.
2. Push to `main`. The `Publish to PyPI` workflow builds and publishes
   via [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/) —
   idempotent on the version field, so re-pushing the same version is a
   no-op.

## Contribution workflow

The authoritative checklist for AI coding assistants and contributors
lives in [`CLAUDE.md`](../CLAUDE.md). Highlights:

- Every change ships through tests. No code lands without a unit test
  that would fail before the change and pass after.
- Live API calls live in `tests/integration/` only.
- Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`).
- Patch bumps for bugfixes and additive features, minor bumps for
  breaking CLI changes.
