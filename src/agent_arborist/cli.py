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


# -----------------------------------------------------------------------------
# Task commands
# -----------------------------------------------------------------------------


@main.group()
def task() -> None:
    """Task execution and management."""
    pass


@task.command("run")
@click.argument("task_id")
@click.option("--prompt", "-p", required=True, help="Prompt file path or - for stdin")
@click.option("--timeout", "-t", default=1800, help="Timeout in seconds")
@click.option("--runtime", "-r", default=None, help="Runtime to use (claude, opencode, gemini)")
def task_run(task_id: str, prompt: str, timeout: int, runtime: str | None) -> None:
    """Execute a task with the specified prompt."""
    # TODO: Implement task execution
    console.print(f"[yellow]TODO:[/yellow] Run task {task_id} with prompt={prompt}, timeout={timeout}, runtime={runtime}")


@task.command("status")
@click.argument("task_id")
def task_status(task_id: str) -> None:
    """Get task status as JSON."""
    # TODO: Implement task status
    console.print(f"[yellow]TODO:[/yellow] Get status for task {task_id}")


@task.command("deps")
@click.argument("task_id")
def task_deps(task_id: str) -> None:
    """Check if task dependencies are satisfied."""
    # TODO: Implement dependency checking
    console.print(f"[yellow]TODO:[/yellow] Check dependencies for task {task_id}")


@task.command("mark")
@click.argument("task_id")
@click.option("--status", "-s", required=True, type=click.Choice(["completed", "failed"]))
def task_mark(task_id: str, status: str) -> None:
    """Manually mark a task's status."""
    # TODO: Implement task marking
    console.print(f"[yellow]TODO:[/yellow] Mark task {task_id} as {status}")


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
