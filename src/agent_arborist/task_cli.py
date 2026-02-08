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
    get_description,
    create_change,
    create_task_change,
    mark_task_done,
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
    # Merge-based rollup functions
    create_merge_commit,
    find_completed_children,
    find_parent_base,
    find_root_task_changes,
    # Child task info for merge prompts
    get_child_task_info,
    get_conflicting_files,
    ChildTaskInfo,
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


def _count_workspace_changes(workspace_path: Path) -> int:
    """Count files changed in workspace (staged + unstaged)."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=workspace_path,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return len(result.stdout.strip().split("\n"))
        return 0
    except Exception:
        return 0


def _persist_run_result(workspace_path: Path, result: "RunResult") -> None:
    """Persist RunResult to file for task complete to read."""
    result_dir = workspace_path / ".arborist"
    result_dir.mkdir(parents=True, exist_ok=True)
    result_file = result_dir / "run_result.json"
    result_file.write_text(result.to_json())


def _persist_test_result(workspace_path: Path, result: "RunTestResult") -> None:
    """Persist RunTestResult to file for task complete to read."""
    result_dir = workspace_path / ".arborist"
    result_dir.mkdir(parents=True, exist_ok=True)
    result_file = result_dir / "test_result.json"
    result_file.write_text(result.to_json())


def _read_run_result(workspace_path: Path) -> "RunResult | None":
    """Read persisted RunResult if it exists."""
    result_file = workspace_path / ".arborist" / "run_result.json"
    if result_file.exists():
        import json
        data = json.loads(result_file.read_text())
        return RunResult(**{k: v for k, v in data.items() if k != "timestamp"})
    return None


def _read_test_result(workspace_path: Path) -> "RunTestResult | None":
    """Read persisted RunTestResult if it exists."""
    result_file = workspace_path / ".arborist" / "test_result.json"
    if result_file.exists():
        import json
        data = json.loads(result_file.read_text())
        return RunTestResult(**{k: v for k, v in data.items() if k != "timestamp"})
    return None


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
    """Initialize jj and validate spec for lazy change creation.

    With lazy creation, changes are created in pre-sync (not here).
    This command only:
    1. Initializes jj in colocated mode if needed
    2. Syncs jj with git
    3. Validates the DAG YAML exists (for early failure)

    Lazy creation means each task's change is created at pre-sync time
    from the correct effective source (predecessor or source_rev).
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

        # Validate DAG YAML exists (for early failure)
        dag_path = _find_dag_yaml_path(spec_id)
        if not dag_path:
            console.print(f"[red]Error:[/red] DAG YAML not found for {spec_id}")
            raise SystemExit(1)

        dag_yaml = dag_path.read_text()
        task_tree = build_task_tree_from_yaml(spec_id, dag_yaml)

        console.print(f"[cyan]Setup for spec:[/cyan] {spec_id}")
        console.print(f"[dim]Source revision:[/dim] {source_rev}")
        console.print(f"[dim]Tasks:[/dim] {len(task_tree.tasks)}")
        console.print(f"[dim]Root tasks:[/dim] {len(task_tree.root_tasks)}")
        console.print("[dim]Changes will be created lazily at pre-sync time[/dim]")
        console.print("[green]Setup complete[/green]")

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@task.command("pre-sync")
@click.argument("task_id")
@click.pass_context
def task_pre_sync(ctx: click.Context, task_id: str) -> None:
    """Prepare task for execution with lazy change creation.

    This command implements lazy creation: changes are created at pre-sync time
    from the correct effective source (predecessor or source_rev).

    Effective source determination:
    - If ARBORIST_PREDECESSOR is set, use the predecessor's [DONE] change
    - Otherwise, use source_rev (the original feature branch)

    This ensures sequential phases (Phase2 depends on Phase1) are created
    FROM Phase1's merge commit, not from source_rev.

    Uses env vars:
    - ARBORIST_SPEC_ID: Spec identifier
    - ARBORIST_TASK_PATH: Hierarchical task path (e.g., "Phase2:T3")
    - ARBORIST_SOURCE_REV: Original source revision
    - ARBORIST_PREDECESSOR: (Optional) Predecessor task to create from
    """
    spec_id = _get_spec_id(ctx)
    task_path = _get_task_path()
    source_rev = _get_source_rev()
    predecessor = os.environ.get("ARBORIST_PREDECESSOR")

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

        if not source_rev:
            console.print("[red]Error:[/red] No source revision (set ARBORIST_SOURCE_REV)")
            console.print("[dim]Run DAG from a feature branch, not main[/dim]")
            raise SystemExit(1)

        console.print(f"[cyan]Pre-sync for task:[/cyan] {task_id}")
        console.print(f"[dim]Task path:[/dim] {':'.join(task_path)}")

        git_root = get_git_root()

        # Determine effective source - DAGU set ARBORIST_PREDECESSOR if we have deps
        if predecessor:
            # Query by deterministic description - predecessor is [DONE] (guaranteed by DAGU ordering)
            effective_source = find_change_by_description(spec_id, [predecessor], git_root)
            if not effective_source:
                console.print(f"[red]Error:[/red] Predecessor change not found: {spec_id}:{predecessor}")
                console.print("[dim]Expected predecessor to be [DONE] before this task runs[/dim]")
                raise SystemExit(1)
            console.print(f"[dim]Predecessor:[/dim] {predecessor} -> {effective_source[:12]}")
        else:
            effective_source = source_rev
            console.print(f"[dim]Source rev:[/dim] {effective_source}")

        # LAZY CREATION: Find or create the change from effective_source
        change_id = find_change_by_description(spec_id, task_path, git_root)
        if change_id:
            console.print(f"[dim]Found existing change:[/dim] {change_id[:12]}")
        else:
            # Create the change from effective_source
            change_id = create_task_change(
                spec_id=spec_id,
                task_id=task_id,
                parent_change=effective_source,
                task_path=task_path,
                cwd=git_root,
            )
            console.print(f"[green]Created change from {effective_source[:12]}:[/green] {change_id[:12]}")

        # Get workspace path
        workspace_path = get_workspace_path(spec_id, task_id)
        console.print(f"[dim]Workspace:[/dim] {workspace_path}")

        # Setup workspace (creates if needed, switches to change - NO REBASE)
        setup_result = setup_task_workspace(
            task_id=task_id,
            change_id=change_id,
            workspace_path=workspace_path,
            cwd=git_root,
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


def _build_leaf_prompt(spec_id: str, task_id: str, task_path: list[str] | None) -> str:
    """Build prompt for leaf task (no children, fresh implementation)."""
    task_path_str = ":".join(task_path) if task_path else task_id
    return f"""You are implementing task {task_id} for spec {spec_id}.

TASK PATH: {task_path_str}

INSTRUCTIONS:
1. Read the task specification in the .arborist/specs/{spec_id}/ directory
2. Find the description for task {task_id}
3. Implement the task according to the specification
4. Ensure your changes are complete and tested

When done, your changes will be automatically committed by the arborist system.
"""


def _build_merge_prompt(
    spec_id: str,
    task_id: str,
    task_path: list[str] | None,
    children: list[ChildTaskInfo],
    conflicting_files: list[str],
) -> str:
    """Build prompt for parent/merge task (children completed, may have conflicts)."""
    task_path_str = ":".join(task_path) if task_path else task_id

    # Build children summary
    children_section = "COMPLETED CHILD TASKS:\n"
    for child in children:
        children_section += f"\n### {child.task_id}\n"
        children_section += f"Description: {child.description}\n"
        if child.files_changed:
            children_section += "Files changed:\n"
            for f in child.files_changed:
                children_section += f"  - {f}\n"
        else:
            children_section += "Files changed: (none)\n"

    # Build conflict section
    if conflicting_files:
        conflict_section = f"""
MERGE CONFLICTS DETECTED:
The following files have conflicts that MUST be resolved:
{chr(10).join(f"  - {f}" for f in conflicting_files)}

HOW TO RESOLVE:
1. Open each conflicted file
2. Look for conflict markers:
   <<<<<<< (start of first version)
   ======= (separator)
   >>>>>>> (end of second version)
3. Understand what each child task intended
4. Edit the file to combine both changes correctly
5. Remove ALL conflict markers
6. Save the file - jj will automatically detect the resolution

DO NOT proceed with integration until ALL conflicts are resolved.
"""
    else:
        conflict_section = """
NO MERGE CONFLICTS - children's work merged cleanly.
"""

    return f"""You are running the MERGE/INTEGRATION step for task {task_id} in spec {spec_id}.

TASK PATH: {task_path_str}

CONTEXT:
This is a PARENT task. The following child tasks have completed their work
and their changes have been merged into your working tree.

{children_section}
{conflict_section}
YOUR RESPONSIBILITIES:
1. RESOLVE any merge conflicts first (if present)
2. INTEGRATE the children's work - ensure features work together
3. Do any PARENT-LEVEL work described in the task spec
4. Verify the combined changes are correct

Read the task specification in .arborist/specs/{spec_id}/ for details on what
task {task_id} should accomplish beyond integrating children's work.
"""


def _build_root_prompt(
    spec_id: str,
    children: list[ChildTaskInfo],
    conflicting_files: list[str],
) -> str:
    """Build prompt for ROOT task (final integration of all work)."""
    # Build children summary
    children_section = "COMPLETED ROOT-LEVEL TASKS:\n"
    for child in children:
        children_section += f"\n### {child.task_id}\n"
        children_section += f"Description: {child.description}\n"
        if child.files_changed:
            children_section += "Files changed:\n"
            for f in child.files_changed:
                children_section += f"  - {f}\n"
        else:
            children_section += "Files changed: (none)\n"

    # Build conflict section
    if conflicting_files:
        conflict_section = f"""
MERGE CONFLICTS DETECTED:
The following files have conflicts that MUST be resolved:
{chr(10).join(f"  - {f}" for f in conflicting_files)}

HOW TO RESOLVE:
1. Open each conflicted file
2. Look for conflict markers:
   <<<<<<< (start of first version)
   ======= (separator)
   >>>>>>> (end of second version)
3. Understand what each task intended
4. Edit the file to combine all changes correctly
5. Remove ALL conflict markers
6. Save the file - jj will automatically detect the resolution

DO NOT proceed until ALL conflicts are resolved.
"""
    else:
        conflict_section = """
NO MERGE CONFLICTS - all work merged cleanly.
"""

    return f"""You are running the FINAL INTEGRATION step (ROOT) for spec {spec_id}.

CONTEXT:
All tasks in the spec have completed. Their work has been merged into your
working tree for final integration.

{children_section}
{conflict_section}
YOUR RESPONSIBILITIES:
1. RESOLVE any merge conflicts first (if present)
2. Ensure ALL features work together correctly
3. Run the full test suite and fix any issues
4. Verify all spec requirements are met

This is the final step before the changes are exported to git.
"""


@task.command("run")
@click.argument("task_id")
@click.option("--timeout", "-t", default=1800, help="Timeout in seconds")
@click.pass_context
def task_run(ctx: click.Context, task_id: str, timeout: int) -> None:
    """Execute the AI runner for a task.

    Runs the configured AI runner (e.g., Claude Code) in the task's workspace.
    Uses env vars: ARBORIST_SPEC_ID, ARBORIST_TASK_PATH, ARBORIST_POST_MERGE
    """
    from agent_arborist.runner import get_runner, get_default_runner, get_default_model

    spec_id = _get_spec_id(ctx)
    task_path = _get_task_path()
    is_post_merge = os.environ.get("ARBORIST_POST_MERGE", "").lower() == "true"

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
        console.print(f"[dim]Post-merge:[/dim] {is_post_merge}")

        # Get git root for jj operations
        git_root = get_git_root()

        # Gather child info and conflicts for post-merge tasks
        children: list[ChildTaskInfo] = []
        conflicting_files: list[str] = []

        if is_post_merge:
            # Get conflicts in current workspace
            conflicting_files = get_conflicting_files(cwd=workspace_path)
            if conflicting_files:
                console.print(f"[yellow]Conflicts:[/yellow] {len(conflicting_files)} files")
                for f in conflicting_files:
                    console.print(f"  [dim]-[/dim] {f}")

            # Get child task info
            if task_id == "ROOT":
                # ROOT merges root-level tasks
                child_changes = find_root_task_changes(spec_id, cwd=git_root)
            else:
                # Parent task merges its children
                child_changes = find_completed_children(spec_id, task_path or [], cwd=git_root)

            for change_id in child_changes:
                try:
                    child_info = get_child_task_info(change_id, cwd=git_root)
                    children.append(child_info)
                    console.print(f"  [dim]Child:[/dim] {child_info.task_id} ({len(child_info.files_changed)} files)")
                except Exception:
                    pass  # Skip if we can't get info

        # Get runner configuration
        runner_type = get_default_runner()
        model = get_default_model()

        runner = get_runner(runner_type, model)

        # Build appropriate prompt based on task type
        if task_id == "ROOT":
            prompt = _build_root_prompt(spec_id, children, conflicting_files)
        elif is_post_merge:
            prompt = _build_merge_prompt(spec_id, task_id, task_path, children, conflicting_files)
        else:
            prompt = _build_leaf_prompt(spec_id, task_id, task_path)

        console.print(f"[dim]Runner:[/dim] {runner_type}")
        console.print(f"[dim]Model:[/dim] {model or 'default'}")

        # Run the task with timing
        import time
        start_time = time.time()
        run_result = runner.run(
            prompt=prompt,
            timeout=timeout,
            cwd=workspace_path,
        )
        duration = time.time() - start_time

        # Count files changed in workspace
        files_changed = _count_workspace_changes(workspace_path)

        result = RunResult(
            success=run_result.success,
            runner=runner_type,
            model=model,
            duration_seconds=duration,
            files_changed=files_changed,
            summary=run_result.output[:2000] if run_result.output else "",
            error=run_result.error if not run_result.success else None,
        )
        _output_result(result, ctx)

        # Persist result for task complete to read
        _persist_run_result(workspace_path, result)

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
                skip_reason="No test command detected",
            )
            _output_result(result, ctx)
            _persist_test_result(workspace_path, result)
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
            output_summary=test_result.stdout[-5000:] if test_result.stdout else "",
            error=test_result.stderr[-1000:] if not success and test_result.stderr else None,
        )
        _output_result(result, ctx)
        _persist_test_result(workspace_path, result)

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
    """Mark a task as complete.

    This command marks the task as [DONE] in its description.
    For the merge-based approach, actual rollup happens via create-merge.

    Uses env vars: ARBORIST_SPEC_ID, ARBORIST_TASK_PATH
    """
    spec_id = _get_spec_id(ctx)
    task_path = _get_task_path()

    if ctx.obj and ctx.obj.get("echo_for_testing"):
        _echo_command("task complete", spec_id=spec_id, task_id=task_id)
        return

    try:
        if not spec_id:
            console.print("[red]Error:[/red] No spec available (set ARBORIST_SPEC_ID)")
            raise SystemExit(1)

        # Handle ROOT completion specially
        if task_id == "ROOT":
            console.print(f"[cyan]Completing ROOT:[/cyan] {spec_id}")
            # ROOT doesn't need marking - finalize handles bookmark/export
            step_result = CommitResult(
                success=True,
                commit_sha="",
                message="ROOT completed",
            )
            _output_result(step_result, ctx)
            console.print("[green]ROOT completed[/green]")
            return

        if not task_path:
            console.print("[red]Error:[/red] No task path available (set ARBORIST_TASK_PATH)")
            raise SystemExit(1)

        # Find change ID by hierarchical description
        change_id = find_change_by_description(spec_id, task_path)
        if not change_id:
            console.print(f"[red]Error:[/red] Task change not found for {spec_id}:{':'.join(task_path)}")
            raise SystemExit(1)

        console.print(f"[cyan]Completing task:[/cyan] {task_id}")
        console.print(f"[dim]Task path:[/dim] {':'.join(task_path)}")
        console.print(f"[dim]Change ID:[/dim] {change_id}")

        # Get workspace path for describe operation
        workspace_path = get_workspace_path(spec_id, task_id)
        cwd = workspace_path if workspace_path.exists() else None

        # Read persisted results for rich description
        run_result = _read_run_result(workspace_path) if workspace_path.exists() else None
        test_result = _read_test_result(workspace_path) if workspace_path.exists() else None

        # Build rich description
        from agent_arborist.tasks import build_rich_description, describe_change

        rich_desc = build_rich_description(
            spec_id=spec_id,
            task_id=task_id,
            status="DONE",
            commit_message=run_result.commit_message if run_result else None,
            summary=run_result.summary if run_result else "",
            files_changed=run_result.files_changed if run_result else 0,
            test_command=test_result.test_command if test_result else None,
            test_passed=test_result.passed if test_result else None,
            test_failed=test_result.failed if test_result else None,
            test_total=test_result.test_count if test_result else None,
            runner=run_result.runner if run_result else "",
            model=run_result.model if run_result else None,
            duration_seconds=run_result.duration_seconds if run_result else 0.0,
        )

        # Update change description with rich content
        try:
            describe_change(rich_desc, change_id, cwd)
            step_result = CommitResult(
                success=True,
                commit_sha="",
                message=f"Marked {task_id} as done",
            )
            _output_result(step_result, ctx)
            console.print("[green]Task marked as complete[/green]")
        except Exception as e:
            step_result = CommitResult(
                success=False,
                error=str(e),
            )
            _output_result(step_result, ctx)
            console.print(f"[red]Failed to complete task:[/red] {e}")
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


