"""Command registry — importing each module attaches its @app.command(s).

Order is irrelevant: typer collects commands in registration order but the
help text lists them alphabetically anyway. We import everything in
:func:`register_all` so :mod:`paperhound.cli` can defer the side effects
until its own helpers are in place.
"""

from __future__ import annotations


def register_all() -> None:
    """Import every command module to trigger typer registration."""
    # Local imports keep the modules out of the import graph until the
    # parent package has finished defining helpers.
    from paperhound.cli._commands import (  # noqa: F401
        citations,
        convert,
        download,
        get,
        library,
        providers,
        search,
        show,
    )
