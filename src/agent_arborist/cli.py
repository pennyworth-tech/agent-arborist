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
    get_git_root,
    init_arborist_home,
    is_initialized,
    ArboristHomeError,
    DAGU_HOME_ENV_VAR,
)
from agent_arborist.task_spec import parse_task_spec
from agent_arborist.dag_builder import DagConfig, DagBuilder
from agent_arborist.dag_generator import DagGenerator
from agent_arborist.git_tasks import (
    get_worktree_path,
    find_parent_branch,
    merge_to_parent,
    cleanup_task,
    run_tests,
    detect_test_command,
    get_conflict_files,
    abort_merge,
    branch_exists,
    create_all_branches_from_manifest,
    sync_task,
    get_current_branch,
)
from agent_arborist.branch_manifest import (
    generate_manifest,
    save_manifest,
    load_manifest,
    load_manifest_from_env,
    BranchManifest,
)
from agent_arborist.task_state import (
    init_task_tree,
    load_task_tree,
    update_task_status,
    get_task_status_summary,
)

console = Console()


def echo_command(cmd: str, **kwargs: str | None) -> None:
    """Output a consistently formatted echo line for testing.

    Format: ECHO: <command> | spec=X | task=Y | other=Z ...

    Standard fields (spec_id, task_id) are always printed first if provided,
    followed by other fields in the order they were passed.
    """
    parts = [f"ECHO: {cmd:<30}"]

    # Standard fields first, in order
    standard_fields = ["spec_id", "task_id"]
    for field in standard_fields:
        if field in kwargs and kwargs[field] is not None:
            parts.append(f"{field}={kwargs[field]}")

    # Then remaining fields
    for key, value in kwargs.items():
        if key not in standard_fields and value is not None:
            parts.append(f"{key}={value}")

    print(" | ".join(parts) if len(parts) > 1 else parts[0])


@click.group()
@click.option("--quiet", "-q", is_flag=True, help="Suppress non-essential output")
@click.option("--home", envvar="ARBORIST_HOME", help="Override arborist home directory")
@click.option("--spec", "-s", envvar="ARBORIST_SPEC", help="Spec name (auto-detected from git branch if not set)")
@click.option("--echo-for-testing", is_flag=True, hidden=True, help="Echo command info and exit (for testing)")
@click.pass_context
def main(ctx: click.Context, quiet: bool, home: str | None, spec: str | None, echo_for_testing: bool) -> None:
    """Agent Arborist - Automated Task Tree Executor.

    Orchestrate DAG workflows with Claude Code and Dagu.
    """
    ctx.ensure_object(dict)
    ctx.obj["quiet"] = quiet
    ctx.obj["home_override"] = home
    ctx.obj["spec_override"] = spec
    ctx.obj["echo_for_testing"] = echo_for_testing

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

    # Resolve spec name (from override or git)
    if spec:
        ctx.obj["spec_name"] = spec
        ctx.obj["spec_id"] = spec
    else:
        spec_info = detect_spec_from_git()
        if spec_info.found:
            ctx.obj["spec_name"] = spec_info.name
            ctx.obj["spec_id"] = spec_info.spec_id
        else:
            ctx.obj["spec_name"] = None
            ctx.obj["spec_id"] = None


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


@task.command("status")
@click.argument("task_id", required=False)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def task_status(ctx: click.Context, task_id: str | None, as_json: bool) -> None:
    """Get task status.

    If TASK_ID is provided, shows that task's status.
    Otherwise, shows summary of all tasks.
    """
    import json

    spec_id = ctx.obj.get("spec_id")

    if ctx.obj.get("echo_for_testing"):
        echo_command(
            "task status",
            task_id=task_id or "all",
            spec_id=spec_id or "none",
            json=str(as_json),
        )
        return

    if not spec_id:
        console.print("[red]Error:[/red] No spec available")
        raise SystemExit(1)

    tree = load_task_tree(spec_id)
    if not tree:
        console.print(f"[red]Error:[/red] No task tree found for spec {spec_id}")
        raise SystemExit(1)

    if task_id:
        task_node = tree.get_task(task_id)
        if not task_node:
            console.print(f"[red]Error:[/red] Task {task_id} not found")
            raise SystemExit(1)

        if as_json:
            console.print(json.dumps({
                "task_id": task_node.task_id,
                "status": task_node.status,
                "description": task_node.description,
                "parent_id": task_node.parent_id,
                "children": task_node.children,
                "branch": task_node.branch,
                "worktree": task_node.worktree,
                "error": task_node.error,
            }, indent=2))
        else:
            status_color = {
                "pending": "yellow",
                "running": "cyan",
                "complete": "green",
                "failed": "red",
            }.get(task_node.status, "white")

            console.print(f"[bold]Task:[/bold] {task_node.task_id}")
            console.print(f"[bold]Status:[/bold] [{status_color}]{task_node.status}[/{status_color}]")
            console.print(f"[dim]Description:[/dim] {task_node.description}")
            if task_node.parent_id:
                console.print(f"[dim]Parent:[/dim] {task_node.parent_id}")
            if task_node.children:
                console.print(f"[dim]Children:[/dim] {', '.join(task_node.children)}")
            if task_node.branch:
                console.print(f"[dim]Branch:[/dim] {task_node.branch}")
            if task_node.worktree:
                console.print(f"[dim]Worktree:[/dim] {task_node.worktree}")
            if task_node.error:
                console.print(f"[red]Error:[/red] {task_node.error}")
    else:
        # Show summary
        summary = get_task_status_summary(tree)

        if as_json:
            console.print(json.dumps(summary, indent=2))
        else:
            console.print(f"[bold]Spec:[/bold] {spec_id}")
            console.print(f"[bold]Total tasks:[/bold] {summary['total']}")
            console.print(f"  [yellow]Pending:[/yellow] {summary['pending']}")
            console.print(f"  [cyan]Running:[/cyan] {summary['running']}")
            console.print(f"  [green]Complete:[/green] {summary['complete']}")
            console.print(f"  [red]Failed:[/red] {summary['failed']}")


