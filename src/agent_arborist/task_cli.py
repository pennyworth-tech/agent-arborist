"""CLI commands for task execution.

This module provides the task subcommands for running tasks.
Uses jj workspaces for parallel execution with atomic squash operations.
"""

import os
import subprocess
from pathlib import Path

import click
import yaml
from rich.console import Console

from agent_arborist.step_results import (
    StepResult,
    PreSyncResult,
    RunResult,
    RunTestResult,
    CommitResult,
)
from agent_arborist.tasks import (
    run_jj,
    is_jj_repo,
    is_colocated,
    get_change_id,
    create_task_change,
    complete_task,
    sync_parent,
    get_workspace_path,
    create_workspace,
    setup_task_workspace,
    find_tasks_by_spec,
    get_task_status,
    describe_change,
    rebase_change,
    edit_change,
    JJResult,
    TaskChange,
    detect_test_command,
    build_task_description,
    find_change_by_description,
    get_parent_task_path,
)
from agent_arborist.task_state import TaskTree, TaskNode, build_task_tree_from_yaml
from agent_arborist.home import get_git_root

console = Console()


def _get_spec_id(ctx: click.Context) -> str | None:
    """Get spec_id from context or environment."""
    spec_id = os.environ.get("ARBORIST_SPEC_ID")
    if not spec_id:
        spec_id = ctx.obj.get("spec_id") if ctx.obj else None
    return spec_id


def _get_task_path() -> list[str] | None:
    """Get task path from ARBORIST_TASK_PATH environment variable.

    Returns:
        List of task IDs (e.g., ["T1", "T2", "T6"]) or None if not set
    """
    path_str = os.environ.get("ARBORIST_TASK_PATH")
    if path_str:
        return path_str.split(":")
    return None


def _get_source_rev() -> str | None:
    """Get source revision from ARBORIST_SOURCE_REV environment variable."""
    return os.environ.get("ARBORIST_SOURCE_REV")


def _find_dag_yaml_path(spec_id: str) -> Path | None:
    """Find DAG YAML file for a spec.

    Search order:
    1. {git_root}/.arborist/dagu/dags/{spec_id}.yaml
    """
    try:
        git_root = get_git_root()
    except Exception:
        return None

    dag_path = git_root / ".arborist" / "dagu" / "dags" / f"{spec_id}.yaml"
    if dag_path.exists():
        return dag_path
    return None


def _find_change_for_task(spec_id: str, task_path: list[str]) -> str | None:
    """Find the jj change ID for a task by its hierarchical description.

    Args:
        spec_id: Specification ID
        task_path: Hierarchical task path (e.g., ["T1", "T2", "T6"])

    Returns:
        Change ID or None if not found
    """
    return find_change_by_description(spec_id, task_path)


def _compute_task_paths(task_tree: TaskTree) -> dict[str, list[str]]:
    """Compute hierarchical paths for all tasks in the tree.

    Args:
        task_tree: TaskTree with all tasks

    Returns:
        Dict mapping task_id to its full path (e.g., {"T6": ["T1", "T2", "T6"]})
    """
    paths: dict[str, list[str]] = {}

    def compute_path(task_id: str) -> list[str]:
        if task_id in paths:
            return paths[task_id]

        task = task_tree.get_task(task_id)
        if not task or not task.parent_id:
            # Root task - path is just the task ID
            paths[task_id] = [task_id]
        else:
            # Child task - path is parent's path + this task
            parent_path = compute_path(task.parent_id)
            paths[task_id] = parent_path + [task_id]

        return paths[task_id]

    # Compute paths for all tasks
    for task_id in task_tree.tasks:
        compute_path(task_id)

    return paths


def _topological_sort(task_tree: TaskTree) -> list[str]:
    """Sort tasks in topological order (parents before children).

    Args:
        task_tree: TaskTree with all tasks

    Returns:
        List of task IDs in topological order
    """
    # Build children map
    children_of: dict[str, list[str]] = {tid: [] for tid in task_tree.tasks}
    for task_id, task in task_tree.tasks.items():
        if task.parent_id and task.parent_id in children_of:
            children_of[task.parent_id].append(task_id)

    # Find root tasks (no parent)
    roots = [tid for tid, task in task_tree.tasks.items() if task.parent_id is None]

    # BFS to get topological order
    result = []
    queue = list(roots)

    while queue:
        task_id = queue.pop(0)
        result.append(task_id)
        queue.extend(children_of.get(task_id, []))

    return result


