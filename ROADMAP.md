# paperhound roadmap

Eight improvements scheduled for the 0.4.x → 0.5.x range. Items land in
order, each as its own version bump + release. Two prior brainstorm
ideas (watch / feed mode and parallel batch ingest) are intentionally
omitted from this roadmap.

## 1. Local library + SQLite index

Persistent per-user library at `~/.paperhound/library/` backed by
SQLite FTS5. New commands:

- `paperhound add <id>` — fetch metadata + (optionally) markdown,
  insert into the index.
- `paperhound list` — list everything in the library.
- `paperhound grep <query>` — full-text search the local corpus
  offline.
- `paperhound rm <id>` — remove an entry.

Goal: cut redundant API hits and let users build a personal corpus.

## 2. MCP server mode

`paperhound mcp` exposes search / show / download as MCP tools so
Claude Code and other agents can call paperhound directly without the
skill shim. Uses the `mcp` Python SDK over stdio.

## 3. Citation graph traversal

OpenAlex and Semantic Scholar expose references and citations. Add:

- `paperhound refs <id>` — list works the paper cites.
- `paperhound cited-by <id>` — list works that cite the paper.
- `--depth N` to traverse a small neighborhood (capped, polite to APIs).

Unlocks lightweight literature-review workflows.

## 4. Citation export (BibTeX / RIS / CSL-JSON)

`paperhound show <id> --format bibtex|ris|csljson|markdown`. Default
remains markdown. Drop-in for Zotero, pandoc, LaTeX users.

## 5. Structured JSONL output

`--json` flag on `search` and `show` emits one paper per line. Enables
shell pipelines (`paperhound search ... --json | jq ...`) and clean
downstream LLM ingestion. Rich-text output stays the default.

## 6. Embedding rerank

After the round-robin aggregator merge, optionally rerank the top-K
results by cosine similarity between the query and each abstract.
Local first (sentence-transformers if installed), fall back gracefully
when the optional dep is missing. New flag: `--rerank`.

## 7. Filter DSL at search

Push filters to providers that support them, client-side fallback
otherwise:

- `--year 2023-2026`
- `--min-citations 50`
- `--venue NeurIPS`
- `--author "Hinton"`

## 8. Better PDF → Markdown

Today docling drops equations and butchers tables. Add:

- `--with-figures` — extract images alongside the markdown.
- `--equations latex` — preserve math as LaTeX.
- `--tables markdown|html` — keep table fidelity.

Big quality jump for downstream LLM consumption of the markdown.

## Process

Each item ships as: implementation + unit tests + `make check` green +
patch version bump in `pyproject.toml` + conventional-commit + push to
`main` (CI auto-publishes to PyPI on the new version). Items land in
the order above.
