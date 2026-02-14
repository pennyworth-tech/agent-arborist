"""CLI entry point for agent-arborist."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.tree import Tree as RichTree

from agent_arborist.constants import DEFAULT_NAMESPACE, DEFAULT_MAX_RETRIES


console = Console()


@click.group()
def main():
    """Agent Arborist - Git-native task tree orchestration."""
    pass


@main.command()
@click.option("--spec-dir", type=click.Path(exists=True, path_type=Path), default="spec")
@click.option("--target-repo", type=click.Path(path_type=Path), default=".")
@click.option("--namespace", default=DEFAULT_NAMESPACE)
@click.option("--spec-id", default=None)
@click.option("--ai", is_flag=True, help="Use AI to generate task tree from spec")
@click.option("--runner", default="claude", help="Runner for AI planning")
@click.option("--model", default="opus", help="Model for AI planning")
def build(spec_dir, target_repo, namespace, spec_id, ai, runner, model):
    """Build a task tree from a spec directory, compute execution order, and write task-tree.json."""
    from agent_arborist.git.repo import git_add_all, git_commit, GitError

    if spec_id is None:
        spec_id = spec_dir.name if spec_dir.name != "spec" else target_repo.resolve().name

    if ai:
        from agent_arborist.tree.ai_planner import plan_tree
        console.print(f"[bold]Planning task tree with AI ({runner}/{model})...[/bold]")
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
    else:
        from agent_arborist.tree.spec_parser import parse_spec
        spec_files = list(spec_dir.glob("tasks*.md")) + list(spec_dir.glob("*.md"))
        if not spec_files:
            console.print(f"[red]Error:[/red] No markdown files found in {spec_dir}")
            sys.exit(1)
        tree = parse_spec(spec_files[0], spec_id=spec_id, namespace=namespace)

    # Compute execution order
    tree.compute_execution_order()

    # Write task-tree.json
    target = target_repo.resolve()
    tree_path = target / "task-tree.json"
    tree_path.write_text(json.dumps(tree.to_dict(), indent=2) + "\n")

    console.print(f"\n[bold]Task Tree: {spec_id}[/bold]")
    console.print(f"  Nodes: {len(tree.nodes)}")
    console.print(f"  Leaves: {len(tree.leaves())}")
    console.print(f"  Execution order: {' -> '.join(tree.execution_order)}")

    _print_tree(tree)

    # Commit the tree file
    try:
        git_add_all(target)
        git_commit(f"arborist: build task tree for {spec_id}", target)
        console.print(f"[green]task-tree.json committed[/green]")
    except GitError as e:
        console.print(f"[yellow]Warning: could not commit task-tree.json: {e}[/yellow]")


@main.command()
@click.option("--spec-id", required=True)
@click.option("--runner-type", "runner", default="claude")
@click.option("--model", default="sonnet")
@click.option("--max-retries", default=DEFAULT_MAX_RETRIES, type=int)
@click.option("--test-command", default="true")
@click.option("--target-repo", type=click.Path(path_type=Path), default=".")
@click.option("--base-branch", default="main")
def garden(spec_id, runner, model, max_retries, test_command, target_repo, base_branch):
    """Execute a single task."""
    from agent_arborist.runner import get_runner
    from agent_arborist.worker.garden import garden as garden_fn

    target = target_repo.resolve()
    tree = _load_tree(target)

    runner_instance = get_runner(runner, model)
    result = garden_fn(
        tree, target, runner_instance,
        test_command=test_command,
        max_retries=max_retries,
        base_branch=base_branch,
    )

    if result.success:
        console.print(f"[green]Task {result.task_id} completed.[/green]")
    else:
        console.print(f"[red]Failed:[/red] {result.error}")
        sys.exit(1)


@main.command()
@click.option("--spec-id", required=True)
@click.option("--runner-type", "runner", default="claude")
@click.option("--model", default="sonnet")
@click.option("--max-retries", default=DEFAULT_MAX_RETRIES, type=int)
@click.option("--test-command", default="true")
@click.option("--target-repo", type=click.Path(path_type=Path), default=".")
@click.option("--base-branch", default="main")
def gardener(spec_id, runner, model, max_retries, test_command, target_repo, base_branch):
    """Run the gardener loop to execute all tasks."""
    from agent_arborist.runner import get_runner
    from agent_arborist.worker.gardener import gardener as gardener_fn

    target = target_repo.resolve()
    tree = _load_tree(target)

    runner_instance = get_runner(runner, model)
    result = gardener_fn(
        tree, target, runner_instance,
        test_command=test_command,
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
@click.option("--target-repo", type=click.Path(path_type=Path), default=".")
def status(target_repo):
    """Show current status of all tasks."""
    from agent_arborist.git.state import scan_completed_tasks, TaskState, get_task_trailers, task_state_from_trailers

    target = target_repo.resolve()
    tree = _load_tree(target)

    rich_tree = RichTree(f"[bold]{tree.namespace}/{tree.spec_id}[/bold]")

    for root_id in tree.root_ids:
        root = tree.nodes[root_id]
        branch = rich_tree.add(f"[cyan]{root.id}[/cyan] {root.name}")
        for child_id in root.children:
            child = tree.nodes[child_id]
            phase_branch = tree.branch_name(child_id)
            trailers = get_task_trailers(phase_branch, child_id, target)
            state = task_state_from_trailers(trailers)
            icon = _status_icon(state)
            branch.add(f"{icon} [dim]{child.id}[/dim] {child.name} ({state.value})")

    console.print(rich_tree)


def _load_tree(target: Path):
    from agent_arborist.tree.model import TaskTree
    tree_path = target / "task-tree.json"
    if not tree_path.exists():
        console.print("[red]Error:[/red] task-tree.json not found. Run 'arborist build' first.")
        sys.exit(1)
    return TaskTree.from_dict(json.loads(tree_path.read_text()))


def _print_tree(tree):
    rich_tree = RichTree(f"[bold]{tree.namespace}/{tree.spec_id}[/bold]")
    for root_id in tree.root_ids:
        root = tree.nodes[root_id]
        branch = rich_tree.add(f"[cyan]{root.id}[/cyan] {root.name}")
        for child_id in root.children:
            child = tree.nodes[child_id]
            branch.add(f"  [dim]{child.id}[/dim] {child.name}")
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
