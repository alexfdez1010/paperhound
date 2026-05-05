"""Search provider abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from paperhound.models import Paper


@dataclass
class SearchQuery:
    """A normalized search request shared across providers."""

    text: str
    limit: int = 10
    year_min: int | None = None
    year_max: int | None = None


class SearchProvider(ABC):
    """Abstract source of paper records (arXiv, Semantic Scholar, ...)."""

    name: str = "base"

    @abstractmethod
    def search(self, query: SearchQuery) -> list[Paper]:
        """Run a search and return normalized Paper objects."""

    @abstractmethod
    def get(self, identifier: str) -> Paper | None:
        """Fetch a single paper by identifier (provider-native or arXiv/DOI)."""
