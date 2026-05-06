# Smoke report — paperhound 0.3.0

Date: 2026-05-06
Tester: manual run via global `uv tool` install (upgraded from 0.1.0 → 0.3.0).
Scratch dir: `/tmp/ph-smoke`.

## Versions

- Global binary before: 0.1.0 (stale)
- Global binary after `uv tool upgrade paperhound`: 0.3.0
- PyPI latest: 0.3.0
- `pyproject.toml` in repo: 0.3.0

## Walkthrough

| # | Command | Result | Notes |
|---|---|---|---|
| 1 | `search "retrieval augmented generation" -n 5` | ✅ exit 0, 3.2 s | All 5 rows from `crossref` only — no diversity |
| 2 | `search ... -n 5 -s arxiv` | ✅ 0.4 s, all 5 from arxiv | Single-source path fine |
| 3 | `search ... -n 5 -s arxiv -s openalex -s dblp -s hf` | ⚠️ 1.2 s, all 5 from arxiv | Multi-source merge does not interleave |
| 4 | `search "agentic workflows" -n 3` | ❌ all 3 from crossref, contains `&amp;` | Default merge starvation + entity leak |
| 5 | `search ... -n 20` | ❌ all 20 from huggingface | Same starvation, different winner |
| 6 | `show 2401.12345` | ✅ 0.7 s | Clean output |
| 7 | `download 2401.12345 -o ./papers` (no trailing `/`) | ❌ wrote 1.9 MB **file** named `papers` | UX trap |
| 8 | `download 2401.12345 -o ./papers/` | ✅ wrote `papers/2401.12345.pdf` | OK |
| 9 | `get 2005.11401 -o rag.md` | ✅ 78 s (cold), 70 KB Markdown | First-run pulls 26 MB OCR model + Loading-weights logs leak to stderr |
| 10 | `convert papers/2401.12345.pdf -o paper.md` | ✅ 13 s (warm) | One `RapidOCR returned empty result` warning — harmless |
| 11 | `search "" -n 3` | ❌ exit 0, 3 garbage crossref hits + 2 stderr warnings | Empty query should be rejected |
| 12 | `show invalid-id-zzz` | ✅ exit 1, "Not found" | Correct |
| 13 | `search "rare-string-no-match-zzzzzzzz12345" -n 3 -s arxiv` | ✅ "No results." | Correct |

## Findings (severity)

### S1 — Aggregator merge starves provider diversity (high)

`SearchAggregator.search` accumulates results in completion order, dedups, then
slices `[: limit]`. The first provider that returns ≥ `limit` results
monopolizes every slot. Crossref returns 100 results in ~3 s and almost always
fills the slice; HF Papers wins at higher `-n`. Net effect: the "5 sources, one
query" promise reduces in practice to "whichever source is fastest today".

Fix: round-robin / interleave. Take the first row of each provider, then the
second of each, etc., dedup as we go. Source diversity preserved; arxiv +
openalex + dblp + crossref + hf each surface 1-2 of the top 5.

Files: `src/paperhound/search/aggregator.py:88-110`.

### S1 — Empty query returns garbage (high)

`paperhound search ""` runs every provider with empty text. arxiv and HF raise
HTTP 400 (logged as WARNING); crossref dutifully returns 3 unrelated papers.
The CLI exits 0 and prints them. Caller has no signal that the query was
nonsense.

Fix: validate at the CLI boundary. Empty / whitespace-only → `BadParameter`.

Files: `src/paperhound/cli.py:141-196`.

### S2 — `download -o ./papers` (no slash, dir doesn't exist) makes a binary file (medium)

`Path("./papers")` is not a directory and has no suffix, so `download_pdf`
treats it as a file and writes 1.9 MB of PDF bytes to `./papers`. Users will
hit this — the help text even says "directory" and "file" without explaining
that the disambiguator is the trailing slash.

Fix: when the destination doesn't exist and has no suffix, treat it as a
directory (mkdir + name file by identifier). Existing slash-terminated and
suffix-bearing paths keep current behavior.

Files: `src/paperhound/download.py:47-75`.

### S2 — HTML entities leak into titles (medium)

Crossref returns titles with `&amp;`, `&lt;`, `&#x2014;` already-encoded. They
flow through to the Rich table verbatim. Likely affects abstracts too.

Fix: `html.unescape` titles + abstracts in `crossref._payload_to_paper`. Guard
the other providers behind unit tests in case any of them do the same.

Files: `src/paperhound/search/crossref.py:21-25, 51-77`.

### S3 — Provider warnings always reach stderr (low)

Root sets logging to `WARNING` by default, so every provider failure / timeout
prints to the user's terminal even on successful searches. Useful for `-v`,
noisy for happy-path use.

Fix: default level → `ERROR`; `-v` → `DEBUG`. Errors that the user actually
needs to see are already raised as `PaperhoundError`.

Files: `src/paperhound/cli.py:121-124`.

### Out of scope (not paperhound's bug)

- Docling first-run downloads ~26 MB OCR model and logs `Loading weights:` /
  `Warning: You are sending unauthenticated requests to the HF Hub` to stderr.
  Could be muted with stderr redirection inside `convert_to_markdown`, but
  hides legitimate errors. Leave alone.
- Docling occasionally emits `glyph[star]` markers for footnote symbols. Known
  upstream issue.

## Action plan

In this order, each in its own commit, each with a unit test that fails before
the change:

1. **fix(cli): reject empty/whitespace search queries** (S1)
2. **feat(aggregator): round-robin merge for provider diversity** (S1)
3. **fix(crossref): unescape HTML entities in titles and abstracts** (S2)
4. **feat(download): treat extension-less missing path as directory** (S2)
5. **chore(cli): default log level ERROR; verbose stays DEBUG** (S3)

Patch bump after each, or batch into a single 0.4.0 since (2) and (4) change
observable behavior. Going with 0.4.0 — round-robin is a behavior change for
any caller that relied on the old "fastest provider wins" ordering.
