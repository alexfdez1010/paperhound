"""Custom exception hierarchy used by paperhound."""


class PaperhoundError(Exception):
    """Base class for all paperhound errors."""


class IdentifierError(PaperhoundError):
    """Raised when a paper identifier cannot be parsed or resolved."""


class ProviderError(PaperhoundError):
    """Raised when a search provider fails or returns invalid data."""


class DownloadError(PaperhoundError):
    """Raised when a paper cannot be downloaded."""


class ConversionError(PaperhoundError):
    """Raised when a document cannot be converted to Markdown."""


class LibraryError(PaperhoundError):
    """Raised when a local-library operation fails (schema mismatch, missing entry, …)."""


class RerankError(PaperhoundError):
    """Raised when embedding rerank fails (missing dep, model load error, …)."""
