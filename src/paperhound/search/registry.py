"""Provider registry. Adding a new provider is one ``register()`` call."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from paperhound.search.base import SearchProvider

ProviderFactory = Callable[[], SearchProvider]

_REGISTRY: dict[str, ProviderFactory] = {}
_ALIASES: dict[str, str] = {}


def register(name: str, factory: ProviderFactory, *, aliases: Iterable[str] = ()) -> None:
    """Register a provider factory under ``name`` (and optional aliases)."""
    canonical = name.lower()
    _REGISTRY[canonical] = factory
    for alias in aliases:
        _ALIASES[alias.lower()] = canonical


def resolve(name: str) -> str:
    """Map an alias or canonical name to its canonical form, or raise KeyError."""
    key = name.lower()
    if key in _REGISTRY:
        return key
    if key in _ALIASES:
        return _ALIASES[key]
    raise KeyError(name)


def names() -> list[str]:
    """All canonical provider names, in registration order."""
    return list(_REGISTRY.keys())


def build(name: str) -> SearchProvider:
    """Instantiate a provider by canonical name or alias."""
    return _REGISTRY[resolve(name)]()


def build_many(names_in: Iterable[str] | None = None) -> list[SearchProvider]:
    """Instantiate every requested provider; default = all registered providers."""
    requested = list(names_in) if names_in else names()
    return [build(n) for n in requested]
