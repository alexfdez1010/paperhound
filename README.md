# paperhound

> **paperhound** — sniff out academic papers from Python or the command line.

A small, fast Python library (and matching CLI) for AI/ML researchers and
tooling authors who want a single dependency to **search**, **inspect**,
**download**, and **convert to Markdown** papers from many academic sources at
once. Conversion is powered by
[docling](https://github.com/docling-project/docling), so the resulting
Markdown is good enough to feed straight into an LLM context window.

paperhound is built primarily as a library — every CLI command is a thin
wrapper around a public Python API you can import directly. The CLI is the
fastest way to drive it from the terminal or from agents, but anything you
can do at the prompt you can also do with three lines of Python.

## Features

- 🔎 **Unified search** — one query, many backends. arXiv, OpenAlex, DBLP,
  Crossref and Hugging Face Papers (and optionally Semantic Scholar / CORE)
  are queried in parallel with a 10-second budget. Results are merged
  round-robin (one from each provider, then the next, …) so a fast provider
  can't monopolize the top-N — and deduplicated by arXiv id / DOI / title.
  Slow providers are dropped silently — you get whatever came back in time.
- 📄 **Inspect before downloading** — fetch the abstract and metadata, decide
  if the paper is worth the bytes.
- ⬇️ **Download by identifier** — arXiv id, DOI, Semantic Scholar paper id,
  or any paper URL. Open-access PDFs are resolved automatically.
- 📝 **PDF → Markdown via docling** — figures, LaTeX equations and HTML
  tables are all opt-in flags.
- 📚 **Local library** — a SQLite FTS5 database at `~/.paperhound/library/`.
  Add a paper, store its Markdown, then offline-grep over titles, abstracts
  and bodies.
- 🧠 **Optional embedding rerank** — install `paperhound[rerank]` and the
  CLI reranks results by query/abstract similarity automatically.
- 🤖 **Agent-ready CLI** — every command speaks JSON via `--json`, and the
  repo ships a [skills.sh](https://skills.sh) skill so any Claude / OpenAI /
  local agent can drive paperhound with no extra glue.
- 🧪 **Heavily tested** — every module has unit tests; live integration tests
  sit under `tests/integration/`.

## Installation

```bash
pip install paperhound
```

or with [uv](https://docs.astral.sh/uv/):

```bash
# As a library inside another project
uv add paperhound

# Or as an isolated CLI on your $PATH
uv tool install paperhound
```

Python 3.10+ is required. Docling pulls in PyTorch on first run, so the very
first conversion may take a moment to download model weights.

### Optional: embedding rerank

```bash
pip install 'paperhound[rerank]'
```

Adds `sentence-transformers` so paperhound can rerank merged search results by
embedding similarity between the query and each candidate's `title + abstract`.
When the extra is installed, rerank runs automatically on every CLI search
(`--no-rerank` to skip). Library callers opt in by calling
`paperhound.rerank.rerank(...)` themselves.

## Quick start (Python)

```python
from paperhound import search_papers, get_paper, convert_to_markdown

# 1. Search across all default providers (arxiv + openalex + dblp + crossref + hf).
papers = search_papers("retrieval augmented generation", limit=5)
for p in papers:
    print(p.year, p.title, p.identifiers.arxiv_id or p.identifiers.doi)

# 2. Pull the abstract for a single paper.
paper = get_paper("1706.03762")
print(paper.title)
print(paper.abstract)

# 3. PDF → Markdown (path or URL).
md = convert_to_markdown("https://arxiv.org/pdf/1706.03762", output="attention.md")
```

Every function returns a typed `paperhound.models.Paper` object — `pydantic`
under the hood, so you get autocomplete, `model_dump(mode="json")`, validation,
and stable field names across providers.

### Building a corpus

```python
from paperhound import Library, search_papers, get_paper

lib = Library()                   # ~/.paperhound/library/ by default
for hit in search_papers("vision language models", limit=20):
    lib.add(hit)                  # idempotent — re-adds update in place

# Offline full-text search later, no API calls.
hits = lib.grep("multi-head attention", limit=10)
for h in hits:
    print(h.id, h.title)
```

### Citation graph

```python
from paperhound.citations import fetch_references, fetch_citations

refs   = fetch_references("1706.03762", depth=1, limit=10)
citing = fetch_citations("1706.03762", depth=2, limit=50)
```

## Library API reference

Top-level package re-exports the symbols you need most often:

| Symbol | Purpose |
|---|---|
| `paperhound.search_papers(query, limit=10, sources=None, **filters)` | Run a unified search; returns `list[Paper]`. |
| `paperhound.get_paper(identifier)` | Resolve an id/DOI/URL to a single `Paper`, or `None`. |
| `paperhound.convert_to_markdown(src, output=None, options=None)` | PDF/URL → Markdown via docling. |
| `paperhound.pdf_to_markdown(...)` | Lower-level PDF-only entry point. |
| `paperhound.Paper`, `Author`, `PaperIdentifier` | Pydantic models. |
| `paperhound.Library` | SQLite FTS5 library wrapper. |

Need finer control? Drop into the underlying modules:

- `paperhound.search` — provider registry, `SearchAggregator`, `SearchQuery`,
  `SearchProvider` base class. Plug in your own provider with one
  `register("name", Factory)` call.
- `paperhound.download` — `resolve_pdf_url`, `download_pdf`.
- `paperhound.convert` — `ConversionOptions`, `convert_to_markdown`.
- `paperhound.citations` — `fetch_references`, `fetch_citations`.
- `paperhound.rerank` — optional, requires the `rerank` extra.
- `paperhound.errors` — `PaperhoundError`, `ProviderError`, `LibraryError`,
  `RerankError`. Every other exception bubbles untouched.

## CLI

Once installed, `paperhound` is on your `$PATH`.

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

`--json` is the pipe-friendly mode: no headers, no Rich formatting, no progress bars.

```bash
# search --json: JSONL — one compact JSON object per line (Paper schema)
paperhound search "graph neural networks" --json | jq '.title'

# show --json: single compact JSON object on one line
paperhound show 1706.03762 --json | jq .abstract
```

The schema is `paperhound.models.Paper` serialised via `model_dump(mode="json")`.
Fields: `title`, `authors[]`, `abstract`, `year`, `venue`, `url`, `pdf_url`,
`citation_count`, `identifiers.{arxiv_id,doi,semantic_scholar_id,openalex_id,
dblp_key,core_id}`, `sources[]`.

`--json` and `--format` are mutually exclusive on `show` — use one or the other.

### Commands

| Command | Description |
|---|---|
| `paperhound search <query>` | Run a unified search. `--limit`, `--source arxiv\|openalex\|dblp\|crossref\|huggingface\|semantic_scholar\|core` (repeatable), `--year RANGE`, `--min-citations N`, `--venue STRING`, `--author STRING`, `--timeout`, `--json` (JSONL output), `--rerank/--no-rerank` (default on when `paperhound[rerank]` is installed), `--rerank-model`. |
| `paperhound show <id>` | Fetch a paper's metadata + abstract. `--format markdown\|bibtex\|ris\|csljson` (default `markdown`), `--json` (compact JSON; mutually exclusive with `--format`). |
| `paperhound download <id> -o <path>` | Download a paper PDF. |
| `paperhound convert <pdf> -o <md>` | Convert a PDF (or any docling-supported file/URL) to Markdown. `--with-figures` saves embedded images to `<stem>_assets/` and references them in the output. `--equations latex` preserves math as `$...$`/`$$...$$`. `--tables html` embeds `<table>` blocks instead of GFM pipe tables. |
| `paperhound get <id> -o <md>` | Download + convert in one step. `--keep-pdf` to keep the PDF. |
| `paperhound refs <id>` | List works the paper cites (its references). `--depth 1\|2`, `--limit N`, `--source openalex\|semantic_scholar`, `--json`. |
| `paperhound cited-by <id>` | List works that cite the paper. Same flags as `refs`. |
| `paperhound add <id>` | Fetch metadata and add to local library. `--convert` also stores Markdown. |
| `paperhound list` | List all papers in the local library. |
| `paperhound grep <query>` | Full-text search the local library (title + abstract + Markdown body). |
| `paperhound rm <id>` | Remove a paper from the local library (and its Markdown file, if any). |
| `paperhound version` | Print the installed version. |

Run `paperhound <command> --help` for full options.

### Conversion options

`paperhound convert` (and the `get` / `add --convert` pipeline) accepts three
flags that control how the PDF is rendered to Markdown:

| Flag | Values | Default | Description |
|---|---|---|---|
| `--with-figures` | — | off | Extract embedded figures to `<stem>_assets/` and embed `![](...)` references. Requires `--output`. |
| `--equations` | `inline`, `latex` | `inline` | `latex` enables formula enrichment — math is preserved as `$...$` / `$$...$$` LaTeX (uses docling's `do_formula_enrichment` VLM; slightly slower). |
| `--tables` | `markdown`, `html` | `markdown` | `html` embeds raw `<table>` blocks for better fidelity with merged/irregular cells. |

```bash
paperhound convert paper.pdf -o paper.md --with-figures --equations latex --tables html
paperhound convert paper.pdf -o paper.md --equations latex
paperhound convert paper.pdf -o paper.md --tables html
```

All three flags default to the original behaviour, so existing pipelines are
unaffected.

### Filters

`paperhound search` accepts four filter flags. Filters are pushed down to
providers that support them (OpenAlex, Crossref, Semantic Scholar) and always
applied client-side after the merge as a safety net.

| Flag | Accepted values | Example |
|---|---|---|
| `--year RANGE` | `YYYY`, `YYYY-YYYY`, `YYYY-`, `-YYYY` | `--year 2022-2024` |
| `--min-citations N` | integer ≥ 0 | `--min-citations 100` |
| `--venue STRING` | case-insensitive substring | `--venue NeurIPS` |
| `--author STRING` | case-insensitive substring | `--author Hinton` |

```bash
paperhound search "vision transformers" --year 2022-2024 --min-citations 100
paperhound search "deep learning" --venue NeurIPS --author Hinton
paperhound search "diffusion models" -s arxiv --year 2023-
paperhound search "llm alignment" --year 2023 --min-citations 50 --json | jq .title
```

**Behavior with missing fields**: papers whose `year` or `venue` field is
unknown (`null`) are kept — the filter cannot be verified. Papers whose
`citation_count` is unknown are excluded when `--min-citations` is set
(conservative: the user asked for a floor).

### Export formats

`paperhound show` can export a paper's metadata in four formats:

```bash
paperhound show 1706.03762                       # rich terminal view
paperhound show 1706.03762 --format bibtex
paperhound show 1706.03762 --format ris
paperhound show 1706.03762 --format csljson
```

BibTeX cite keys are derived deterministically as `<firstAuthorLastName><year><firstSignificantTitleWord>` (accents stripped, lowercased). LaTeX special characters (`&`, `%`, `$`, `_`, etc.) are escaped automatically.

### Local library

paperhound keeps a persistent per-user library at `~/.paperhound/library/`
(override with `PAPERHOUND_LIBRARY_DIR`). The library is backed by a SQLite
FTS5 database — no extra dependencies required.

```bash
paperhound add 1706.03762
paperhound add 1706.03762 --convert
paperhound list
paperhound grep "attention mechanism"
paperhound rm 1706.03762
```

Re-adding a paper is idempotent — it updates the metadata in place. The
schema is versioned; on a version mismatch paperhound reports a clear error
rather than silently operating on a stale schema.

### Citation graph

```bash
paperhound refs 1706.03762
paperhound cited-by 1706.03762
paperhound refs 1706.03762 --depth 2 --limit 50
paperhound cited-by 1706.03762 --source semantic_scholar
paperhound refs 1706.03762 --json | jq '.[].title'
```

Both commands return the same `Paper` format as `search`. The default provider
order is **OpenAlex first, Semantic Scholar as fallback** (automatically
triggered when OpenAlex returns nothing or errors). Results are deduplicated
by arXiv id / DOI / title before being returned. At `--depth 2`, total fetched
is capped at `limit * 2` and a small pause (0.1 s) is inserted between hops to
stay in the polite API pool.

### Rerank

When `paperhound[rerank]` is installed, every CLI `search` call reranks
results by embedding similarity between the query and each candidate's
`title + abstract`. Pass `--no-rerank` to skip it for one call.

```bash
pip install 'paperhound[rerank]'

paperhound search "vision language models"          # rerank on by default
paperhound search "graph neural networks" --no-rerank
paperhound search "agents" --rerank-model sentence-transformers/all-mpnet-base-v2
```

Without the extra installed the CLI silently falls back to the merge-order
ranking — no error, no hang. Library users that want to invoke rerank
directly call `paperhound.rerank.rerank(query, papers, model_name=None)`.

How it works:

1. The aggregator fetches up to `limit * 3` candidates (capped at 50).
2. Each candidate's text (`title + abstract`) is embedded alongside the query
   using the chosen SentenceTransformer model (cached per process).
3. Candidates are sorted by cosine similarity (descending).
4. Papers with neither a title nor an abstract keep their merge-order rank
   and are placed at the end.
5. The top `--limit` results are returned.

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
| `PAPERHOUND_LIBRARY_DIR` | Override the library directory (default `~/.paperhound/library/`). |

### Adding a new provider

`paperhound.search` is a registry of provider factories. To add a new source:

1. Create `src/paperhound/search/<name>.py` with a class subclassing
   `SearchProvider`. Declare its `capabilities` (`TEXT_SEARCH`, `ID_LOOKUP`,
   `OPEN_ACCESS_PDF`) and override `available()` if it needs an API key.
2. Add unit tests in `tests/unit/test_<name>.py` that mock HTTP with `respx`.
3. Register it in `src/paperhound/search/__init__.py` with one
   `register("name", Factory)` call. Done — the CLI picks it up automatically.

## Use it from agents

paperhound ships a ready-to-install
[skill at `skills/paperhound/SKILL.md`](skills/paperhound/SKILL.md) that
documents every command, recommends the JSON output flag, and gives an
end-to-end example. Install it with one command:

```bash
npx skills add alexfdez1010/paperhound
```

This uses the [`skills` CLI](https://github.com/vercel-labs/skills) to
discover the `SKILL.md` under `skills/paperhound/` and place it in your
agent's skill directory (`~/.claude/skills/paperhound/` for Claude Code).
Pass `-a <agent>` to target a specific agent (e.g. `-a claude-code`,
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

1. Bump `version` in `pyproject.toml`.
2. Push to `main`. The `Publish to PyPI` workflow builds and publishes via
   [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/) —
   idempotent on the version field, so re-pushing the same version is a
   no-op.

## License

MIT — see [LICENSE](LICENSE).
