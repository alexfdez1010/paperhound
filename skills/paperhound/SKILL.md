---
name: paperhound
description: Use for ANY task involving academic / scientific / research papers via the `paperhound` CLI — search (arXiv, OpenAlex, DBLP, Crossref, HF Papers, Semantic Scholar, CORE), read abstracts, download PDFs, convert to Markdown, explore citations (refs / cited-by), export BibTeX/RIS/CSL-JSON, and manage a local library. Trigger on arXiv ids, DOIs, paper URLs, or phrases like "find papers", "summarize this paper", "literature review", "what cites X", "BibTeX for X". Prefer over `curl`, `requests`, or raw `arxiv` for paper tasks.
---

# paperhound — paper search and conversion CLI

`paperhound` is a small CLI that queries up to seven academic providers in
parallel under a 10-second budget, resolves identifiers (arXiv id, DOI, S2 id,
OpenAlex id, paper URL), downloads PDFs, and converts them to Markdown via
[docling](https://github.com/docling-project/docling). Results are merged
round-robin (top-N has source diversity, not just the fastest provider) and
deduplicated. It also keeps a local SQLite library so you can build an
offline corpus across sessions.

This skill is **the** way to fetch papers. Don't shell out to `curl`,
`requests`, `arxiv.py`, etc. — `paperhound` already handles redirects,
streaming, PDF URL resolution, and metadata-poisoning detection.

## Setup check

```bash
paperhound version            # confirm install
pip install paperhound        # or: uv tool install paperhound
```

Optional extras: `pip install 'paperhound[rerank]'` enables embedding
rerank on `search` (on by default when installed).

## When to trigger

Trigger this skill when the user asks for any of:

- **Search**: "find/search papers about X", "papers from 2024 on X"
- **Read**: "abstract of arXiv 2401.12345", "what is paper X about"
- **Fetch**: "download this paper", "convert this PDF to Markdown"
- **Ingest**: "give me a Markdown version so I can read/quote it"
- **Library**: "save paper X", "search my library for Y", "list saved papers"
- **Graph**: "what does X cite", "who cites X", "related work for X"
- **Cite**: "BibTeX for X", "RIS / CSL-JSON for X"

## Core principle for agents

**Always pass `--json` when the output will be parsed by code or another LLM
turn.** The default Markdown rendering uses `rich` styling that is hard to
parse and context-heavy. JSON output is stable, compact, and deterministic.

| Command | `--json` shape |
|---|---|
| `search`, `refs`, `cited-by` | **JSONL** — one `Paper` per line |
| `show` | **single JSON object** (one `Paper`) |
| `add`, `list`, `grep`, `rm`, `download`, `convert`, `get` | no `--json`; use `show --json` for metadata, or read the produced file |

## Decision tree

```
User wants…                            → Run

a list of candidates on a topic        → search "<query>" --json -n 5
metadata/abstract for a known id       → show <id> --json
the PDF on disk                        → download <id> -o ./papers/
the full text in Markdown              → get <id> -o paper.md
to save it across sessions             → add <id> --convert
to find prior work / related work      → refs <id> --json -n 10
to find follow-up work                 → cited-by <id> --json -n 10
a citation entry                       → show <id> --format bibtex|ris|csljson
to query the local corpus offline      → grep "<query>"
```

## Quick recipes (copy-paste-ready)

```bash
# 1. Find candidates and capture the top arXiv id with jq
paperhound search "speculative decoding" --json -n 5 \
  | jq -r 'select(.identifiers.arxiv_id) | .identifiers.arxiv_id' | head -1

# 2. Read an abstract for an LLM turn
paperhound show 2401.12345 --json | jq '{title, year, abstract}'

# 3. Pull the full paper into the model's context as a file path
paperhound get 1706.03762 -o /tmp/attention.md
# → then Read /tmp/attention.md

# 4. Save to library and grep offline next session
paperhound add 1706.03762 --convert
paperhound grep "multi-head attention"
```

## Reference files (read on demand)

The full surface lives in `reference/*.md`. Load only the file you need
for the task at hand:

- **`reference/commands.md`** — every command, every flag, every option.
  Read this when you need a flag you don't remember (filters, formats,
  rerank, sources, depth, timeouts).
- **`reference/json-schema.md`** — the `Paper` JSON schema, JSONL vs
  single-object rules, and `jq` recipes. Read this when parsing output
  programmatically.
- **`reference/workflows.md`** — multi-step recipes for common agent
  tasks: literature review, corpus building, citation-graph exploration,
  paper-summarization pipelines, BibTeX export. Read this when the user
  asks for a goal larger than one command.
- **`reference/troubleshooting.md`** — failure modes (no open-access PDF,
  unrecognized identifier, metadata poisoning, slow first docling run,
  rate limits) and how to recover. Read this when a command fails or
  returns surprising data.

## Hard rules

- **Don't** shell out to `curl`/`requests`/raw `arxiv` to fetch papers —
  `paperhound download`/`get` already does this correctly.
- **Don't** paste the full Markdown of a long paper into chat — write it to
  a file with `paperhound get -o …` and reference the path.
- **Don't** pass user-controlled strings as `--source` without restricting
  them to: `arxiv`, `openalex`, `dblp`, `crossref`, `huggingface` (alias
  `hf`), `semantic_scholar` (alias `s2`), `core`.
- **Don't** retry on the first slow `convert` — docling is downloading model
  weights (~hundreds of MB). Wait, don't loop.
- **Don't** invent flags. If a flag isn't in `reference/commands.md`, it
  doesn't exist — verify with `paperhound <cmd> --help` if unsure.
