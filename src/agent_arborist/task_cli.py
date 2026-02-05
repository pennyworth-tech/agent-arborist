"""CLI commands for task execution.

This module provides the task subcommands for running tasks.
Uses jj workspaces for parallel execution with atomic squash operations.
"""

import os
import subprocess
from pathlib import Path

import click
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
)
from agent_arborist.manifest import (
    load_manifest,
    load_manifest_from_env,
    save_manifest,
    find_manifest_path,
    ChangeManifest,
    create_all_changes_from_manifest,
)

console = Console()


def _get_spec_id(ctx: click.Context) -> str | None:
    """Get spec_id from context or environment."""
    spec_id = os.environ.get("ARBORIST_SPEC_ID")
    if not spec_id:
        spec_id = ctx.obj.get("spec_id") if ctx.obj else None
    return spec_id


def _get_manifest(ctx: click.Context, spec_id: str | None = None) -> ChangeManifest:
    """Get manifest from env or discover from spec_id."""
    # Try env var first (for DAG execution)
    manifest_path_str = os.environ.get("ARBORIST_MANIFEST")

    if manifest_path_str:
        return load_manifest(Path(manifest_path_str))

    # Try spec_id discovery
    spec_id = spec_id or _get_spec_id(ctx)
    if spec_id:
        manifest_path = find_manifest_path(spec_id)
        if manifest_path:
            return load_manifest(manifest_path)

    raise ValueError("No manifest available. Set ARBORIST_MANIFEST or ARBORIST_SPEC_ID.")


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

    if task_id:
        # Show specific task
        try:
            manifest = _get_manifest(ctx, spec_id)
            task_info = manifest.get_task(task_id)

            if not task_info:
                console.print(f"[red]Error:[/red] Task {task_id} not found in manifest")
                raise SystemExit(1)

            # Get current status from repo by finding the task
            task_status = "unknown"
            if spec_id:
                tasks = find_tasks_by_spec(spec_id)
                for t in tasks:
                    if t.task_id == task_id:
                        task_status = t.status
                        break

            if as_json:
                import json
                print(json.dumps({
                    "task_id": task_id,
                    "change_id": task_info.change_id,
                    "parent_change": task_info.parent_change,
                    "status": task_status,
                    "children": task_info.children,
                }))
            else:
                console.print(f"[bold]Task:[/bold] {task_id}")
                console.print(f"[dim]Change ID:[/dim] {task_info.change_id}")
                console.print(f"[dim]Parent:[/dim] {task_info.parent_change}")
                console.print(f"[dim]Status:[/dim] {task_status}")
                if task_info.children:
                    console.print(f"[dim]Children:[/dim] {', '.join(task_info.children)}")

        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            raise SystemExit(1)

    else:
        # Show all tasks in spec
        if not spec_id:
            console.print("[red]Error:[/red] No spec available")
            console.print("Use --spec or set ARBORIST_SPEC_ID")
            raise SystemExit(1)

        tasks = find_tasks_by_spec(spec_id)

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

    if ctx.obj and ctx.obj.get("echo_for_testing"):
        _echo_command("task setup-spec", spec_id=spec_id)
        return

    if not spec_id:
        console.print("[red]Error:[/red] No spec available")
        raise SystemExit(1)

    try:
        # Auto-initialize jj in colocated mode if not already a jj repo
        if not is_jj_repo():
            console.print("[cyan]Initializing jj in colocated mode...[/cyan]")
            run_jj("git", "init", "--colocate")
            console.print("[green]jj initialized successfully[/green]")

        manifest = _get_manifest(ctx, spec_id)

        console.print(f"[cyan]Setting up jj changes for spec:[/cyan] {spec_id}")

        result = create_all_changes_from_manifest(manifest)

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
    """
    spec_id = _get_spec_id(ctx)

    if ctx.obj and ctx.obj.get("echo_for_testing"):
        _echo_command("task pre-sync", spec_id=spec_id, task_id=task_id)
        return

    try:
        if not spec_id:
            console.print("[red]Error:[/red] No spec available")
            raise SystemExit(1)

        manifest = _get_manifest(ctx, spec_id)
        task_info = manifest.get_task(task_id)

        if not task_info:
            console.print(f"[red]Error:[/red] Task {task_id} not found in manifest")
            raise SystemExit(1)

        console.print(f"[cyan]Pre-sync for task:[/cyan] {task_id}")
        console.print(f"[dim]Change ID:[/dim] {task_info.change_id}")
        console.print(f"[dim]Parent:[/dim] {task_info.parent_change}")

        # Get workspace path
        workspace_path = get_workspace_path(spec_id, task_id)
        console.print(f"[dim]Workspace:[/dim] {workspace_path}")

        # Setup workspace (creates if needed, switches to change, rebases)
        setup_result = setup_task_workspace(
            task_id=task_id,
            change_id=task_info.change_id,
            parent_change=task_info.parent_change,
            workspace_path=workspace_path,
        )

        if not setup_result.success:
            console.print(f"[red]Error setting up workspace:[/red] {setup_result.error}")
            raise SystemExit(1)

        # Update description to mark as running
        describe_change(
            task_info.change_id,
            description=f"spec:{spec_id}:{task_id}:running",
            cwd=workspace_path,
        )

        result = PreSyncResult(
            success=True,
            worktree_path=str(workspace_path),
            branch=task_info.change_id,  # Use change_id as "branch" for compatibility
        )
        _output_result(result, ctx)

        # Set environment for subsequent steps
        console.print(f"[green]Pre-sync complete[/green]")
        console.print(f"[dim]Workspace:[/dim] {workspace_path}")

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
    """
    from agent_arborist.runner import get_runner, get_default_runner, get_default_model

    spec_id = _get_spec_id(ctx)

    if ctx.obj and ctx.obj.get("echo_for_testing"):
        _echo_command("task run", spec_id=spec_id, task_id=task_id, timeout=str(timeout))
        return

    try:
        if not spec_id:
            console.print("[red]Error:[/red] No spec available")
            raise SystemExit(1)

        manifest = _get_manifest(ctx, spec_id)
        task_info = manifest.get_task(task_id)

        if not task_info:
            console.print(f"[red]Error:[/red] Task {task_id} not found in manifest")
            raise SystemExit(1)

        # Get workspace path
        workspace_path = get_workspace_path(spec_id, task_id)

        if not workspace_path.exists():
            console.print(f"[red]Error:[/red] Workspace not found: {workspace_path}")
            console.print("Run 'arborist jj pre-sync' first")
            raise SystemExit(1)

        console.print(f"[cyan]Running task:[/cyan] {task_id}")
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
    """
    spec_id = _get_spec_id(ctx)

    if ctx.obj and ctx.obj.get("echo_for_testing"):
        _echo_command("task run-test", spec_id=spec_id, task_id=task_id, test_cmd=cmd)
        return

    try:
        if not spec_id:
            console.print("[red]Error:[/red] No spec available")
            raise SystemExit(1)

        manifest = _get_manifest(ctx, spec_id)
        task_info = manifest.get_task(task_id)

        if not task_info:
            console.print(f"[red]Error:[/red] Task {task_id} not found in manifest")
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
    """
    spec_id = _get_spec_id(ctx)

    if ctx.obj and ctx.obj.get("echo_for_testing"):
        _echo_command("task complete", spec_id=spec_id, task_id=task_id)
        return

    try:
        if not spec_id:
            console.print("[red]Error:[/red] No spec available")
            raise SystemExit(1)

        manifest = _get_manifest(ctx, spec_id)
        task_info = manifest.get_task(task_id)

        if not task_info:
            console.print(f"[red]Error:[/red] Task {task_id} not found in manifest")
            raise SystemExit(1)

        console.print(f"[cyan]Completing task:[/cyan] {task_id}")
        console.print(f"[dim]Squashing into parent:[/dim] {task_info.parent_change}")

        # Get workspace path (may not exist for completion from merge container)
        workspace_path = get_workspace_path(spec_id, task_id)
        cwd = workspace_path if workspace_path.exists() else None

        # Complete the task (squash into parent)
        result = complete_task(
            task_id=task_id,
            change_id=task_info.change_id,
            parent_change=task_info.parent_change,
            cwd=cwd,
        )

        if result.success:
            step_result = CommitResult(
                success=True,
                worktree_path=str(workspace_path) if workspace_path.exists() else "",
                commit_sha=result.new_parent_id or "",
                commit_message=f"Squashed {task_id}",
            )
            _output_result(step_result, ctx)
            console.print("[green]Task completed and squashed[/green]")
        else:
            step_result = CommitResult(
                success=False,
                error=result.error or "Unknown error",
            )
            _output_result(step_result, ctx)
            console.print(f"[red]Failed to complete task:[/red] {result.error}")
            raise SystemExit(1)

    except SystemExit:
        raise
    except Exception as e:
        result = CommitResult(
            success=False,
            error=str(e),
        )
        _output_result(result, ctx)
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@task.command("sync-parent")
@click.argument("task_id")
@click.pass_context
def task_sync_parent(ctx: click.Context, task_id: str) -> None:
    """Sync parent task after a child completes.

    This rebases remaining children onto the updated parent.
    Called after each child task completes in a parent subdag.
    """
    spec_id = _get_spec_id(ctx)

    if ctx.obj and ctx.obj.get("echo_for_testing"):
        _echo_command("task sync-parent", spec_id=spec_id, task_id=task_id)
        return

    try:
        manifest = _get_manifest(ctx, spec_id)
        task_info = manifest.get_task(task_id)

        if not task_info:
            console.print(f"[red]Error:[/red] Task {task_id} not found in manifest")
            raise SystemExit(1)

        console.print(f"[cyan]Syncing parent after children:[/cyan] {task_id}")

        # Sync: rebase remaining children onto parent
        result = sync_parent(
            parent_change=task_info.change_id,
            spec_id=spec_id or manifest.spec_id,
        )

        if result.get("rebased"):
            console.print(f"[green]Rebased children:[/green] {result['rebased']}")
        else:
            console.print("[dim]No children to rebase[/dim]")

        if result.get("errors"):
            for err in result["errors"]:
                console.print(f"[red]Error:[/red] {err}")
            raise SystemExit(1)

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
