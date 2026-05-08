# Command reference

Every command, every flag. Order: discovery → ingest → graph → library → utility.

All commands accept `-h` / `--help` for the live help text. Global flag
`--version` / `-V` prints the installed version.

---

## `search` — unified search across providers

```bash
paperhound search "<query>" \
  [--limit N] [--year RANGE] [--min-citations N] [--venue STRING] [--author STRING] \
  [--type T[,T...]] [--peer-reviewed] [--preprints-only] \
  [--source arxiv|openalex|dblp|crossref|huggingface|semantic_scholar|core] \
  [--timeout SECONDS] [--json] [--rerank/--no-rerank] [--rerank-model NAME]
```

| Flag | Default | Notes |
|---|---|---|
| `--limit`, `-n` | `10` | Max papers returned. Cap at 5 for "a few". |
| `--year` | unset | `2023`, `2023-2026`, `2023-`, `-2026` (inclusive). |
| `--min-citations` | unset | Papers with unknown citation count are excluded. |
| `--venue` | unset | Case-insensitive substring match. |
| `--author` | unset | Case-insensitive substring match against any author. |
| `--type` | unset | One or more of `journal`, `conference`, `preprint`, `book`, `other`. Repeatable / comma-separated. Papers with unknown publication type are excluded. |
| `--peer-reviewed` | off | Shortcut for `--type journal,conference,book` — drops preprints and untagged records. |
| `--preprints-only` | off | Shortcut for `--type preprint`. Mutually exclusive with `--peer-reviewed`. |
| `--source`, `-s` | `arxiv,openalex,dblp,crossref,huggingface` | Repeatable. Use `-s s2` / `-s core` to opt into Semantic Scholar / CORE. |
| `--timeout` | `10` | Seconds. Slow providers are dropped silently. |
| `--json` | off | Emits **JSONL**, one `Paper` per line. |
| `--rerank/--no-rerank` | on (if extra installed) | Embedding rerank using sentence-transformers. |
| `--rerank-model` | `sentence-transformers/all-MiniLM-L6-v2` | HF model id. |

**Filter push-down**: `--year`, `--min-citations`, `--venue`, `--author`, and
`--type` (where expressible) are pushed down to OpenAlex / Crossref / Semantic
Scholar; always re-applied client-side after the merge so the cap is exact.

**Rerank install**: `pip install 'paperhound[rerank]'`. Without the extra,
the CLI silently falls back to merge order — never errors.

---

## `show` — abstract + metadata for a single paper

```bash
paperhound show <identifier> \
  [-s arxiv|openalex|dblp|crossref|hf|s2|core ...] \
  [--json] [--format markdown|bibtex|ris|csljson]
```

| Flag | Default | Notes |
|---|---|---|
| `<identifier>` | required | arXiv id (`2401.12345`, `cs.AI/0301001`), DOI, S2 id (40-char hex), OpenAlex id, or any paper URL. |
| `--source`, `-s` | auto | Restrict lookup to one or more providers. Use `-s arxiv` to defeat upstream metadata poisoning. |
| `--json` | off | **Single compact JSON object** (one line). Mutually exclusive with `--format`. |
| `--format` | `markdown` | `markdown` (rich terminal view), `bibtex`, `ris`, `csljson`. |

**Format details**:

- `bibtex` — `@article` / `@inproceedings` / `@misc`; cite key
  `<lastNameLower><year><firstSignificantWord>`; LaTeX special chars escaped.
- `ris` — `TY` / `AU` / `TI` / `AB` / `PY` / `DO` / `UR` / `ER`; Zotero,
  Mendeley, EndNote-compatible.
- `csljson` — single-element CSL-JSON array; Pandoc-compatible.

**Poisoning auto-defense**: by default paperhound cross-checks titles between
providers and drops mismatched records. Force the canonical record with
`-s arxiv` (or another single source) when in doubt.

---

## `download` — fetch the PDF

```bash
paperhound download <identifier> -o <path-or-dir>
```

- arXiv ids → PDF URL constructed directly.
- DOIs / S2 ids → open-access PDF resolved via Semantic Scholar; if no OA
  version exists, the command exits non-zero.
- `-o` semantics:
  - path with a suffix (`paper.pdf`) → treated as a file.
  - path without suffix (`./papers`, `./papers/`) → treated as a directory;
    file is named after the identifier.
  - missing directories are created.