@task.command("pre-sync")
@click.argument("task_id")
@click.pass_context
def task_pre_sync(ctx: click.Context, task_id: str) -> None:
    """Create worktree and sync from parent for a task.

    This command reads branch info from the ARBORIST_MANIFEST environment variable.
    Branches must already exist (run 'arborist branches create-all' first).
    """
    import os

    manifest_path = os.environ.get("ARBORIST_MANIFEST")
    if not manifest_path:
        console.print("[red]Error:[/red] ARBORIST_MANIFEST environment variable not set")
        console.print("This command should be run from a DAGU DAG step")
        raise SystemExit(1)

    try:
        manifest = load_manifest(Path(manifest_path))
    except FileNotFoundError:
        console.print(f"[red]Error:[/red] Manifest not found: {manifest_path}")
        raise SystemExit(1)
    except Exception as e:
        console.print(f"[red]Error loading manifest:[/red] {e}")
        raise SystemExit(1)

    task_info = manifest.get_task(task_id)
    if not task_info:
        console.print(f"[red]Error:[/red] Task {task_id} not found in manifest")
        raise SystemExit(1)

    # Get worktree path
    worktree_path = get_worktree_path(manifest.spec_id, task_id)

    if ctx.obj.get("echo_for_testing"):
        echo_command(
            "task pre-sync",
            task_id=task_id,
            spec_id=manifest.spec_id,
            branch=task_info.branch,
            parent=task_info.parent_branch,
            worktree=str(worktree_path),
        )
        return

    if not ctx.obj.get("quiet"):
        console.print(f"[cyan]Syncing task {task_id}...[/cyan]")
        console.print(f"[dim]Branch: {task_info.branch}[/dim]")
        console.print(f"[dim]Parent: {task_info.parent_branch}[/dim]")

    # Sync the task (create worktree and sync from parent)
    result = sync_task(task_info.branch, task_info.parent_branch, worktree_path)

    if result.success:
        console.print(f"[green]OK:[/green] {result.message}")
        # Update state
        update_task_status(manifest.spec_id, task_id, "running", branch=task_info.branch, worktree=str(worktree_path))
    else:
        console.print(f"[red]Error:[/red] {result.message}")
        if result.error:
            console.print(f"[dim]{result.error}[/dim]")
        raise SystemExit(1)


@task.command("run")
@click.argument("task_id")
@click.option("--timeout", "-t", default=1800, help="Timeout in seconds")
@click.option(
    "--runner",
    "-r",
    type=click.Choice(["claude", "opencode", "gemini"]),
    default=None,
    help=f"Runner to use (default: {DEFAULT_RUNNER})",
)
@click.pass_context
def task_run(ctx: click.Context, task_id: str, timeout: int, runner: str | None) -> None:
    """Execute a task using AI in its worktree.

    The AI runner will be invoked in the task's worktree directory,
    allowing it to explore files and implement the task.
    """
    import os

    manifest_path = os.environ.get("ARBORIST_MANIFEST")
    if not manifest_path:
        console.print("[red]Error:[/red] ARBORIST_MANIFEST environment variable not set")
        raise SystemExit(1)

    try:
        manifest = load_manifest(Path(manifest_path))
    except Exception as e:
        console.print(f"[red]Error loading manifest:[/red] {e}")
        raise SystemExit(1)

    task_info = manifest.get_task(task_id)
    if not task_info:
        console.print(f"[red]Error:[/red] Task {task_id} not found in manifest")
        raise SystemExit(1)

    # Load task tree for description
    tree = load_task_tree(manifest.spec_id)
    task_node = tree.get_task(task_id) if tree else None
    task_description = task_node.description if task_node else task_id

    # Get worktree path
    worktree_path = get_worktree_path(manifest.spec_id, task_id)

    # Get runner type early for echo
    runner_type = runner or DEFAULT_RUNNER

    if ctx.obj.get("echo_for_testing"):
        echo_command(
            "task run",
            task_id=task_id,
            spec_id=manifest.spec_id,
            runner=runner_type,
            timeout=str(timeout),
            worktree=str(worktree_path),
        )
        return

    if not worktree_path.exists():
        console.print(f"[red]Error:[/red] Worktree not found at {worktree_path}")
        console.print("Run 'arborist task pre-sync' first")
        raise SystemExit(1)

    # Build prompt for AI
    prompt = f"""Implement task {task_id}: "{task_description}"

You are in the project worktree. Read the task spec at specs/{manifest.spec_id}/tasks.md for full context including dependencies and requirements.

Complete the implementation for this specific task. After implementing:
1. Ensure all code compiles/lints
2. Add any necessary tests
3. Stage your changes with git add

Do NOT commit - that will be handled by the task workflow.
"""

    # Get runner
    runner_type = runner or DEFAULT_RUNNER
    runner_instance = get_runner(runner_type)

    if not runner_instance.is_available():
        console.print(f"[red]Error:[/red] {runner_type} not found in PATH")
        raise SystemExit(1)

    if not ctx.obj.get("quiet"):
        console.print(f"[cyan]Running task {task_id} with {runner_type}...[/cyan]")
        console.print(f"[dim]Worktree: {worktree_path}[/dim]")

    # Run the AI in the worktree directory
    result = runner_instance.run(prompt, timeout=timeout, cwd=worktree_path)

    if result.success:
        console.print(f"[green]OK:[/green] Task {task_id} completed")
        if result.output and not ctx.obj.get("quiet"):
            console.print(f"\n[dim]Output:[/dim]\n{result.output[:1000]}")
    else:
        console.print(f"[red]Error:[/red] Task failed")
        if result.error:
            console.print(f"[dim]{result.error}[/dim]")
        update_task_status(manifest.spec_id, task_id, "failed", error=result.error)
        raise SystemExit(1)


@task.command("run-test")
@click.argument("task_id")
@click.option("--cmd", help="Override test command (auto-detected if not specified)")
@click.pass_context
def task_run_test(ctx: click.Context, task_id: str, cmd: str | None) -> None:
    """Run tests for a task.

    Auto-detects test command based on project files (pytest, npm test, etc.).
    For parent tasks, verifies all children are complete first.
    """
    import os

    manifest_path = os.environ.get("ARBORIST_MANIFEST")
    if not manifest_path:
        console.print("[red]Error:[/red] ARBORIST_MANIFEST environment variable not set")
        raise SystemExit(1)

    try:
        manifest = load_manifest(Path(manifest_path))
    except Exception as e:
        console.print(f"[red]Error loading manifest:[/red] {e}")
        raise SystemExit(1)

    task_info = manifest.get_task(task_id)
    if not task_info:
        console.print(f"[red]Error:[/red] Task {task_id} not found in manifest")
        raise SystemExit(1)

    # Get worktree path
    worktree_path = get_worktree_path(manifest.spec_id, task_id)

    if ctx.obj.get("echo_for_testing"):
        echo_command(
            "task run-test",
            task_id=task_id,
            spec_id=manifest.spec_id,
            cmd=cmd or "auto",
            worktree=str(worktree_path),
        )
        return

    # For parent tasks, check children are complete
    if task_info.children:
        tree = load_task_tree(manifest.spec_id)
        if tree:
            if not tree.are_children_complete(task_id):
                incomplete = [
                    c for c in tree.get_children(task_id)
                    if c.status != "complete"
                ]
                console.print(f"[red]Error:[/red] Children not complete:")
                for child in incomplete:
                    console.print(f"  - {child.task_id}: {child.status}")
                raise SystemExit(1)
            console.print(f"[green]OK:[/green] All {len(task_info.children)} children complete")

    if not worktree_path.exists():
        console.print(f"[yellow]WARN:[/yellow] No worktree at {worktree_path}, using git root")
        worktree_path = get_git_root()

    # Detect or use provided test command
    test_cmd = cmd or detect_test_command(worktree_path)
    if not test_cmd:
        console.print("[dim]No test command detected, skipping tests[/dim]")
        return

    if not ctx.obj.get("quiet"):
        console.print(f"[cyan]Running tests: {test_cmd}[/cyan]")

    result = run_tests(worktree_path, test_cmd)

    if result.success:
        console.print(f"[green]OK:[/green] {result.message}")
    else:
        console.print(f"[red]FAIL:[/red] {result.message}")
        if result.error:
            console.print(f"[dim]{result.error[:500]}[/dim]")
        raise SystemExit(1)


