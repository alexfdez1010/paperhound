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

## Commands

Always pass `--json` when you plan to consume the output programmatically.

### Search — unified across providers

```bash
paperhound search "<query>" [--limit N] [--year-min YYYY] [--year-max YYYY] [--source arxiv|openalex|dblp|crossref|huggingface|semantic_scholar|core] [--timeout SECONDS] [--json]
```

- Default `--limit` is 10. Cap it (e.g. `-n 5`) when the user asks for "a few".
- `--source` is repeatable; omit it to query the default set
  (arxiv + openalex + dblp + crossref + huggingface). Pass `-s s2` /
  `-s core` to opt into Semantic Scholar or CORE.
- `--timeout` defaults to 10s. Providers that exceed the budget are dropped
  from the response — the command still succeeds with whatever returned.
- JSON output is a list of objects with: `title`, `authors[]`, `abstract`,
  `year`, `venue`, `url`, `pdf_url`, `citation_count`,
  `identifiers.{arxiv_id,doi,semantic_scholar_id,openalex_id,dblp_key,core_id}`,
  `sources[]`.

### Show — abstract + metadata for a single paper

```bash
paperhound show <identifier> [--json]
```

- `<identifier>` accepts: arXiv id (`2401.12345`, `cs.AI/0301001`),
  DOI (`10.1234/foo.bar`), Semantic Scholar id (40-char hex), or any paper URL.

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

## Recommended workflow for agents

1. Run `paperhound search "<query>" --json -n 5` to find candidates.
2. Read the JSON, pick the most relevant paper, capture
   `identifiers.arxiv_id` (preferred) or `identifiers.doi`.
3. If the user wants the abstract: `paperhound show <id> --json` and surface
   `title`, `authors`, `year`, `abstract`, `url`.
4. If the user wants the full text: `paperhound get <id> -o paper.md` and read
   the resulting file.

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

## Don'ts

- Don't shell out to `curl`/`requests` to fetch papers — `paperhound download` already handles redirects, streaming, and PDF URL resolution.
- Don't paste the full Markdown of a long paper into chat; write it to a file
  with `paperhound get -o …` and reference the path.
- Don't pass user-controlled strings as `--source` values without restricting
  them to the known set: `arxiv`, `openalex`, `dblp`, `crossref`,
  `huggingface` (alias `hf`), `semantic_scholar` (alias `s2`), `core`.
