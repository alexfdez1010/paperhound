"""arXiv search provider built on the ``arxiv`` library."""

from __future__ import annotations

import arxiv

from paperhound.errors import ProviderError
from paperhound.identifiers import normalize_arxiv
from paperhound.models import Author, Paper, PaperIdentifier
from paperhound.search.base import SearchProvider, SearchQuery


def _result_to_paper(result: arxiv.Result) -> Paper:
    arxiv_id = result.get_short_id()
    # The "short id" includes a version suffix; strip it for the canonical form.
    canonical = arxiv_id.split("v")[0] if "v" in arxiv_id else arxiv_id
    return Paper(
        title=(result.title or "").strip(),
        authors=[Author(name=str(a)) for a in result.authors],
        abstract=(result.summary or "").strip() or None,
        year=result.published.year if result.published else None,
        venue="arXiv",
        publication_type="preprint",
        url=result.entry_id,
        pdf_url=result.pdf_url,
        identifiers=PaperIdentifier(arxiv_id=canonical, doi=result.doi or None),
        sources=["arxiv"],
    )


class ArxivProvider(SearchProvider):
    """Wraps :mod:`arxiv` to expose a ``SearchProvider`` interface."""

    name = "arxiv"
    description = (
        "arXiv preprint server (CS, math, physics, quant-bio, ...). Authoritative"
        " source for arXiv ids and the canonical PDF mirror."
    )
    homepage = "https://arxiv.org/"

    def __init__(self, client: arxiv.Client | None = None) -> None:
        self._client = client or arxiv.Client(page_size=50, delay_seconds=3, num_retries=3)

    def search(self, query: SearchQuery) -> list[Paper]:
        terms = [query.text]
        if query.year_min or query.year_max:
            lo = f"{query.year_min}0101" if query.year_min else "00000101"
            hi = f"{query.year_max}1231" if query.year_max else "99991231"
            terms.append(f"submittedDate:[{lo} TO {hi}]")
        search = arxiv.Search(
            query=" AND ".join(terms),
            max_results=max(1, query.limit),
            sort_by=arxiv.SortCriterion.Relevance,
        )
        try:
            return [_result_to_paper(r) for r in self._client.results(search)]
        except Exception as exc:
            raise ProviderError(f"arXiv search failed: {exc}") from exc

    def get(self, identifier: str) -> Paper | None:
        try:
            arxiv_id = normalize_arxiv(identifier)
        except Exception as exc:
            raise ProviderError(f"Not a valid arXiv id: {identifier!r}") from exc
        try:
            search = arxiv.Search(id_list=[arxiv_id])
            results = list(self._client.results(search))
        except Exception as exc:
            raise ProviderError(f"arXiv lookup failed: {exc}") from exc
        if not results:
            return None
        return _result_to_paper(results[0])
