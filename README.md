# paperhound

> **paperhound** — sniff out academic papers from the command line.

A small, fast CLI for AI/ML researchers who want a single tool to **search**,
**inspect**, **download**, and **convert to Markdown** papers from arXiv and
Semantic Scholar. Conversion is powered by [docling](https://github.com/docling-project/docling),
so the resulting Markdown is good enough to feed straight into an LLM context.

## Features

- 🔎 **Unified search** — one query, all backends. arXiv and Semantic Scholar
  are queried in parallel and the results are merged and deduplicated.
- 📄 **Inspect before downloading** — `paperhound show <id>` prints the
  abstract and metadata so you can decide if it's worth a download.
- ⬇️ **Download by identifier** — arXiv id, DOI, Semantic Scholar paper id, or
  any paper URL. Open-access PDFs are resolved automatically.
- 📝 **PDF → Markdown via docling** — `paperhound convert paper.pdf` or
  `paperhound get <id>` for the full pipeline.
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
| `paperhound search <query>` | Run a unified search. `--limit`, `--source arxiv\|semantic_scholar`, `--year-min`, `--year-max`, `--json`. |
| `paperhound show <id>` | Fetch a paper's metadata + abstract. |
| `paperhound download <id> -o <path>` | Download a paper PDF. |
| `paperhound convert <pdf> -o <md>` | Convert a PDF (or any docling-supported file/URL) to Markdown. |
| `paperhound get <id> -o <md>` | Download + convert in one step. `--keep-pdf` to keep the PDF. |
| `paperhound version` | Print the installed version. |

Run `paperhound <command> --help` for full options.

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
| `SEMANTIC_SCHOLAR_API_KEY` | Optional. Every Semantic Scholar Graph API endpoint we use (`/paper/search`, `/paper/{paper_id}`) is reachable anonymously, but the unauthenticated quota is shared globally and 429s are common; the provider retries them automatically. Set this to your own key for steadier throughput. |

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
Integration tests under `tests/integration/` always hit the real arXiv and
Semantic Scholar APIs — no env-var gate, no mocks. The `SemanticScholarProvider`
retries 429s with exponential backoff so the S2 suite is robust to the public
shared rate limit; export `SEMANTIC_SCHOLAR_API_KEY` only if you want faster
runs.

## Releasing to PyPI

1. Bump `version` in `pyproject.toml` and `paperhound/__init__.py`.
2. Tag the release: `git tag v0.1.1 && git push --tags`.
3. The `Publish to PyPI` GitHub Action builds and publishes via
   [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/) — no
   API token required, just configure the trusted publisher once on PyPI.

## License

MIT — see [LICENSE](LICENSE).
