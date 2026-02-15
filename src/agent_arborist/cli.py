"""CLI entry point for agent-arborist."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.tree import Tree as RichTree

from agent_arborist.config import get_config, get_step_runner_model, ArboristConfig
from agent_arborist.constants import DEFAULT_NAMESPACE, DEFAULT_MAX_RETRIES
from agent_arborist.git.repo import git_current_branch, git_toplevel


console = Console()


def _load_config() -> ArboristConfig:
    """Load merged config from global + project files + env vars."""
    arborist_home = Path(".arborist")
    if not arborist_home.is_absolute():
        try:
            arborist_home = Path(git_toplevel()) / ".arborist"
        except Exception:
            arborist_home = Path.cwd() / ".arborist"
    return get_config(arborist_home if arborist_home.exists() else None)


def _default_repo() -> str:
    """Resolve git root of cwd, falling back to cwd."""
    try:
        return str(git_toplevel())
    except Exception:
        return "."


@click.group()
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    default="WARNING",
    help="Set logging verbosity",
)
def main(log_level):
    """Agent Arborist - Git-native task tree orchestration."""
    logging.basicConfig(
        level=log_level.upper(),
        format="%(levelname)s %(name)s: %(message)s",
    )


@main.command()
@click.option("--spec-dir", type=click.Path(exists=True, path_type=Path), default="spec")
@click.option("--output", "-o", type=click.Path(path_type=Path), default="task-tree.json",
              help="Output path for the task tree JSON file")
@click.option("--namespace", default=DEFAULT_NAMESPACE)
@click.option("--spec-id", default=None)
@click.option("--no-ai", is_flag=True, help="Disable AI planning; use markdown parser instead")
@click.option("--runner", default=None, help="Runner for AI planning (default: from config or 'claude')")
@click.option("--model", default=None, help="Model for AI planning (default: from config or 'opus')")
def build(spec_dir, output, namespace, spec_id, no_ai, runner, model):
    """Build a task tree from a spec directory and write it to a JSON file."""
    if spec_id is None:
        spec_id = spec_dir.name if spec_dir.name != "spec" else Path.cwd().resolve().name

    if no_ai:
        from agent_arborist.tree.spec_parser import parse_spec
        spec_files = list(spec_dir.glob("tasks*.md")) + list(spec_dir.glob("*.md"))
        if not spec_files:
            console.print(f"[red]Error:[/red] No markdown files found in {spec_dir}")
            sys.exit(1)
        tree = parse_spec(spec_files[0], spec_id=spec_id, namespace=namespace)
    else:
        from agent_arborist.tree.ai_planner import plan_tree, DAG_DEFAULT_RUNNER, DAG_DEFAULT_MODEL
        # Resolve runner/model: CLI flag > config > DAG defaults
        cfg = _load_config()
        resolved_runner = runner or cfg.defaults.runner or DAG_DEFAULT_RUNNER
        resolved_model = model or cfg.defaults.model or DAG_DEFAULT_MODEL
        console.print(f"[bold]Planning task tree with AI ({resolved_runner}/{resolved_model})...[/bold]")
        runner, model = resolved_runner, resolved_model
        result = plan_tree(
            spec_dir=spec_dir,
            spec_id=spec_id,
            namespace=namespace,
            runner_type=runner,
            model=model,
        )
        if not result.success:
            console.print(f"[red]Error:[/red] {result.error}")
            sys.exit(1)
        tree = result.tree

    # Compute execution order
    tree.compute_execution_order()

    # Write task tree JSON
    tree_path = Path(output).resolve()
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_text(json.dumps(tree.to_dict(), indent=2) + "\n")

    console.print(f"\n[bold]Task Tree: {spec_id}[/bold]")
    console.print(f"  Output: {tree_path}")
    console.print(f"  Nodes: {len(tree.nodes)}")
    console.print(f"  Leaves: {len(tree.leaves())}")
    console.print(f"  Execution order: {' -> '.join(tree.execution_order)}")

    _print_tree(tree)


@main.command()
@click.option("--tree", "tree_path", type=click.Path(exists=True, path_type=Path), required=True,
              help="Path to task-tree.json")
@click.option("--runner-type", "runner", default=None, help="Runner type (default: from config or 'claude')")
@click.option("--model", default=None, help="Model name (default: from config or 'sonnet')")
@click.option("--max-retries", default=DEFAULT_MAX_RETRIES, type=int)
@click.option("--test-command", default=None, help="Test command (default: from config or 'true')")
@click.option("--target-repo", type=click.Path(path_type=Path), default=None)
@click.option("--base-branch", default=None, help="Base branch (default: current branch)")
def garden(tree_path, runner, model, max_retries, test_command, target_repo, base_branch):
    """Execute a single task."""
    from agent_arborist.runner import get_runner
    from agent_arborist.worker.garden import garden as garden_fn

    cfg = _load_config()
    resolved_runner, resolved_model = get_step_runner_model(cfg, "run", runner, model)
    resolved_test_command = test_command or cfg.test.command or "true"

    target = target_repo.resolve() if target_repo else Path(_default_repo()).resolve()
    if base_branch is None:
        base_branch = git_current_branch(target)
    tree = _load_tree(tree_path)

    runner_instance = get_runner(resolved_runner, resolved_model)
    result = garden_fn(
        tree, target, runner_instance,
        test_command=resolved_test_command,
        max_retries=max_retries,
        base_branch=base_branch,
    )

    if result.success:
        console.print(f"[green]Task {result.task_id} completed.[/green]")
    else:
        console.print(f"[red]Failed:[/red] {result.error}")
        sys.exit(1)


@main.command()
@click.option("--tree", "tree_path", type=click.Path(exists=True, path_type=Path), required=True,
              help="Path to task-tree.json")
@click.option("--runner-type", "runner", default=None, help="Runner type (default: from config or 'claude')")
@click.option("--model", default=None, help="Model name (default: from config or 'sonnet')")
@click.option("--max-retries", default=DEFAULT_MAX_RETRIES, type=int)
@click.option("--test-command", default=None, help="Test command (default: from config or 'true')")
@click.option("--target-repo", type=click.Path(path_type=Path), default=None)
@click.option("--base-branch", default=None, help="Base branch (default: current branch)")
def gardener(tree_path, runner, model, max_retries, test_command, target_repo, base_branch):
    """Run the gardener loop to execute all tasks."""
    from agent_arborist.runner import get_runner
    from agent_arborist.worker.gardener import gardener as gardener_fn

    cfg = _load_config()
    resolved_runner, resolved_model = get_step_runner_model(cfg, "run", runner, model)
    resolved_test_command = test_command or cfg.test.command or "true"

    target = target_repo.resolve() if target_repo else Path(_default_repo()).resolve()
    if base_branch is None:
        base_branch = git_current_branch(target)
    tree = _load_tree(tree_path)

    runner_instance = get_runner(resolved_runner, resolved_model)
    result = gardener_fn(
        tree, target, runner_instance,
        test_command=resolved_test_command,
        max_retries=max_retries,
        base_branch=base_branch,
    )

    if result.success:
        console.print(f"[green]All tasks complete! {result.tasks_completed} tasks.[/green]")
        console.print(f"Order: {' -> '.join(result.order)}")
    else:
        console.print(f"[red]Failed:[/red] {result.error}")
        console.print(f"Completed {result.tasks_completed} tasks: {' -> '.join(result.order)}")
        sys.exit(1)


@main.command()
@click.option("--tree", "tree_path", type=click.Path(exists=True, path_type=Path), required=True,
              help="Path to task-tree.json")
@click.option("--target-repo", type=click.Path(path_type=Path), default=None)
def status(tree_path, target_repo):
    """Show current status of all tasks."""
    from agent_arborist.git.state import scan_completed_tasks, TaskState, get_task_trailers, task_state_from_trailers

    target = target_repo.resolve() if target_repo else Path(_default_repo()).resolve()
    tree = _load_tree(tree_path)

    rich_tree = RichTree(f"[bold]{tree.namespace}/{tree.spec_id}[/bold]")

    def _add_status_subtree(rich_node, node_id):
        node = tree.nodes[node_id]
        if node.is_leaf:
            phase_branch = tree.branch_name(node_id)
            trailers = get_task_trailers(phase_branch, node_id, target)
            state = task_state_from_trailers(trailers)
            icon = _status_icon(state)
            rich_node.add(f"{icon} [dim]{node.id}[/dim] {node.name} ({state.value})")
        else:
            branch = rich_node.add(f"[cyan]{node.id}[/cyan] {node.name}")
            for child_id in node.children:
                _add_status_subtree(branch, child_id)

    for root_id in tree.root_ids:
        _add_status_subtree(rich_tree, root_id)

    console.print(rich_tree)


def _load_tree(tree_path: Path):
    from agent_arborist.tree.model import TaskTree
    if not tree_path.exists():
        console.print(f"[red]Error:[/red] {tree_path} not found. Run 'arborist build' first.")
        sys.exit(1)
    return TaskTree.from_dict(json.loads(tree_path.read_text()))


def _print_tree(tree):
    rich_tree = RichTree(f"[bold]{tree.namespace}/{tree.spec_id}[/bold]")

    def _add_subtree(rich_node, node_id):
        node = tree.nodes[node_id]
        if node.is_leaf:
            rich_node.add(f"[dim]{node.id}[/dim] {node.name}")
        else:
            branch = rich_node.add(f"[cyan]{node.id}[/cyan] {node.name}")
            for child_id in node.children:
                _add_subtree(branch, child_id)

    for root_id in tree.root_ids:
        _add_subtree(rich_tree, root_id)
    console.print(rich_tree)


def _status_icon(state):
    from agent_arborist.git.state import TaskState
    icons = {
        TaskState.COMPLETE: "[green]OK[/green]",
        TaskState.IMPLEMENTING: "[yellow]...[/yellow]",
        TaskState.TESTING: "[yellow]...[/yellow]",
        TaskState.REVIEWING: "[yellow]...[/yellow]",
        TaskState.PENDING: "[dim]--[/dim]",
        TaskState.FAILED: "[red]FAIL[/red]",
    }
    return icons.get(state, "[dim]--[/dim]")
