"""Search provider abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from paperhound.models import Paper


class Capability(str, Enum):
    """Optional capabilities a provider may declare."""

    TEXT_SEARCH = "text_search"
    ID_LOOKUP = "id_lookup"
    OPEN_ACCESS_PDF = "open_access_pdf"


@dataclass
class SearchQuery:
    """A normalized search request shared across providers."""

    text: str
    limit: int = 10
    year_min: int | None = None
    year_max: int | None = None


class SearchProvider(ABC):
    """Abstract source of paper records (arXiv, OpenAlex, DBLP, ...)."""

    name: str = "base"
    capabilities: frozenset[Capability] = frozenset({Capability.TEXT_SEARCH, Capability.ID_LOOKUP})
    timeout: float = 30.0

    def available(self) -> bool:
        """Return True if the provider is usable in the current environment.

        Override to check API keys, network reachability, etc. The aggregator
        skips providers that report ``False`` so misconfigured sources degrade
        silently instead of raising at search time.
        """
        return True

    def supports(self, capability: Capability) -> bool:
        return capability in self.capabilities

    @abstractmethod
    def search(self, query: SearchQuery) -> list[Paper]:
        """Run a search and return normalized Paper objects."""

    @abstractmethod
    def get(self, identifier: str) -> Paper | None:
        """Fetch a single paper by identifier (provider-native or arXiv/DOI)."""