@task.command("post-merge")
@click.argument("task_id")
@click.option("--no-resolve", is_flag=True, help="Don't attempt AI conflict resolution")
@click.pass_context
def task_post_merge(ctx: click.Context, task_id: str, no_resolve: bool) -> None:
    """Merge task branch to parent branch.

    By default, attempts AI-powered conflict resolution if conflicts occur.
    Use --no-resolve to fail on conflicts instead.
    """
    import os

    manifest_path = os.environ.get("ARBORIST_MANIFEST")
    if not manifest_path:
        console.print("[red]Error:[/red] ARBORIST_MANIFEST environment variable not set")
        raise SystemExit(1)

    try:
        manifest = load_manifest(Path(manifest_path))
    except Exception as e:
        console.print(f"[red]Error loading manifest:[/red] {e}")
        raise SystemExit(1)

    task_info = manifest.get_task(task_id)
    if not task_info:
        console.print(f"[red]Error:[/red] Task {task_id} not found in manifest")
        raise SystemExit(1)

    # Get branch names from manifest
    task_branch = task_info.branch
    parent_branch = task_info.parent_branch

    if ctx.obj.get("echo_for_testing"):
        echo_command(
            "task post-merge",
            task_id=task_id,
            spec_id=manifest.spec_id,
            branch=task_branch,
            parent=parent_branch,
            no_resolve=str(no_resolve),
        )
        return

    if not ctx.obj.get("quiet"):
        console.print(f"[cyan]Merging {task_branch} → {parent_branch}[/cyan]")

    result = merge_to_parent(task_branch, parent_branch)

    if result.success:
        console.print(f"[green]OK:[/green] {result.message}")
        update_task_status(manifest.spec_id, task_id, "complete")
        return

    # Handle conflicts
    if result.conflicts:
        console.print(f"[yellow]Conflicts in {len(result.conflicts)} files:[/yellow]")
        for f in result.conflicts:
            console.print(f"  - {f}")

        if no_resolve:
            abort_merge()
            console.print("[red]Merge aborted due to conflicts[/red]")
            raise SystemExit(1)

        # Attempt AI conflict resolution
        console.print("\n[cyan]Attempting AI conflict resolution...[/cyan]")

        runner = get_runner(DEFAULT_RUNNER)
        if not runner.is_available():
            abort_merge()
            console.print(f"[red]Error:[/red] {DEFAULT_RUNNER} not available for conflict resolution")
            raise SystemExit(1)

        git_root = get_git_root()
        resolved_all = True

        for conflict_file in result.conflicts:
            conflict_path = git_root / conflict_file
            if not conflict_path.exists():
                continue

            conflict_content = conflict_path.read_text()

            resolve_prompt = f"""Resolve this git merge conflict in {conflict_file}.

The file contains conflict markers (<<<<<<, ======, >>>>>>).
Analyze both versions and produce the correctly merged result.

Output ONLY the resolved file content, no explanation.

Conflicted file:
```
{conflict_content}
```"""

            resolve_result = runner.run(resolve_prompt, timeout=60)

            if resolve_result.success and resolve_result.output:
                # Write resolved content
                conflict_path.write_text(resolve_result.output.strip())
                subprocess.run(["git", "add", conflict_file], cwd=git_root, check=True)
                console.print(f"  [green]Resolved:[/green] {conflict_file}")
            else:
                console.print(f"  [red]Failed:[/red] {conflict_file}")
                resolved_all = False

        if resolved_all:
            # Complete the merge
            subprocess.run(
                ["git", "commit", "--no-edit"],
                cwd=git_root,
                check=True,
                capture_output=True,
            )
            console.print(f"[green]OK:[/green] Merge completed with AI-resolved conflicts")
            update_task_status(manifest.spec_id, task_id, "complete")
        else:
            abort_merge()
            console.print("[red]Error:[/red] Could not resolve all conflicts")
            update_task_status(manifest.spec_id, task_id, "failed", error="Merge conflicts")
            raise SystemExit(1)
    else:
        console.print(f"[red]Error:[/red] {result.message}")
        if result.error:
            console.print(f"[dim]{result.error}[/dim]")
        raise SystemExit(1)


@task.command("post-cleanup")
@click.argument("task_id")
@click.option("--keep-branch", is_flag=True, help="Don't delete the branch")
@click.pass_context
def task_post_cleanup(ctx: click.Context, task_id: str, keep_branch: bool) -> None:
    """Remove worktree and branch for a completed task."""
    import os

    manifest_path = os.environ.get("ARBORIST_MANIFEST")
    if not manifest_path:
        console.print("[red]Error:[/red] ARBORIST_MANIFEST environment variable not set")
        raise SystemExit(1)

    try:
        manifest = load_manifest(Path(manifest_path))
    except Exception as e:
        console.print(f"[red]Error loading manifest:[/red] {e}")
        raise SystemExit(1)

    task_info = manifest.get_task(task_id)
    if not task_info:
        console.print(f"[red]Error:[/red] Task {task_id} not found in manifest")
        raise SystemExit(1)

    task_branch = task_info.branch
    worktree_path = get_worktree_path(manifest.spec_id, task_id)

    if ctx.obj.get("echo_for_testing"):
        echo_command(
            "task post-cleanup",
            task_id=task_id,
            spec_id=manifest.spec_id,
            branch=task_branch,
            keep_branch=str(keep_branch),
            worktree=str(worktree_path),
        )
        return

    if not ctx.obj.get("quiet"):
        console.print(f"[cyan]Cleaning up task {task_id}...[/cyan]")

    result = cleanup_task(task_branch, worktree_path, delete_branch=not keep_branch)

    if result.success:
        console.print(f"[green]OK:[/green] {result.message}")
        # Clear worktree from state
        tree = load_task_tree(manifest.spec_id)
        if tree:
            task_node = tree.get_task(task_id)
            if task_node:
                update_task_status(manifest.spec_id, task_id, task_node.status, worktree=None)
    else:
        console.print(f"[yellow]WARN:[/yellow] {result.message}")
        if result.error:
            console.print(f"[dim]{result.error}[/dim]")