@task.command("create-merge")
@click.argument("task_id")
@click.pass_context
def task_create_merge(ctx: click.Context, task_id: str) -> None:
    """Create a merge commit for a parent task or ROOT.

    For parent tasks: Creates a merge commit with all completed children as parents.
    For ROOT: Creates a merge commit with all completed root tasks as parents.

    This is the key step in the merge-based rollup approach:
    - Each parent task becomes a merge commit combining its children
    - The merge commit's working copy is where the parent does its own work
    - ROOT is a special case that merges all root tasks for final export

    Uses env vars: ARBORIST_SPEC_ID, ARBORIST_TASK_PATH, ARBORIST_SOURCE_REV
    """
    spec_id = _get_spec_id(ctx)
    task_path = _get_task_path()
    source_rev = _get_source_rev()

    if ctx.obj and ctx.obj.get("echo_for_testing"):
        _echo_command("task create-merge", spec_id=spec_id, task_id=task_id)
        return

    try:
        if not spec_id:
            console.print("[red]Error:[/red] No spec available (set ARBORIST_SPEC_ID)")
            raise SystemExit(1)

        # Get git root for operations
        git_root = get_git_root()

        if task_id == "ROOT":
            # ROOT merge: combine all completed root tasks
            console.print(f"[cyan]Creating ROOT merge for spec:[/cyan] {spec_id}")

            # Find all root task changes
            root_changes = find_root_task_changes(spec_id, cwd=git_root)

            if not root_changes:
                console.print("[red]Error:[/red] No completed root tasks found")
                raise SystemExit(1)

            console.print(f"[dim]Root tasks to merge:[/dim] {len(root_changes)}")
            child_task_ids = []
            for change_id in root_changes:
                desc = get_description(change_id, cwd=git_root)
                console.print(f"  - {change_id[:12]}: {desc}")
                # Extract task ID from description (first line, after spec_id:)
                first_line = desc.split("\n")[0]
                if ":" in first_line:
                    parts = first_line.split(":")
                    if len(parts) >= 2:
                        # Get task ID (e.g., "T001" from "spec:T001: message")
                        task_part = parts[1].split()[0]  # Handle "T001 [DONE]" -> "T001"
                        child_task_ids.append(task_part)

            # Create the ROOT merge commit with rich description
            from agent_arborist.tasks import build_rich_description
            root_desc = build_rich_description(
                spec_id=spec_id,
                task_id="ROOT",
                status="MERGE",
                children_ids=child_task_ids,
            )
            merge_change = create_merge_commit(
                parent_changes=root_changes,
                description=root_desc,
                cwd=git_root,
            )

            console.print(f"[green]ROOT merge created:[/green] {merge_change}")

            # Create/setup workspace for ROOT
            workspace_path = get_workspace_path(spec_id, "ROOT")
            setup_result = setup_task_workspace(
                task_id="ROOT",
                change_id=merge_change,
                workspace_path=workspace_path,
                cwd=git_root,
            )

            if not setup_result.success:
                console.print(f"[red]Error setting up ROOT workspace:[/red] {setup_result.error}")
                raise SystemExit(1)

            console.print(f"[dim]Workspace:[/dim] {workspace_path}")

        else:
            # Parent task merge: combine all completed children
            if not task_path:
                console.print("[red]Error:[/red] No task path available (set ARBORIST_TASK_PATH)")
                raise SystemExit(1)

            console.print(f"[cyan]Creating merge for parent task:[/cyan] {task_id}")
            console.print(f"[dim]Task path:[/dim] {':'.join(task_path)}")

            # Find all completed child changes
            child_changes = find_completed_children(spec_id, task_path, cwd=git_root)

            if not child_changes:
                console.print("[red]Error:[/red] No completed children found")
                raise SystemExit(1)

            console.print(f"[dim]Children to merge:[/dim] {len(child_changes)}")
            child_task_ids = []
            for change_id in child_changes:
                desc = get_description(change_id, cwd=git_root)
                console.print(f"  - {change_id[:12]}: {desc}")
                # Extract task ID from description
                first_line = desc.split("\n")[0]
                if ":" in first_line:
                    parts = first_line.split(":")
                    # Find the last task ID in the path (immediate child)
                    for part in reversed(parts[1:]):
                        task_part = part.split()[0]  # Handle "T001 [DONE]" -> "T001"
                        if task_part.startswith("T"):
                            child_task_ids.append(task_part)
                            break

            # Create the merge commit for this parent with rich description
            from agent_arborist.tasks import build_rich_description
            merge_desc = build_rich_description(
                spec_id=spec_id,
                task_id=task_id,
                status="MERGE",
                children_ids=child_task_ids,
            )
            merge_change = create_merge_commit(
                parent_changes=child_changes,
                description=merge_desc,
                cwd=git_root,
            )

            console.print(f"[green]Merge created:[/green] {merge_change}")

            # Setup workspace for parent's own work
            workspace_path = get_workspace_path(spec_id, task_id)
            setup_result = setup_task_workspace(
                task_id=task_id,
                change_id=merge_change,
                workspace_path=workspace_path,
                cwd=git_root,
            )

            if not setup_result.success:
                console.print(f"[red]Error setting up workspace:[/red] {setup_result.error}")
                raise SystemExit(1)

            console.print(f"[dim]Workspace:[/dim] {workspace_path}")

        console.print("[green]Merge commit created successfully[/green]")

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
    Respects ARBORIST_CONTAINER_MODE env var: none/disabled = skip.
    """
    from agent_arborist.step_results import ContainerUpResult

    spec_id = _get_spec_id(ctx)

    if ctx.obj and ctx.obj.get("echo_for_testing"):
        _echo_command("task container-up", spec_id=spec_id, task_id=task_id)
        return

    # Check container mode - skip if disabled
    container_mode = os.environ.get("ARBORIST_CONTAINER_MODE", "auto").lower()
    if container_mode in ("none", "disabled"):
        step_result = ContainerUpResult(
            success=True,
            skipped=True,
            skip_reason=f"Container mode is {container_mode}",
        )
        _output_result(step_result, ctx)
        console.print(f"[dim]Skipping container (mode={container_mode})[/dim]")
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
