# Troubleshooting

Diagnose and recover from common failures. Read this when a command exits
non-zero, returns empty results, or returns surprising data.

---

## 1. `error: No open-access PDF found …`

`download` / `get` exit 1 when there is no OA PDF link. The metadata
record exists, but the upstream provider doesn't expose a PDF URL.

**Recover**:

```bash
# 1. Inspect what the providers know
paperhound show <id> --json | jq '{pdf_url, url, identifiers}'

# 2. If pdf_url is null but url points to the publisher, tell the user:
#    "There's no open-access PDF — only the publisher landing page at <url>."
# 3. If the paper has a DOI but no arXiv id, try a search by title to find an arXiv preprint:
paperhound search "<paper title>" --json -n 5 \
  | jq 'select(.identifiers.arxiv_id) | .identifiers.arxiv_id'
```

Don't loop the download — there is no OA copy to fetch.

---

## 2. `error: Unrecognized paper identifier: …`

The string didn't match any known identifier shape (arXiv, DOI, S2 hex,
OpenAlex, paper URL). Common causes: typo, raw title, OpenReview id (not
yet supported).

**Recover**:

```bash
paperhound search "<the title or topic>" --json -n 5
# Then pick identifiers.arxiv_id / .doi from the result.
```

---

## 3. Empty result list

`search` always exits 0 — empty stdout means no provider returned a hit
within the budget.

**Recover**:

1. **Loosen filters** — drop `--year`, `--min-citations`, `--venue`,
   `--author` one at a time.
2. **Widen sources** — add `-s s2 -s core`.
3. **Raise the timeout** — `--timeout 20` for slow days.
4. **Try keywords closer to the paper's vocabulary** — academic search
   indexes don't expand synonyms; "LLM agents" finds different papers
   than "large language model agents".

---

## 4. Wrong abstract / wrong title (metadata poisoning)

OpenAlex / Crossref occasionally return junk records that hijacked an
identifier slot. paperhound auto-detects this by cross-checking titles
between providers and dropping mismatches, but the heuristic isn't
perfect for borderline cases.

**Recover** — force the canonical source:

```bash
# arXiv ids → trust arXiv
paperhound show 2001.08361 -s arxiv --json

# DOIs → trust Crossref
paperhound show 10.1234/foo -s crossref --json
```

`-s` is repeatable; pass two trusted sources for cross-validation.

---

## 5. Rate-limited / 403 / 429

Providers throttle aggressive use:

- **Semantic Scholar** returns `403` if the API key is invalid, `429` if
  you're hitting the unauthenticated limit. paperhound retries with
  backoff and surfaces the underlying message.
- **OpenAlex / Crossref** are best-effort polite by default.
- **arXiv** has soft rate limits via the `arxiv` Python client.

**Recover**:

1. **Wait** — rate limits are short (seconds to a minute).
2. **Drop the slow provider** — `-s arxiv -s openalex` excludes Semantic
   Scholar / CORE for one call.
3. **Set an S2 API key** if you have one: `export
   SEMANTIC_SCHOLAR_API_KEY=...` (paperhound picks it up via env).
4. **Don't loop** — the aggregator already handles transient failures by
   silently dropping that provider for the call.

---

## 6. `convert` first run is slow / appears to hang

docling downloads model weights (hundreds of MB) on first use. This is
**expected** and one-time.

**Don't**:

- Cancel and retry — you'll re-trigger the download.
- Pipe output to `head` and assume it failed.

**Do**:

- Wait. Subsequent runs are seconds.
- If the user is impatient, skip `convert` and use `show --json`'s
  abstract for a one-line answer.

---

## 7. Library can't write / locked

Symptoms: `LibraryError: database is locked` or permission errors.

**Recover**:

```bash
# Check the library dir
ls -la ~/.paperhound/library/

# Override location for this session
export PAPERHOUND_LIBRARY_DIR=/tmp/ph-lib
paperhound list
```

Concurrent `paperhound add` from multiple shells can briefly lock SQLite.
Wait a second, retry once.

---

## 8. Embedding rerank not running

`search` silently falls back to merge order when the `rerank` extra is
missing (no error). Confirm install:

```bash
python -c "import sentence_transformers; print(sentence_transformers.__version__)"
```

If missing:

```bash
pip install 'paperhound[rerank]'
```

For deterministic comparison: pass `--no-rerank` to disable for one call.

---

## 9. Long titles wrap weirdly in non-JSON mode

Default Markdown rendering uses Rich panels. If output looks broken in a
narrow terminal or in a non-TTY context, switch to `--json` — it never
wraps, never colors, and is always one line per record (or one object for
`show`).

---

## 10. Identifier kinds and what they look like

| Kind | Example | Notes |
|---|---|---|
| arXiv (new) | `2401.12345`, `2401.12345v3` | 4 digits + `.` + 5 digits, optional `vN`. |
| arXiv (old) | `cs.AI/0301001` | category + slash + 7 digits. |
| DOI | `10.1234/foo.bar` | starts with `10.`. |
| Semantic Scholar | 40-char lowercase hex | e.g. `0796f6cd7f0403a854d67d525e9b32af3b277331`. |
| OpenAlex | `W2741809807` | `W` + digits. |
| URL | `https://arxiv.org/abs/...`, `https://doi.org/...`, `https://www.semanticscholar.org/paper/...` | resolver extracts the underlying id. |

When the user gives you a noisy string, prefer the regex above to decide
the kind before calling the CLI. paperhound itself will accept all of
them, but knowing the kind helps you pick `-s` to avoid poisoning.
