# CLAUDE.md — paperhound development process

Authoritative checklist for AI coding assistants working in this repo.

## Golden rule

**Every change ships through tests.** No code lands without a unit test
that would fail before the change and pass after. Live API calls live in
`tests/integration/` only.

## Standard task loop

For any feature, bugfix, or refactor — follow these steps in order:

1. **Read context.** Skim the touched module and its existing tests.
   Reuse types from `paperhound.models` and errors from
   `paperhound.errors`.
2. **Plan.** Write the tasks down with `TaskCreate`. Mark each task
   `in_progress` before you start it and `completed` the moment it lands.
3. **Test first (or alongside).** Add unit tests in `tests/unit/` that
   cover:
   - the happy path
   - every documented edge case
   - one negative path (invalid input → typed error)
   - one regression seed (the exact input that motivated the change, if
     any)
4. **Implement.** Keep modules small and composable. Pure functions
   first; CLI wiring last. Inject HTTP clients (`httpx.Client`) so tests
   never touch the network.
5. **Run the gate.** Locally:

   ```bash
   make check          # ruff check + ruff format --check + pytest unit
   ```

   `make check` is the same gate CI runs. Do not push if it fails.
6. **Update docs.** If user-visible behavior changed, update **all** of:
   - `README.md` (commands table + relevant section)
   - `skills/paperhound/SKILL.md` (commands + agent workflow)
   - the typer `--help` epilog in `src/paperhound/cli.py`
7. **Bump the version.** Patch bumps for bugfixes and additive features
   (new flag/command), minor bumps for breaking CLI changes. Edit
   `pyproject.toml` (`version = ...`); `paperhound.__version__` reads
   package metadata, so the single source of truth is `pyproject.toml`.
8. **Commit.** Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`,
   `chore:`). Author email **must** be
   `alejandrofernandezcamello@gmail.com`. Never add a Claude
   co-author trailer.
9. **Push to `main`.** The `Publish to PyPI` workflow runs on every
   push to `main` and is idempotent on the version field — it skips if
   the version already exists on PyPI. So: bumping the version + pushing
   = publishing.

## Testing standards

Heavy testing is non-negotiable. The bar for a new feature:

- One or more **unit test files** under `tests/unit/test_<feature>.py`.
- Tests are **fast and offline.** Mock HTTP with `respx`. Never depend
  on real network in unit tests.
- **Parametrize** edge cases instead of writing copy-paste tests.
- For string formatters / parsers (BibTeX, identifiers, etc.) cover:
  empty input, missing optional fields, special characters, unicode,
  abnormally long input.
- For CLI commands: use `typer.testing.CliRunner`, monkeypatch the
  dependency surface (the aggregator, downloader, etc.), and assert
  exit code + stdout/stderr.
- Integration tests under `tests/integration/` always hit live APIs;
  add one only if the feature touches a new external surface.

If a regression slips through, write the test that would have caught it
**before** writing the fix.

## Don'ts

- Don't add features that aren't covered by tests in the same commit.
- Don't widen the public surface (`paperhound/__init__.py` re-exports)
  unless the symbol is genuinely user-facing.
- Don't hard-code versions in code; use `paperhound.__version__`.
- Don't bypass `make check` with `--no-verify`. If a hook fails, fix the
  cause.
- Don't commit secrets, API keys, or `.env` files.

## Quick reference

| Need to… | Run |
|---|---|
| Install dev deps | `make install` |
| Run unit tests | `make test` |
| Run live tests | `make test-integration` |
| Lint + format check + unit | `make check` |
| Build sdist+wheel | `make build` |
| Bump + publish | edit `pyproject.toml` version, commit, `git push origin main` |