def _create_changes_from_tree(
    spec_id: str,
    task_tree: TaskTree,
    source_rev: str,
) -> dict:
    """Create jj changes for all tasks in the tree.

    Creates changes in topological order with hierarchical descriptions.

    Args:
        spec_id: Specification ID
        task_tree: TaskTree with all tasks
        source_rev: Base revision (e.g., "main", branch name)

    Returns:
        Dict with:
        - verified: list of task IDs whose changes already exist
        - created: list of task IDs for newly created changes
        - errors: list of error messages
    """
    result = {
        "verified": [],
        "created": [],
        "errors": [],
    }

    # Compute task paths
    task_paths = _compute_task_paths(task_tree)

    # Track change IDs as we create/find them
    change_ids: dict[str, str] = {}

    # Process in topological order
    task_order = _topological_sort(task_tree)

    for task_id in task_order:
        task_path = task_paths[task_id]

        # Check if change already exists
        existing = find_change_by_description(spec_id, task_path)
        if existing:
            change_ids[task_id] = existing
            result["verified"].append(task_id)
            continue

        # Determine parent change
        task = task_tree.get_task(task_id)
        if task and task.parent_id:
            # Child task - parent is the parent task's change
            if task.parent_id not in change_ids:
                result["errors"].append(
                    f"{task_id}: Parent task {task.parent_id} not yet created"
                )
                continue
            parent_change = change_ids[task.parent_id]
        else:
            # Root task - parent is the source revision
            parent_change = source_rev

        # Create the change
        try:
            new_change_id = create_task_change(
                spec_id=spec_id,
                task_id=task_id,
                parent_change=parent_change,
                task_path=task_path,
            )
            change_ids[task_id] = new_change_id
            result["created"].append(task_id)
        except Exception as e:
            result["errors"].append(f"{task_id}: Failed to create - {e}")

    return result


def _get_task_info_from_env() -> tuple[str | None, list[str] | None, str | None]:
    """Get task info from environment variables.

    Returns:
        Tuple of (spec_id, task_path, source_rev)
    """
    spec_id = os.environ.get("ARBORIST_SPEC_ID")
    task_path = _get_task_path()
    source_rev = _get_source_rev()
    return spec_id, task_path, source_rev


def _find_parent_change(spec_id: str, task_path: list[str]) -> str | None:
    """Find the parent task's change ID.

    Args:
        spec_id: Specification ID
        task_path: Current task's path

    Returns:
        Parent's change ID, or None if this is a root task
    """
    parent_path = get_parent_task_path(task_path)
    if not parent_path:
        return None
    return find_change_by_description(spec_id, parent_path)


def _output_result(result: StepResult, ctx: click.Context) -> None:
    """Output step result in appropriate format."""
    output_format = ctx.obj.get("output_format", "json") if ctx.obj else "json"

    if output_format == "json":
        print(result.to_json())
    else:
        # Rich console output for text mode
        if result.success:
            console.print(f"[green]Success[/green]")
        else:
            console.print(f"[red]Failed:[/red] {result.error}")


def _echo_command(cmd: str, **kwargs: str | None) -> None:
    """Output a consistently formatted echo line for testing."""
    parts = [f"ECHO: {cmd:<30}"]

    standard_fields = ["spec_id", "task_id"]
    for field in standard_fields:
        if field in kwargs and kwargs[field] is not None:
            parts.append(f"{field}={kwargs[field]}")

    for key, value in kwargs.items():
        if key not in standard_fields and value is not None:
            parts.append(f"{key}={value}")

    print(" | ".join(parts) if len(parts) > 1 else parts[0])


@click.group()
def task() -> None:
    """Task execution commands.

    Commands for executing parallel tasks with jj workspaces.
    Key benefits:
    - Atomic squash operations (no merge conflicts during sync)
    - Change IDs are stable across amends
    - Parallel execution via jj workspaces
    """
    pass


