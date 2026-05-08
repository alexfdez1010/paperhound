"""Search providers, registry, and aggregator."""

from paperhound.search.aggregator import DEFAULT_TIMEOUT, SearchAggregator
from paperhound.search.arxiv_provider import ArxivProvider
from paperhound.search.base import (
    Capability,
    ProviderEnvVar,
    SearchProvider,
    SearchQuery,
)
from paperhound.search.core import CoreProvider
from paperhound.search.crossref import CrossrefProvider
from paperhound.search.dblp import DBLPProvider
from paperhound.search.huggingface import HuggingFaceProvider
from paperhound.search.info import EnvVarStatus, ProviderStatus, provider_statuses
from paperhound.search.openalex import OpenAlexProvider
from paperhound.search.registry import (
    build,
    build_many,
    names,
    register,
    resolve,
)
from paperhound.search.semantic_scholar import SemanticScholarProvider

# Canonical registration order also drives default search ordering.
register("arxiv", ArxivProvider)
register("openalex", OpenAlexProvider)
register("dblp", DBLPProvider)
register("crossref", CrossrefProvider)
register("huggingface", HuggingFaceProvider, aliases=("hf",))
register("semantic_scholar", SemanticScholarProvider, aliases=("s2",))
register("core", CoreProvider)

__all__ = [
    "ArxivProvider",
    "Capability",
    "CoreProvider",
    "CrossrefProvider",
    "DBLPProvider",
    "DEFAULT_TIMEOUT",
    "EnvVarStatus",
    "HuggingFaceProvider",
    "OpenAlexProvider",
    "ProviderEnvVar",
    "ProviderStatus",
    "SearchAggregator",
    "SearchProvider",
    "SearchQuery",
    "SemanticScholarProvider",
    "build",
    "build_many",
    "names",
    "provider_statuses",
    "register",
    "resolve",
]
