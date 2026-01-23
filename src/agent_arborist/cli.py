"""Agent Arborist CLI - Automated Task Tree Executor."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from agent_arborist import __version__
from agent_arborist.checks import check_dagu, check_runtimes
from agent_arborist.spec import detect_spec_from_git
from agent_arborist.runner import get_runner, RunnerType, DEFAULT_RUNNER
from agent_arborist.home import (
    get_arborist_home,
    get_dagu_home,
    init_arborist_home,
    is_initialized,
    ArboristHomeError,
    DAGU_HOME_ENV_VAR,
)

console = Console()


@click.group()
@click.option("--quiet", "-q", is_flag=True, help="Suppress non-essential output")
@click.option("--home", envvar="ARBORIST_HOME", help="Override arborist home directory")
@click.pass_context
def main(ctx: click.Context, quiet: bool, home: str | None) -> None:
    """Agent Arborist - Automated Task Tree Executor.

    Orchestrate DAG workflows with Claude Code and Dagu.
    """
    ctx.ensure_object(dict)
    ctx.obj["quiet"] = quiet
    ctx.obj["home_override"] = home

    # Set DAGU_HOME if arborist is initialized
    try:
        arborist_home = get_arborist_home(override=home)
        if is_initialized(arborist_home):
            dagu_home = get_dagu_home(arborist_home)
            os.environ[DAGU_HOME_ENV_VAR] = str(dagu_home)
            ctx.obj["arborist_home"] = arborist_home
            ctx.obj["dagu_home"] = dagu_home
    except ArboristHomeError:
        # Not in a git repo or not initialized - that's fine for some commands
        pass


@main.command()
@click.option("--check", "-c", is_flag=True, help="Also check dependencies")
def version(check: bool) -> None:
    """Show version and optionally check dependencies."""
    console.print(f"agent-arborist {__version__}")

    if check:
        console.print()
        _check_dependencies()


@main.command()
def init() -> None:
    """Initialize arborist in the current git repository.

    Creates a .arborist/ directory in the git root.
    Must be run from within a git repository.
    """
    try:
        home = init_arborist_home()
        console.print(f"[green]Initialized arborist at[/green] {home}")
    except ArboristHomeError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@main.group(invoke_without_command=True)
@click.pass_context
def doctor(ctx: click.Context) -> None:
    """Check dependencies and system requirements."""
    if ctx.invoked_subcommand is None:
        _check_dependencies()


@doctor.command("check-runner")
@click.option(
    "--runner",
    "-r",
    type=click.Choice(["claude", "opencode", "gemini"]),
    default=DEFAULT_RUNNER,
    help=f"Runner to test (default: {DEFAULT_RUNNER})",
)
def doctor_check_runner(runner: RunnerType) -> None:
    """Test that a runner can execute prompts."""
    console.print(f"[cyan]Testing {runner} runner...[/cyan]")

    runner_instance = get_runner(runner)

    if not runner_instance.is_available():
        console.print(f"[red]FAIL:[/red] {runner} not found in PATH")
        raise SystemExit(1)

    console.print(f"[dim]Found {runner} at {runner_instance.command}[/dim]")
    console.print("[dim]Sending test prompt...[/dim]\n")

    result = runner_instance.run("Tell me a short joke (one liner).", timeout=30)

    if result.success:
        console.print(f"[green]OK:[/green] Runner responded successfully\n")
        console.print(f"[bold]Response:[/bold]\n{result.output}")
    else:
        console.print(f"[red]FAIL:[/red] {result.error}")
        if result.output:
            console.print(f"[dim]Output:[/dim] {result.output}")
        raise SystemExit(result.exit_code if result.exit_code != 0 else 1)


@doctor.command("check-dagu")
@click.pass_context
def doctor_check_dagu(ctx: click.Context) -> None:
    """Test that dagu is installed and working correctly."""
    console.print("[cyan]Checking dagu installation...[/cyan]")

    # Check if dagu is installed
    dagu_path = shutil.which("dagu")
    if not dagu_path:
        console.print("[red]FAIL:[/red] dagu not found in PATH")
        console.print("[dim]Install dagu: https://dagu.readthedocs.io/[/dim]")
        raise SystemExit(1)

    console.print(f"[green]OK:[/green] Found dagu at {dagu_path}")

    # Check version
    try:
        result = subprocess.run(
            [dagu_path, "version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            # dagu outputs version to stderr
            dagu_version = (result.stdout or result.stderr).strip()
            console.print(f"[green]OK:[/green] dagu version {dagu_version}")
        else:
            console.print("[red]FAIL:[/red] Could not get dagu version")
            raise SystemExit(1)
    except subprocess.TimeoutExpired:
        console.print("[red]FAIL:[/red] dagu version timed out")
        raise SystemExit(1)

    # Check DAGU_HOME
    dagu_home = os.environ.get(DAGU_HOME_ENV_VAR)
    if dagu_home:
        console.print(f"[green]OK:[/green] DAGU_HOME={dagu_home}")
        dagu_home_path = Path(dagu_home)
        if dagu_home_path.is_dir():
            console.print(f"[green]OK:[/green] DAGU_HOME directory exists")
        else:
            console.print(f"[yellow]WARN:[/yellow] DAGU_HOME directory does not exist (will be created on first use)")
    else:
        console.print(f"[yellow]WARN:[/yellow] DAGU_HOME not set (using default: ~/.config/dagu)")
        console.print("[dim]Run 'arborist init' to set up DAGU_HOME in your project[/dim]")

    # Test with a simple dry run
    console.print("\n[cyan]Testing dagu with dry run...[/cyan]")

    # Create a test DAG
    hello_dag = """name: arborist-test
