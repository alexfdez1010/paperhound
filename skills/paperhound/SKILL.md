---
name: paperhound
description: Search, inspect, download, and convert academic papers (arXiv, OpenAlex, DBLP, Crossref, Hugging Face Papers, Semantic Scholar, CORE) to Markdown via the `paperhound` CLI. Use whenever the user asks to find papers, fetch a paper's abstract, download a PDF, or turn a paper into Markdown.
---

# paperhound — paper search and conversion CLI

`paperhound` is a small command-line tool that queries arXiv, OpenAlex, DBLP,
Crossref and Hugging Face Papers (and optionally Semantic Scholar / CORE) in
parallel under a 10-second budget, resolves identifiers (arXiv id, DOI,
Semantic Scholar paper id, OpenAlex Work id, or any paper URL), downloads the
PDF, and converts it to Markdown using
[docling](https://github.com/docling-project/docling). Results are merged
round-robin across providers (so the top-N has source diversity, not just the
fastest provider), then deduplicated. Slow providers are dropped silently —
you always get whatever finished within the budget.

## Setup check

Before using, confirm it is installed:

```bash
paperhound version
```

If the command is missing, install it:

```bash
pip install paperhound        # or: uv tool install paperhound
```

## Installing this skill

Use the [skills.sh](https://skills.sh) CLI:

```bash
npx skills add alexfdez1010/paperhound
```

It picks up this `SKILL.md` (frontmatter `name` + `description`) and installs
it under `~/.claude/skills/paperhound/`. Add `-a claude-code` to target a
specific agent, or `-y` to skip prompts.

## When to use this skill

Trigger this skill when the user asks for any of:

- "Find/search papers about X"
- "What's the abstract of paper X / arXiv 2401.12345?"
- "Download this paper" (with an id, DOI, or URL)
- "Convert this PDF to markdown"
- "Get me a markdown version of paper X so I can quote it"
- "Add paper X to my library"
- "Search my library for Y"
- "List papers I've saved"
- "What papers does this paper cite?" / "Show me the references for X"
- "What papers cite this paper?" / "Who cited X?"

## Commands

Always pass `--json` when you plan to consume the output programmatically.

### Local library — add / list / grep / rm

paperhound keeps a persistent per-user library at `~/.paperhound/library/`
(SQLite FTS5, no extra dependencies). Override the directory with the
`PAPERHOUND_LIBRARY_DIR` environment variable.

```bash
# Add a paper's metadata to the library (idempotent re-add updates the row)
paperhound add <identifier>

# Add and also convert the PDF to Markdown, stored in the library directory
paperhound add <identifier> --convert

# List all saved papers
paperhound list

# Full-text search over title + abstract + Markdown body (offline)
paperhound grep "<query>" [--limit N]

# Remove a paper from the library (and deletes its Markdown file, if any)
paperhound rm <identifier> [--yes]
```

Typical agent workflow to build a local corpus:

1. `paperhound search "…" --json -n 10` — find candidates.
2. `paperhound add <id> --convert` — persist metadata + Markdown.
3. `paperhound grep "…"` — query the corpus offline for future sessions.

### Search — unified across providers

```bash
paperhound search "<query>" [--limit N] [--year-min YYYY] [--year-max YYYY] [--source arxiv|openalex|dblp|crossref|huggingface|semantic_scholar|core] [--timeout SECONDS] [--json] [--rerank] [--rerank-model NAME]
```

- Default `--limit` is 10. Cap it (e.g. `-n 5`) when the user asks for "a few".
- `--source` is repeatable; omit it to query the default set
  (arxiv + openalex + dblp + crossref + huggingface). Pass `-s s2` /
  `-s core` to opt into Semantic Scholar or CORE.
- `--timeout` defaults to 10s. Providers that exceed the budget are dropped
  from the response — the command still succeeds with whatever returned.
- `--json` emits **JSONL** (one compact JSON object per line, no indent).
  Parse each line individually with `json.loads(line)` or pipe to `jq '.title'`.
- JSON schema (`paperhound.models.Paper`): `title`, `authors[]`, `abstract`,
  `year`, `venue`, `url`, `pdf_url`, `citation_count`,
  `identifiers.{arxiv_id,doi,semantic_scholar_id,openalex_id,dblp_key,core_id}`,
  `sources[]`.
- `--rerank` re-sorts results by embedding similarity (query vs. title+abstract).
  Requires `pip install 'paperhound[rerank]'`. Default model:
  `sentence-transformers/all-MiniLM-L6-v2`. Override with `--rerank-model NAME`.

### Show — abstract + metadata for a single paper

```bash
paperhound show <identifier> [--json] [--format markdown|bibtex|ris|csljson]
```

- `<identifier>` accepts: arXiv id (`2401.12345`, `cs.AI/0301001`),
  DOI (`10.1234/foo.bar`), Semantic Scholar id (40-char hex), or any paper URL.
- `--json` emits a **single compact JSON object** (one line, `paperhound.models.Paper`
  schema). Mutually exclusive with `--format` — use one or the other.
- `--format` controls the output format (default `markdown`):
  - `markdown` — rich terminal view (title, authors, abstract, identifiers).
  - `bibtex` — `@article`/`@inproceedings`/`@misc` entry; cite key is
    `<lastNameLower><year><firstSignificantWord>`; LaTeX special chars escaped.
  - `ris` — RIS block (`TY`, `AU`, `TI`, `AB`, `PY`, `DO`, `UR`, `ER`);
    compatible with Zotero, Mendeley, EndNoteX.
  - `csljson` — single-element CSL-JSON array; compatible with Pandoc and
    citation processors.

### Download — fetch the PDF

```bash
paperhound download <identifier> -o <path-or-dir>
```

- For arXiv ids the PDF URL is constructed directly.
- For DOIs / S2 ids paperhound looks up the open-access PDF via Semantic
  Scholar; if no open-access version exists the command exits non-zero.
- `-o` semantics: a path with a suffix (`paper.pdf`) is treated as a file; a
  path without one (`./papers`, `./papers/`) is treated as a directory and
  the file is named after the identifier. Missing directories are created.

### Convert — PDF → Markdown via docling

```bash
paperhound convert <path-or-url> [-o output.md]
```

- Without `-o`, the Markdown is written to stdout.

### Get — download and convert in one step

```bash
paperhound get <identifier> [-o output.md] [--keep-pdf]
```

- Default Markdown filename is `<id>.md` in the current directory.
- The intermediate PDF is deleted unless `--keep-pdf` is passed.

### Citation graph — refs and cited-by

```bash
# Works the paper cites (its reference list)
paperhound refs <identifier> [--depth 1|2] [--limit N] [--source openalex|semantic_scholar] [--json]

# Works that cite the paper
paperhound cited-by <identifier> [--depth 1|2] [--limit N] [--source openalex|semantic_scholar] [--json]
```

- Default provider order: OpenAlex → Semantic Scholar (automatic fallback).
- `--depth 2` fetches references/citations of references/citations (BFS, capped
  at `limit * 2` total, 0.1 s polite pause between hops, deduped by id/DOI/title).
- Output is the same `Paper` format as `search` — use `--json` for scripting.

Typical agent workflow for related-work exploration:

1. `paperhound refs 1706.03762 --json -n 10` — get the top references.
2. Pick an interesting reference, run `paperhound show <id>` to confirm relevance.
3. `paperhound cited-by 1706.03762 --json -n 10` — find who built on this work.

## Recommended workflow for agents

1. Run `paperhound search "<query>" --json -n 5` to find candidates.
2. Read the JSON, pick the most relevant paper, capture
   `identifiers.arxiv_id` (preferred) or `identifiers.doi`.
3. If the user wants the abstract: `paperhound show <id> --json` and surface
   `title`, `authors`, `year`, `abstract`, `url`.
4. If the user wants the full text: `paperhound get <id> -o paper.md` and read
   the resulting file.

### Corpus-building workflow

```bash
# 1. Save a paper for offline access
paperhound add 1706.03762 --convert

# 2. In future sessions, search offline without API calls
paperhound grep "multi-head attention"

# 3. Browse the corpus
paperhound list
```

## Examples

```bash
# 1. Search and grab the most relevant arXiv id
paperhound search "diffusion transformers" -n 5 --json

# 2. Show the abstract
paperhound show 2401.12345 --json

# 3. Just download the PDF
paperhound download 1706.03762 -o ./papers/

# 4. Get markdown for an LLM-friendly version of a paper
paperhound get 1706.03762 -o attention.md
```

## Failure modes you should expect

- **No open-access PDF**: `download`/`get` exit 1 with `error: No open-access PDF found …`. Try Semantic Scholar (`paperhound show <id> --json`) and inspect `pdf_url`; if null, tell the user.
- **Unrecognized identifier**: `error: Unrecognized paper identifier: …`. Re-run `paperhound search` to find a canonical id.
- **Network/provider error**: aggregator silently drops failing providers, so search still returns results from whichever provider responded; warn the user only if the merged list is empty.
- **docling first run is slow**: it downloads model weights on first conversion. Don't retry; just wait.

## MCP server (optional)

paperhound ships a built-in MCP server. If you prefer direct MCP tool calls
over shell invocations, install the optional extra and wire it once:

```bash
pip install 'paperhound[mcp]'
```

Add to `~/.claude/settings.json` (or project-level `.claude/settings.json`):

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

The MCP server exposes the same operations as the CLI — `search`, `show`,
`download`, `convert`, `library_add`, `library_list`, `library_grep` — as
structured tool calls. Use the CLI skill **or** the MCP server, not both.

## Don'ts

- Don't shell out to `curl`/`requests` to fetch papers — `paperhound download` already handles redirects, streaming, and PDF URL resolution.
- Don't paste the full Markdown of a long paper into chat; write it to a file
  with `paperhound get -o …` and reference the path.
- Don't pass user-controlled strings as `--source` values without restricting
  them to the known set: `arxiv`, `openalex`, `dblp`, `crossref`,
  `huggingface` (alias `hf`), `semantic_scholar` (alias `s2`), `core`.
