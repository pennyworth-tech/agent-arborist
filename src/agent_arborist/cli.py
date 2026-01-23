"""Agent Arborist CLI - Automated Task Tree Executor."""

import click
from rich.console import Console
from rich.table import Table

from agent_arborist import __version__
from agent_arborist.checks import check_dagu, check_runtimes

console = Console()


@click.group()
@click.option("--quiet", "-q", is_flag=True, help="Suppress non-essential output")
@click.pass_context
def main(ctx: click.Context, quiet: bool) -> None:
    """Agent Arborist - Automated Task Tree Executor.

    Orchestrate DAG workflows with Claude Code and Dagu.
    """
    ctx.ensure_object(dict)
    ctx.obj["quiet"] = quiet


@main.command()
@click.option("--check", "-c", is_flag=True, help="Also check dependencies")
def version(check: bool) -> None:
    """Show version and optionally check dependencies."""
    console.print(f"agent-arborist {__version__}")

    if check:
        console.print()
        _check_dependencies()


@main.command()
def doctor() -> None:
    """Check all dependencies and system requirements."""
    _check_dependencies()


def _check_dependencies() -> None:
    """Check and display dependency status."""
    table = Table(title="Dependency Status")
    table.add_column("Dependency", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Version")
    table.add_column("Path")
    table.add_column("Notes")

    all_ok = True

    # Check dagu (required)
    dagu = check_dagu()
    if dagu.ok:
        status = "[green]OK[/green]"
    else:
        status = "[red]FAIL[/red]"
        all_ok = False

    table.add_row(
        "dagu",
        status,
        dagu.version or "-",
        dagu.path or "-",
        dagu.error or f"(min: {dagu.min_version})",
    )

    # Check runtimes (at least one required)
    runtimes = check_runtimes()
    any_runtime_ok = False

    for runtime in runtimes:
        if runtime.ok:
            status = "[green]OK[/green]"
            any_runtime_ok = True
        elif runtime.installed:
            status = "[yellow]WARN[/yellow]"
        else:
            status = "[dim]-[/dim]"

        table.add_row(
            runtime.name,
            status,
            runtime.version or "-",
            runtime.path or "-",
            runtime.error or "(optional)",
        )

    if not any_runtime_ok:
        all_ok = False

    console.print(table)

    if not any_runtime_ok:
        console.print(
            "\n[red]At least one runtime (claude, opencode, gemini) is required[/red]"
        )

    if all_ok:
        console.print("\n[green]All dependencies OK[/green]")
    else:
        console.print("\n[red]Some dependencies are missing or outdated[/red]")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