@task.command("status")
@click.argument("task_id", required=False)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def task_status(ctx: click.Context, task_id: str | None, as_json: bool) -> None:
    """Show status of jj tasks.

    Without TASK_ID, shows all tasks in the current spec.
    With TASK_ID, shows details for that specific task.
    """
    spec_id = _get_spec_id(ctx)

    if ctx.obj and ctx.obj.get("echo_for_testing"):
        _echo_command("task status", spec_id=spec_id or "", task_id=task_id or "all", json=str(as_json))
        return

    if not is_jj_repo():
        console.print("[red]Error:[/red] Not in a jj repository")
        raise SystemExit(1)

    if not spec_id:
        console.print("[red]Error:[/red] No spec available")
        console.print("Use --spec or set ARBORIST_SPEC_ID")
        raise SystemExit(1)

    # Find all tasks for this spec from jj
    tasks = find_tasks_by_spec(spec_id)

    if task_id:
        # Show specific task
        task = next((t for t in tasks if t.task_id == task_id), None)

        if not task:
            console.print(f"[red]Error:[/red] Task {task_id} not found in jj")
            raise SystemExit(1)

        if as_json:
            import json
            print(json.dumps({
                "task_id": task_id,
                "change_id": task.change_id,
                "status": task.status,
                "has_conflict": task.has_conflict,
            }))
        else:
            console.print(f"[bold]Task:[/bold] {task_id}")
            console.print(f"[dim]Change ID:[/dim] {task.change_id}")
            console.print(f"[dim]Status:[/dim] {task.status}")
            if task.has_conflict:
                console.print("[red]Has conflicts[/red]")
    else:
        # Show all tasks in spec
        if as_json:
            import json
            print(json.dumps([
                {"task_id": t.task_id, "change_id": t.change_id, "status": t.status}
                for t in tasks
            ]))
        else:
            if not tasks:
                console.print(f"[yellow]No tasks found for spec:[/yellow] {spec_id}")
            else:
                from rich.table import Table
                table = Table(title=f"Tasks for {spec_id}")
                table.add_column("Task ID")
                table.add_column("Change ID")
                table.add_column("Status")

                for t in sorted(tasks, key=lambda x: x.task_id):
                    status_color = {
                        "pending": "yellow",
                        "running": "cyan",
                        "done": "green",
                    }.get(t.status, "white")
                    table.add_row(t.task_id, t.change_id[:12], f"[{status_color}]{t.status}[/{status_color}]")

                console.print(table)


