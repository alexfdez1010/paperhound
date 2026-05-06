"""paperhound — search, download, and convert academic papers from the command line."""

from importlib.metadata import PackageNotFoundError, version

from paperhound.models import Author, Paper, PaperIdentifier

try:
    __version__ = version("paperhound")
except PackageNotFoundError:  # editable install without metadata, tests, etc.
    __version__ = "0.0.0+unknown"

__all__ = ["Author", "Paper", "PaperIdentifier", "__version__"]
