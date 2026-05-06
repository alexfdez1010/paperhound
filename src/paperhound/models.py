"""Domain models shared across the package."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field


@dataclass
class SearchFilters:
    """Optional filters applied to a search (push-down where supported, client-side otherwise).

    Missing fields on a Paper (None values) are treated as follows:
    - year_min / year_max: paper is kept (we cannot verify the filter).
    - min_citations: paper is excluded (conservative — user asked for a floor).
    - venue / author: paper is kept (we cannot verify the filter).
    """

    year_min: int | None = None
    year_max: int | None = None
    min_citations: int | None = None
    venue: str | None = None
    author: str | None = None

    def is_empty(self) -> bool:
        return all(
            v is None
            for v in (self.year_min, self.year_max, self.min_citations, self.venue, self.author)
        )


class Author(BaseModel):
    """A paper author."""

    name: str
    affiliation: str | None = None


class PaperIdentifier(BaseModel):
    """All known identifiers for a paper."""

    arxiv_id: str | None = None
    doi: str | None = None
    semantic_scholar_id: str | None = None
    openalex_id: str | None = None
    dblp_key: str | None = None
    core_id: str | None = None

    def primary(self) -> str:
        """Return the most stable identifier available."""
        return (
            self.arxiv_id
            or self.doi
            or self.semantic_scholar_id
            or self.openalex_id
            or self.dblp_key
            or self.core_id
            or ""
        )

    def is_empty(self) -> bool:
        return not self.primary()


class Paper(BaseModel):
    """Normalized representation of a paper across providers."""

    title: str
    authors: list[Author] = Field(default_factory=list)
    abstract: str | None = None
    year: int | None = None
    venue: str | None = None
    url: str | None = None
    pdf_url: str | None = None
    citation_count: int | None = None
    identifiers: PaperIdentifier = Field(default_factory=PaperIdentifier)
    sources: list[str] = Field(default_factory=list)

    @property
    def primary_id(self) -> str:
        return self.identifiers.primary()

    def author_names(self) -> list[str]:
        return [a.name for a in self.authors]

    def merge(self, other: Paper) -> Paper:
        """Combine two records of the same paper, preferring richer fields."""
        merged = self.model_copy(deep=True)
        merged.abstract = self.abstract or other.abstract
        merged.year = self.year or other.year
        merged.venue = self.venue or other.venue
        merged.url = self.url or other.url
        merged.pdf_url = self.pdf_url or other.pdf_url
        merged.citation_count = (
            self.citation_count if self.citation_count is not None else other.citation_count
        )
        merged.identifiers = PaperIdentifier(
            arxiv_id=self.identifiers.arxiv_id or other.identifiers.arxiv_id,
            doi=self.identifiers.doi or other.identifiers.doi,
            semantic_scholar_id=self.identifiers.semantic_scholar_id
            or other.identifiers.semantic_scholar_id,
            openalex_id=self.identifiers.openalex_id or other.identifiers.openalex_id,
            dblp_key=self.identifiers.dblp_key or other.identifiers.dblp_key,
            core_id=self.identifiers.core_id or other.identifiers.core_id,
        )
        if not merged.authors:
            merged.authors = other.authors
        merged.sources = sorted(set(self.sources) | set(other.sources))
        return merged
