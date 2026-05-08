"""Provider introspection — used by ``paperhound providers``.

Builds a structured status report for every registered provider: description,
homepage, env-var configuration, default-list membership, runtime availability,
and a one-line ``fix`` hint when something is missing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from paperhound.search.base import Capability, ProviderEnvVar
from paperhound.search.registry import build, names


@dataclass(frozen=True)
class EnvVarStatus:
    """Snapshot of one env var: declared config + whether it is currently set."""

    name: str
    required: bool
    purpose: str
    signup_url: str | None
    is_set: bool


@dataclass(frozen=True)
class ProviderStatus:
    """Full status row for one provider."""

    name: str
    description: str
    homepage: str
    capabilities: tuple[str, ...]
    default_enabled: bool
    available: bool
    env_vars: tuple[EnvVarStatus, ...] = field(default_factory=tuple)
    fix: str | None = None


def _capabilities(caps: frozenset[Capability]) -> tuple[str, ...]:
    return tuple(sorted(c.value for c in caps))


def _env_status(var: ProviderEnvVar) -> EnvVarStatus:
    return EnvVarStatus(
        name=var.name,
        required=var.required,
        purpose=var.purpose,
        signup_url=var.signup_url,
        is_set=bool(os.environ.get(var.name)),
    )


def _fix_hint(env_statuses: tuple[EnvVarStatus, ...], available: bool) -> str | None:
    """Build a one-line setup hint, or None if nothing needs fixing."""
    missing_required = [e for e in env_statuses if e.required and not e.is_set]
    missing_optional = [e for e in env_statuses if not e.required and not e.is_set]
    if missing_required:
        parts = []
        for env in missing_required:
            line = f"export {env.name}=…"
            if env.signup_url:
                line += f"  (key: {env.signup_url})"
            parts.append(line)
        return " ; ".join(parts)
    if not available:
        return "Provider reports unavailable. Check network or upstream status."
    if missing_optional:
        env = missing_optional[0]
        hint = f"Optional: export {env.name}=…"
        if env.signup_url:
            hint += f"  ({env.signup_url})"
        return hint
    return None


def provider_statuses(default_sources: tuple[str, ...]) -> list[ProviderStatus]:
    """Return one ``ProviderStatus`` per registered provider, in registry order."""
    rows: list[ProviderStatus] = []
    defaults = {d.lower() for d in default_sources}
    for name in names():
        provider = build(name)
        env_statuses = tuple(_env_status(v) for v in provider.env_vars)
        try:
            available = bool(provider.available())
        except Exception:
            available = False
        finally:
            close = getattr(provider, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        rows.append(
            ProviderStatus(
                name=name,
                description=provider.description,
                homepage=provider.homepage,
                capabilities=_capabilities(provider.capabilities),
                default_enabled=name in defaults,
                available=available,
                env_vars=env_statuses,
                fix=_fix_hint(env_statuses, available),
            )
        )
    return rows
