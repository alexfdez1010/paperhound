"""``paperhound providers`` — list registered search backends + setup hints."""

from __future__ import annotations

import json
import sys

import typer

from paperhound import cli
from paperhound.search import provider_statuses


def _provider_status_to_dict(status) -> dict[str, object]:  # type: ignore[no-untyped-def]
    return {
        "name": status.name,
        "description": status.description,
        "homepage": status.homepage,
        "capabilities": list(status.capabilities),
        "default_enabled": status.default_enabled,
        "available": status.available,
        "env_vars": [
            {
                "name": env.name,
                "required": env.required,
                "purpose": env.purpose,
                "signup_url": env.signup_url,
                "is_set": env.is_set,
            }
            for env in status.env_vars
        ],
        "fix": status.fix,
    }


def _render_table(rows) -> None:  # type: ignore[no-untyped-def]
    from rich.console import Console as _Console
    from rich.table import Table

    table_console = _Console(width=140, soft_wrap=False)

    table = Table(show_lines=True, header_style="bold cyan")
    table.add_column("Provider", no_wrap=True)
    table.add_column("Default", justify="center", no_wrap=True)
    table.add_column("Status", justify="center", no_wrap=True)
    table.add_column("Description", overflow="fold")
    table.add_column("Env / Fix", overflow="fold")

    for row in rows:
        if row.available:
            status_label = "[green]available[/green]"
        else:
            status_label = "[red]unavailable[/red]"

        env_lines: list[str] = []
        for env in row.env_vars:
            tag = "required" if env.required else "optional"
            mark = "[green]set[/green]" if env.is_set else "[yellow]unset[/yellow]"
            env_lines.append(f"{env.name} ({tag}, {mark}) — {env.purpose}")
            if env.signup_url and not env.is_set:
                env_lines.append(f"  ↳ {env.signup_url}")
        if row.fix:
            env_lines.append(f"[dim]fix:[/dim] {row.fix}")
        env_block = "\n".join(env_lines) if env_lines else "[dim]no configuration needed[/dim]"

        table.add_row(
            f"[bold]{row.name}[/bold]\n[dim]{row.homepage}[/dim]" if row.homepage else row.name,
            "yes" if row.default_enabled else "-",
            status_label,
            row.description or "-",
            env_block,
        )

    table_console.print(table)


@cli.app.command(
    name="providers",
    epilog=("Examples:\n\n\b\n  paperhound providers\n  paperhound providers --json"),
)
def providers(
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit a JSON array of provider status objects instead of a Rich table.",
    ),
) -> None:
    """List search providers with description, status, and setup hints.

    Reports each registered provider's role in paperhound, whether it is in the
    default search set, whether it currently reports as available (env vars set,
    etc.), and what to export to enable or upgrade it.
    """
    rows = provider_statuses(cli.DEFAULT_SOURCES)

    if json_output:
        sys.stdout.write(json.dumps([_provider_status_to_dict(r) for r in rows], indent=2) + "\n")
        return

    _render_table(rows)