steps:
  - name: hello
    command: echo "Hello from arborist!"
"""

    # If DAGU_HOME is set, place DAG in $DAGU_HOME/dags/ to verify the path works
    env = os.environ.copy()
    test_dag_path: Path | None = None

    if dagu_home:
        dagu_home_path = Path(dagu_home)
        dags_dir = dagu_home_path / "dags"
        if dags_dir.is_dir():
            test_dag_path = dags_dir / "arborist-test.yaml"
            test_dag_path.write_text(hello_dag)
            console.print(f"[dim]Placed test DAG in {test_dag_path}[/dim]")
            dag_ref = "arborist-test"  # Use name, dagu should find it via DAGU_HOME
        else:
            # dags dir doesn't exist, use temp file
            with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
                f.write(hello_dag)
                dag_ref = f.name
        env[DAGU_HOME_ENV_VAR] = dagu_home
    else:
        # No DAGU_HOME, use temp file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(hello_dag)
            dag_ref = f.name

    try:
        result = subprocess.run(
            [dagu_path, "dry", "--quiet", dag_ref],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )

        if result.returncode == 0:
            console.print("[green]OK:[/green] dagu dry run succeeded")
            if "Succeeded" in result.stdout:
                console.print("[green]OK:[/green] Test DAG executed successfully")
                if test_dag_path:
                    console.print("[green]OK:[/green] DAGU_HOME is working correctly")
            else:
                console.print(f"[dim]Output:[/dim]\n{result.stdout}")
        else:
            console.print("[red]FAIL:[/red] dagu dry run failed")
            if result.stderr:
                console.print(f"[dim]Error:[/dim] {result.stderr}")
            raise SystemExit(1)

    except subprocess.TimeoutExpired:
        console.print("[red]FAIL:[/red] dagu dry run timed out")
        raise SystemExit(1)
    finally:
        # Clean up test DAG
        if test_dag_path and test_dag_path.exists():
            test_dag_path.unlink()
        elif not test_dag_path and dag_ref and Path(dag_ref).exists():
            # Was a temp file
            Path(dag_ref).unlink(missing_ok=True)

    console.print("\n[green]All dagu checks passed![/green]")


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


# -----------------------------------------------------------------------------
# Spec commands
# -----------------------------------------------------------------------------


@main.group()
def spec() -> None:
    """Spec detection and management."""
    pass


@spec.command("whoami")
def spec_whoami() -> None:
    """Detect current spec from git branch."""
    info = detect_spec_from_git()

    if info.found:
        console.print(f"[green]Spec:[/green] {info.spec_id}")
        console.print(f"[dim]Source:[/dim] {info.source}")
        if info.branch:
            console.print(f"[dim]Branch:[/dim] {info.branch}")
    else:
        console.print(f"[yellow]Not detected:[/yellow] {info.error}")
        if info.branch:
            console.print(f"[dim]Branch:[/dim] {info.branch}")
        console.print()
        console.print("Set spec manually with [cyan]--spec[/cyan] or [cyan]-s[/cyan] on subsequent commands.")


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
