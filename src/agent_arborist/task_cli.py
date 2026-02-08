"""CLI commands for task execution.

This module provides the task subcommands for running tasks
in a sequential execution model.

Key concepts:
- Sequential execution (one task at a time)
- Plain git commits
- Container mode: auto, enabled, or disabled
- DAGU handles orchestration
"""

import json
import os
import subprocess
from pathlib import Path

import click
from rich.console import Console

from agent_arborist.step_results import (
    StepResult,
    RunResult,
    RunTestResult,
)
from agent_arborist.tasks import (
    is_git_repo,
    get_current_branch,
    has_uncommitted_changes,
    count_changed_files,
    commit_task,
    detect_test_command,
    run_tests,
    GitResult,
)
from agent_arborist.home import get_git_root

console = Console()


def _get_spec_id() -> str | None:
    """Get spec_id from environment."""
    return os.environ.get("ARBORIST_SPEC_ID")


def _get_task_id() -> str | None:
    """Get task_id from environment."""
    return os.environ.get("ARBORIST_TASK_ID")


def _get_source_rev() -> str | None:
    """Get source revision from environment."""
    return os.environ.get("ARBORIST_SOURCE_REV")


def _get_container_mode() -> str:
    """Get container mode from environment."""
    return os.environ.get("ARBORIST_CONTAINER_MODE", "auto")


def _output_result(result: StepResult, ctx: click.Context) -> None:
    """Output step result in appropriate format."""
    output_format = ctx.obj.get("output_format", "json") if ctx.obj else "json"

    if output_format == "json":
        print(result.to_json())
    else:
        if result.success:
            console.print("[green]Success[/green]")
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


def _persist_run_result(result: RunResult) -> None:
    """Persist RunResult to file for later reference."""
    git_root = get_git_root()
    if not git_root:
        return

    result_dir = git_root / ".arborist"
    result_dir.mkdir(parents=True, exist_ok=True)
    result_file = result_dir / "last_run_result.json"
    result_file.write_text(result.to_json())


def _persist_test_result(result: RunTestResult) -> None:
    """Persist RunTestResult to file for later reference."""
    git_root = get_git_root()
    if not git_root:
        return

    result_dir = git_root / ".arborist"
    result_dir.mkdir(parents=True, exist_ok=True)
    result_file = result_dir / "last_test_result.json"
    result_file.write_text(result.to_json())


@click.group()
def task() -> None:
    """Task execution commands.

    Commands for executing tasks sequentially with git commits.
    """
    pass


@task.command()
@click.argument("task_id")
@click.option("--runner", help="AI runner to use")
@click.option("--model", help="Model to use")
@click.option("--timeout", type=int, default=1800, help="Timeout in seconds")
@click.pass_context
def run(
    ctx: click.Context,
    task_id: str,
    runner: str | None,
    model: str | None,
    timeout: int,
) -> None:
    """Run a task and commit changes.

    Executes the AI runner for a task, then stages and commits all changes.
    """
    spec_id = _get_spec_id()
    container_mode = _get_container_mode()

    # Check for echo mode (testing)
    if ctx.obj and ctx.obj.get("echo_for_testing"):
        _echo_command(
            "task run",
            spec_id=spec_id,
            task_id=task_id,
            runner=runner,
            model=model,
        )
        result = RunResult(
            success=True,
            task_id=task_id,
            message="Echo mode",
            files_changed=0,
        )
        _output_result(result, ctx)
        return

    # Validate environment
    git_root = get_git_root()
    if not git_root or not is_git_repo(git_root):
        result = RunResult(
            success=False,
            task_id=task_id,
            message="Not in a git repository",
            error="Must run from within a git repository",
        )
        _output_result(result, ctx)
        ctx.exit(1)

    # Get runner configuration
    from agent_arborist.config import get_config, get_step_runner_model
    from agent_arborist.home import get_arborist_home

    try:
        arborist_home = get_arborist_home()
        config = get_config(arborist_home)
        resolved_runner, resolved_model = get_step_runner_model(
            config, "run", cli_runner=runner, cli_model=model
        )
    except Exception:
        resolved_runner = runner or "claude"
        resolved_model = model or "sonnet"

    # Build task prompt
    # TODO: Get task description from DAG or spec
    task_prompt = f"Execute task {task_id}"
    if spec_id:
        task_prompt = f"Execute task {task_id} for spec {spec_id}"

    # Run the AI task
    from agent_arborist.runner import run_ai_task

    try:
        # Determine if we should use container
        from agent_arborist.container_runner import ContainerMode, should_use_container
        use_container = should_use_container(
            ContainerMode(container_mode) if container_mode else ContainerMode.AUTO,
            git_root,
        )

        ai_result = run_ai_task(
            prompt=task_prompt,
            runner=resolved_runner,  # type: ignore  # Already validated as RunnerType
            model=resolved_model,
            cwd=git_root,
            timeout=timeout,
            use_container=use_container,
        )

        if not ai_result.success:
            result = RunResult(
                success=False,
                task_id=task_id,
                message="AI task failed",
                error=ai_result.error or "Unknown error",
                runner=resolved_runner,
                model=resolved_model,
            )
            _persist_run_result(result)
            _output_result(result, ctx)
            ctx.exit(1)

        # Commit changes
        files_changed = count_changed_files(git_root)
        summary = ai_result.summary or f"Completed task {task_id}"

        if has_uncommitted_changes(git_root):
            commit_result = commit_task(
                spec_id=spec_id or "unknown",
                task_id=task_id,
                summary=summary,
                cwd=git_root,
            )

            if not commit_result.success:
                result = RunResult(
                    success=False,
                    task_id=task_id,
                    message="Failed to commit changes",
                    error=commit_result.error,
                    files_changed=files_changed,
                    runner=resolved_runner,
                    model=resolved_model,
                )
                _persist_run_result(result)
                _output_result(result, ctx)
                ctx.exit(1)

        result = RunResult(
            success=True,
            task_id=task_id,
            message=summary,
            files_changed=files_changed,
            runner=resolved_runner,
            model=resolved_model,
            duration_seconds=ai_result.duration_seconds,
        )
        _persist_run_result(result)
        _output_result(result, ctx)

    except Exception as e:
        result = RunResult(
            success=False,
            task_id=task_id,
            message="Task execution failed",
            error=str(e),
            runner=resolved_runner,
            model=resolved_model,
        )
        _persist_run_result(result)
        _output_result(result, ctx)
        ctx.exit(1)


