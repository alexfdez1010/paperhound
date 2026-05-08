"""Tests for ``paperhound.search.info`` (provider introspection)."""

from __future__ import annotations

import pytest

from paperhound.search import provider_statuses
from paperhound.search.info import (
    EnvVarStatus,
    ProviderStatus,
    _fix_hint,
)

DEFAULTS = ("arxiv", "openalex", "dblp", "crossref", "huggingface")


def _names(rows: list[ProviderStatus]) -> list[str]:
    return [r.name for r in rows]


def test_provider_statuses_covers_every_registered_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Strip env vars so optional/required state is deterministic.
    for var in ("OPENALEX_MAILTO", "CROSSREF_MAILTO", "SEMANTIC_SCHOLAR_API_KEY", "CORE_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    rows = provider_statuses(DEFAULTS)
    assert _names(rows) == [
        "arxiv",
        "openalex",
        "dblp",
        "crossref",
        "huggingface",
        "semantic_scholar",
        "core",
    ]
    by_name = {r.name: r for r in rows}

    # arxiv/dblp/huggingface need no config -> always available.
    for n in ("arxiv", "dblp", "huggingface"):
        assert by_name[n].available is True
        assert by_name[n].env_vars == ()

    # Default-list flag matches the tuple we passed in.
    assert by_name["arxiv"].default_enabled is True
    assert by_name["semantic_scholar"].default_enabled is False
    assert by_name["core"].default_enabled is False

    # Optional env vars: provider stays available, fix hint mentions the var.
    openalex = by_name["openalex"]
    assert openalex.available is True
    assert openalex.env_vars[0].name == "OPENALEX_MAILTO"
    assert openalex.env_vars[0].required is False
    assert openalex.env_vars[0].is_set is False
    assert openalex.fix is not None
    assert "OPENALEX_MAILTO" in openalex.fix

    # CORE: required env var missing -> unavailable, fix hint mentions the key.
    core = by_name["core"]
    assert core.available is False
    assert core.env_vars[0].name == "CORE_API_KEY"
    assert core.env_vars[0].required is True
    assert core.fix is not None
    assert "CORE_API_KEY" in core.fix


def test_provider_statuses_picks_up_set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORE_API_KEY", "abc123")
    rows = provider_statuses(DEFAULTS)
    by_name = {r.name: r for r in rows}
    core = by_name["core"]
    assert core.env_vars[0].is_set is True
    assert core.available is True
    # When the only required var is set and there are no missing optionals,
    # there is nothing to fix.
    assert core.fix is None


def test_fix_hint_prefers_required_over_optional() -> None:
    required = EnvVarStatus(
        name="REQ", required=True, purpose="needed", signup_url=None, is_set=False
    )
    optional = EnvVarStatus(
        name="OPT", required=False, purpose="nice", signup_url=None, is_set=False
    )
    hint = _fix_hint((required, optional), available=False)
    assert hint is not None
    assert "REQ" in hint
    assert "OPT" not in hint


def test_fix_hint_returns_none_when_all_set_and_available() -> None:
    var = EnvVarStatus(name="X", required=True, purpose="", signup_url=None, is_set=True)
    assert _fix_hint((var,), available=True) is None
