# JSON output reference

`paperhound` emits one shape: the `Paper` object, defined by
`paperhound.models.Paper` (Pydantic). Two emit modes:

- **JSONL** — one compact `Paper` per line (no indent, no array wrapper).
  Used by `search`, `refs`, `cited-by`. Parse with `for line in stdout:
  json.loads(line)` or `jq -c .`.
- **Single object** — one compact `Paper` on a single line. Used by
  `show --json`.

No command emits a JSON array. Library commands (`add`, `list`, `grep`,
`rm`) have no `--json` flag — use `show --json` for metadata.

## `Paper` schema

```jsonc
{
  "title":            "string",                   // required, whitespace-collapsed
  "authors": [
    { "name": "string", "affiliation": "string|null" }
  ],
  "abstract":         "string|null",              // whitespace-collapsed
  "year":             "integer|null",
  "venue":            "string|null",
  "url":              "string|null",              // landing page
  "pdf_url":          "string|null",              // direct PDF, when known
  "citation_count":   "integer|null",             // null = unknown (not 0)
  "identifiers": {
    "arxiv_id":            "string|null",         // e.g. "2401.12345" or "cs.AI/0301001"
    "doi":                 "string|null",         // e.g. "10.1234/foo.bar"
    "semantic_scholar_id": "string|null",         // 40-char hex
    "openalex_id":         "string|null",         // e.g. "W2741809807"
    "dblp_key":            "string|null",
    "core_id":             "string|null"
  },
  "sources": ["arxiv", "openalex", ...]           // providers that contributed to this record
}
```

### Field semantics

| Field | Notes |
|---|---|
| `title` | Always present and non-empty. Newlines/tabs collapsed to single spaces. |
| `authors[].name` | Plain string, provider-formatted (`"Vaswani, Ashish"` or `"Ashish Vaswani"` depending on source). |
| `abstract` | May be `null` if the provider doesn't return one. Treat `null` as "unknown" not "empty". |
| `citation_count` | `null` ≠ 0. Filters that require a known count exclude `null` rows. |
| `identifiers` | At least one is non-null when the record came from a provider; `identifiers.primary()` (server-side) prefers `arxiv_id` → `doi` → `semantic_scholar_id` → `openalex_id` → `dblp_key` → `core_id`. |
| `sources` | Sorted, deduped list of providers that contributed fields after merge. Useful for trust scoring. |

### Stability

- Field names are stable across patch versions.
- Adding new optional fields is **not** a breaking change. Don't fail your
  parser on unknown keys.
- Removing fields is a breaking change and only happens on a minor bump.

## `jq` recipes

```bash
# Get the top arXiv id from a search
paperhound search "diffusion transformers" --json -n 5 \
  | jq -r 'select(.identifiers.arxiv_id) | .identifiers.arxiv_id' | head -1

# Pull title + year + abstract for an LLM turn
paperhound show 2401.12345 --json | jq '{title, year, abstract}'

# Filter to highly-cited papers from a search
paperhound search "RAG" --json -n 50 \
  | jq -c 'select(.citation_count != null and .citation_count >= 100)'

# Extract DOIs only
paperhound search "..." --json -n 20 \
  | jq -r '.identifiers.doi // empty'

# Build a CSV: id,title,year
paperhound refs 1706.03762 --json -n 20 \
  | jq -r '[.identifiers.arxiv_id // .identifiers.doi // "", .title, (.year // "")] | @csv'

# Count results by provider
paperhound search "RAG" --json -n 50 \
  | jq -r '.sources[]' | sort | uniq -c | sort -rn
```

## Python parsing

```python
import json, subprocess

# search → JSONL
out = subprocess.check_output(
    ["paperhound", "search", "speculative decoding", "--json", "-n", "5"],
    text=True,
)
papers = [json.loads(line) for line in out.splitlines() if line.strip()]

# show → single object
out = subprocess.check_output(
    ["paperhound", "show", "2401.12345", "--json"], text=True,
)
paper = json.loads(out)
```

## Picking an identifier from a `Paper`

When you need a stable id to pass to a follow-up command, prefer in order:

1. `identifiers.arxiv_id` — most direct for `download`/`get`, no API roundtrip.
2. `identifiers.doi` — universal but requires OA-PDF resolution.
3. `identifiers.semantic_scholar_id` — works everywhere paperhound looks up.
4. `identifiers.openalex_id` — works for `show`, `refs`, `cited-by`.
5. `url` — last resort; the resolver accepts paper URLs.

Avoid building queries from `title` alone; titles aren't unique and reverse
lookup isn't deterministic.