@task.command("run-test")
@click.argument("task_id")
@click.option("--test-cmd", help="Test command to run")
@click.option("--timeout", type=int, default=300, help="Timeout in seconds")
@click.pass_context
def run_test(
    ctx: click.Context,
    task_id: str,
    test_cmd: str | None,
    timeout: int,
) -> None:
    """Run tests for a task.

    Executes the test command (auto-detected or specified).
    """
    spec_id = _get_spec_id()

    # Check for echo mode
    if ctx.obj and ctx.obj.get("echo_for_testing"):
        _echo_command(
            "task run-test",
            spec_id=spec_id,
            task_id=task_id,
            test_cmd=test_cmd,
        )
        result = RunTestResult(
            success=True,
            task_id=task_id,
            message="Echo mode",
        )
        _output_result(result, ctx)
        return

    git_root = get_git_root()
    if not git_root:
        result = RunTestResult(
            success=False,
            task_id=task_id,
            message="Not in a git repository",
            error="Must run from within a git repository",
        )
        _output_result(result, ctx)
        ctx.exit(1)

    # Get test command from config if not specified
    if not test_cmd:
        try:
            from agent_arborist.config import get_config
            from agent_arborist.home import get_arborist_home

            arborist_home = get_arborist_home()
            config = get_config(arborist_home)
            test_cmd = config.test.command
        except Exception:
            pass

    # Run tests
    test_result = run_tests(
        cwd=git_root,
        test_cmd=test_cmd,
        timeout=timeout,
    )

    result = RunTestResult(
        success=test_result.success,
        task_id=task_id,
        message=test_result.message,
        error=test_result.error,
        test_command=test_cmd or detect_test_command(git_root),
        stdout=test_result.stdout,
        stderr=test_result.stderr,
    )
    _persist_test_result(result)
    _output_result(result, ctx)

    if not result.success:
        ctx.exit(1)


@task.command()
@click.argument("task_id")
@click.pass_context
def status(ctx: click.Context, task_id: str) -> None:
    """Show status of a task.

    Displays current git status and recent commits.
    """
    spec_id = _get_spec_id()

    git_root = get_git_root()
    if not git_root:
        console.print("[red]Not in a git repository[/red]")
        ctx.exit(1)

    console.print(f"\n[bold]Task Status: {task_id}[/bold]")
    if spec_id:
        console.print(f"Spec: {spec_id}")

    console.print(f"\nBranch: {get_current_branch(git_root)}")

    if has_uncommitted_changes(git_root):
        console.print(f"[yellow]Uncommitted changes: {count_changed_files(git_root)} files[/yellow]")
    else:
        console.print("[green]Working tree clean[/green]")

    # Show recent commits
    from agent_arborist.tasks import get_commit_log
    commits = get_commit_log(limit=5, cwd=git_root)
    if commits:
        console.print("\nRecent commits:")
        for commit in commits:
            console.print(f"  {commit}")


@task.command()
@click.pass_context
def list(ctx: click.Context) -> None:
    """List tasks from the current spec DAG.

    Reads the DAG file and lists all tasks.
    """
    spec_id = _get_spec_id()
    if not spec_id:
        console.print("[red]ARBORIST_SPEC_ID not set[/red]")
        ctx.exit(1)

    git_root = get_git_root()
    if not git_root:
        console.print("[red]Not in a git repository[/red]")
        ctx.exit(1)

    dag_path = git_root / ".arborist" / "dagu" / "dags" / f"{spec_id}.yaml"
    if not dag_path.exists():
        console.print(f"[red]DAG not found: {dag_path}[/red]")
        ctx.exit(1)

    # Parse DAG and list tasks
    from agent_arborist.dag_builder import parse_yaml_to_bundle

    yaml_content = dag_path.read_text()
    bundle = parse_yaml_to_bundle(yaml_content)

    console.print(f"\n[bold]Tasks for spec: {spec_id}[/bold]\n")

    # List steps from root DAG
    for step in bundle.root.steps:
        if step.call:
            console.print(f"  [cyan]{step.call}[/cyan] (subdag)")
        elif step.command and "task run" in step.command:
            task_id = step.command.split()[-1]
            console.print(f"  {task_id}")

    # List steps from subdags
    for subdag in bundle.subdags:
        console.print(f"\n  [bold]{subdag.name}[/bold]:")
        for step in subdag.steps:
            if step.call:
                console.print(f"    [cyan]{step.call}[/cyan] (subdag)")
            elif step.command and "task run" in step.command:
                task_id = step.command.split()[-1]
                console.print(f"    {task_id}")


def register_task_commands(main_group: click.Group) -> None:
    """Register task commands with the main CLI group.

    Args:
        main_group: The main click group to add commands to.
    """
    main_group.add_command(task)