@task.command("setup-spec")
@click.pass_context
def task_setup_spec(ctx: click.Context) -> None:
    """Setup jj changes for all tasks in the spec.

    Creates all changes from the manifest if they don't exist.
    This is typically run as the first step in a DAG.
    """
    spec_id = _get_spec_id(ctx)
    source_rev = _get_source_rev()

    if ctx.obj and ctx.obj.get("echo_for_testing"):
        _echo_command("task setup-spec", spec_id=spec_id)
        return

    if not spec_id:
        console.print("[red]Error:[/red] No spec available (set ARBORIST_SPEC_ID)")
        raise SystemExit(1)

    if not source_rev:
        console.print("[red]Error:[/red] No source revision (set ARBORIST_SOURCE_REV)")
        raise SystemExit(1)

    try:
        # Auto-initialize jj in colocated mode if not already a jj repo
        if not is_jj_repo():
            console.print("[cyan]Initializing jj in colocated mode...[/cyan]")
            run_jj("git", "init", "--colocate")
            console.print("[green]jj initialized successfully[/green]")

        # Sync jj with git to pick up any recent git commits (e.g., DAG files)
        if is_colocated():
            console.print("[dim]Syncing jj with git...[/dim]")
            run_jj("git", "import")

        # Find and parse DAG YAML for task structure
        dag_path = _find_dag_yaml_path(spec_id)
        if not dag_path:
            console.print(f"[red]Error:[/red] DAG YAML not found for {spec_id}")
            raise SystemExit(1)

        dag_yaml = dag_path.read_text()
        task_tree = build_task_tree_from_yaml(spec_id, dag_yaml)

        console.print(f"[cyan]Setting up jj changes for spec:[/cyan] {spec_id}")
        console.print(f"[dim]Source revision:[/dim] {source_rev}")
        console.print(f"[dim]Tasks:[/dim] {len(task_tree.tasks)}")

        # Create changes with hierarchical descriptions
        result = _create_changes_from_tree(spec_id, task_tree, source_rev)

        if result["verified"]:
            console.print(f"[green]Verified:[/green] {len(result['verified'])} existing changes")
        if result["created"]:
            console.print(f"[green]Created:[/green] {len(result['created'])} new changes")
        if result["errors"]:
            console.print(f"[red]Errors:[/red] {len(result['errors'])}")
            for err in result["errors"]:
                console.print(f"  - {err}")
            raise SystemExit(1)

        console.print("[green]Setup complete[/green]")

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@task.command("pre-sync")
@click.argument("task_id")
@click.pass_context
def task_pre_sync(ctx: click.Context, task_id: str) -> None:
    """Prepare task for execution by creating/switching workspace and rebasing.

    This command:
    1. Creates a workspace for the task if needed
    2. Switches to the task's change
    3. Rebases onto parent to get latest changes

    Uses env vars: ARBORIST_SPEC_ID, ARBORIST_TASK_PATH, ARBORIST_SOURCE_REV
    """
    spec_id = _get_spec_id(ctx)
    task_path = _get_task_path()
    source_rev = _get_source_rev()

    if ctx.obj and ctx.obj.get("echo_for_testing"):
        _echo_command("task pre-sync", spec_id=spec_id, task_id=task_id)
        return

    try:
        if not spec_id:
            console.print("[red]Error:[/red] No spec available (set ARBORIST_SPEC_ID)")
            raise SystemExit(1)

        if not task_path:
            console.print("[red]Error:[/red] No task path available (set ARBORIST_TASK_PATH)")
            raise SystemExit(1)

        # Find change ID by hierarchical description
        change_id = find_change_by_description(spec_id, task_path)
        if not change_id:
            console.print(f"[red]Error:[/red] Task change not found for {spec_id}:{':'.join(task_path)}")
            raise SystemExit(1)

        # Find parent change (either parent task or source_rev)
        parent_change = _find_parent_change(spec_id, task_path) or source_rev or "main"

        console.print(f"[cyan]Pre-sync for task:[/cyan] {task_id}")
        console.print(f"[dim]Task path:[/dim] {':'.join(task_path)}")
        console.print(f"[dim]Change ID:[/dim] {change_id}")
        console.print(f"[dim]Parent:[/dim] {parent_change}")

        # Get workspace path
        workspace_path = get_workspace_path(spec_id, task_id)
        console.print(f"[dim]Workspace:[/dim] {workspace_path}")

        # Setup workspace (creates if needed, switches to change, rebases)
        setup_result = setup_task_workspace(
            task_id=task_id,
            change_id=change_id,
            parent_change=parent_change,
            workspace_path=workspace_path,
        )

        if not setup_result.success:
            console.print(f"[red]Error setting up workspace:[/red] {setup_result.error}")
            raise SystemExit(1)

        # Update description to mark as running
        desc = build_task_description(spec_id, task_path)
        describe_change(
            description=f"{desc} [RUNNING]",
            revset=change_id,
            cwd=workspace_path,
        )

        result = PreSyncResult(
            success=True,
            worktree_path=str(workspace_path),
            branch=change_id,  # Use change_id as "branch" for compatibility
        )
        _output_result(result, ctx)

        console.print(f"[green]Pre-sync complete[/green]")
        console.print(f"[dim]Workspace:[/dim] {workspace_path}")

    except SystemExit:
        raise
    except Exception as e:
        result = PreSyncResult(
            success=False,
            error=str(e),
        )
        _output_result(result, ctx)
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@task.command("run")
@click.argument("task_id")
@click.option("--timeout", "-t", default=1800, help="Timeout in seconds")
@click.pass_context
def task_run(ctx: click.Context, task_id: str, timeout: int) -> None:
    """Execute the AI runner for a task.

    Runs the configured AI runner (e.g., Claude Code) in the task's workspace.
    Uses env vars: ARBORIST_SPEC_ID, ARBORIST_TASK_PATH
    """
    from agent_arborist.runner import get_runner, get_default_runner, get_default_model

    spec_id = _get_spec_id(ctx)
    task_path = _get_task_path()

    if ctx.obj and ctx.obj.get("echo_for_testing"):
        _echo_command("task run", spec_id=spec_id, task_id=task_id, timeout=str(timeout))
        return

    try:
        if not spec_id:
            console.print("[red]Error:[/red] No spec available (set ARBORIST_SPEC_ID)")
            raise SystemExit(1)

        # Get workspace path
        workspace_path = get_workspace_path(spec_id, task_id)

        if not workspace_path.exists():
            console.print(f"[red]Error:[/red] Workspace not found: {workspace_path}")
            console.print("Run 'arborist task pre-sync' first")
            raise SystemExit(1)

        console.print(f"[cyan]Running task:[/cyan] {task_id}")
        if task_path:
            console.print(f"[dim]Task path:[/dim] {':'.join(task_path)}")
        console.print(f"[dim]Workspace:[/dim] {workspace_path}")

        # Get runner configuration
        runner_type = get_default_runner()
        model = get_default_model()

        runner = get_runner(runner_type, workspace_path)

        # TODO: Load task prompt from spec
        prompt = f"Execute task {task_id} for spec {spec_id}. See the task description in the spec file."

        console.print(f"[dim]Runner:[/dim] {runner_type.value}")
        console.print(f"[dim]Model:[/dim] {model or 'default'}")

        # Run the task
        run_result = runner.run(
            prompt=prompt,
            timeout=timeout,
            model=model,
        )

        result = RunResult(
            success=run_result.success,
            runner_type=runner_type.value,
            worktree_path=str(workspace_path),
            prompt=prompt,
            error=run_result.error if not run_result.success else None,
        )
        _output_result(result, ctx)

        if run_result.success:
            console.print("[green]Task execution complete[/green]")
        else:
            console.print(f"[red]Task execution failed:[/red] {run_result.error}")
            raise SystemExit(1)

    except SystemExit:
        raise
    except Exception as e:
        result = RunResult(
            success=False,
            error=str(e),
        )
        _output_result(result, ctx)
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@task.command("run-test")
@click.argument("task_id")
@click.option("--cmd", help="Override test command")
@click.pass_context
def task_run_test(ctx: click.Context, task_id: str, cmd: str | None) -> None:
    """Run tests in the task's workspace.

    Detects and runs the appropriate test command for the project.
    Uses env vars: ARBORIST_SPEC_ID
    """
    spec_id = _get_spec_id(ctx)

    if ctx.obj and ctx.obj.get("echo_for_testing"):
        _echo_command("task run-test", spec_id=spec_id, task_id=task_id, test_cmd=cmd)
        return

    try:
        if not spec_id:
            console.print("[red]Error:[/red] No spec available (set ARBORIST_SPEC_ID)")
            raise SystemExit(1)

        # Get workspace path
        workspace_path = get_workspace_path(spec_id, task_id)

        if not workspace_path.exists():
            console.print(f"[red]Error:[/red] Workspace not found: {workspace_path}")
            raise SystemExit(1)

        console.print(f"[cyan]Running tests for task:[/cyan] {task_id}")

        # Detect or use provided test command
        test_cmd = cmd or detect_test_command(workspace_path)

        if not test_cmd:
            console.print("[yellow]No test command detected, skipping tests[/yellow]")
            result = RunTestResult(
                success=True,
                skipped=True,
                skip_reason="No test command detected",
                worktree_path=str(workspace_path),
            )
            _output_result(result, ctx)
            return

        console.print(f"[dim]Test command:[/dim] {test_cmd}")

        # Run tests
        test_result = subprocess.run(
            test_cmd,
            shell=True,
            cwd=workspace_path,
            capture_output=True,
            text=True,
        )

        success = test_result.returncode == 0

        result = RunTestResult(
            success=success,
            test_command=test_cmd,
            worktree_path=str(workspace_path),
            test_output=test_result.stdout[-5000:] if test_result.stdout else None,
            error=test_result.stderr[-1000:] if not success and test_result.stderr else None,
        )
        _output_result(result, ctx)

        if success:
            console.print("[green]Tests passed[/green]")
        else:
            console.print("[red]Tests failed[/red]")
            raise SystemExit(1)

    except SystemExit:
        raise
    except Exception as e:
        result = RunTestResult(
            success=False,
            error=str(e),
        )
        _output_result(result, ctx)
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@task.command("complete")
@click.argument("task_id")
@click.pass_context
def task_complete(ctx: click.Context, task_id: str) -> None:
    """Complete a task by squashing into parent.

    This command:
    1. Marks the task as done
    2. Squashes the task's changes into its parent
    3. The task change becomes empty (but keeps its description)

    Uses env vars: ARBORIST_SPEC_ID, ARBORIST_TASK_PATH, ARBORIST_SOURCE_REV
    """
    spec_id = _get_spec_id(ctx)
    task_path = _get_task_path()
    source_rev = _get_source_rev()

    if ctx.obj and ctx.obj.get("echo_for_testing"):
        _echo_command("task complete", spec_id=spec_id, task_id=task_id)
        return

    try:
        if not spec_id:
            console.print("[red]Error:[/red] No spec available (set ARBORIST_SPEC_ID)")
            raise SystemExit(1)

        if not task_path:
            console.print("[red]Error:[/red] No task path available (set ARBORIST_TASK_PATH)")
            raise SystemExit(1)

        # Find change ID by hierarchical description
        change_id = find_change_by_description(spec_id, task_path)
        if not change_id:
            console.print(f"[red]Error:[/red] Task change not found for {spec_id}:{':'.join(task_path)}")
            raise SystemExit(1)

        # Find parent change (either parent task or source_rev)
        parent_change = _find_parent_change(spec_id, task_path) or source_rev or "main"

        console.print(f"[cyan]Completing task:[/cyan] {task_id}")
        console.print(f"[dim]Task path:[/dim] {':'.join(task_path)}")
        console.print(f"[dim]Squashing into parent:[/dim] {parent_change}")

        # Get workspace path (may not exist for completion from merge container)
        workspace_path = get_workspace_path(spec_id, task_id)
        cwd = workspace_path if workspace_path.exists() else None

        # Complete the task (squash into parent)
        complete_result = complete_task(
            task_id=task_id,
            change_id=change_id,
            parent_change=parent_change,
            cwd=cwd,
        )

        if complete_result.success:
            step_result = CommitResult(
                success=True,
                worktree_path=str(workspace_path) if workspace_path.exists() else "",
                commit_sha="",
                commit_message=f"Squashed {task_id}",
            )
            _output_result(step_result, ctx)
            console.print("[green]Task completed and squashed[/green]")
        else:
            step_result = CommitResult(
                success=False,
                error=complete_result.error or "Unknown error",
            )
            _output_result(step_result, ctx)
            console.print(f"[red]Failed to complete task:[/red] {complete_result.error}")
            raise SystemExit(1)

    except SystemExit:
        raise
    except Exception as e:
        step_result = CommitResult(
            success=False,
            error=str(e),
        )
        _output_result(step_result, ctx)
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@task.command("sync-parent")
@click.argument("task_id")
@click.pass_context
def task_sync_parent(ctx: click.Context, task_id: str) -> None:
    """Sync parent task after a child completes.

    This rebases remaining children onto the updated parent.
    Called after each child task completes in a parent subdag.

    Uses env vars: ARBORIST_SPEC_ID, ARBORIST_TASK_PATH
    """
    spec_id = _get_spec_id(ctx)
    task_path = _get_task_path()

    if ctx.obj and ctx.obj.get("echo_for_testing"):
        _echo_command("task sync-parent", spec_id=spec_id, task_id=task_id)
        return

    try:
        if not spec_id:
            console.print("[red]Error:[/red] No spec available (set ARBORIST_SPEC_ID)")
            raise SystemExit(1)

        if not task_path:
            console.print("[red]Error:[/red] No task path available (set ARBORIST_TASK_PATH)")
            raise SystemExit(1)

        # Find change ID by hierarchical description
        change_id = find_change_by_description(spec_id, task_path)
        if not change_id:
            console.print(f"[red]Error:[/red] Task change not found for {spec_id}:{':'.join(task_path)}")
            raise SystemExit(1)

        console.print(f"[cyan]Syncing parent after children:[/cyan] {task_id}")
        console.print(f"[dim]Task path:[/dim] {':'.join(task_path)}")

        # Sync: rebase remaining children onto parent
        sync_result = sync_parent(
            parent_change=change_id,
            spec_id=spec_id,
        )

        if sync_result.get("children_rebased"):
            console.print(f"[green]Rebased children:[/green] {sync_result['children_rebased']}")
        else:
            console.print("[dim]No children to rebase[/dim]")

        if sync_result.get("conflicts_found"):
            console.print("[yellow]Conflicts detected in parent[/yellow]")

        console.print("[green]Sync complete[/green]")

    except SystemExit:
        raise
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@task.command("cleanup")
@click.argument("task_id")
@click.pass_context
def task_cleanup(ctx: click.Context, task_id: str) -> None:
    """Clean up task workspace.

    Removes the workspace for a completed task.
    """
    spec_id = _get_spec_id(ctx)

    if ctx.obj and ctx.obj.get("echo_for_testing"):
        _echo_command("task cleanup", spec_id=spec_id, task_id=task_id)
        return

    try:
        if not spec_id:
            console.print("[red]Error:[/red] No spec available")
            raise SystemExit(1)

        workspace_name = f"ws-{task_id}"
        workspace_path = get_workspace_path(spec_id, task_id)

        if workspace_path.exists():
            console.print(f"[cyan]Cleaning up workspace:[/cyan] {workspace_name}")

            # Remove workspace
            run_jj("workspace", "forget", workspace_name, check=False)

            # Remove directory
            import shutil
            if workspace_path.exists():
                shutil.rmtree(workspace_path)

            console.print("[green]Cleanup complete[/green]")
        else:
            console.print(f"[dim]Workspace not found:[/dim] {workspace_path}")

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@task.command("container-up")
@click.argument("task_id")
@click.pass_context
def task_container_up(ctx: click.Context, task_id: str) -> None:
    """Start devcontainer for a task's workspace.

    Uses devcontainer CLI to start a container in the task's workspace.
    """
    from agent_arborist.step_results import ContainerUpResult

    spec_id = _get_spec_id(ctx)

    if ctx.obj and ctx.obj.get("echo_for_testing"):
        _echo_command("task container-up", spec_id=spec_id, task_id=task_id)
        return

    try:
        if not spec_id:
            console.print("[red]Error:[/red] No spec available")
            raise SystemExit(1)

        workspace_path = get_workspace_path(spec_id, task_id)

        if not workspace_path.exists():
            console.print(f"[red]Error:[/red] Workspace not found: {workspace_path}")
            raise SystemExit(1)

        console.print(f"[cyan]Starting container for:[/cyan] {workspace_path}")

        # Start devcontainer
        result = subprocess.run(
            ["devcontainer", "up", "--workspace-folder", str(workspace_path)],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError(f"devcontainer up failed: {result.stderr}")

        step_result = ContainerUpResult(
            success=True,
            worktree_path=str(workspace_path),
        )
        _output_result(step_result, ctx)
        console.print("[green]Container started[/green]")

    except Exception as e:
        step_result = ContainerUpResult(
            success=False,
            error=str(e),
        )
        _output_result(step_result, ctx)
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@task.command("container-stop")
@click.argument("task_id")
@click.pass_context
def task_container_stop(ctx: click.Context, task_id: str) -> None:
    """Stop devcontainer for a task's workspace."""
    from agent_arborist.step_results import ContainerStopResult

    spec_id = _get_spec_id(ctx)

    if ctx.obj and ctx.obj.get("echo_for_testing"):
        _echo_command("task container-stop", spec_id=spec_id, task_id=task_id)
        return

    try:
        if not spec_id:
            console.print("[red]Error:[/red] No spec available")
            raise SystemExit(1)

        workspace_path = get_workspace_path(spec_id, task_id)

        if not workspace_path.exists():
            console.print(f"[dim]Workspace not found:[/dim] {workspace_path}")
            step_result = ContainerStopResult(
                success=True,
                worktree_path="",
                container_stopped=False,
            )
            _output_result(step_result, ctx)
            return

        console.print(f"[cyan]Stopping container for:[/cyan] {workspace_path}")

        # Stop container by devcontainer.local_folder label
        cmd = f'docker stop $(docker ps -q --filter label=devcontainer.local_folder="{workspace_path}") 2>/dev/null || true'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

        container_stopped = bool(result.stdout.strip())

        step_result = ContainerStopResult(
            success=True,
            worktree_path=str(workspace_path),
            container_stopped=container_stopped,
        )
        _output_result(step_result, ctx)

        if container_stopped:
            console.print("[green]Container stopped[/green]")
        else:
            console.print("[dim]No running container found[/dim]")

    except Exception as e:
        step_result = ContainerStopResult(
            success=False,
            error=str(e),
        )
        _output_result(step_result, ctx)
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


def register_task_commands(main_cli: click.Group) -> None:
    """Register task command group with main CLI."""
    main_cli.add_command(task)
