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
from agent_arborist.runner import (
    get_runner,
    RunnerType,
    get_default_runner,
    get_default_model,
    ARBORIST_DEFAULT_RUNNER_ENV_VAR,
    ARBORIST_DEFAULT_MODEL_ENV_VAR,
)
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
from agent_arborist.container_runner import ContainerMode
from agent_arborist.container_context import (
    wrap_subprocess_command,
    get_container_mode_from_env,
)
from agent_arborist import dagu_runs
from agent_arborist.git_tasks import (
    get_worktree_path,
    find_parent_branch,
    find_worktree_for_branch,
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
    build_task_tree_from_yaml,
)
from agent_arborist.step_results import (
    StepResult,
    PreSyncResult,
    RunResult,
    CommitResult,
    RunTestResult,
    PostMergeResult,
    PostCleanupResult,
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


def output_result(result: StepResult, ctx: click.Context) -> None:
    """Output step result in appropriate format.

    JSON goes to stdout (for Dagu capture).
    Text format uses rich console for human-readable output.
    """
    output_format = ctx.obj.get("output_format", "json")

    if output_format == "json":
        # JSON output to stdout for Dagu capture
        print(result.to_json())
    else:
        # Human-readable text using rich console
        _output_text_result(result, ctx)


def _count_changed_files(worktree_path: Path) -> int:
    """Count files changed in worktree since last commit."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~1"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return len([f for f in result.stdout.strip().split("\n") if f])
    except Exception:
        pass
    return 0


def _get_last_commit_message(worktree_path: Path, task_id: str) -> str | None:
    """Get last commit message if it matches expected task format."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            msg = result.stdout.strip()
            if msg.startswith(f"task({task_id}):"):
                return msg
    except Exception:
        pass
    return None


def _get_head_sha(worktree_path: Path) -> str | None:
    """Get the HEAD commit SHA."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _count_staged_files(worktree_path: Path) -> int:
    """Count files staged for commit."""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return len([f for f in result.stdout.strip().split("\n") if f])
    except Exception:
        pass
    return 0


def _output_text_result(result: StepResult, ctx: click.Context) -> None:
    """Output result in human-readable text format."""
    quiet = ctx.obj.get("quiet", False)

    if isinstance(result, PreSyncResult):
        if result.success:
            console.print(f"[green]OK:[/green] Task synced at {result.worktree_path}")
            if not quiet:
                console.print(f"  Branch: {result.branch}")
                console.print(f"  Parent: {result.parent_branch}")
        else:
            console.print(f"[red]Error:[/red] Pre-sync failed")
            if result.error:
                console.print(f"[dim]{result.error}[/dim]")

    elif isinstance(result, RunResult):
        if result.success:
            console.print(f"[green]OK:[/green] Task executed successfully")
            if not quiet:
                console.print(f"  Files changed: {result.files_changed}")
                console.print(f"  Duration: {result.duration_seconds:.1f}s")
                if result.commit_message:
                    console.print(f"  Commit: {result.commit_message}")
        else:
            console.print(f"[red]Error:[/red] Task execution failed")
            if result.error:
                console.print(f"[dim]{result.error}[/dim]")

    elif isinstance(result, CommitResult):
        if result.success:
            console.print(f"[green]OK:[/green] Commit created")
            if not quiet and result.commit_sha:
                console.print(f"  SHA: {result.commit_sha[:8]}")
                console.print(f"  Message: {result.message}")
        else:
            console.print(f"[red]Error:[/red] Commit failed")
            if result.error:
                console.print(f"[dim]{result.error}[/dim]")

    elif isinstance(result, RunTestResult):
        if result.success:
            console.print(f"[green]OK:[/green] Tests passed")
            if not quiet:
                if result.test_count is not None:
                    console.print(f"  Total: {result.test_count}")
                if result.passed is not None:
                    console.print(f"  Passed: {result.passed}")
        else:
            console.print(f"[red]Error:[/red] Tests failed")
            if result.failed is not None:
                console.print(f"  Failed: {result.failed}")
            if result.error:
                console.print(f"[dim]{result.error}[/dim]")

    elif isinstance(result, PostMergeResult):
        if result.success:
            console.print(f"[green]OK:[/green] Merged {result.source_branch} -> {result.merged_into}")
            if not quiet and result.commit_sha:
                console.print(f"  SHA: {result.commit_sha[:8]}")
        else:
            console.print(f"[red]Error:[/red] Merge failed")
            if result.conflicts:
                console.print(f"  Conflicts: {', '.join(result.conflicts)}")
            if result.error:
                console.print(f"[dim]{result.error}[/dim]")

    elif isinstance(result, PostCleanupResult):
        if result.success:
            console.print(f"[green]OK:[/green] Cleanup complete")
            if not quiet:
                if result.worktree_removed:
                    console.print("  Worktree removed")
                if result.branch_deleted:
                    console.print("  Branch deleted")
        else:
            console.print(f"[yellow]Warning:[/yellow] Cleanup incomplete")
            if result.error:
                console.print(f"[dim]{result.error}[/dim]")


def _print_dag_tree(dag_run: dagu_runs.DagRun, console: Console, prefix: str = "", is_last: bool = True) -> None:
    """Print a DAG run and its children as a tree.

    Args:
        dag_run: The DAG run to print
        console: Rich console for output
        prefix: Prefix for tree drawing characters
        is_last: Whether this is the last child at this level
    """
    from agent_arborist import dagu_runs

    attempt = dag_run.latest_attempt
    if not attempt:
        return

    # Print this DAG's steps
    for i, step in enumerate(attempt.steps):
        is_last_step = i == len(attempt.steps) - 1
        has_children = step.child_dag_name and dag_run.children

        # Determine tree characters
        if is_last_step:
            connector = "└──" if not prefix else prefix + "└──"
            child_prefix = prefix + "    "
        else:
            connector = "├──" if not prefix else prefix + "├──"
            child_prefix = prefix + "│   "

        # Format status
        status_name = step.status.to_name()
        if step.status == dagu_runs.DaguStatus.SUCCESS:
            status_str = f"[green]{status_name}[/green]"
        elif step.status == dagu_runs.DaguStatus.FAILED:
            status_str = f"[red]{status_name}[/red]"
        elif step.status == dagu_runs.DaguStatus.RUNNING:
            status_str = f"[yellow]{status_name}[/yellow]"
        else:
            status_str = status_name

        # Format duration
        duration_str = dagu_runs._format_duration(step.started_at, step.finished_at)

        # Print step
        line = f"{connector} {step.name} {status_str} ({duration_str})"
        console.print(line)

        # If this is a call step with children, print them
        if step.child_dag_name:
            # Find matching children
            matching_children = [c for c in dag_run.children if c.dag_name == step.child_dag_name]

            for child_idx, child in enumerate(matching_children):
                is_last_child = child_idx == len(matching_children) - 1

                # Determine child prefix
                if is_last_step:
                    child_connector = child_prefix + "└──"
                    grandchild_prefix = child_prefix + "    "
                else:
                    child_connector = child_prefix + "├──"
                    grandchild_prefix = child_prefix + "│   "

                # Print child DAG name
                child_attempt = child.latest_attempt
                child_status = child_attempt.status.to_name() if child_attempt else "unknown"
                child_duration = dagu_runs._format_duration(
                    child_attempt.started_at, child_attempt.finished_at
                ) if child_attempt else "N/A"

                console.print(f"{child_connector} {child.dag_name} {child_status} ({child_duration})")

                # Recursively print child's steps
                for step_idx, child_step in enumerate(child_attempt.steps if child_attempt else []):
                    is_last_grandchild = step_idx == len((child_attempt.steps if child_attempt else [])) - 1

                    if is_last_grandchild:
                        step_connector = grandchild_prefix + "└──"
                    else:
                        step_connector = grandchild_prefix + "├──"

                    child_step_status = child_step.status.to_name()
                    if child_step.status == dagu_runs.DaguStatus.SUCCESS:
                        child_status_str = f"[green]{child_step_status}[/green]"
                    elif child_step.status == dagu_runs.DaguStatus.FAILED:
                        child_status_str = f"[red]{child_step_status}[/red]"
                    elif child_step.status == dagu_runs.DaguStatus.RUNNING:
                        child_status_str = f"[yellow]{child_step_status}[/yellow]"
                    else:
                        child_status_str = child_step_status

                    child_step_duration = dagu_runs._format_duration(
                        child_step.started_at, child_step.finished_at
                    )

                    console.print(f"{step_connector} {child_step.name} {child_status_str} ({child_step_duration})")


@click.group()
@click.option("--quiet", "-q", is_flag=True, help="Suppress non-essential output")
@click.option("--home", envvar="ARBORIST_HOME", help="Override arborist home directory")
@click.option("--spec", "-s", envvar="ARBORIST_SPEC", help="Spec name (auto-detected from git branch if not set)")
@click.option(
    "--format", "-f", "output_format",
    type=click.Choice(["json", "text"]),
    default="json",
    envvar="ARBORIST_OUTPUT_FORMAT",
    help="Output format: json (default) or text"
)
@click.option("--echo-for-testing", is_flag=True, hidden=True, help="Echo command info and exit (for testing)")
@click.pass_context
def main(ctx: click.Context, quiet: bool, home: str | None, spec: str | None, output_format: str, echo_for_testing: bool) -> None:
    """Agent Arborist - Automated Task Tree Executor.

    Orchestrate DAG workflows with Claude Code and Dagu.
    """
    ctx.ensure_object(dict)
    ctx.obj["quiet"] = quiet
    ctx.obj["home_override"] = home
    ctx.obj["spec_override"] = spec
    ctx.obj["output_format"] = output_format
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
    default=None,
    help=f"Runner to test (default: ${ARBORIST_DEFAULT_RUNNER_ENV_VAR} or opencode)",
)
def doctor_check_runner(runner: RunnerType | None) -> None:
    """Test that a runner can execute prompts."""
    runner_type = runner or get_default_runner()
    console.print(f"[cyan]Testing {runner_type} runner...[/cyan]")

    runner_instance = get_runner(runner_type)

    if not runner_instance.is_available():
        console.print(f"[red]FAIL:[/red] {runner_type} not found in PATH")
        raise SystemExit(1)

    console.print(f"[dim]Found {runner_type} at {runner_instance.command}[/dim]")
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
# Config commands
# -----------------------------------------------------------------------------


@main.group()
def config() -> None:
    """Configuration management."""
    pass


@config.command("show")
@click.pass_context
def config_show(ctx: click.Context) -> None:
    """Show effective configuration (merged from all sources).

    Displays the current configuration after merging:
    - Global config (~/.arborist_config.json)
    - Project config (.arborist/config.json)
    - Environment variables

    Output is JSON format for easy parsing.
    """
    import json as json_module

    from agent_arborist.config import get_config

    arborist_home = ctx.obj.get("arborist_home")
    config = get_config(arborist_home=arborist_home)
    print(json_module.dumps(config.to_dict(), indent=2))


@config.command("init")
@click.option("--global", "is_global", is_flag=True, help="Create global config at ~/.arborist_config.json")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing config file")
@click.pass_context
def config_init(ctx: click.Context, is_global: bool, force: bool) -> None:
    """Initialize a configuration file with template.

    Creates a commented configuration file with all available options.

    By default, creates project config in .arborist/config.json.
    Use --global to create ~/.arborist_config.json instead.
    """
    import json as json_module

    from agent_arborist.config import (
        generate_config_template,
        get_global_config_path,
        get_project_config_path,
    )

    if is_global:
        config_path = get_global_config_path()
    else:
        arborist_home = ctx.obj.get("arborist_home")
        if not arborist_home:
            console.print("[red]Error:[/red] Not in an arborist project")
            console.print("Run 'arborist init' first, or use --global for global config")
            raise SystemExit(1)
        config_path = get_project_config_path(arborist_home)

    if config_path.exists() and not force:
        console.print(f"[red]Error:[/red] Config file already exists: {config_path}")
        console.print("Use --force to overwrite")
        raise SystemExit(1)

    # Ensure parent directory exists
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Generate and write template
    template = generate_config_template()
    config_path.write_text(json_module.dumps(template, indent=2))

    console.print(f"[green]Created config file:[/green] {config_path}")


@config.command("validate")
@click.pass_context
def config_validate(ctx: click.Context) -> None:
    """Validate configuration files.

    Checks both global and project config files for:
    - Valid JSON syntax
    - Valid field names (no unknown fields)
    - Valid values (runners, modes, etc.)

    Exits with code 0 if valid, non-zero if errors found.
    """
    from agent_arborist.config import (
        ConfigLoadError,
        ConfigValidationError,
        get_global_config_path,
        get_project_config_path,
        load_config_file,
    )

    errors = []
    validated = []

    # Validate global config
    global_path = get_global_config_path()
    if global_path.exists():
        try:
            config = load_config_file(global_path, strict=True)
            config.validate()
            validated.append(f"Global config: {global_path}")
        except ConfigLoadError as e:
            errors.append(f"Global config ({global_path}): {e}")
        except ConfigValidationError as e:
            errors.append(f"Global config ({global_path}): {e}")

    # Validate project config
    arborist_home = ctx.obj.get("arborist_home")
    if arborist_home:
        project_path = get_project_config_path(arborist_home)
        if project_path.exists():
            try:
                config = load_config_file(project_path, strict=True)
                config.validate()
                validated.append(f"Project config: {project_path}")
            except ConfigLoadError as e:
                errors.append(f"Project config ({project_path}): {e}")
            except ConfigValidationError as e:
                errors.append(f"Project config ({project_path}): {e}")

    # Report results
    if validated:
        for v in validated:
            console.print(f"[green]Valid:[/green] {v}")

    if errors:
        for e in errors:
            console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)

    if not validated and not errors:
        console.print("[dim]No config files found to validate[/dim]")
    else:
        console.print("\n[green]All config files are valid![/green]")


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
    Branches must already exist (run 'arborist spec branch-create-all' first).
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

    # Sync the task (create worktree and sync from parent)
    result = sync_task(task_info.branch, task_info.parent_branch, worktree_path)

    # Build step result
    step_result = PreSyncResult(
        success=result.success,
        worktree_path=str(worktree_path),
        branch=task_info.branch,
        parent_branch=task_info.parent_branch,
        created_worktree=worktree_path.exists(),
        synced_from_parent=result.success,
        error=result.error if not result.success else None,
    )

    # Output result
    output_result(step_result, ctx)

    if result.success:
        # Update state
        update_task_status(manifest.spec_id, task_id, "running", branch=task_info.branch, worktree=str(worktree_path))
    else:
        raise SystemExit(1)


@task.command("run")
@click.argument("task_id")
@click.option("--timeout", "-t", default=1800, help="Timeout in seconds")
@click.option(
    "--runner",
    "-r",
    type=click.Choice(["claude", "opencode", "gemini"]),
    default=None,
    help=f"Runner to use (default: ${ARBORIST_DEFAULT_RUNNER_ENV_VAR} or opencode)",
)
@click.option(
    "--model",
    "-m",
    default=None,
    help="Model to use (default: runner's default model)",
)
@click.pass_context
def task_run(ctx: click.Context, task_id: str, timeout: int, runner: str | None, model: str | None) -> None:
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

    # Resolve runner/model from config (CLI args override config)
    from agent_arborist.config import get_config, get_step_runner_model
    arborist_home = ctx.obj.get("arborist_home")
    arborist_config = get_config(arborist_home=arborist_home)
    runner_type, resolved_model = get_step_runner_model(
        arborist_config, step="run", cli_runner=runner, cli_model=model
    )

    if ctx.obj.get("echo_for_testing"):
        echo_command(
            "task run",
            task_id=task_id,
            spec_id=manifest.spec_id,
            runner=runner_type,
            model=resolved_model,
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
3. Stage ALL your changes with: git add -A
4. Create a SINGLE commit with this EXACT format:

git commit -m "task({task_id}): <one-line summary>

- <detail about what was done>
- <another detail if needed>
- <etc>

(generated by {runner_type} / {resolved_model} on branch {task_info.branch})"

IMPORTANT:
- The first line MUST be: task({task_id}): followed by a brief summary
- Use bullet points for details in the body
- Include the footer line with runner/model/branch info
- Make exactly ONE commit with all your changes
"""

    import time

    # Get runner with specified or default model
    runner_instance = get_runner(runner_type, model=resolved_model)

    if not runner_instance.is_available():
        console.print(f"[red]Error:[/red] {runner_type} not found in PATH")
        raise SystemExit(1)

    # Check if we need to wrap runner command with devcontainer exec
    container_mode = get_container_mode_from_env()
    container_cmd_prefix = None
    if container_mode != ContainerMode.DISABLED:
        from agent_arborist.container_context import should_use_container
        if should_use_container(worktree_path, container_mode):
            container_cmd_prefix = [
                "devcontainer",
                "exec",
                "--workspace-folder",
                str(worktree_path.resolve()),
            ]

    # Run the AI in the worktree directory (or container if needed)
    start_time = time.time()
    result = runner_instance.run(
        prompt,
        timeout=timeout,
        cwd=worktree_path,
        container_cmd_prefix=container_cmd_prefix,
    )
    duration = time.time() - start_time

    # Gather metrics for output
    files_changed = _count_changed_files(worktree_path)
    commit_message = _get_last_commit_message(worktree_path, task_id)

    # Build step result
    step_result = RunResult(
        success=result.success,
        files_changed=files_changed,
        commit_message=commit_message,
        summary=result.output[:500] if result.output else "",
        runner=runner_type,
        model=resolved_model,
        duration_seconds=round(duration, 2),
        error=result.error if not result.success else None,
    )

    # Output result
    output_result(step_result, ctx)

    if not result.success:
        update_task_status(manifest.spec_id, task_id, "failed", error=result.error)
        raise SystemExit(1)


@task.command("commit")
@click.argument("task_id")
@click.pass_context
def task_commit(ctx: click.Context, task_id: str) -> None:
    """Ensure task has a commit - either from AI or create fallback.

    The AI should have already committed with format: task(<id>): summary
    This step is a safety net if the AI didn't commit properly.
    """
    import os
    import subprocess

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

    if ctx.obj.get("echo_for_testing"):
        echo_command(
            "task commit",
            task_id=task_id,
            spec_id=manifest.spec_id,
            worktree=str(worktree_path),
        )
        return

    if not worktree_path.exists():
        console.print(f"[red]Error:[/red] Worktree not found at {worktree_path}")
        raise SystemExit(1)

    # Check if there are staged changes that need committing
    staged_result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=worktree_path,
        capture_output=True,
    )
    has_staged = staged_result.returncode != 0

    # Check if there are unstaged changes
    unstaged_result = subprocess.run(
        ["git", "diff", "--quiet"],
        cwd=worktree_path,
        capture_output=True,
    )
    has_unstaged = unstaged_result.returncode != 0

    # Check last commit message
    last_commit = subprocess.run(
        ["git", "log", "-1", "--format=%s"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
    )
    last_msg = last_commit.stdout.strip() if last_commit.returncode == 0 else ""

    # Check if AI already committed with proper format
    ai_committed = last_msg.startswith(f"task({task_id}):")

    was_fallback = False
    commit_msg = last_msg
    error_msg = None

    if ai_committed and not has_staged and not has_unstaged:
        # AI committed successfully, nothing more to do
        pass
    elif has_staged or has_unstaged:
        # Stage any unstaged changes
        if has_unstaged:
            subprocess.run(["git", "add", "-A"], cwd=worktree_path, check=True)

        # Create fallback commit message
        commit_msg = f"task({task_id}): {task_description}\n\n(fallback commit - AI did not commit)"
        was_fallback = True

        try:
            subprocess.run(
                ["git", "commit", "-m", commit_msg],
                cwd=worktree_path,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr if e.stderr else "Commit failed"
            step_result = CommitResult(
                success=False,
                commit_sha=None,
                message=commit_msg,
                files_staged=_count_staged_files(worktree_path),
                was_fallback=was_fallback,
                error=error_msg,
            )
            output_result(step_result, ctx)
            raise SystemExit(1)
    else:
        # No changes and no AI commit - success with no changes
        pass

    # Build step result
    step_result = CommitResult(
        success=True,
        commit_sha=_get_head_sha(worktree_path),
        message=commit_msg,
        files_staged=_count_staged_files(worktree_path) if was_fallback else 0,
        was_fallback=was_fallback,
    )

    # Output result
    output_result(step_result, ctx)


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
        # No tests - success with no tests
        step_result = RunTestResult(
            success=True,
            test_command=None,
            output_summary="No test command detected, skipping tests",
        )
        output_result(step_result, ctx)
        return

    # Check if we need to wrap test command with devcontainer exec
    container_mode = get_container_mode_from_env()
    container_cmd_prefix = None
    if container_mode != ContainerMode.DISABLED:
        from agent_arborist.container_context import should_use_container
        if should_use_container(worktree_path, container_mode):
            container_cmd_prefix = [
                "devcontainer",
                "exec",
                "--workspace-folder",
                str(worktree_path.resolve()),
            ]

    result = run_tests(worktree_path, test_cmd, container_cmd_prefix)

    # Build step result
    step_result = RunTestResult(
        success=result.success,
        test_command=test_cmd,
        output_summary=result.message[:500] if result.message else "",
        error=result.error if not result.success else None,
    )

    # Output result
    output_result(step_result, ctx)

    if not result.success:
        raise SystemExit(1)


@task.command("post-merge")
@click.argument("task_id")
@click.option("--timeout", "-t", default=300, help="Timeout in seconds for AI merge")
@click.option(
    "--runner",
    "-r",
    type=click.Choice(["claude", "opencode", "gemini"]),
    default=None,
    help=f"Runner to use (default: ${ARBORIST_DEFAULT_RUNNER_ENV_VAR} or opencode)",
)
@click.option(
    "--model",
    "-m",
    default=None,
    help="Model to use (default: runner's default model)",
)
@click.pass_context
def task_post_merge(ctx: click.Context, task_id: str, timeout: int, runner: str | None, model: str | None) -> None:
    """Merge task branch to parent branch using AI.

    AI performs a squash merge with proper commit message format:
    - Leaf tasks: task-leaf(T004): description
    - Parent tasks: task-merge(T002): description

    AI handles conflict resolution if needed.
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

    # Get branch names from manifest
    task_branch = task_info.branch
    parent_branch = task_info.parent_branch

    # Resolve runner/model from config (CLI args override config)
    from agent_arborist.config import get_config, get_step_runner_model
    arborist_home = ctx.obj.get("arborist_home")
    arborist_config = get_config(arborist_home=arborist_home)
    runner_type, resolved_model = get_step_runner_model(
        arborist_config, step="post-merge", cli_runner=runner, cli_model=model
    )

    # Get the task worktree (where we'll do the merge work)
    task_worktree = find_worktree_for_branch(task_branch)

    if not task_worktree:
        console.print(f"[red]Error:[/red] Task worktree not found for {task_branch}")
        console.print(f"[dim]Make sure the task worktree exists before merging[/dim]")
        raise SystemExit(1)

    if ctx.obj.get("echo_for_testing"):
        echo_command(
            "task post-merge",
            task_id=task_id,
            spec_id=manifest.spec_id,
            runner=runner_type,
            model=resolved_model,
            branch=task_branch,
            parent=parent_branch,
            worktree=str(task_worktree),
        )
        return

    if not ctx.obj.get("quiet"):
        console.print(f"[cyan]Merging {task_branch} → {parent_branch} (squash)[/cyan]")

    # Build prompt for AI to do the merge in the task worktree
    merge_prompt = f"""Perform a squash merge of branch '{task_branch}' into '{parent_branch}'.

STEPS:
1. Checkout the parent branch: git checkout {parent_branch}
2. Run: git merge --squash {task_branch}
3. If there are conflicts, resolve them carefully by examining both versions
4. After resolving any conflicts, stage all changes with: git add -A
5. Create a SINGLE commit with this EXACT format:

git commit -m "task({task_id}): <one-line summary of what was merged>

- <detail about changes merged>
- <another detail if needed>

(merged by {runner_type} / {resolved_model} from {task_branch})"

6. Switch back to the original branch: git checkout {task_branch}

IMPORTANT:
- The first line MUST be: task({task_id}): followed by a brief summary
- Use bullet points for details in the body
- Include the footer line showing this was a merge
- If the merge has no changes (branches identical), just report that - no commit needed
- Always switch back to {task_branch} at the end to restore the worktree state

Do NOT push. Just complete the merge and commit locally.
"""

    runner_instance = get_runner(runner_type, model=resolved_model)

    if not runner_instance.is_available():
        console.print(f"[red]Error:[/red] {runner_type} not available")
        raise SystemExit(1)

    if not ctx.obj.get("quiet"):
        console.print(f"[dim]Running {runner_type} in {task_worktree}[/dim]")

    # Check if we need to wrap runner command with devcontainer exec
    container_mode = get_container_mode_from_env()
    container_cmd_prefix = None
    if container_mode != ContainerMode.DISABLED:
        from agent_arborist.container_context import should_use_container
        if should_use_container(task_worktree, container_mode):
            container_cmd_prefix = [
                "devcontainer",
                "exec",
                "--workspace-folder",
                str(task_worktree.resolve()),
            ]

    # Run AI in task worktree
    result = runner_instance.run(
        merge_prompt,
        timeout=timeout,
        cwd=task_worktree,
        container_cmd_prefix=container_cmd_prefix,
    )

    # Build step result
    step_result = PostMergeResult(
        success=result.success,
        merged_into=parent_branch,
        source_branch=task_branch,
        commit_sha=_get_head_sha(task_worktree) if result.success else None,
        conflicts=[],  # AI should have resolved any conflicts
        conflict_resolved=False,
        error=result.error if not result.success else None,
    )

    # Output result
    output_result(step_result, ctx)

    if result.success:
        update_task_status(manifest.spec_id, task_id, "complete")
    else:
        update_task_status(manifest.spec_id, task_id, "failed", error="Merge failed")
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

    result = cleanup_task(task_branch, worktree_path, delete_branch=not keep_branch)

    # Build step result
    step_result = PostCleanupResult(
        success=result.success,
        worktree_removed=not worktree_path.exists(),
        branch_deleted=not keep_branch and not branch_exists(task_branch),
        cleaned_up=result.success,
        error=result.error if not result.success else None,
    )

    # Output result
    output_result(step_result, ctx)

    if result.success:
        # Clear worktree from state
        tree = load_task_tree(manifest.spec_id)
        if tree:
            task_node = tree.get_task(task_id)
            if task_node:
                update_task_status(manifest.spec_id, task_id, task_node.status, worktree=None)


@task.command("container-up")
@click.argument("task_id")
@click.pass_context
def task_container_up(ctx: click.Context, task_id: str) -> None:
    """Start devcontainer for a task's worktree.

    The .devcontainer/.env file is copied to the worktree during pre-sync.
    Environment variables are managed via devcontainer.json configuration.

    Requires ARBORIST_MANIFEST and ARBORIST_WORKTREE environment variables.
    """
    import os
    import subprocess

    manifest_path = os.environ.get("ARBORIST_MANIFEST")
    worktree_path = os.environ.get("ARBORIST_WORKTREE")

    if not manifest_path:
        console.print("[red]Error:[/red] ARBORIST_MANIFEST environment variable not set")
        console.print("This command should be run from a DAGU DAG step")
        raise SystemExit(1)

    if not worktree_path:
        console.print("[red]Error:[/red] ARBORIST_WORKTREE environment variable not set")
        console.print("This command should be run from a DAGU DAG step")
        raise SystemExit(1)

    worktree = Path(worktree_path)
    if not worktree.exists():
        console.print(f"[red]Error:[/red] Worktree does not exist: {worktree}")
        raise SystemExit(1)

    if ctx.obj.get("echo_for_testing"):
        echo_command(
            "task container-up",
            task_id=task_id,
            worktree=str(worktree),
        )
        return

    # Build the command
    cmd_parts = ['devcontainer', 'up', '--workspace-folder', str(worktree)]

    console.print(f"[cyan]Starting container for:[/cyan] {worktree}")

    try:
        result = subprocess.run(
            cmd_parts,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            console.print(f"[red]Error starting container:[/red]")
            console.print(result.stderr)
            raise SystemExit(1)

        console.print(f"[green]Container started successfully[/green]")

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@task.command("container-stop")
@click.argument("task_id")
@click.pass_context
def task_container_stop(ctx: click.Context, task_id: str) -> None:
    """Stop devcontainer for a task's worktree (but don't remove it).

    Uses docker ps filter to find and stop the container by devcontainer.local_folder label.
    The container is stopped but not removed, allowing for debugging.
    Use 'arborist cleanup containers' to fully remove stopped containers.

    Requires ARBORIST_WORKTREE environment variable.
    """
    import os
    import subprocess

    worktree_path = os.environ.get("ARBORIST_WORKTREE")

    if not worktree_path:
        console.print("[red]Error:[/red] ARBORIST_WORKTREE environment variable not set")
        console.print("This command should be run from a DAGU DAG step")
        raise SystemExit(1)

    worktree = Path(worktree_path)

    if ctx.obj.get("echo_for_testing"):
        echo_command(
            "task container-stop",
            task_id=task_id,
            worktree=str(worktree),
        )
        return

    # Build the command to stop the container
    # Find container by devcontainer.local_folder label and stop it
    cmd = f'docker stop $(docker ps -q --filter label=devcontainer.local_folder="{worktree}") 2>/dev/null || true'

    console.print(f"[cyan]Stopping container for:[/cyan] {worktree}")

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
        )

        # Command always succeeds due to || true
        # Check if any container was stopped
        if result.stdout.strip():
            console.print(f"[green]Container stopped successfully[/green]")
        else:
            console.print(f"[dim]No running container found for this worktree[/dim]")

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


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

    Auto-detects spec from git branch, or use --spec to specify.
    Can also use ARBORIST_MANIFEST env var when running from a DAG step.

    Creates the base branch and all task branches in topological order.
    """
    import os

    # Try to get manifest path from multiple sources
    manifest_path_str = os.environ.get("ARBORIST_MANIFEST")

    if manifest_path_str:
        manifest_path = Path(manifest_path_str)
    else:
        # Auto-detect from spec_id and dagu_home
        spec_id = ctx.obj.get("spec_id")
        dagu_home = ctx.obj.get("dagu_home")

        if not spec_id:
            console.print("[red]Error:[/red] No spec available")
            console.print("Either:")
            console.print("  - Run from a spec branch (e.g., 002-my-feature)")
            console.print("  - Use --spec option (e.g., --spec 002-my-feature)")
            console.print("  - Set ARBORIST_MANIFEST environment variable")
            raise SystemExit(1)

        if not dagu_home:
            console.print("[red]Error:[/red] DAGU_HOME not set")
            console.print("Run 'arborist init' first to initialize the project")
            raise SystemExit(1)

        manifest_path = Path(dagu_home) / "dags" / f"{spec_id}.json"

    try:
        manifest = load_manifest(manifest_path)
    except FileNotFoundError:
        console.print(f"[red]Error:[/red] Manifest not found: {manifest_path}")
        console.print("Run 'arborist spec dag-build' first to generate the manifest")
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


@spec.command("dag-build")
@click.argument("directory", required=False, type=click.Path(exists=True))
@click.option(
    "--runner",
    "-r",
    type=click.Choice(["claude", "opencode", "gemini"]),
    default=None,
    help=f"Runner for AI inference (default: ${ARBORIST_DEFAULT_RUNNER_ENV_VAR} or opencode)",
)
@click.option(
    "--model",
    "-m",
    type=str,
    default=None,
    help=f"Model to use (default: ${ARBORIST_DEFAULT_MODEL_ENV_VAR} or sonnet)",
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
    default=600,
    help="Timeout for AI inference in seconds (default: 600)",
)
@click.option(
    "--container-mode",
    type=click.Choice(["auto", "enabled", "disabled"]),
    default="auto",
    help="Container execution mode: auto (detect .devcontainer), enabled (require), disabled (never)",
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
    model: str | None,
    output: str | None,
    dry_run: bool,
    show: bool,
    no_ai: bool,
    timeout: int,
    container_mode: str,
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
            runner=runner or get_default_runner(),
            model=model or get_default_model() or "default",
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

        # Determine container mode
        container_mode_enum = ContainerMode(container_mode)

        # Get repo path for devcontainer detection
        try:
            repo_path = get_git_root()
        except ArboristHomeError:
            repo_path = None

        # Load arborist config for step-specific runner/model settings
        arborist_home = ctx.obj.get("arborist_home")
        try:
            from agent_arborist.config import get_config
            arborist_config = get_config(arborist_home=arborist_home)
        except Exception:
            arborist_config = None

        dag_name_safe = dag_name.replace("-", "_")
        config = DagConfig(
            name=dag_name_safe,
            description=task_spec.project,
            spec_id=dag_name,
            container_mode=container_mode_enum,
            repo_path=repo_path,
            runner=runner,
            model=model,
            arborist_config=arborist_config,
        )
        builder = DagBuilder(config)
        dag_yaml = builder.build_yaml(task_spec)
    else:
        # AI inference mode
        runner_type = runner or get_default_runner()
        resolved_model = model if model is not None else get_default_model()
        model_display = f" ({resolved_model})" if resolved_model else ""
        if not ctx.obj.get("quiet"):
            console.print(f"[cyan]Generating DAG using {runner_type}{model_display}...[/cyan]")

        # Check if runner is available (pass model explicitly to avoid double-defaulting)
        runner_instance = get_runner(runner_type, model=resolved_model)
        if not runner_instance.is_available():
            console.print(f"[red]Error:[/red] {runner_type} not found in PATH")
            console.print("Install the runner or use --no-ai for deterministic parsing")
            raise SystemExit(1)

        # Compute manifest path for the generator
        dagu_home = ctx.obj.get("dagu_home")
        if output:
            manifest_path_for_gen = str(Path(output).with_suffix(".json").resolve())
        elif dagu_home:
            manifest_path_for_gen = str((Path(dagu_home) / "dags" / f"{dag_name}.json").resolve())
        else:
            manifest_path_for_gen = f"{dag_name}.json"

        # Determine container mode
        container_mode_enum = ContainerMode(container_mode)

        # Get repo path for devcontainer detection
        try:
            repo_path = get_git_root()
        except ArboristHomeError:
            repo_path = None

        # Generate using AI - pass the spec directory for AI to explore
        generator = DagGenerator(
            runner=runner_instance,
            container_mode=container_mode_enum,
            repo_path=repo_path,
        )
        result = generator.generate(spec_dir, dag_name, timeout=timeout, manifest_path=manifest_path_for_gen)

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

    # Build task tree from generated YAML (not from spec file)
    # This ensures manifest matches what AI generated
    task_tree = build_task_tree_from_yaml(dag_name, dag_yaml)

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

    # Inject ARBORIST_MANIFEST env into generated DAG YAML (multi-document)
    import yaml
    documents = list(yaml.safe_load_all(dag_yaml))

    # Root DAG is first document
    root_dag = documents[0]

    # Add env section if not present
    if "env" not in root_dag:
        root_dag["env"] = []

    # TODO: We must use absolute paths AND add env to ALL documents because:
    # 1. Dagu filters inherited env vars - only PATH, HOME, DAGU_*, etc. pass through
    # 2. ARBORIST_MANIFEST set in process env when calling `dagu start` is NOT inherited
    # 3. Sub-DAGs (via `call:`) don't inherit env from parent DAG document
    # 4. Sub-DAGs also don't inherit workingDir, so relative paths break
    # See: https://docs.dagu.cloud/writing-workflows/environment-variables
    # NOTE: DAGU requires KEY=value format, not KEY: value
    manifest_env = f"ARBORIST_MANIFEST={manifest_path.resolve()}"

    # Add manifest env to ALL documents (root and sub-DAGs)
    for doc in documents:
        if "env" not in doc:
            doc["env"] = []

        has_manifest = any(
            isinstance(e, str) and e.startswith("ARBORIST_MANIFEST=")
            for e in doc["env"]
        )
        if has_manifest:
            # Replace existing manifest with correct path
            doc["env"] = [
                manifest_env if (isinstance(e, str) and e.startswith("ARBORIST_MANIFEST=")) else e
                for e in doc["env"]
            ]
            # Remove duplicates (keep first)
            seen = set()
            unique_env = []
            for e in doc["env"]:
                key = e.split("=")[0] if isinstance(e, str) and "=" in e else e
                if key not in seen:
                    seen.add(key)
                    unique_env.append(e)
            doc["env"] = unique_env
        else:
            doc["env"].append(manifest_env)

    # If echo_only, inject --echo-for-testing into all arborist commands (in all documents)
    if echo_only:
        for doc in documents:
            for step in doc.get("steps", []):
                cmd = step.get("command", "")
                # Handle both 'arborist' and potential path variations
                if "arborist " in cmd:
                    step["command"] = cmd.replace("arborist ", "arborist --echo-for-testing ", 1)

    # Re-serialize as multi-document YAML
    yaml_parts = []
    for doc in documents:
        yaml_parts.append(yaml.dump(doc, default_flow_style=False, sort_keys=False))
    dag_yaml = "---\n".join(yaml_parts)

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

    # Parse the DAG (multi-document YAML - use first document as root)
    try:
        dag_content = dag_path.read_text()
        documents = list(yaml.safe_load_all(dag_content))
        dag_data = documents[0] if documents else {}
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
@click.option("--timeout", default=86400, help="Execution timeout in seconds (default: 86400)")
@click.pass_context
def dag_run(
    ctx: click.Context,
    dag_name: str | None,
    dry_run: bool,
    params: str | None,
    run_id: str | None,
    timeout: int,
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
            timeout=str(timeout),
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
            timeout=timeout,
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
@click.option("--expand-subdags", "-e", is_flag=True, help="Expand sub-DAG tree hierarchy")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def dag_run_show(
    ctx: click.Context,
    dag_name: str | None,
    run_id: str | None,
    logs: bool,
    step: str | None,
    expand_subdags: bool,
    as_json: bool,
) -> None:
    """Show details of a DAG run.

    DAG_NAME is the name of the DAG (default: current spec-id).

    Displays step-by-step execution details, timing, and optionally logs.
    With --expand-subdags, shows the full hierarchy of sub-DAG executions.
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
            expand_subdags=str(expand_subdags),
            json=str(as_json),
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

    # If using new options, use data layer instead of dagu CLI
    if expand_subdags or as_json:
        import json

        # If no run_id specified, get the latest run
        if not run_id:
            runs = dagu_runs.list_dag_runs(Path(dagu_home), dag_name=resolved_dag_name, limit=1)
            if not runs:
                console.print(f"[dim]No runs found for DAG: {resolved_dag_name}[/dim]")
                return
            run_id = runs[0].run_id

        # Load the DAG run with optional sub-DAG expansion
        dag_run = dagu_runs.load_dag_run(
            Path(dagu_home), resolved_dag_name, run_id, expand_subdags=expand_subdags
        )

        if not dag_run:
            console.print(f"[red]Error:[/red] DAG run not found: {resolved_dag_name} ({run_id})")
            raise SystemExit(1)

        attempt = dag_run.latest_attempt
        if not attempt:
            console.print(f"[dim]No attempt data available for run: {run_id}[/dim]")
            return

        if as_json:
            # Output as JSON
            json_data = {
                "dag_name": dag_run.dag_name,
                "run_id": dag_run.run_id,
                "status": attempt.status.to_name(),
                "started_at": attempt.started_at.isoformat() if attempt.started_at else None,
                "finished_at": attempt.finished_at.isoformat() if attempt.finished_at else None,
            }

            # Add duration
            if attempt.started_at and attempt.finished_at:
                duration_seconds = (attempt.finished_at - attempt.started_at).total_seconds()
                json_data["duration_seconds"] = duration_seconds

            # Add steps
            json_data["steps"] = []
            for step in attempt.steps:
                step_data = {
                    "name": step.name,
                    "status": step.status.to_name(),
                    "started_at": step.started_at.isoformat() if step.started_at else None,
                    "finished_at": step.finished_at.isoformat() if step.finished_at else None,
                }
                if step.child_dag_name:
                    step_data["child_dag_name"] = step.child_dag_name
                    step_data["child_run_ids"] = step.child_run_ids
                json_data["steps"].append(step_data)

            # Add children if expanded
            if expand_subdags:
                json_data["children"] = []
                for child in dag_run.children:
                    child_attempt = child.latest_attempt
                    child_data = {
                        "dag_name": child.dag_name,
                        "run_id": child.run_id,
                        "status": child_attempt.status.to_name() if child_attempt else "unknown",
                        "started_at": child_attempt.started_at.isoformat() if child_attempt and child_attempt.started_at else None,
                        "finished_at": child_attempt.finished_at.isoformat() if child_attempt and child_attempt.finished_at else None,
                        "parent_dag_name": child.parent_dag_name,
                        "parent_dag_id": child.parent_dag_id,
                        "root_dag_name": child.root_dag_name,
                        "root_dag_id": child.root_dag_id,
                    }

                    # Add child steps
                    if child_attempt:
                        child_data["steps"] = []
                        for step in child_attempt.steps:
                            child_step_data = {
                                "name": step.name,
                                "status": step.status.to_name(),
                                "started_at": step.started_at.isoformat() if step.started_at else None,
                                "finished_at": step.finished_at.isoformat() if step.finished_at else None,
                            }
                            child_data["steps"].append(child_step_data)

                    json_data["children"].append(child_data)

            console.print(json.dumps(json_data, indent=2))
        else:
            # Output as tree with expanded sub-DAGs
            console.print(f"[bold cyan]{dag_run.dag_name}[/bold cyan]")
            console.print(f"[dim]Run ID:[/dim] {dag_run.run_id}")

            # Format status
            status_name = attempt.status.to_name()
            if attempt.status == dagu_runs.DaguStatus.SUCCESS:
                status_display = f"[green]{status_name}[/green]"
            elif attempt.status == dagu_runs.DaguStatus.FAILED:
                status_display = f"[red]{status_name}[/red]"
            elif attempt.status == dagu_runs.DaguStatus.RUNNING:
                status_display = f"[yellow]{status_name}[/yellow]"
            else:
                status_display = status_name

            duration_str = dagu_runs._format_duration(attempt.started_at, attempt.finished_at)
            console.print(f"[dim]Status:[/dim] {status_display}")
            console.print(f"[dim]Duration:[/dim] {duration_str}")

            # Show sub-DAG hierarchy
            console.print("\n[bold]Sub-DAG Hierarchy:[/bold]")
            _print_dag_tree(dag_run, console=console, prefix="")

        return

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


@dag.command("run-list")
@click.option("--limit", "-n", default=20, help="Limit number of results")
@click.option("--dag-name", "-d", help="Filter by specific DAG name")
@click.option(
    "--status",
    "-s",
    type=click.Choice(
        ["pending", "running", "failed", "skipped", "success"], case_sensitive=False
    ),
    help="Filter by status",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def dag_run_list(
    ctx: click.Context,
    limit: int,
    dag_name: str | None,
    status: str | None,
    as_json: bool,
) -> None:
    """List DAG runs with status, timing, and run IDs.

    Shows historical DAG executions from the local Dagu data directory.
    Can filter by DAG name and status. Output as table or JSON.
    """
    import json

    dagu_home = ctx.obj.get("dagu_home")

    if ctx.obj.get("echo_for_testing"):
        echo_command(
            "dag run-list",
            dagu_home=str(dagu_home) if dagu_home else "none",
            limit=str(limit),
            dag_name=dag_name or "all",
            status=status or "all",
            json=str(as_json),
        )
        return

    # Check DAGU_HOME is set
    if not dagu_home:
        console.print("[red]Error:[/red] DAGU_HOME not set")
        console.print("Run 'arborist init' first to initialize the project")
        raise SystemExit(1)

    # Convert status string to enum if provided
    status_filter = None
    if status:
        status_filter = dagu_runs.DaguStatus.from_name(status)
        if status_filter is None:
            console.print(f"[red]Error:[/red] Invalid status: {status}")
            raise SystemExit(1)

    # Load runs
    runs = dagu_runs.list_dag_runs(
        Path(dagu_home), dag_name=dag_name, status=status_filter, limit=limit
    )

    if not runs:
        console.print("[dim]No DAG runs found[/dim]")
        return

    if as_json:
        # Output as JSON
        json_runs = []
        for run in runs:
            attempt = run.latest_attempt
            json_run = {
                "dag_name": run.dag_name,
                "run_id": run.run_id,
                "status": attempt.status.to_name() if attempt else "unknown",
                "started_at": attempt.started_at.isoformat() if attempt and attempt.started_at else None,
                "finished_at": attempt.finished_at.isoformat() if attempt and attempt.finished_at else None,
            }
            # Calculate duration
            if attempt and attempt.started_at and attempt.finished_at:
                duration_seconds = (attempt.finished_at - attempt.started_at).total_seconds()
                json_run["duration_seconds"] = duration_seconds
            json_runs.append(json_run)

        console.print(json.dumps(json_runs, indent=2))
    else:
        # Output as table
        table = Table(title="DAG Runs")
        table.add_column("DAG", style="cyan")
        table.add_column("Run ID", style="dim")
        table.add_column("Status", style="bold")
        table.add_column("Started")
        table.add_column("Duration")

        for run in runs:
            attempt = run.latest_attempt
            if not attempt:
                continue

            # Format status with color
            status_name = attempt.status.to_name()
            if attempt.status == dagu_runs.DaguStatus.SUCCESS:
                status_display = f"[green]{status_name}[/green]"
            elif attempt.status == dagu_runs.DaguStatus.FAILED:
                status_display = f"[red]{status_name}[/red]"
            elif attempt.status == dagu_runs.DaguStatus.RUNNING:
                status_display = f"[yellow]{status_name}[/yellow]"
            else:
                status_display = status_name

            # Format start time
            if attempt.started_at:
                started_str = attempt.started_at.strftime("%Y-%m-%d %H:%M")
            else:
                started_str = "N/A"

            # Format duration
            duration_str = dagu_runs._format_duration(
                attempt.started_at, attempt.finished_at
            )

            # Truncate run ID for display
            run_id_short = run.run_id[:8] if len(run.run_id) > 8 else run.run_id

            table.add_row(run.dag_name, run_id_short, status_display, started_str, duration_str)

        console.print(table)


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


# -----------------------------------------------------------------------------
# Cleanup commands
# -----------------------------------------------------------------------------


@main.group()
def cleanup() -> None:
    """Cleanup worktrees, containers, and branches."""
    pass


@cleanup.command("containers")
@click.option("--dry-run", "-n", is_flag=True, help="Show what would be cleaned without doing it")
@click.option("--all", is_flag=True, help="Cleanup all specs (ignore current spec)")
@click.pass_context
def cleanup_containers(ctx: click.Context, dry_run: bool, all: bool) -> None:
    """Stop and remove all devcontainer instances for worktrees.

    Auto-detects spec from git branch, or use --spec to specify, or --all for all specs.

    This finds all containers created by devcontainer up for arborist worktrees,
    stops them, and removes them. Containers are identified by the
    devcontainer.local_folder label.
    """
    arborist_home = ctx.obj.get("arborist_home")

    if not arborist_home:
        console.print("[red]Error:[/red] Arborist not initialized")
        console.print("Run 'arborist init' first")
        raise SystemExit(1)

    # Get spec from context unless --all is specified
    spec = None if all else ctx.obj.get("spec_id")

    worktrees_dir = arborist_home / "worktrees"

    if not worktrees_dir.exists():
        console.print("[dim]No worktrees directory found[/dim]")
        return

    # Find all worktree paths
    worktree_paths = []
    if spec:
        spec_dir = worktrees_dir / spec
        if spec_dir.exists():
            for task_dir in spec_dir.iterdir():
                if task_dir.is_dir():
                    worktree_paths.append(task_dir)
    else:
        for spec_dir in worktrees_dir.iterdir():
            if spec_dir.is_dir():
                for task_dir in spec_dir.iterdir():
                    if task_dir.is_dir():
                        worktree_paths.append(task_dir)

    if not worktree_paths:
        console.print("[dim]No worktrees found[/dim]")
        return

    console.print(f"[cyan]Found {len(worktree_paths)} worktree(s)[/cyan]")

    stopped_count = 0
    for worktree_path in worktree_paths:
        # Find containers with this worktree's label
        label_filter = f"label=devcontainer.local_folder={worktree_path}"

        try:
            # List containers with this label
            result = subprocess.run(
                ["docker", "ps", "-q", "--filter", label_filter],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                console.print(f"[yellow]Warning:[/yellow] Failed to list containers for {worktree_path.name}")
                continue

            container_ids = result.stdout.strip().split("\n")
            container_ids = [cid for cid in container_ids if cid]

            if not container_ids:
                continue

            for container_id in container_ids:
                if dry_run:
                    console.print(f"[dim]Would stop and remove container {container_id[:12]} for {worktree_path.name}[/dim]")
                else:
                    # Stop the container
                    stop_result = subprocess.run(
                        ["docker", "stop", container_id],
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )

                    if stop_result.returncode == 0:
                        console.print(f"[green]✓[/green] Stopped container {container_id[:12]} for {worktree_path.name}")

                        # Remove the container
                        rm_result = subprocess.run(
                            ["docker", "rm", container_id],
                            capture_output=True,
                            text=True,
                            timeout=30,
                        )

                        if rm_result.returncode == 0:
                            console.print(f"[green]✓[/green] Removed container {container_id[:12]}")
                            stopped_count += 1
                        else:
                            console.print(f"[yellow]⚠[/yellow] Stopped but failed to remove container {container_id[:12]}")
                    else:
                        console.print(f"[red]✗[/red] Failed to stop container {container_id[:12]}")

        except subprocess.TimeoutExpired:
            console.print(f"[yellow]Warning:[/yellow] Timeout checking containers for {worktree_path.name}")
        except Exception as e:
            console.print(f"[yellow]Warning:[/yellow] Error processing {worktree_path.name}: {e}")

    if dry_run:
        console.print(f"\n[dim]Dry run complete - no containers were actually stopped or removed[/dim]")
    else:
        console.print(f"\n[green]Stopped and removed {stopped_count} container(s)[/green]")


@cleanup.command("dags")
@click.option("--dry-run", "-n", is_flag=True, help="Show what would be cleaned without doing it")
@click.option("--all", is_flag=True, help="Cleanup all specs (ignore current spec)")
@click.pass_context
def cleanup_dags(ctx: click.Context, dry_run: bool, all: bool) -> None:
    """Remove DAG YAML and JSON files from dagu/dags directory.

    Auto-detects spec from git branch, or use --spec to specify, or --all for all specs.

    This removes generated DAG files but does not affect task specs.
    DAGs can be regenerated from specs using 'arborist spec dag-build'.
    """
    dagu_home = ctx.obj.get("dagu_home")

    if not dagu_home:
        console.print("[red]Error:[/red] Arborist not initialized")
        console.print("Run 'arborist init' first")
        raise SystemExit(1)

    # Get spec from context unless --all is specified
    spec = None if all else ctx.obj.get("spec_id")

    dags_dir = dagu_home / "dags"

    if not dags_dir.exists():
        console.print("[dim]No dags directory found[/dim]")
        return

    # Find DAG files
    if spec:
        dag_files = list(dags_dir.glob(f"{spec}.yaml")) + list(dags_dir.glob(f"{spec}.json"))
    else:
        dag_files = list(dags_dir.glob("*.yaml")) + list(dags_dir.glob("*.json"))

    if not dag_files:
        console.print(f"[dim]No DAG files found{' for spec ' + spec if spec else ''}[/dim]")
        return

    console.print(f"[cyan]Found {len(dag_files)} DAG file(s)[/cyan]")

    removed_count = 0
    for dag_file in dag_files:
        if dry_run:
            console.print(f"[dim]Would remove {dag_file.name}[/dim]")
        else:
            try:
                dag_file.unlink()
                console.print(f"[green]✓[/green] Removed {dag_file.name}")
                removed_count += 1
            except Exception as e:
                console.print(f"[red]✗[/red] Failed to remove {dag_file.name}: {e}")

    if dry_run:
        console.print(f"\n[dim]Dry run complete - no files were actually removed[/dim]")
    else:
        console.print(f"\n[green]Removed {removed_count} DAG file(s)[/green]")


@cleanup.command("logs")
@click.option("--dry-run", "-n", is_flag=True, help="Show what would be cleaned without doing it")
@click.option("--all", is_flag=True, help="Cleanup all specs (ignore current spec)")
@click.pass_context
def cleanup_logs(ctx: click.Context, dry_run: bool, all: bool) -> None:
    """Remove DAG execution logs from dagu/logs directory.

    Auto-detects spec from git branch, or use --spec to specify, or --all for all specs.

    This removes log directories for DAG runs but does not affect DAG definitions.
    Logs are organized by DAG name (normalized with underscores).
    """
    dagu_home = ctx.obj.get("dagu_home")

    if not dagu_home:
        console.print("[red]Error:[/red] Arborist not initialized")
        console.print("Run 'arborist init' first")
        raise SystemExit(1)

    # Get spec from context unless --all is specified
    spec = None if all else ctx.obj.get("spec_id")

    logs_dir = dagu_home / "logs"

    if not logs_dir.exists():
        console.print("[dim]No logs directory found[/dim]")
        return

    # Find log directories
    if spec:
        # Normalize spec name (dagu converts hyphens to underscores)
        normalized_spec = spec.replace("-", "_")
        log_dirs = [d for d in logs_dir.iterdir() if d.is_dir() and d.name.startswith(normalized_spec)]
    else:
        log_dirs = [d for d in logs_dir.iterdir() if d.is_dir()]

    if not log_dirs:
        console.print(f"[dim]No log directories found{' for spec ' + spec if spec else ''}[/dim]")
        return

    console.print(f"[cyan]Found {len(log_dirs)} log director{('y' if len(log_dirs) == 1 else 'ies')}[/cyan]")

    removed_count = 0
    for log_dir in log_dirs:
        if dry_run:
            console.print(f"[dim]Would remove {log_dir.name}/[/dim]")
        else:
            try:
                shutil.rmtree(log_dir)
                console.print(f"[green]✓[/green] Removed {log_dir.name}/")
                removed_count += 1
            except Exception as e:
                console.print(f"[red]✗[/red] Failed to remove {log_dir.name}/: {e}")

    if dry_run:
        console.print(f"\n[dim]Dry run complete - no directories were actually removed[/dim]")
    else:
        console.print(f"\n[green]Removed {removed_count} log director{('y' if removed_count == 1 else 'ies')}[/green]")


@cleanup.command("branches")
@click.option("--force", "-f", is_flag=True, help="Force removal of worktrees and branches")
@click.pass_context
def cleanup_branches(ctx: click.Context, force: bool) -> None:
    """Remove all worktrees and branches for the current spec.

    Auto-detects spec from git branch, or use --spec to specify.
    Finds branches matching {spec}_a* pattern and worktrees in .arborist/worktrees/{spec}/.

    Use --force to force removal even if branches are not fully merged.
    """
    spec_id = ctx.obj.get("spec_id")

    if not spec_id:
        console.print("[red]Error:[/red] No spec available")
        console.print("Either:")
        console.print("  - Run from a spec branch (e.g., 002-my-feature)")
        console.print("  - Use --spec option (e.g., --spec 002-my-feature)")
        raise SystemExit(1)

    if ctx.obj.get("echo_for_testing"):
        echo_command(
            "cleanup branches",
            spec_id=spec_id,
            force=str(force),
        )
        return

    git_root = get_git_root()
    branch_pattern = f"{spec_id}_a"

    # Find all branches matching the pattern
    result = subprocess.run(
        ["git", "branch", "--list", f"{branch_pattern}*"],
        cwd=git_root,
        capture_output=True,
        text=True,
    )
    branches = [b.strip().lstrip("*+ ") for b in result.stdout.strip().split("\n") if b.strip()]

    # Find worktrees using git worktree list (more reliable than directory listing)
    # This catches worktrees even if arborist_home is different or directory structure varies
    worktree_result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=git_root,
        capture_output=True,
        text=True,
    )
    worktrees = []
    current_worktree = None
    for line in worktree_result.stdout.strip().split("\n"):
        if line.startswith("worktree "):
            current_worktree = {"path": Path(line[9:])}
        elif line.startswith("branch refs/heads/") and current_worktree:
            branch_name = line[18:]
            # Check if this worktree's branch matches our pattern
            if branch_name.startswith(branch_pattern):
                current_worktree["branch"] = branch_name
                worktrees.append(current_worktree)
            current_worktree = None
        elif line == "" and current_worktree:
            current_worktree = None

    # Also find worktrees directory for this spec (for cleanup)
    try:
        arborist_home = get_arborist_home()
        worktrees_dir = arborist_home / "worktrees" / spec_id
    except ArboristHomeError:
        worktrees_dir = None

    if not branches and not worktrees:
        console.print(f"[dim]No branches or worktrees found for spec {spec_id}[/dim]")
        return

    if not ctx.obj.get("quiet"):
        console.print(f"[cyan]Cleaning up for spec {spec_id}...[/cyan]")
        if branches:
            console.print(f"[dim]Found {len(branches)} branches matching {branch_pattern}*[/dim]")
        if worktrees:
            console.print(f"[dim]Found {len(worktrees)} worktrees[/dim]")
        if force:
            console.print(f"[yellow]Force mode enabled[/yellow]")

    cleaned = []
    errors = []

    # Remove worktrees first (must be done before deleting branches)
    for worktree_info in worktrees:
        worktree_path = worktree_info["path"]
        if not ctx.obj.get("quiet"):
            console.print(f"[dim]Removing worktree {worktree_path.name}...[/dim]")
        try:
            cmd = ["git", "worktree", "remove", str(worktree_path)]
            if force:
                cmd.append("--force")
            subprocess.run(cmd, cwd=git_root, check=True, capture_output=True)
            cleaned.append(f"worktree:{worktree_path.name}")
        except subprocess.CalledProcessError as e:
            errors.append(f"worktree {worktree_path.name}: {e.stderr.strip() if e.stderr else str(e)}")

    # Clean up empty worktrees directory
    if worktrees_dir and worktrees_dir.exists():
        try:
            worktrees_dir.rmdir()  # Only removes if empty
        except OSError:
            pass  # Not empty, that's fine

    # Delete branches (longer names first to delete children before parents)
    for branch in sorted(branches, key=len, reverse=True):
        if not ctx.obj.get("quiet"):
            console.print(f"[dim]Deleting branch {branch}...[/dim]")
        try:
            cmd = ["git", "branch", "-D" if force else "-d", branch]
            subprocess.run(cmd, cwd=git_root, check=True, capture_output=True)
            cleaned.append(f"branch:{branch}")
        except subprocess.CalledProcessError as e:
            errors.append(f"branch {branch}: {e.stderr.strip() if e.stderr else str(e)}")

    if errors:
        console.print(f"[yellow]Cleaned up {len(cleaned)} items with {len(errors)} errors:[/yellow]")
        for err in errors:
            console.print(f"  [red]Error:[/red] {err}")
        raise SystemExit(1)
    else:
        console.print(f"[green]OK:[/green] Cleaned up {len(cleaned)} items")


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
