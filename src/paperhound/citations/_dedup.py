"""Citation-graph dedup helpers (kept compatible with the search aggregator)."""

from __future__ import annotations

from paperhound.models import Paper


def dedup_key(paper: Paper) -> str:
    """Pick the best key to detect duplicates across citation backends."""
    ids = paper.identifiers
    if ids.arxiv_id:
        return f"arxiv:{ids.arxiv_id}"
    if ids.doi:
        return f"doi:{ids.doi.lower()}"
    if ids.openalex_id:
        return f"openalex:{ids.openalex_id}"
    if ids.semantic_scholar_id:
        return f"s2:{ids.semantic_scholar_id}"
    return f"title:{paper.title.lower().strip()}"


def deduplicate(papers: list[Paper]) -> list[Paper]:
    """Merge duplicates while preserving first-seen order."""
    seen: dict[str, Paper] = {}
    order: list[str] = []
    for paper in papers:
        key = dedup_key(paper)
        if key in seen:
            seen[key] = seen[key].merge(paper)
        else:
            seen[key] = paper
            order.append(key)
    return [seen[k] for k in order]