# -----------------------------------------------------------------------------
# Spec commands
# -----------------------------------------------------------------------------


@main.group()
def spec() -> None:
    """Spec management, DAG generation, and branch operations."""
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


@spec.command("branch-create-all")
@click.pass_context
def spec_branch_create_all(ctx: click.Context) -> None:
    """Create all branches from manifest.

    This command reads the ARBORIST_MANIFEST environment variable to find the
    manifest file, then creates the base branch and all task branches in
    topological order.

    Run this once at the start of a DAG execution.
    """
    import os

    manifest_path = os.environ.get("ARBORIST_MANIFEST")
    if not manifest_path:
        console.print("[red]Error:[/red] ARBORIST_MANIFEST environment variable not set")
        console.print("This command should be run from a DAGU DAG step")
        raise SystemExit(1)

    try:
        manifest = load_manifest(Path(manifest_path))
    except FileNotFoundError:
        console.print(f"[red]Error:[/red] Manifest not found: {manifest_path}")
        raise SystemExit(1)
    except Exception as e:
        console.print(f"[red]Error loading manifest:[/red] {e}")
        raise SystemExit(1)

    if ctx.obj.get("echo_for_testing"):
        echo_command(
            "spec branch-create-all",
            spec_id=manifest.spec_id,
            source=manifest.source_branch,
            base=manifest.base_branch,
            tasks=str(len(manifest.tasks)),
        )
        return

    if not ctx.obj.get("quiet"):
        console.print(f"[cyan]Creating branches from manifest...[/cyan]")
        console.print(f"[dim]Source: {manifest.source_branch}[/dim]")
        console.print(f"[dim]Base: {manifest.base_branch}[/dim]")
        console.print(f"[dim]Tasks: {len(manifest.tasks)}[/dim]")

    result = create_all_branches_from_manifest(manifest)

    if result.success:
        console.print(f"[green]OK:[/green] {result.message}")
    else:
        console.print(f"[red]Error:[/red] {result.message}")
        if result.error:
            console.print(f"[dim]{result.error}[/dim]")
        raise SystemExit(1)


@spec.command("branch-cleanup-all")
@click.option("--force", "-f", is_flag=True, help="Force removal of worktrees and branches")
@click.pass_context
def spec_branch_cleanup_all(ctx: click.Context, force: bool) -> None:
    """Remove all worktrees and branches for the current spec.

    This command reads the ARBORIST_MANIFEST environment variable to find the
    manifest file, then removes all task worktrees and branches.

    Use --force to force removal even if branches are not fully merged.
    """
    import os

    manifest_path = os.environ.get("ARBORIST_MANIFEST")
    if not manifest_path:
        console.print("[red]Error:[/red] ARBORIST_MANIFEST environment variable not set")
        console.print("This command should be run from a DAGU DAG step")
        raise SystemExit(1)

    try:
        manifest = load_manifest(Path(manifest_path))
    except FileNotFoundError:
        console.print(f"[red]Error:[/red] Manifest not found: {manifest_path}")
        raise SystemExit(1)
    except Exception as e:
        console.print(f"[red]Error loading manifest:[/red] {e}")
        raise SystemExit(1)

    if ctx.obj.get("echo_for_testing"):
        echo_command(
            "spec branch-cleanup-all",
            spec_id=manifest.spec_id,
            force=str(force),
            tasks=str(len(manifest.tasks)),
        )
        return

    if not ctx.obj.get("quiet"):
        console.print(f"[cyan]Cleaning up branches for spec {manifest.spec_id}...[/cyan]")
        console.print(f"[dim]Tasks: {len(manifest.tasks)}[/dim]")
        if force:
            console.print(f"[yellow]Force mode enabled[/yellow]")

    cleaned = []
    errors = []

    # Clean up each task in reverse order (children before parents)
    for task_info in reversed(manifest.tasks):
        worktree_path = get_worktree_path(manifest.spec_id, task_info.task_id)

        if not ctx.obj.get("quiet"):
            console.print(f"[dim]Cleaning up {task_info.task_id}...[/dim]")

        result = cleanup_task(task_info.branch, worktree_path, delete_branch=True)

        if result.success:
            cleaned.append(task_info.task_id)
        else:
            if force:
                # Force cleanup: remove worktree and branch with -D
                git_root = get_git_root()
                try:
                    if worktree_path.exists():
                        subprocess.run(
                            ["git", "worktree", "remove", str(worktree_path), "--force"],
                            cwd=git_root,
                            check=True,
                            capture_output=True,
                        )
                    if branch_exists(task_info.branch):
                        subprocess.run(
                            ["git", "branch", "-D", task_info.branch],
                            cwd=git_root,
                            check=True,
                            capture_output=True,
                        )
                    cleaned.append(task_info.task_id)
                except subprocess.CalledProcessError as e:
                    errors.append(f"{task_info.task_id}: {e.stderr.decode() if e.stderr else str(e)}")
            else:
                errors.append(f"{task_info.task_id}: {result.message}")

    # Also clean up the base branch if requested
    if branch_exists(manifest.base_branch):
        if not ctx.obj.get("quiet"):
            console.print(f"[dim]Cleaning up base branch {manifest.base_branch}...[/dim]")
        try:
            git_root = get_git_root()
            if force:
                subprocess.run(
                    ["git", "branch", "-D", manifest.base_branch],
                    cwd=git_root,
                    check=True,
                    capture_output=True,
                )
            else:
                subprocess.run(
                    ["git", "branch", "-d", manifest.base_branch],
                    cwd=git_root,
                    check=True,
                    capture_output=True,
                )
            cleaned.append("base")
        except subprocess.CalledProcessError as e:
            errors.append(f"base branch: {e.stderr.decode() if e.stderr else str(e)}")

    if errors:
        console.print(f"[yellow]Cleaned up {len(cleaned)} tasks with {len(errors)} errors:[/yellow]")
        for err in errors:
            console.print(f"  [red]Error:[/red] {err}")
        raise SystemExit(1)
    else:
        console.print(f"[green]OK:[/green] Cleaned up {len(cleaned)} tasks and branches")


