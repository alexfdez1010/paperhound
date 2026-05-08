# 🐾 paperhound

> **Sniff out academic papers from the command line — and from your agents.**

[![PyPI](https://img.shields.io/pypi/v/paperhound.svg)](https://pypi.org/project/paperhound/)
[![Python](https://img.shields.io/pypi/pyversions/paperhound.svg)](https://pypi.org/project/paperhound/)
[![License](https://img.shields.io/pypi/l/paperhound.svg)](LICENSE)

`paperhound` is a fast, agent-ready CLI for AI/ML researchers and
tooling authors. One binary to **search**, **inspect**, **download**,
and **convert to Markdown** academic papers from many sources at once —
arXiv, OpenAlex, DBLP, Crossref, Hugging Face Papers, Semantic Scholar
and CORE. Conversion is powered by
[docling](https://github.com/docling-project/docling), so the resulting
Markdown is good enough to feed straight into an LLM context window.

## ✨ Features

- 🔎 **Unified search** — one query, many backends in parallel under a
  10-second budget. Results merged round-robin (no provider can
  monopolize the top-N) and deduplicated by arXiv id / DOI / title.
- 📄 **Inspect before downloading** — abstract + metadata in one call.
- ⬇️ **Download by identifier** — arXiv id, DOI, Semantic Scholar id, or
  any paper URL. Open-access PDFs are resolved automatically.
- 📝 **PDF → Markdown via docling** — figures, LaTeX equations and HTML
  tables are opt-in flags.
- 📚 **Local library** — SQLite FTS5 at `~/.paperhound/library/`. Add a
  paper, store its Markdown, then offline-grep over titles, abstracts
  and bodies.
- 🧠 **Embedding rerank** — install `paperhound[rerank]` and the CLI
  reranks search results by query/abstract similarity automatically.
- 🤖 **Agent-ready** — every command speaks JSON via `--json`, and a
  [skills.sh](https://skills.sh) skill ships in this repo for one-line
  install.
- 🔗 **Citation graph** — `refs` and `cited-by` walk the OpenAlex /
  Semantic Scholar graph with depth control.
- 📤 **Export** — BibTeX, RIS, CSL-JSON straight from `show`.

## 🤖 Install the agent skill (recommended first step)

The fastest way to use paperhound is from an agent (Claude, OpenAI,
opencode, …). Install the skill — it teaches the agent every command,
flag, and JSON schema:

```bash
npx skills add alexfdez1010/paperhound
```

This places `SKILL.md` in your agent's skill directory
(`~/.claude/skills/paperhound/` for Claude Code). Pass `-a <agent>` to
target a specific agent (e.g. `-a claude-code`, `-a opencode`).

The skill auto-installs the `paperhound` CLI on first use, so you don't
need to install anything else manually.

## 📦 Install the CLI

```bash
# pip
pip install paperhound

# uv (isolated CLI on $PATH)
uv tool install paperhound

# uv — upgrade later
uv tool upgrade paperhound

# uv (as a library inside another project)
uv add paperhound
```

Optional embedding rerank:

```bash
pip install 'paperhound[rerank]'
```

Python 3.10+ is required.

## 🚀 CLI usage

Once installed, `paperhound` is on your `$PATH`.

```bash
# 🔎 Search across all providers
paperhound search "diffusion transformers" --limit 5

# 📄 Show abstract + metadata
paperhound show 2401.12345
paperhound show 10.1038/s41586-020-2649-2          # DOI
paperhound show https://arxiv.org/abs/1706.03762   # URL
paperhound show 2001.08361 -s arxiv                # force a single provider

# ⬇️ Download the PDF
paperhound download 1706.03762 -o ./papers/

# 📝 Convert a local PDF to Markdown
paperhound convert ./papers/1706.03762.pdf -o attention.md

# 🪄 Or do it all at once: resolve, download, convert, clean up
paperhound get 1706.03762 -o attention.md
```

### 📋 Commands

| Command | Description |
|---|---|
| `paperhound search <query>` | Unified search. `--limit`, `--source` (repeatable), `--year RANGE`, `--min-citations N`, `--venue STRING`, `--author STRING`, `--timeout`, `--json`, `--rerank/--no-rerank`, `--rerank-model`. |
| `paperhound show <id>` | Metadata + abstract. `--source` (`-s`, repeatable — restrict the lookup to avoid poisoned aggregator metadata), `--format markdown\|bibtex\|ris\|csljson`, `--json`. |
| `paperhound download <id> -o <path>` | Download a paper PDF. |
| `paperhound convert <pdf> -o <md>` | Convert a PDF (or URL) to Markdown. `--with-figures`, `--equations latex`, `--tables html`. |
| `paperhound get <id> -o <md>` | Download + convert in one step. `--keep-pdf` to retain the PDF. |
| `paperhound refs <id>` | Works the paper cites. `--depth`, `--limit`, `--source`, `--json`. |
| `paperhound cited-by <id>` | Works that cite the paper. Same flags as `refs`. |
| `paperhound add <id>` | Add to local library. `--convert` also stores Markdown. |
| `paperhound list` | List papers in the local library. |
| `paperhound grep <query>` | Full-text search the local library. |
| `paperhound rm <id>` | Remove a paper from the local library. |
| `paperhound providers` | List every search provider with its description, default-set membership, runtime availability, env-var status, and one-line setup hint. `--json` for machine-readable output. |
| `paperhound version` | Print the installed version. |

Run `paperhound <command> --help` for full options.

### 🤖 JSON output

`--json` is the pipe-friendly mode: no headers, no Rich formatting, no
progress bars.

```bash
# JSONL — one compact JSON object per line
paperhound search "graph neural networks" --json | jq '.title'

# Single compact JSON object
paperhound show 1706.03762 --json | jq .abstract
```

Schema: `paperhound.models.Paper` via `model_dump(mode="json")`. Fields
include `title`, `authors[]`, `abstract`, `year`, `venue`,
`publication_type` (`journal`/`conference`/`preprint`/`book`/`other`),
`url`, `pdf_url`, `citation_count`, `identifiers.{arxiv_id,doi,…}`,
`sources[]`.

### 🎚️ Filters

`paperhound search` supports the filters below, pushed down to
providers that support them (OpenAlex, Crossref, Semantic Scholar) and
re-applied client-side as a safety net.

| Flag | Accepted values | Example |
|---|---|---|
| `--year RANGE` | `YYYY`, `YYYY-YYYY`, `YYYY-`, `-YYYY` | `--year 2022-2024` |
| `--min-citations N` | integer ≥ 0 | `--min-citations 100` |
| `--venue STRING` | case-insensitive substring | `--venue NeurIPS` |
| `--author STRING` | case-insensitive substring | `--author Hinton` |
| `--type T[,T…]` | `journal`, `conference`, `preprint`, `book`, `other` (repeatable) | `--type journal,conference` |
| `--peer-reviewed` | shortcut for `--type journal,conference,book` | `--peer-reviewed` |
| `--preprints-only` | shortcut for `--type preprint` | `--preprints-only` |

```bash
paperhound search "vision transformers" --year 2022-2024 --min-citations 100
paperhound search "deep learning" --venue NeurIPS --author Hinton
paperhound search "diffusion models" --peer-reviewed
paperhound search "agentic workflows" --preprints-only
```

Papers with unknown `year`/`venue` are kept (filter unverifiable);
papers with unknown `citation_count` or unknown `publication_type` are
excluded when the matching filter (`--min-citations`, `--type`,
`--peer-reviewed`, or `--preprints-only`) is set.

### 📑 Conversion options

| Flag | Values | Default | Description |
|---|---|---|---|
| `--with-figures` | — | off | Extract figures to `<stem>_assets/` and embed `![](...)`. Requires `--output`. |
| `--equations` | `inline`, `latex` | `inline` | `latex` preserves math as `$...$` / `$$...$$` (uses docling's `do_formula_enrichment`). |
| `--tables` | `markdown`, `html` | `markdown` | `html` embeds raw `<table>` blocks for merged/irregular cells. |

```bash
paperhound convert paper.pdf -o paper.md --with-figures --equations latex --tables html
```

### 📤 Export formats

```bash
paperhound show 1706.03762 --format bibtex
paperhound show 1706.03762 --format ris
paperhound show 1706.03762 --format csljson
```

BibTeX cite keys are derived as
`<firstAuthorLastName><year><firstSignificantTitleWord>` (accents
stripped, lowercased). LaTeX special characters are escaped
automatically.

### 📚 Local library

```bash
paperhound add 1706.03762
paperhound add 1706.03762 --convert
paperhound list
paperhound grep "attention mechanism"
paperhound rm 1706.03762
```

Default location: `~/.paperhound/library/` (override with
`PAPERHOUND_LIBRARY_DIR`). Re-adds are idempotent.

### 🔗 Citation graph

```bash
paperhound refs 1706.03762
paperhound cited-by 1706.03762 --depth 2 --limit 50
paperhound refs 1706.03762 --source semantic_scholar --json | jq '.[].title'
```

Default provider order: **OpenAlex first, Semantic Scholar fallback**.
Results are deduplicated by arXiv id / DOI / title. At `--depth 2`,
total fetched is capped at `limit * 2`.

### 🧠 Rerank

With `paperhound[rerank]` installed, every CLI `search` reranks results
by embedding similarity between the query and each candidate's
`title + abstract`.

```bash
paperhound search "vision language models"          # rerank on by default
paperhound search "graph neural networks" --no-rerank
paperhound search "agents" --rerank-model sentence-transformers/all-mpnet-base-v2
```

Without the extra installed, the CLI silently falls back to merge-order
ranking — no error, no hang.

## 🆔 Identifier formats

paperhound accepts whatever you have on hand:

- **arXiv ids**: `2401.12345`, `2401.12345v3`, `cs.AI/0301001`, `arXiv:2401.12345`
- **DOIs**: `10.1038/s41586-020-2649-2`, `doi:10.1038/...`
- **Semantic Scholar paper ids**: 40-char hex
- **URLs**: `arxiv.org/abs/...`, `arxiv.org/pdf/...`, `doi.org/...`,
  `semanticscholar.org/paper/...`

## ⚙️ Configuration

| Env var | Purpose |
|---|---|
| `OPENALEX_MAILTO` | Optional. Adds your email to OpenAlex requests for the polite pool (better rate limits). |
| `CROSSREF_MAILTO` | Optional. Same idea for Crossref's polite pool. |
| `CORE_API_KEY` | Required to enable the CORE provider. Get a free key at <https://core.ac.uk/services/api>. |
| `SEMANTIC_SCHOLAR_API_KEY` | Optional. The anonymous quota is shared globally and 429s are common; set this for steadier throughput. |
| `PAPERHOUND_LIBRARY_DIR` | Override the library directory (default `~/.paperhound/library/`). |

Run `paperhound providers` (or `paperhound providers --json`) to see, at a
glance, which providers are configured on the current machine and what
to export to enable or upgrade each one.

## 📚 More

- 🐍 **[Using paperhound from Python](docs/PYTHON.md)** — library API,
  building a corpus, citation graph, adding a new provider.
- 🛠️ **[Development](docs/DEVELOPMENT.md)** — tests, lint, releasing
  to PyPI.
- 🧪 **[Testing procedure](docs/TESTING.md)** — standardized
  post-publish smoke pass.

## 📄 License

MIT — see [LICENSE](LICENSE).
