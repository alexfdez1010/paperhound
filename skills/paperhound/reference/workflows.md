# Workflow recipes

End-to-end patterns for the goals an LLM agent typically gets asked. Each
section is independent — read only the one you need.

---

## 1. Answer "what is paper X about?"

Given an id, DOI, or URL.

```bash
paperhound show <id> --json | jq '{title, authors: [.authors[].name], year, venue, abstract, url}'
```

**Use the JSON object directly in the response** — don't re-render Markdown
from it; the user just wants title + authors + year + abstract + URL.

If the abstract is `null`, fall back to fetching the full paper:

```bash
paperhound get <id> -o /tmp/paper.md
# Then Read /tmp/paper.md and summarize the introduction.
```

---

## 2. Find candidates on a topic ("a few papers about X")

```bash
paperhound search "<topic>" --json -n 5
```

For each line, surface to the user: `title`, `authors[0..2]`, `year`,
`identifiers.arxiv_id // identifiers.doi`, and a short reason from the
abstract.

**Tighten the query when filters help**:

```bash
# Recent papers with non-trivial impact
paperhound search "<topic>" --json -n 10 --year 2023- --min-citations 20

# Specific venue
paperhound search "<topic>" --json -n 10 --venue "NeurIPS"

# Specific author
paperhound search "<topic>" --json -n 10 --author "LeCun"
```

**Boost relevance** with embedding rerank (default-on if installed):

```bash
pip install 'paperhound[rerank]'   # one-time
paperhound search "<topic>" --json -n 10           # rerank on
paperhound search "<topic>" --json -n 10 --no-rerank   # baseline
```

---

## 3. Read a paper into the model's context

The right pattern is **write to a file, then `Read` the file** — never paste
the full Markdown into chat.

```bash
paperhound get <id> -o /tmp/<short-name>.md
```

Then `Read /tmp/<short-name>.md` (use `offset`/`limit` for large papers).
The file persists for the session and is cheap to re-read.

If the user only needs a section (intro, related work, results), still
download the full Markdown — `Read` lets you target line ranges, and that
is cheaper than re-querying.

---

## 4. Literature review — "summarize the work on X"

Two-pass pattern: shallow scan, then targeted deep reads.

```bash
# Pass 1: broad scan, capture ids
paperhound search "<topic>" --json -n 20 --year 2022- \
  | jq -r '.identifiers.arxiv_id // .identifiers.doi // empty' \
  > /tmp/lit_ids.txt

# Pass 2: deep read the most relevant 3-5 (after you've ranked them from titles/abstracts)
while read id; do
  paperhound show "$id" --json
done < /tmp/lit_ids.txt | jq -s '.'    # array of Paper objects in memory
```

When the user wants the **citation network**:

```bash
# What does the seminal paper cite?
paperhound refs <seed-id> --json -n 15 --depth 2

# Who built on it?
paperhound cited-by <seed-id> --json -n 15 --depth 2
```

`--depth 2` is BFS one hop further; capped at `limit*2` to bound cost.

---

## 5. Build an offline corpus across sessions

The library is the right place when the user expects the work to persist
across conversations or across days.

```bash
# Save metadata + full Markdown
paperhound add 1706.03762 --convert
paperhound add 2005.14165 --convert
paperhound add 2201.11903 --convert

# In a later session, browse:
paperhound list

# Search the corpus offline (FTS5 on title + abstract + body):
paperhound grep "chain of thought"
paperhound grep "in-context learning" --limit 5
```

The corpus lives at `~/.paperhound/library/` (override with
`PAPERHOUND_LIBRARY_DIR`). It's append-only from the agent's POV unless the
user asks you to `paperhound rm`.

---

## 6. Citation export (BibTeX, RIS, CSL-JSON)

```bash
# BibTeX — paste into a .bib file or LaTeX preamble
paperhound show 1706.03762 --format bibtex

# RIS — for Zotero / Mendeley / EndNote
paperhound show 1706.03762 --format ris

# CSL-JSON — for Pandoc with --citeproc
paperhound show 1706.03762 --format csljson
```

Batch export (e.g., from a search result set):

```bash
paperhound search "<topic>" --json -n 20 \
  | jq -r '.identifiers.arxiv_id // .identifiers.doi // empty' \
  | while read id; do paperhound show "$id" --format bibtex; done \
  > refs.bib
```

`--format` and `--json` are mutually exclusive — pick one per invocation.

---

## 7. Convert a local PDF the user already has

```bash
paperhound convert ./paper.pdf -o ./paper.md \
  --with-figures --equations latex --tables html
```

- `--with-figures` extracts images to `paper_assets/` and inserts `![](...)`
  references. Only works with `-o`.
- `--equations latex` keeps math as LaTeX (`$...$` / `$$...$$`).
- `--tables html` for papers with merged/irregular cells.

URLs work too: `paperhound convert https://arxiv.org/pdf/1706.03762`.

---

## 8. "Find me the PDF and nothing else"

```bash
paperhound download <id> -o ./papers/
```

The file is named after the identifier and lands in `./papers/` (created
if missing). Use this when the user wants the raw PDF (e.g., to print, to
attach to email, to feed to a different tool).

---

## 9. Pipelines worth knowing

```bash
# Top-cited paper from a search, then download:
ID=$(paperhound search "RAG" --json -n 50 \
       | jq -r 'select(.citation_count != null) | .citation_count as $c
                | [$c, .identifiers.arxiv_id // .identifiers.doi] | @tsv' \
       | sort -rn | head -1 | cut -f2)
paperhound get "$ID" -o /tmp/top.md

# Co-citation: papers that both X and Y cite
paperhound refs <X> --json -n 50 > /tmp/x.jsonl
paperhound refs <Y> --json -n 50 > /tmp/y.jsonl
jq -s 'def ids: map(.identifiers.doi // .identifiers.arxiv_id // empty);
       (.[0] | ids) as $a | (.[1] | ids) as $b | $a - ($a - $b)' \
   /tmp/x.jsonl /tmp/y.jsonl
```