---

## `convert` — PDF → Markdown via docling

```bash
paperhound convert <path-or-url> \
  [-o output.md] \
  [--with-figures] [--equations inline|latex] [--tables markdown|html]
```

| Flag | Default | Notes |
|---|---|---|
| `-o` | stdout | Without `-o`, Markdown is written to stdout. |
| `--with-figures` | off | Extract figures to `<stem>_assets/` and add `![](...)` references. **Requires `-o`.** |
| `--equations` | `inline` | `latex` enables formula enrichment; math kept as `$...$` / `$$...$$`. |
| `--tables` | `markdown` | `html` embeds raw `<table>` for merged/irregular cells. |

First run downloads docling model weights (hundreds of MB). Don't retry, wait.

---

## `get` — download + convert in one step

```bash
paperhound get <identifier> [-o output.md] [--keep-pdf]
```

- Default Markdown filename: `<id>.md` in the current directory.
- Intermediate PDF deleted unless `--keep-pdf`.

---

## `refs` — works the paper cites (its reference list)

```bash
paperhound refs <identifier> \
  [--depth 1|2] [--limit N] [--source openalex|semantic_scholar] [--json]
```

| Flag | Default | Notes |
|---|---|---|
| `--depth` | `1` | `2` = BFS one hop deeper, capped at `limit*2`, 0.1 s polite pause between hops, deduped by id/DOI/title. |
| `--limit`, `-n` | `10` | |
| `--source` | OpenAlex → S2 fallback | |
| `--json` | off | **JSONL** — one `Paper` per line. |

---

## `cited-by` — works that cite the paper

```bash
paperhound cited-by <identifier> \
  [--depth 1|2] [--limit N] [--source openalex|semantic_scholar] [--json]
```

Same flags and semantics as `refs`; reverse direction.

---

## Library — persistent local corpus

The library lives at `~/.paperhound/library/` (SQLite FTS5, no extra deps).
Override with the `PAPERHOUND_LIBRARY_DIR` environment variable.

### `add` — save a paper

```bash
paperhound add <identifier> [--convert]
```

- Re-adding an existing entry updates its metadata (idempotent).
- `--convert` also fetches the PDF and stores its Markdown in the library
  directory.

### `list` — list saved papers

```bash
paperhound list
```

Prints a Rich table (id, title, authors, year, MD?). No `--json` flag.

### `grep` — full-text search the corpus (offline)

```bash
paperhound grep "<query>" [--limit N]
```

Searches title + abstract + Markdown body via SQLite FTS5. Pure offline,
zero network. Default limit 20 (max 200).

### `rm` — remove a paper

```bash
paperhound rm <identifier> [--yes]
```

Deletes the row and the Markdown file (if any). Prompts unless `-y`.

---

## `version`

```bash
paperhound version            # prints the installed version
paperhound --version          # equivalent (eager flag)
paperhound -V                 # equivalent
```

---

## `providers` — list backends with status + setup hints

```bash
paperhound providers          # Rich table
paperhound providers --json   # JSON array of provider status objects
```

Per provider you get: `name`, `description`, `homepage`, `capabilities`,
`default_enabled`, `available`, `env_vars` (each with
`name`/`required`/`purpose`/`signup_url`/`is_set`), and a one-line
`fix` hint when something needs configuring.

Use it to debug "why are my searches sparse?" — typical fixes are
`export CORE_API_KEY=…` (enables CORE) or
`export SEMANTIC_SCHOLAR_API_KEY=…` (raises S2 rate limit).

---

## Source aliases

Always restrict user-controlled `--source` values to this set:

| Canonical | Aliases |
|---|---|
| `arxiv` | — |
| `openalex` | — |
| `dblp` | — |
| `crossref` | — |
| `huggingface` | `hf` |
| `semantic_scholar` | `s2` |
| `core` | — |

---

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success. |
| 1 | Generic error (typed `PaperhoundError`, e.g., not found, network, no OA PDF). Error message goes to stderr. |
| 2 | Typer usage error (bad flag, bad identifier shape). |

Detect "no results" by inspecting stdout: `search` exits 0 with empty
JSONL; `show` exits 1 with `error: …` on stderr if the id isn't resolvable.
