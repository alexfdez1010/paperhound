# 🐍 Using paperhound from Python

Every CLI command in paperhound is a thin wrapper around a public Python
API. This page documents the library entry points so you can drive
paperhound from your own scripts, notebooks, or services.

## Installation

```bash
pip install paperhound
# or
uv add paperhound
```

For embedding rerank support:

```bash
pip install 'paperhound[rerank]'
```

Python 3.10+ is required. Docling pulls in PyTorch on first run, so the
very first PDF conversion may take a moment to download model weights.

## Quick start

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
under the hood, so you get autocomplete, `model_dump(mode="json")`,
validation, and stable field names across providers.

## Building a corpus

```python
from paperhound import Library, search_papers

lib = Library()                   # ~/.paperhound/library/ by default
for hit in search_papers("vision language models", limit=20):
    lib.add(hit)                  # idempotent — re-adds update in place

# Offline full-text search later, no API calls.
hits = lib.grep("multi-head attention", limit=10)
for h in hits:
    print(h.id, h.title)
```

## Citation graph

```python
from paperhound.citations import fetch_references, fetch_citations

refs   = fetch_references("1706.03762", depth=1, limit=10)
citing = fetch_citations("1706.03762", depth=2, limit=50)
```

## Rerank

When the `rerank` extra is installed, library callers opt in explicitly:

```python
from paperhound import search_papers
from paperhound.rerank import rerank

candidates = search_papers("agentic workflows", limit=30)
ranked = rerank("agentic workflows", candidates, model_name=None)
```

`model_name=None` uses the default `sentence-transformers/all-MiniLM-L6-v2`.
The CLI runs rerank automatically; the library does not.

## API reference

The top-level package re-exports the symbols you need most often:

| Symbol | Purpose |
|---|---|
| `paperhound.search_papers(query, limit=10, sources=None, **filters)` | Run a unified search; returns `list[Paper]`. |
| `paperhound.get_paper(identifier)` | Resolve an id/DOI/URL to a single `Paper`, or `None`. |
| `paperhound.convert_to_markdown(src, output=None, options=None)` | PDF/URL → Markdown via docling. |
| `paperhound.pdf_to_markdown(...)` | Lower-level PDF-only entry point. |
| `paperhound.Paper`, `Author`, `PaperIdentifier` | Pydantic models. |
| `paperhound.Library` | SQLite FTS5 library wrapper. |

Need finer control? Drop into the underlying modules:

- `paperhound.search` — provider registry, `SearchAggregator`,
  `SearchQuery`, `SearchProvider` base class. Plug in your own provider
  with one `register("name", Factory)` call.
- `paperhound.download` — `resolve_pdf_url`, `download_pdf`.
- `paperhound.convert` — `ConversionOptions`, `convert_to_markdown`.
- `paperhound.citations` — `fetch_references`, `fetch_citations`.
- `paperhound.rerank` — optional, requires the `rerank` extra.
- `paperhound.errors` — `PaperhoundError`, `ProviderError`,
  `LibraryError`, `RerankError`. Every other exception bubbles untouched.

## Adding a new provider

`paperhound.search` is a registry of provider factories. To add a new
source:

1. Create `src/paperhound/search/<name>.py` with a class subclassing
   `SearchProvider`. Declare its `capabilities` (`TEXT_SEARCH`,
   `ID_LOOKUP`, `OPEN_ACCESS_PDF`) and override `available()` if it
   needs an API key.
2. Add unit tests in `tests/unit/test_<name>.py` that mock HTTP with
   `respx`.
3. Register it in `src/paperhound/search/__init__.py` with one
   `register("name", Factory)` call. Done — the CLI picks it up
   automatically.
