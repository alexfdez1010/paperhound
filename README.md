# paperhound

> **paperhound** — sniff out academic papers from the command line.

A small, fast CLI for AI/ML researchers who want a single tool to **search**,
**inspect**, **download**, and **convert to Markdown** papers from many academic
sources at once. Conversion is powered by
[docling](https://github.com/docling-project/docling), so the resulting Markdown
is good enough to feed straight into an LLM context.

## Features

- 🔎 **Unified search** — one query, many backends. arXiv, OpenAlex, DBLP,
  Crossref and Hugging Face Papers (and optionally Semantic Scholar / CORE) are
  queried in parallel with a 10-second budget. Results are merged round-robin
  (one from each provider, then the next, …) so a fast provider can't
  monopolize the top-N — and deduplicated by arXiv id / DOI / title. Slow
  providers are dropped silently — the CLI returns whatever came back in time.
- 📄 **Inspect before downloading** — `paperhound show <id>` prints the
  abstract and metadata so you can decide if it's worth a download.
- ⬇️ **Download by identifier** — arXiv id, DOI, Semantic Scholar paper id, or
  any paper URL. Open-access PDFs are resolved automatically.
- 📝 **PDF → Markdown via docling** — `paperhound convert paper.pdf` or
  `paperhound get <id>` for the full pipeline.
- 📚 **Local library** — `paperhound add <id>` stores metadata in a
  SQLite FTS5 database at `~/.paperhound/library/`. `paperhound list` shows
  all saved papers; `paperhound grep <query>` does offline full-text search
  over titles, abstracts, and stored Markdown bodies; `paperhound rm <id>`
  removes an entry.
- 🔌 **MCP server** — `paperhound mcp` exposes all tools over stdio so
  Claude Code and other MCP-compatible agents can call paperhound directly
  without a skill shim. Install the optional extra: `pip install 'paperhound[mcp]'`.
- 🤖 **Agent-ready** — ships with a `SKILL.md` and JSON output mode so any
  Claude / OpenAI / local agent can drive the CLI.
- 🧪 **Heavily tested** — every module has unit tests; live integration tests
  are gated behind an environment variable.

## Installation

```bash
pip install paperhound
```

or with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install paperhound
```

Python 3.10+ is required. Docling pulls in PyTorch on first run, so the very
first conversion may take a moment to download model weights.

## Quick start

```bash
# Search across all providers
paperhound search "diffusion transformers" --limit 5

# Show the abstract for a specific paper
paperhound show 2401.12345
paperhound show 10.1038/s41586-020-2649-2          # DOI works too
paperhound show https://arxiv.org/abs/1706.03762   # ...and URLs

# Download the PDF
paperhound download 1706.03762 -o ./papers/

# Convert a local PDF to Markdown
paperhound convert ./papers/1706.03762.pdf -o attention.md

# Or do it all at once: search-resolve, download, convert, clean up
paperhound get 1706.03762 -o attention.md
```

### JSON output for scripts and agents

```bash
paperhound search "graph neural networks" --json | jq '.[].title'
paperhound show 1706.03762 --json
```

## Commands

| Command | Description |
|---|---|
| `paperhound search <query>` | Run a unified search. `--limit`, `--source arxiv\|openalex\|dblp\|crossref\|huggingface\|semantic_scholar\|core` (repeatable), `--year-min`, `--year-max`, `--timeout`, `--json`. |
| `paperhound show <id>` | Fetch a paper's metadata + abstract. |
| `paperhound download <id> -o <path>` | Download a paper PDF. |
| `paperhound convert <pdf> -o <md>` | Convert a PDF (or any docling-supported file/URL) to Markdown. |
| `paperhound get <id> -o <md>` | Download + convert in one step. `--keep-pdf` to keep the PDF. |
| `paperhound add <id>` | Fetch metadata and add to local library. `--convert` also stores Markdown. |
| `paperhound list` | List all papers in the local library. |
| `paperhound grep <query>` | Full-text search the local library (title + abstract + Markdown body). |
| `paperhound rm <id>` | Remove a paper from the local library (and its Markdown file, if any). |
| `paperhound mcp` | Start an MCP server over stdio exposing all tools. Requires `pip install 'paperhound[mcp]'`. |
| `paperhound version` | Print the installed version. |

Run `paperhound <command> --help` for full options.

## Local library

paperhound keeps a persistent per-user library at `~/.paperhound/library/`
(override with `PAPERHOUND_LIBRARY_DIR`).  The library is backed by a SQLite
FTS5 database — no extra dependencies required.

```bash
# Add a paper (metadata only)
paperhound add 1706.03762

# Add and also save the Markdown version of the PDF
paperhound add 1706.03762 --convert

# List all saved papers
paperhound list

# Full-text search offline
paperhound grep "attention mechanism"

# Remove a paper (and its Markdown file, if any)
paperhound rm 1706.03762
```

Re-adding a paper is idempotent — it updates the metadata in place.
The schema is versioned; on a version mismatch paperhound reports a clear error
rather than silently operating on a stale schema.

## MCP server

`paperhound mcp` starts an MCP (Model Context Protocol) server over stdio,
exposing paperhound as callable tools to Claude Code and any other
MCP-compatible agent.

### Installation

```bash
pip install 'paperhound[mcp]'
```

### Tools exposed

| Tool | Description |
|---|---|
| `search(query, limit, sources)` | Search papers across providers; returns list of paper records. |
| `show(identifier)` | Fetch metadata + abstract for a single paper. |
| `download(identifier, dest)` | Download a paper PDF; returns the path. |
| `convert(identifier, dest)` | Convert a PDF/URL to Markdown; returns path or inline Markdown. |
| `library_add(identifier, convert)` | Add a paper to the local library (optionally with Markdown). |
| `library_list()` | List all papers in the local library. |
| `library_grep(query, limit)` | Full-text search the local library; returns records with snippets. |

### Wiring into Claude Code

Add the following to your Claude Code `settings.json`
(`~/.claude/settings.json` or the project-level `.claude/settings.json`):

```json
{
  "mcpServers": {
    "paperhound": {
      "command": "paperhound",
      "args": ["mcp"]
    }
  }
}
```

Or, if `paperhound` is installed in a virtual environment:

```json
{
  "mcpServers": {
    "paperhound": {
      "command": "/path/to/venv/bin/paperhound",
      "args": ["mcp"]
    }
  }
}
```

After saving, restart Claude Code. The `paperhound` tools will appear in the
available tool list and Claude can call them directly — no skill shim needed.

## Identifier formats

paperhound accepts whatever you have on hand:

- arXiv ids: `2401.12345`, `2401.12345v3`, `cs.AI/0301001`, `arXiv:2401.12345`
- DOIs: `10.1038/s41586-020-2649-2`, `doi:10.1038/...`
- Semantic Scholar paper ids: 40-char hex
- URLs: `arxiv.org/abs/...`, `arxiv.org/pdf/...`, `doi.org/...`,
  `semanticscholar.org/paper/...`

## Configuration

| Env var | Purpose |
|---|---|
| `OPENALEX_MAILTO` | Optional. Adds your email to OpenAlex requests so they land in the polite pool (better rate limits). |
| `CROSSREF_MAILTO` | Optional. Same idea for Crossref's polite pool. |
| `CORE_API_KEY` | Required to enable the CORE provider. Without a key the provider reports unavailable and the aggregator skips it silently. Get a free key at <https://core.ac.uk/services/api>. |
| `SEMANTIC_SCHOLAR_API_KEY` | Optional. Semantic Scholar's anonymous quota is shared globally and 429s are common; the provider retries with exponential backoff. Set this to your own key for steadier throughput. |

### Adding a new provider

`paperhound.search` is a registry of provider factories. To add a new source:

1. Create `src/paperhound/search/<name>.py` with a class subclassing
   `SearchProvider`. Declare its `capabilities` (`TEXT_SEARCH`, `ID_LOOKUP`,
   `OPEN_ACCESS_PDF`) and override `available()` if it needs an API key.
2. Add unit tests in `tests/unit/test_<name>.py` that mock HTTP with `respx`.
3. Register it in `src/paperhound/search/__init__.py` with one
   `register("name", Factory)` call. Done — the CLI picks it up automatically.

## Use it from agents

paperhound is designed to be driven by AI agents. The repo ships a ready-to-install
[skill at `skills/paperhound/SKILL.md`](skills/paperhound/SKILL.md) that documents
every command, recommends the JSON output flag, and gives an end-to-end example.

Install it into Claude Code (or any [skills.sh](https://skills.sh)-compatible
agent) with one command:

```bash
npx skills add alexfdez1010/paperhound
```

This uses the [`skills` CLI](https://github.com/vercel-labs/skills) to discover
the `SKILL.md` under `skills/paperhound/` and place it in your agent's skill
directory (`~/.claude/skills/paperhound/` for Claude Code). Pass
`-a <agent>` to target a specific agent (e.g. `-a claude-code`,
`-a opencode`).

## Development

```bash
make install            # uv sync --extra dev
make test               # unit tests (network-free, respx-mocked)
make test-integration   # live API tests — always live, no env-var gate
make test-all           # unit + integration
make check              # lint + format check + unit tests (run before pushing)
```

Unit tests use `respx` to mock HTTP, so they never touch the network.
Integration tests under `tests/integration/` always hit the real provider APIs
(arXiv, OpenAlex, DBLP, Crossref, Hugging Face Papers, Semantic Scholar) — no
env-var gate, no mocks. The `SemanticScholarProvider` retries 429s with
exponential backoff; export `SEMANTIC_SCHOLAR_API_KEY` only if you want faster
runs.

## Releasing to PyPI

1. Bump `version` in `pyproject.toml` and `paperhound/__init__.py`.
2. Tag the release: `git tag v0.1.1 && git push --tags`.
3. The `Publish to PyPI` GitHub Action builds and publishes via
   [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/) — no
   API token required, just configure the trusted publisher once on PyPI.

## License

MIT — see [LICENSE](LICENSE).