@spec.command("dag-build")
@click.argument("directory", required=False, type=click.Path(exists=True))
@click.option(
    "--runner",
    "-r",
    type=click.Choice(["claude", "opencode", "gemini"]),
    default=None,
    help=f"Runner for AI inference (default: {DEFAULT_RUNNER})",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    help="Output path for DAG YAML (default: $DAGU_HOME/dags/<spec-id>.yaml)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Generate DAG without writing (implies --show)",
)
@click.option(
    "--show",
    is_flag=True,
    help="Display the generated YAML after writing",
)
@click.option(
    "--no-ai",
    is_flag=True,
    help="Use deterministic parser instead of AI inference",
)
@click.option(
    "--timeout",
    "-t",
    type=int,
    default=120,
    help="Timeout for AI inference in seconds (default: 120)",
)
@click.option(
    "--echo-only",
    is_flag=True,
    hidden=True,
    help="Generate DAG with --echo-for-testing flags for testing",
)
@click.pass_context
def spec_dag_build(
    ctx: click.Context,
    directory: str | None,
    runner: str | None,
    output: str | None,
    dry_run: bool,
    show: bool,
    no_ai: bool,
    timeout: int,
    echo_only: bool,
) -> None:
    """Build a DAGU DAG from a task spec directory using AI inference.

    DIRECTORY is the path to the task spec directory (default: specs/<spec-id>).
    The directory should contain task markdown files.

    By default, uses AI (claude/opencode/gemini) to analyze the spec and generate
    the DAG with proper dependencies. Use --no-ai for deterministic parsing.
    """
    # Resolve spec_id (full identifier like "002-my-feature")
    spec_id = ctx.obj.get("spec_id")

    if ctx.obj.get("echo_for_testing"):
        echo_command(
            "spec dag-build",
            spec_id=spec_id or "none",
            directory=directory or "auto",
            runner=runner or DEFAULT_RUNNER,
            no_ai=str(no_ai),
            echo_only=str(echo_only),
        )
        return

    # Resolve directory
    if directory:
        spec_dir = Path(directory)
    else:
        if not spec_id:
            console.print("[red]Error:[/red] No spec available")
            console.print("Either:")
            console.print("  - Provide a directory argument")
            console.print("  - Use --spec option (e.g., --spec 002-my-feature)")
            console.print("  - Run from a spec branch (e.g., 002-my-feature)")
            raise SystemExit(1)

        # Default to specs/<spec-id>
        try:
            git_root = get_git_root()
            spec_dir = git_root / "specs" / spec_id
        except ArboristHomeError:
            console.print("[red]Error:[/red] Not in a git repository")
            raise SystemExit(1)

    if not spec_dir.is_dir():
        console.print(f"[red]Error:[/red] Directory not found: {spec_dir}")
        raise SystemExit(1)

    # Find task spec files in directory
    task_files = list(spec_dir.glob("tasks*.md")) + list(spec_dir.glob("**/tasks*.md"))
    if not task_files:
        # Also try any .md file
        task_files = list(spec_dir.glob("*.md"))

    if not task_files:
        console.print(f"[red]Error:[/red] No task spec files found in {spec_dir}")
        raise SystemExit(1)

    # Use the first task file found (or combine them in future)
    task_file = task_files[0]
    if not ctx.obj.get("quiet"):
        console.print(f"[dim]Using task spec:[/dim] {task_file}")

    # Determine DAG name
    dag_name = spec_id or spec_dir.name

    if no_ai:
        # Deterministic parsing mode
        if not ctx.obj.get("quiet"):
            console.print("[dim]Using deterministic parser (--no-ai)[/dim]")

        try:
            task_spec = parse_task_spec(task_file)
        except Exception as e:
            console.print(f"[red]Error parsing task spec:[/red] {e}")
            raise SystemExit(1)

        if not ctx.obj.get("quiet"):
            console.print(f"[dim]Found {len(task_spec.tasks)} tasks in {len(task_spec.phases)} phases[/dim]")

        dag_name_safe = dag_name.replace("-", "_")
        config = DagConfig(
            name=dag_name_safe,
            description=task_spec.project,
        )
        builder = DagBuilder(config)
        dag_yaml = builder.build_yaml(task_spec)
    else:
        # AI inference mode
        runner_type = runner or DEFAULT_RUNNER
        if not ctx.obj.get("quiet"):
            console.print(f"[cyan]Generating DAG using {runner_type}...[/cyan]")

        # Check if runner is available
        runner_instance = get_runner(runner_type)
        if not runner_instance.is_available():
            console.print(f"[red]Error:[/red] {runner_type} not found in PATH")
            console.print("Install the runner or use --no-ai for deterministic parsing")
            raise SystemExit(1)

        # Read spec content
        spec_content = task_file.read_text()

        # Generate using AI
        generator = DagGenerator(runner=runner_instance)
        result = generator.generate(spec_content, dag_name, timeout=timeout)

        if not result.success:
            console.print(f"[red]Error generating DAG:[/red] {result.error}")
            if result.raw_output:
                console.print(f"[dim]Raw output:[/dim]\n{result.raw_output[:500]}...")
            raise SystemExit(1)

        dag_yaml = result.yaml_content
        if not ctx.obj.get("quiet"):
            console.print("[green]OK:[/green] DAG generated successfully")

    if dry_run:
        console.print(dag_yaml)
        return

    # Determine output path - use spec_id for filename
    if output:
        output_path = Path(output)
    else:
        dagu_home = ctx.obj.get("dagu_home")
        if not dagu_home:
            console.print("[red]Error:[/red] DAGU_HOME not set")
            console.print("Run 'arborist init' first or specify --output")
            raise SystemExit(1)
        output_path = Path(dagu_home) / "dags" / f"{dag_name}.yaml"

    # Ensure parent directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Generate and save branch manifest
    if not ctx.obj.get("quiet"):
        console.print("[cyan]Generating branch manifest...[/cyan]")

    # Get current branch for base naming
    source_branch = get_current_branch()

    # Build task tree from spec
    from agent_arborist.task_state import build_task_tree_from_spec
    task_tree = build_task_tree_from_spec(dag_name, task_file)

    # Generate manifest
    manifest = generate_manifest(dag_name, task_tree, source_branch)

    # Save manifest alongside DAG
    manifest_path = output_path.with_suffix(".json")
    save_manifest(manifest, manifest_path)

    if not ctx.obj.get("quiet"):
        console.print(f"[green]Manifest written to:[/green] {manifest_path}")
        console.print(f"[dim]  Source branch: {manifest.source_branch}[/dim]")
        console.print(f"[dim]  Base branch: {manifest.base_branch}[/dim]")
        console.print(f"[dim]  Tasks: {len(manifest.tasks)}[/dim]")

    # Inject ARBORIST_MANIFEST env into generated DAG YAML
    import yaml
    dag_data = yaml.safe_load(dag_yaml)

    # Add env section if not present
    if "env" not in dag_data:
        dag_data["env"] = []

    # Add manifest path - use DAG_DIR variable that DAGU provides
    manifest_env = f"ARBORIST_MANIFEST: ${{DAG_DIR}}/{manifest_path.name}"
    dag_data["env"].append(manifest_env)

    # If echo_only, inject --echo-for-testing into all arborist commands
    if echo_only:
        for step in dag_data.get("steps", []):
            cmd = step.get("command", "")
            # Handle both 'arborist' and potential path variations
            if "arborist " in cmd:
                step["command"] = cmd.replace("arborist ", "arborist --echo-for-testing ", 1)

    # Re-serialize YAML
    dag_yaml = yaml.dump(dag_data, default_flow_style=False, sort_keys=False)

    # Write the DAG
    output_path.write_text(dag_yaml)
    console.print(f"[green]DAG written to:[/green] {output_path}")

    # Show the YAML if requested
    if show:
        console.print()
        console.print(dag_yaml)

    # Validate with dagu if available
    dagu_path = shutil.which("dagu")
    if dagu_path and not ctx.obj.get("quiet"):
        console.print("\n[cyan]Validating DAG with dagu...[/cyan]")
        try:
            result = subprocess.run(
                [dagu_path, "dry", "--quiet", str(output_path)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                console.print("[green]OK:[/green] DAG validation passed")
            else:
                console.print(f"[yellow]WARN:[/yellow] DAG validation issues")
                if result.stderr:
                    console.print(f"[dim]{result.stderr}[/dim]")
        except subprocess.TimeoutExpired:
            console.print("[yellow]WARN:[/yellow] DAG validation timed out")
        except Exception as e:
            console.print(f"[yellow]WARN:[/yellow] Could not validate DAG: {e}")


@spec.command("dag-show")
@click.argument("dag_name", required=False)
@click.option("--deps", is_flag=True, help="Show dependency graph")
@click.option("--blocking", is_flag=True, help="Show what each step blocks")
@click.option("--yaml", "show_yaml", is_flag=True, help="Show raw YAML content")
@click.pass_context
def spec_dag_show(
    ctx: click.Context,
    dag_name: str | None,
    deps: bool,
    blocking: bool,
    show_yaml: bool,
) -> None:
    """Show information about a DAG.

    DAG_NAME is the name of the DAG (default: current spec-id).
    Looks for <dag-name>.yaml in $DAGU_HOME/dags/.
    """
    import yaml

    spec_id = ctx.obj.get("spec_id")

    if ctx.obj.get("echo_for_testing"):
        echo_command(
            "spec dag-show",
            dag_name=dag_name or spec_id or "none",
            deps=str(deps),
            blocking=str(blocking),
            yaml=str(show_yaml),
        )
        return

    # Resolve DAG name
    if not dag_name:
        dag_name = spec_id
        if not dag_name:
            console.print("[red]Error:[/red] No DAG name specified and no spec available")
            console.print("Provide a DAG name or use --spec option")
            raise SystemExit(1)

    # Find the DAG file
    dagu_home = ctx.obj.get("dagu_home")
    if dagu_home:
        dag_path = Path(dagu_home) / "dags" / f"{dag_name}.yaml"
    else:
        # Try current directory
        dag_path = Path(f"{dag_name}.yaml")

    if not dag_path.exists():
        console.print(f"[red]Error:[/red] DAG file not found: {dag_path}")
        raise SystemExit(1)

    # Parse the DAG
    try:
        dag_content = dag_path.read_text()
        dag_data = yaml.safe_load(dag_content)
    except Exception as e:
        console.print(f"[red]Error parsing DAG:[/red] {e}")
        raise SystemExit(1)

    steps = dag_data.get("steps", [])

    # Show raw YAML if requested
    if show_yaml:
        console.print(dag_content)
        return

    # Default: show summary
    if not deps and not blocking:
        console.print(f"[bold]DAG:[/bold] {dag_data.get('name', dag_name)}")
        console.print(f"[dim]Description:[/dim] {dag_data.get('description', '-')}")
        console.print(f"[dim]Steps:[/dim] {len(steps)}")
        console.print(f"[dim]File:[/dim] {dag_path}")
        console.print()

        # Show steps summary
        table = Table(title="Steps")
        table.add_column("Step", style="cyan")
        table.add_column("Depends On")
        table.add_column("Blocked By")

        # Build reverse dependency map (what blocks what)
        blocked_by: dict[str, list[str]] = {s["name"]: [] for s in steps}
        for step in steps:
            for dep in step.get("depends", []):
                if dep in blocked_by:
                    blocked_by[dep].append(step["name"])

        for step in steps:
            step_deps = step.get("depends", [])
            step_blocks = blocked_by.get(step["name"], [])
            table.add_row(
                step["name"],
                ", ".join(step_deps) if step_deps else "-",
                ", ".join(step_blocks) if step_blocks else "-",
            )

        console.print(table)
        return

    # Show dependency graph
    if deps:
        console.print(f"[bold]Dependencies for {dag_name}:[/bold]")
        console.print()
        for step in steps:
            step_deps = step.get("depends", [])
            if step_deps:
                console.print(f"  {step['name']}")
                for dep in step_deps:
                    console.print(f"    ← {dep}")
            else:
                console.print(f"  {step['name']} [dim](no dependencies)[/dim]")
        console.print()

    # Show blocking graph
    if blocking:
        console.print(f"[bold]Blocking relationships for {dag_name}:[/bold]")
        console.print()

        # Build reverse map
        blocked_by: dict[str, list[str]] = {s["name"]: [] for s in steps}
        for step in steps:
            for dep in step.get("depends", []):
                if dep in blocked_by:
                    blocked_by[dep].append(step["name"])

        for step in steps:
            blocks = blocked_by.get(step["name"], [])
            if blocks:
                console.print(f"  {step['name']}")
                for blocked in blocks:
                    console.print(f"    → {blocked}")
            else:
                console.print(f"  {step['name']} [dim](blocks nothing)[/dim]")
        console.print()


# -----------------------------------------------------------------------------
# DAG commands
# -----------------------------------------------------------------------------


@main.group()
def dag() -> None:
    """DAG execution and monitoring."""
    pass


@dag.command("run")
@click.argument("dag_name", required=False)
@click.option("--dry-run", is_flag=True, help="Simulate execution without running commands")
@click.option("--params", "-p", help="Parameters to pass to the DAG (key=value pairs)")
@click.option("--run-id", "-r", help="Specify a run ID (auto-generated if not set)")
@click.pass_context
def dag_run(
    ctx: click.Context,
    dag_name: str | None,
    dry_run: bool,
    params: str | None,
    run_id: str | None,
) -> None:
    """Execute a DAG.

    DAG_NAME is the name of the DAG (default: current spec-id).
    Looks for <dag-name>.yaml in $DAGU_HOME/dags/.

    Sets ARBORIST_MANIFEST environment variable from the companion .json file.
    """
    spec_id = ctx.obj.get("spec_id")
    dagu_home = ctx.obj.get("dagu_home")

    # Resolve DAG name
    resolved_dag_name = dag_name or spec_id

    if ctx.obj.get("echo_for_testing"):
        echo_command(
            "dag run",
            spec_id=spec_id or "none",
            dag_name=resolved_dag_name or "none",
            dry_run=str(dry_run),
            params=params or "none",
            run_id=run_id or "auto",
            dagu_home=str(dagu_home) if dagu_home else "none",
        )
        return

    # Check DAGU_HOME is set
    if not dagu_home:
        console.print("[red]Error:[/red] DAGU_HOME not set")
        console.print("Run 'arborist init' first to initialize the project")
        raise SystemExit(1)

    # Resolve DAG name
    if not resolved_dag_name:
        console.print("[red]Error:[/red] No DAG name specified and no spec available")
        console.print("Provide a DAG name or use --spec option")
        raise SystemExit(1)

    # Find DAG file
    dag_path = Path(dagu_home) / "dags" / f"{resolved_dag_name}.yaml"
    if not dag_path.exists():
        console.print(f"[red]Error:[/red] DAG file not found: {dag_path}")
        raise SystemExit(1)

    # Find manifest file (companion .json)
    manifest_path = dag_path.with_suffix(".json")

    # Check dagu is installed
    dagu_path = shutil.which("dagu")
    if not dagu_path:
        console.print("[red]Error:[/red] dagu not found in PATH")
        console.print("Install dagu: https://dagu.readthedocs.io/")
        raise SystemExit(1)

    # Build environment with ARBORIST_MANIFEST
    env = os.environ.copy()
    env[DAGU_HOME_ENV_VAR] = str(dagu_home)
    if manifest_path.exists():
        env["ARBORIST_MANIFEST"] = str(manifest_path)

    # Build dagu command
    dagu_cmd = "dry" if dry_run else "start"
    cmd = [dagu_path, dagu_cmd]

    # --run-id is only valid for start, not dry
    if run_id and not dry_run:
        cmd.extend(["--run-id", run_id])

    cmd.append(str(dag_path))

    # Add params after -- separator
    if params:
        cmd.append("--")
        cmd.append(params)

    if not ctx.obj.get("quiet"):
        action = "Dry running" if dry_run else "Starting"
        console.print(f"[cyan]{action} DAG {resolved_dag_name}...[/cyan]")
        console.print(f"[dim]DAG file: {dag_path}[/dim]")
        if manifest_path.exists():
            console.print(f"[dim]Manifest: {manifest_path}[/dim]")

    try:
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=600,  # 10 minute timeout
        )

        if result.returncode == 0:
            console.print(f"[green]OK:[/green] DAG {dagu_cmd} completed")
            if result.stdout and not ctx.obj.get("quiet"):
                console.print(result.stdout)
        else:
            console.print(f"[red]Error:[/red] DAG {dagu_cmd} failed")
            if result.stderr:
                console.print(f"[dim]{result.stderr}[/dim]")
            if result.stdout:
                console.print(f"[dim]{result.stdout}[/dim]")
            raise SystemExit(1)

    except subprocess.TimeoutExpired:
        console.print("[red]Error:[/red] DAG execution timed out")
        raise SystemExit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@dag.command("run-status")
@click.argument("dag_name", required=False)
@click.option("--run-id", "-r", help="Specific run ID (default: most recent)")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option("--watch", "-w", is_flag=True, help="Continuously watch status updates")
@click.pass_context
def dag_run_status(
    ctx: click.Context,
    dag_name: str | None,
    run_id: str | None,
    as_json: bool,
    watch: bool,
) -> None:
    """Get status of a DAG run.

    DAG_NAME is the name of the DAG (default: current spec-id).

    Without --run-id, shows the status of the most recent run.
    """
    spec_id = ctx.obj.get("spec_id")
    dagu_home = ctx.obj.get("dagu_home")

    # Resolve DAG name
    resolved_dag_name = dag_name or spec_id

    if ctx.obj.get("echo_for_testing"):
        echo_command(
            "dag run-status",
            spec_id=spec_id or "none",
            dag_name=resolved_dag_name or "none",
            run_id=run_id or "latest",
            json=str(as_json),
            watch=str(watch),
            dagu_home=str(dagu_home) if dagu_home else "none",
        )
        return

    # Check DAGU_HOME is set
    if not dagu_home:
        console.print("[red]Error:[/red] DAGU_HOME not set")
        console.print("Run 'arborist init' first to initialize the project")
        raise SystemExit(1)

    # Resolve DAG name
    if not resolved_dag_name:
        console.print("[red]Error:[/red] No DAG name specified and no spec available")
        console.print("Provide a DAG name or use --spec option")
        raise SystemExit(1)

    # Find DAG file
    dag_path = Path(dagu_home) / "dags" / f"{resolved_dag_name}.yaml"
    if not dag_path.exists():
        console.print(f"[red]Error:[/red] DAG file not found: {dag_path}")
        raise SystemExit(1)

    # Check dagu is installed
    dagu_path = shutil.which("dagu")
    if not dagu_path:
        console.print("[red]Error:[/red] dagu not found in PATH")
        raise SystemExit(1)

    # Build environment
    env = os.environ.copy()
    env[DAGU_HOME_ENV_VAR] = str(dagu_home)

    # Build dagu status command
    cmd = [dagu_path, "status"]

    if run_id:
        cmd.extend(["--run-id", run_id])

    cmd.append(str(dag_path))

    if not ctx.obj.get("quiet") and not as_json:
        console.print(f"[cyan]Checking status of {resolved_dag_name}...[/cyan]")

    try:
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            output = result.stdout.strip()
            if as_json:
                # Try to parse and pretty-print JSON, or just output raw
                try:
                    import json
                    data = json.loads(output)
                    console.print(json.dumps(data, indent=2))
                except json.JSONDecodeError:
                    # Not JSON, just output as-is
                    console.print(output)
            else:
                if output:
                    console.print(output)
                else:
                    console.print("[dim]No status information available[/dim]")
        else:
            # dagu status may return non-zero for "no runs" case
            if "no" in result.stderr.lower() or "not found" in result.stderr.lower():
                console.print("[dim]No runs found for this DAG[/dim]")
            else:
                console.print(f"[red]Error:[/red] Status check failed")
                if result.stderr:
                    console.print(f"[dim]{result.stderr}[/dim]")
                raise SystemExit(1)

    except subprocess.TimeoutExpired:
        console.print("[red]Error:[/red] Status check timed out")
        raise SystemExit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@dag.command("run-show")
@click.argument("dag_name", required=False)
@click.option("--run-id", "-r", help="Specific run ID (default: most recent)")
@click.option("--logs", is_flag=True, help="Include step logs in output")
@click.option("--step", "-s", help="Show details for a specific step")
@click.pass_context
def dag_run_show(
    ctx: click.Context,
    dag_name: str | None,
    run_id: str | None,
    logs: bool,
    step: str | None,
) -> None:
    """Show details of a DAG run.

    DAG_NAME is the name of the DAG (default: current spec-id).

    Displays step-by-step execution details, timing, and optionally logs.
    """
    spec_id = ctx.obj.get("spec_id")
    dagu_home = ctx.obj.get("dagu_home")

    # Resolve DAG name
    resolved_dag_name = dag_name or spec_id

    if ctx.obj.get("echo_for_testing"):
        echo_command(
            "dag run-show",
            spec_id=spec_id or "none",
            dag_name=resolved_dag_name or "none",
            run_id=run_id or "latest",
            logs=str(logs),
            step=step or "all",
            dagu_home=str(dagu_home) if dagu_home else "none",
        )
        return

    # Check DAGU_HOME is set
    if not dagu_home:
        console.print("[red]Error:[/red] DAGU_HOME not set")
        console.print("Run 'arborist init' first to initialize the project")
        raise SystemExit(1)

    # Resolve DAG name
    if not resolved_dag_name:
        console.print("[red]Error:[/red] No DAG name specified and no spec available")
        console.print("Provide a DAG name or use --spec option")
        raise SystemExit(1)

    # Find DAG file
    dag_path = Path(dagu_home) / "dags" / f"{resolved_dag_name}.yaml"
    if not dag_path.exists():
        console.print(f"[red]Error:[/red] DAG file not found: {dag_path}")
        raise SystemExit(1)

    # Check dagu is installed
    dagu_path = shutil.which("dagu")
    if not dagu_path:
        console.print("[red]Error:[/red] dagu not found in PATH")
        raise SystemExit(1)

    # Build environment
    env = os.environ.copy()
    env[DAGU_HOME_ENV_VAR] = str(dagu_home)

    # Use dagu status to get run details
    cmd = [dagu_path, "status"]

    if run_id:
        cmd.extend(["--run-id", run_id])

    cmd.append(str(dag_path))

    if not ctx.obj.get("quiet"):
        console.print(f"[cyan]Run details for {resolved_dag_name}[/cyan]")
        if run_id:
            console.print(f"[dim]Run ID: {run_id}[/dim]")

    try:
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            output = result.stdout.strip()

            if not output:
                console.print("[dim]No run information available[/dim]")
                return

            # Filter by step if specified
            if step:
                lines = output.split("\n")
                filtered_lines = [l for l in lines if step.lower() in l.lower()]
                if filtered_lines:
                    console.print(f"\n[bold]Step: {step}[/bold]")
                    for line in filtered_lines:
                        console.print(line)
                else:
                    console.print(f"[dim]No information found for step: {step}[/dim]")
            else:
                # Show all steps
                console.print(output)

            # If logs requested, try to find and display log files
            if logs:
                console.print("\n[bold]Logs:[/bold]")
                # Look for log files in dagu's data directory
                log_dir = Path(dagu_home) / "data" / resolved_dag_name
                if log_dir.exists():
                    log_files = list(log_dir.glob("**/*.log"))
                    if log_files:
                        for log_file in log_files[:5]:  # Limit to 5 logs
                            if step and step.lower() not in log_file.name.lower():
                                continue
                            console.print(f"\n[dim]--- {log_file.name} ---[/dim]")
                            try:
                                log_content = log_file.read_text()
                                console.print(log_content[:2000])  # Limit output
                                if len(log_content) > 2000:
                                    console.print("[dim]... (truncated)[/dim]")
                            except Exception as e:
                                console.print(f"[dim]Could not read log: {e}[/dim]")
                    else:
                        console.print("[dim]No log files found[/dim]")
                else:
                    console.print("[dim]No log directory found[/dim]")
        else:
            if "no" in result.stderr.lower() or "not found" in result.stderr.lower():
                console.print("[dim]No runs found for this DAG[/dim]")
            else:
                console.print(f"[red]Error:[/red] Could not get run details")
                if result.stderr:
                    console.print(f"[dim]{result.stderr}[/dim]")
                raise SystemExit(1)

    except subprocess.TimeoutExpired:
        console.print("[red]Error:[/red] Request timed out")
        raise SystemExit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@dag.command("dashboard")
@click.option("--port", "-p", type=int, default=8080, help="Port to run dashboard on")
@click.option("--host", "-H", default="127.0.0.1", help="Host to bind to")
@click.pass_context
def dag_dashboard(
    ctx: click.Context,
    port: int,
    host: str,
) -> None:
    """Launch the Dagu web dashboard.

    Starts the Dagu server which provides a web UI for monitoring and
    managing DAG executions. Press Ctrl+C to stop the server.

    The dashboard will be available at http://<host>:<port>/
    """
    import signal

    arborist_home = ctx.obj.get("arborist_home")
    dagu_home = ctx.obj.get("dagu_home")

    if ctx.obj.get("echo_for_testing"):
        echo_command(
            "dag dashboard",
            arborist_home=str(arborist_home) if arborist_home else "none",
            dagu_home=str(dagu_home) if dagu_home else "none",
            port=str(port),
            host=host,
        )
        return

    # Check DAGU_HOME is set
    if not dagu_home:
        console.print("[red]Error:[/red] DAGU_HOME not set")
        console.print("Run 'arborist init' first to initialize the project")
        raise SystemExit(1)

    # Check dagu is installed
    dagu_path = shutil.which("dagu")
    if not dagu_path:
        console.print("[red]Error:[/red] dagu not found in PATH")
        console.print("Install dagu: https://dagu.readthedocs.io/")
        raise SystemExit(1)

    # Build environment
    env = os.environ.copy()
    env[DAGU_HOME_ENV_VAR] = str(dagu_home)

    # Build dagu server command
    dags_dir = Path(dagu_home) / "dags"
    cmd = [
        dagu_path,
        "server",
        "--host",
        host,
        "--port",
        str(port),
        "--dags",
        str(dags_dir),
    ]

    if not ctx.obj.get("quiet"):
        console.print(f"[cyan]Starting Dagu dashboard...[/cyan]")
        console.print(f"[dim]DAGU_HOME: {dagu_home}[/dim]")
        console.print(f"[dim]DAGs directory: {dags_dir}[/dim]")
        console.print(f"[green]Dashboard URL: http://{host}:{port}/[/green]")
        console.print("[dim]Press Ctrl+C to stop[/dim]")

    process: subprocess.Popen | None = None

    def signal_handler(sig: int, frame: object) -> None:
        """Handle Ctrl+C gracefully."""
        console.print("\n[yellow]Shutting down dashboard...[/yellow]")
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        raise SystemExit(0)

    # Register signal handler
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Start dagu server as a subprocess
        # Use stdin/stdout/stderr pass-through for interactive output
        process = subprocess.Popen(
            cmd,
            env=env,
        )

        # Wait for the process to complete (blocking)
        exit_code = process.wait()

        if exit_code != 0:
            console.print(f"[red]Error:[/red] Dashboard exited with code {exit_code}")
            raise SystemExit(exit_code)

    except Exception as e:
        if process is not None:
            process.terminate()
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


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
