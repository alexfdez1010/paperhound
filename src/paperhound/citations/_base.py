"""Abstract interface every citation backend implements."""

from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

from paperhound.models import Paper


class CitationBackend(ABC):
    """Fetch references / citing works for a paper from a single source.

    Concrete subclasses should be cheap to construct (no I/O in ``__init__``)
    so the traversal layer can spin one up per call.
    """

    name: str

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    @abstractmethod
    def references(self, identifier: str, limit: int) -> list[Paper]:
        """Return up to *limit* works that *identifier* cites."""

    @abstractmethod
    def citations(self, identifier: str, limit: int) -> list[Paper]:
        """Return up to *limit* works that cite *identifier*."""
