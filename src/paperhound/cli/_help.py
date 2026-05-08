"""Long-form help epilogs shared by the typer app and individual commands.

Click's ``\b`` marker (on its own line, with blank lines around the paragraph)
tells the help formatter not to rewrap the following block — preserves manual
line breaks in examples.
"""

from __future__ import annotations

ROOT_EPILOG = (
    "Examples:\n"
    "\n"
    "\b\n"
    '  paperhound search "retrieval augmented generation" -n 5\n'
    '  paperhound search "diffusion models" --year 2022-2024 --min-citations 100\n'
    '  paperhound search "transformers" --venue NeurIPS --author Vaswani\n'
    '  paperhound search "llm agents" --json | jq .title\n'
    "  paperhound show 2401.12345\n"
    "  paperhound show 2401.12345 -s arxiv\n"
    "  paperhound show 2401.12345 --json\n"
    "  paperhound show 2401.12345 --format bibtex\n"
    "  paperhound show 2401.12345 --format ris\n"
    "  paperhound show 2401.12345 --format csljson\n"
    "  paperhound download 10.48550/arXiv.2401.12345 -o ./papers\n"
    "  paperhound convert paper.pdf -o paper.md\n"
    "  paperhound convert paper.pdf -o paper.md --with-figures --equations latex --tables html\n"
    "  paperhound get 2401.12345 -o rag.md\n"
    "  paperhound add 2401.12345 --convert\n"
    "  paperhound list\n"
    '  paperhound grep "attention mechanism"\n'
    "  paperhound rm 2401.12345\n"
    "  paperhound refs 1706.03762 --depth 2\n"
    "  paperhound cited-by 1706.03762 --limit 10\n"
    "  paperhound providers\n"
    "  paperhound providers --json\n"
    "\n"
    "\b\n"
    "Sources:     arxiv, openalex, dblp, crossref, huggingface (alias: hf),\n"
    "             semantic_scholar (alias: s2), core. Defaults to arxiv +\n"
    "             openalex + dblp + crossref + huggingface (parallel, 10s\n"
    "             budget; round-robin merge across providers; partial\n"
    "             results returned on timeout).\n"
    "Filters:     --year RANGE (2023, 2023-2026, 2023-, -2026), --min-citations N,\n"
    "             --venue STRING (case-insensitive substring), --author STRING,\n"
    "             --type {journal,conference,preprint,book,other} (repeatable),\n"
    "             --peer-reviewed (= journal+conference+book),\n"
    "             --preprints-only (= preprint).\n"
    "             Pushed down to OpenAlex, Crossref, and Semantic Scholar;\n"
    "             applied client-side for all providers after merge.\n"
    "             Papers with unknown publication type are excluded when\n"
    "             --type / --peer-reviewed / --preprints-only is set.\n"
    "Identifiers: arXiv id (2401.12345), DOI, Semantic Scholar id, or paper URL.\n"
    "Library:     ~/.paperhound/library/ (override: PAPERHOUND_LIBRARY_DIR).\n"
    "JSON output: search --json emits JSONL (one Paper object per line);\n"
    "             show --json emits a single compact JSON object.\n"
    "             Schema: paperhound.models.Paper (model_dump mode='json').\n"
    "Rerank:      on by default when paperhound[rerank] is installed.\n"
    "             Install: pip install 'paperhound[rerank]'.\n"
    "             Disable for one call with --no-rerank.\n"
    "Convert:     --with-figures saves images to <stem>_assets/ (requires -o).\n"
    "             --equations latex  preserves math as $...$ / $$...$$.\n"
    "             --tables html      embeds <table> blocks instead of GFM tables.\n"
    "Docs:        https://github.com/alexfdez1010/paperhound"
)

ROOT_HELP = (
    "Search, download, and convert academic papers from the command line.\n\n"
    "Aggregates arXiv, OpenAlex, DBLP, Crossref, Hugging Face Papers"
    " (and optionally Semantic Scholar / CORE) in parallel, then converts"
    " PDFs to Markdown via docling."
)
