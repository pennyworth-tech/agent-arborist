# Copyright 2026 Pennyworth Technologies, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""CLI entry point for agent-arborist."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.tree import Tree as RichTree

from agent_arborist.config import (
    get_config, get_step_runner_model, ArboristConfig,
    VALID_RUNNERS, generate_config_template,
)
from agent_arborist.git.repo import (
    git_current_branch, git_toplevel, spec_id_from_branch,
)


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


def _resolve_container_workspace(
    cli_mode: str | None, cfg: ArboristConfig, target: Path,
) -> Path | None:
    """Resolve container mode and return workspace path or None."""
    from agent_arborist.devcontainer import should_use_container
    resolved_mode = cli_mode or cfg.defaults.container_mode
    if should_use_container(resolved_mode, target):
        return target
    return None


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
def init():
    """Initialize .arborist/ directory with config and logs."""
    try:
        root = Path(git_toplevel())
    except Exception:
        root = Path.cwd()

    arborist_dir = root / ".arborist"
    config_path = arborist_dir / "config.json"
    # --- .arborist/ directory ---
    if arborist_dir.exists():
        console.print(f"[dim].arborist/ already exists at {arborist_dir}[/dim]")
    else:
        if click.confirm("Create .arborist/ directory?", default=True):
            arborist_dir.mkdir(parents=True)
            console.print(f"[green]Created[/green] {arborist_dir}")
        else:
            console.print("[yellow]Aborted.[/yellow]")
            return

    # --- config.json ---
    if config_path.exists():
        console.print(f"[dim]config.json already exists at {config_path}[/dim]")
    else:
        # Ask for default runner/model
        runner_choices = list(VALID_RUNNERS)
        console.print("\n[bold]Default runner/model for this project:[/bold]")
        runner = click.prompt(
            "  Runner",
            type=click.Choice(runner_choices, case_sensitive=False),
            default="claude",
        )
        default_models = {
            "claude": "sonnet",
            "gemini": "gemini-2.5-flash",
            "opencode": "cerebras/zai-glm-4.7",
        }
        model = click.prompt(
            "  Model",
            default=default_models.get(runner, ""),
        )

        template = generate_config_template()
        # Strip _comment keys for a clean project config
        config_data = {
            "version": "1",
            "defaults": {
                "runner": runner,
                "model": model,
            },
            "steps": {
                "run": {"runner": None, "model": None},
                "implement": {"runner": None, "model": None},
                "review": {"runner": None, "model": None},
                "post-merge": {"runner": None, "model": None},
            },
        }

        if click.confirm(f"\nWrite config to {config_path}?", default=True):
            config_path.write_text(json.dumps(config_data, indent=2) + "\n")
            console.print(f"[green]Created[/green] {config_path}")
        else:
            console.print("[yellow]Skipped config.json[/yellow]")

    console.print("\n[bold]Done.[/bold] You can edit .arborist/config.json to customize further.")


@main.command()
@click.option("--spec-dir", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None,
              help="Output path (default: openspec/changes/<spec_id>/task-tree.json)")
@click.option("--no-ai", is_flag=True, help="Disable AI planning; use markdown parser instead")
@click.option("--runner", default=None, help="Runner for AI planning (default: from config or 'claude')")
@click.option("--model", default=None, help="Model for AI planning (default: from config or 'opus')")
@click.option("--container-mode", "-c", "container_mode", default=None,
              type=click.Choice(["auto", "enabled", "disabled"]),
              help="Container mode for AI planning (default: from config or 'auto')")
def build(spec_dir, output, no_ai, runner, model, container_mode):
    """Build a task tree from a spec directory and write it to a JSON file."""
    branch = git_current_branch(Path.cwd())
    spec_id = spec_id_from_branch(branch)
    if spec_dir is None:
        spec_dir = Path("openspec") / "changes" / spec_id
    if output is None:
        output = Path("openspec") / "changes" / spec_id / "task-tree.json"
    if no_ai:
        from agent_arborist.tree.spec_parser import parse_spec
        spec_files = list(spec_dir.glob("tasks*.md")) + list(spec_dir.glob("*.md"))
        if not spec_files:
            console.print(f"[red]Error:[/red] No markdown files found in {spec_dir}")
            sys.exit(1)
        tree = parse_spec(spec_files[0])
    else:
        from agent_arborist.tree.ai_planner import plan_tree, DAG_DEFAULT_RUNNER, DAG_DEFAULT_MODEL
        # Resolve runner/model: CLI flag > config > DAG defaults
        cfg = _load_config()
        resolved_runner = runner or cfg.defaults.runner or DAG_DEFAULT_RUNNER
        resolved_model = model or cfg.defaults.model or DAG_DEFAULT_MODEL
        console.print(f"[bold]Planning task tree with AI ({resolved_runner}/{resolved_model})...[/bold]")
        runner, model = resolved_runner, resolved_model
        target = Path.cwd().resolve()
        container_ws = _resolve_container_workspace(container_mode, cfg, target)
        result = plan_tree(
            spec_dir=spec_dir,
            runner_type=runner,
            model=model,
            timeout=cfg.timeouts.runner_timeout,
            container_workspace=container_ws,
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

    console.print(f"\n[bold]Task Tree: {Path(output).stem}[/bold]")
    console.print(f"  Output: {tree_path}")
    console.print(f"  Nodes: {len(tree.nodes)}")
    console.print(f"  Leaves: {len(tree.leaves())}")
    console.print(f"  Execution order: {' -> '.join(tree.execution_order)}")

    _print_tree(tree)


@main.command()
@click.option("--tree", "tree_path", type=click.Path(exists=True, path_type=Path), default=None,
              help="Path to task-tree.json (default: openspec/changes/<spec_id>/task-tree.json)")
@click.option("--runner-type", "runner", default=None, help="Runner type (default: from config or 'claude')")
@click.option("--model", default=None, help="Model name (default: from config or 'sonnet')")
@click.option("--max-retries", default=None, type=int, help="Max retries per task (default: from config or 5)")
@click.option("--target-repo", type=click.Path(path_type=Path), default=None)
@click.option("--base-branch", default=None, help="Git branch to derive spec_id from (default: current branch)")
@click.option("--report-dir", type=click.Path(path_type=Path), default=None,
              help="Directory for report JSON files (default: next to task tree)")
@click.option("--log-dir", type=click.Path(path_type=Path), default=None,
              help="Directory for runner log files (default: next to task tree)")
@click.option("--container-mode", "-c", "container_mode", default=None,
              type=click.Choice(["auto", "enabled", "disabled"]),
              help="Container mode (default: from config or 'auto')")
def garden(tree_path, runner, model, max_retries, target_repo, base_branch, report_dir, log_dir, container_mode):
    """Execute a single task."""
    from agent_arborist.runner import get_runner
    from agent_arborist.worker.garden import garden as garden_fn

    cfg = _load_config()
    impl_runner_name, impl_model = get_step_runner_model(cfg, "implement", runner, model, fallback_step="run")
    rev_runner_name, rev_model = get_step_runner_model(cfg, "review", runner, model, fallback_step="run")
    resolved_max_retries = max_retries if max_retries is not None else cfg.defaults.max_retries

    target = target_repo.resolve() if target_repo else Path(_default_repo()).resolve()
    if base_branch is None:
        base_branch = git_current_branch(target)
    spec_id = spec_id_from_branch(base_branch)
    if tree_path is None:
        tree_path = Path("openspec") / "changes" / spec_id / "task-tree.json"
    tree = _load_tree(tree_path)

    if report_dir is None:
        report_dir = tree_path.resolve().parent / "reports"
    if log_dir is None:
        log_dir = tree_path.resolve().parent / "logs"

    impl_runner_instance = get_runner(impl_runner_name, impl_model)
    rev_runner_instance = get_runner(rev_runner_name, rev_model)
    resolved_test_timeout = cfg.test.timeout or cfg.timeouts.test_command
    container_ws = _resolve_container_workspace(container_mode, cfg, target)
    result = garden_fn(
        tree, target,
        implement_runner=impl_runner_instance,
        review_runner=rev_runner_instance,
        test_command="true",
        max_retries=resolved_max_retries,
        report_dir=Path(report_dir).resolve(),
        log_dir=Path(log_dir).resolve(),
        runner_timeout=cfg.timeouts.runner_timeout,
        test_timeout=resolved_test_timeout,
        container_workspace=container_ws,
        container_up_timeout=cfg.timeouts.container_up,
        container_check_timeout=cfg.timeouts.container_check,
        spec_id=spec_id,
    )

    if result.success:
        console.print(f"[green]Task {result.task_id} completed.[/green]")
    else:
        console.print(f"[red]Failed:[/red] {result.error}")
        sys.exit(1)


@main.command()
@click.option("--tree", "tree_path", type=click.Path(exists=True, path_type=Path), default=None,
              help="Path to task-tree.json (default: openspec/changes/<spec_id>/task-tree.json)")
@click.option("--runner-type", "runner", default=None, help="Runner type (default: from config or 'claude')")
@click.option("--model", default=None, help="Model name (default: from config or 'sonnet')")
@click.option("--max-retries", default=None, type=int, help="Max retries per task (default: from config or 5)")
@click.option("--target-repo", type=click.Path(path_type=Path), default=None)
@click.option("--base-branch", default=None, help="Git branch to derive spec_id from (default: current branch)")
@click.option("--report-dir", type=click.Path(path_type=Path), default=None,
              help="Directory for report JSON files (default: next to task tree)")
@click.option("--log-dir", type=click.Path(path_type=Path), default=None,
              help="Directory for runner log files (default: next to task tree)")
@click.option("--container-mode", "-c", "container_mode", default=None,
              type=click.Choice(["auto", "enabled", "disabled"]),
              help="Container mode (default: from config or 'auto')")
def gardener(tree_path, runner, model, max_retries, target_repo, base_branch, report_dir, log_dir, container_mode):
    """Run the gardener loop to execute all tasks."""
    from agent_arborist.runner import get_runner
    from agent_arborist.worker.gardener import gardener as gardener_fn

    cfg = _load_config()
    impl_runner_name, impl_model = get_step_runner_model(cfg, "implement", runner, model, fallback_step="run")
    rev_runner_name, rev_model = get_step_runner_model(cfg, "review", runner, model, fallback_step="run")
    resolved_max_retries = max_retries if max_retries is not None else cfg.defaults.max_retries

    target = target_repo.resolve() if target_repo else Path(_default_repo()).resolve()
    if base_branch is None:
        base_branch = git_current_branch(target)
    spec_id = spec_id_from_branch(base_branch)
    if tree_path is None:
        tree_path = Path("openspec") / "changes" / spec_id / "task-tree.json"
    tree = _load_tree(tree_path)

    if report_dir is None:
        report_dir = tree_path.resolve().parent / "reports"
    if log_dir is None:
        log_dir = tree_path.resolve().parent / "logs"

    resolved_test_timeout = cfg.test.timeout or cfg.timeouts.test_command
    impl_runner_instance = get_runner(impl_runner_name, impl_model)
    rev_runner_instance = get_runner(rev_runner_name, rev_model)
    container_ws = _resolve_container_workspace(container_mode, cfg, target)
    result = gardener_fn(
        tree, target,
        implement_runner=impl_runner_instance,
        review_runner=rev_runner_instance,
        test_command="true",
        max_retries=resolved_max_retries,
        report_dir=Path(report_dir).resolve(),
        log_dir=Path(log_dir).resolve(),
        runner_timeout=cfg.timeouts.runner_timeout,
        test_timeout=resolved_test_timeout,
        container_workspace=container_ws,
        container_up_timeout=cfg.timeouts.container_up,
        container_check_timeout=cfg.timeouts.container_check,
        spec_id=spec_id,
    )

    if result.success:
        console.print(f"[green]All tasks complete! {result.tasks_completed} tasks.[/green]")
        console.print(f"Order: {' -> '.join(result.order)}")
    else:
        console.print(f"[red]Failed:[/red] {result.error}")
        console.print(f"Completed {result.tasks_completed} tasks: {' -> '.join(result.order)}")
        sys.exit(1)


@main.command()
@click.option("--tree", "tree_path", type=click.Path(exists=True, path_type=Path), default=None,
              help="Path to task-tree.json (default: openspec/changes/<spec_id>/task-tree.json)")
@click.option("--target-repo", type=click.Path(path_type=Path), default=None)
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text",
              help="Output format (text or json)")
def status(tree_path, target_repo, output_format):
    """Show current status of all tasks."""
    from agent_arborist.git.state import scan_completed_tasks, get_task_trailers, task_state_from_trailers

    target = target_repo.resolve() if target_repo else Path(_default_repo()).resolve()
    branch = git_current_branch(target)
    spec_id = spec_id_from_branch(branch)
    if tree_path is None:
        tree_path = Path("openspec") / "changes" / spec_id / "task-tree.json"
    tree = _load_tree(tree_path)

    completed = scan_completed_tasks(tree, target, spec_id=spec_id)

    if output_format == "json":
        status_data = {
            "tree": tree.to_dict(),
            "branch": branch,
            "completed": list(completed),
            "tasks": {}
        }

        for node_id, node in tree.nodes.items():
            if node.is_leaf:
                trailers = get_task_trailers("HEAD", node_id, target, spec_id=spec_id)
                state = task_state_from_trailers(trailers)
                status_data["tasks"][node_id] = {
                    "id": node.id,
                    "name": node.name,
                    "state": state.value,
                    "trailers": trailers
                }

        print(json.dumps(status_data, indent=2, ensure_ascii=False))
    else:
        rich_tree = RichTree("[bold]Task Tree[/bold]")

        def _add_status_subtree(rich_node, node_id):
            node = tree.nodes[node_id]
            if node.is_leaf:
                trailers = get_task_trailers("HEAD", node_id, target, spec_id=spec_id)
                state = task_state_from_trailers(trailers)
                icon = _status_icon(state)
                rich_node.add(f"{icon} [dim]{node.id}[/dim] {node.name} ({state.value})")
            else:
                branch_node = rich_node.add(f"[cyan]{node.id}[/cyan] {node.name}")
                for child_id in node.children:
                    _add_status_subtree(branch_node, child_id)

        for root_id in tree.root_ids:
            _add_status_subtree(rich_tree, root_id)

        console.print(rich_tree)


@main.command()
@click.option("--tree", "tree_path", type=click.Path(exists=True, path_type=Path), default=None,
              help="Path to task-tree.json (default: openspec/changes/<spec_id>/task-tree.json)")
@click.option("--task-id", required=True, help="Task ID to inspect (e.g. T003)")
@click.option("--target-repo", type=click.Path(path_type=Path), default=None)
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text",
              help="Output format (text or json)")
def inspect(tree_path, task_id, target_repo, output_format):
    """Deep-dive into a single task: metadata, commit history, trailers, and state."""
    from agent_arborist.git.repo import git_log
    from agent_arborist.git.state import get_task_trailers, task_state_from_trailers

    target = target_repo.resolve() if target_repo else Path(_default_repo()).resolve()
    branch = git_current_branch(target)
    spec_id = spec_id_from_branch(branch)
    if tree_path is None:
        tree_path = Path("openspec") / "changes" / spec_id / "task-tree.json"
    tree = _load_tree(tree_path)

    if task_id not in tree.nodes:
        console.print(f"[red]Error:[/red] Task '{task_id}' not found in tree.")
        console.print(f"Available tasks: {', '.join(sorted(tree.nodes.keys()))}")
        sys.exit(1)

    node = tree.nodes[task_id]

    if output_format == "json":
        inspect_data = {
            "task": {
                "id": node.id,
                "name": node.name,
                "description": node.description,
                "is_leaf": node.is_leaf,
                "parent": node.parent,
                "children": node.children,
                "depends_on": node.depends_on,
                "test_commands": [tc.to_dict() for tc in node.test_commands],
            },
            "state": None,
            "trailers": {}
        }

        trailers = get_task_trailers("HEAD", task_id, target, spec_id=spec_id)
        state = task_state_from_trailers(trailers)
        inspect_data["state"] = state.value
        inspect_data["trailers"] = trailers

        if trailers:
            grep_pattern = f"task({spec_id}@{task_id}"
            try:
                log_output = git_log(
                    "HEAD",
                    "%h %s%n%(trailers:key=Arborist-Step,key=Arborist-Result,key=Arborist-Test,key=Arborist-Review,key=Arborist-Retry,key=Arborist-Test-Type,key=Arborist-Test-Passed,key=Arborist-Test-Failed,key=Arborist-Test-Runtime)",
                    target,
                    n=50,
                    grep=grep_pattern,
                    fixed_strings=True,
                )
                inspect_data["commits"] = [
                    line.strip() for line in log_output.split("\n") if line.strip()
                ]
            except GitError:
                inspect_data["commits"] = []

        print(json.dumps(inspect_data, indent=2))
    else:
        # --- Task metadata ---
        console.print(f"\n[bold]Task: {task_id}[/bold] — {node.name}")
        if node.description:
            console.print(f"  Description: {node.description}")
        console.print(f"  Leaf: {node.is_leaf}")
        if node.parent:
            console.print(f"  Parent: {node.parent}")
        if node.children:
            console.print(f"  Children: {', '.join(node.children)}")
        if node.depends_on:
            console.print(f"  Depends on: {', '.join(node.depends_on)}")

        if node.test_commands:
            console.print("  Test commands:")
            for tc in node.test_commands:
                fw = f" ({tc.framework})" if tc.framework else ""
                to = f" timeout={tc.timeout}s" if tc.timeout else ""
                console.print(f"    [{tc.type.value}] {tc.command}{fw}{to}")

        # Current state from most recent trailer
        grep_pattern = f"task({spec_id}@{task_id}"
        trailers = get_task_trailers("HEAD", task_id, target, spec_id=spec_id)
        state = task_state_from_trailers(trailers)
        if not trailers:
            console.print("\n[dim]No commits found for this task (not started).[/dim]")
            return

        console.print(f"\n[bold]State:[/bold] {state.value}")
        if trailers:
            console.print("[bold]Latest trailers:[/bold]")
            for key, val in trailers.items():
                console.print(f"  {key}: {val}")

        # --- Full commit history for this task ---
        console.print(f"\n[bold]Commit history[/bold] (grep: {grep_pattern})")
        try:
            log_output = git_log(
                "HEAD",
                "%h %s%n%(trailers:key=Arborist-Step,key=Arborist-Result,key=Arborist-Test,key=Arborist-Review,key=Arborist-Retry,key=Arborist-Test-Type,key=Arborist-Test-Passed,key=Arborist-Test-Failed,key=Arborist-Test-Runtime)",
                target,
                n=50,
                grep=grep_pattern,
                fixed_strings=True,
            )
            if log_output.strip():
                for line in log_output.split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("Arborist-"):
                        console.print(f"    [dim]{line}[/dim]")
                    else:
                        console.print(f"  [cyan]{line}[/cyan]")
            else:
                console.print("  [dim]No commits found for this task.[/dim]")
        except GitError:
            console.print("  [dim]No commits found for this task.[/dim]")

        console.print()


@main.command()
@click.option("--tree", "tree_path", type=click.Path(exists=True, path_type=Path), default=None,
              help="Path to task-tree.json (default: openspec/changes/<spec_id>/task-tree.json)")
@click.option("--report-dir", type=click.Path(path_type=Path), default=None,
              help="Directory for reports (default: next to task tree)")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text",
              help="Output format (text or json)")
@click.option("--task-id", help="Filter by specific task ID")
def reports(tree_path, report_dir, output_format, task_id):
    """List task execution reports."""
    target = Path(_default_repo()).resolve()
    branch = git_current_branch(target)
    spec_id = spec_id_from_branch(branch)

    if tree_path is None:
        tree_path = Path("openspec") / "changes" / spec_id / "task-tree.json"

    tree_path = Path(tree_path).resolve()
    if report_dir is None:
        report_dir = tree_path.parent / "reports"

    report_dir = Path(report_dir).resolve()

    if not report_dir.exists():
        if output_format == "json":
            print(json.dumps({"reports": [], "summary": {"total": 0, "passed": 0, "failed": 0, "avg_retries": 0}}, indent=2))
        else:
            console.print("[yellow]No reports directory found[/yellow]")
        return

    all_reports = []
    for fname in sorted(report_dir.glob("*.json")):
        try:
            data = json.loads(fname.read_text())
            if task_id is None or data.get("task_id") == task_id:
                all_reports.append(data)
        except Exception:
            pass

    summary = {
        "total": len(all_reports),
        "passed": sum(1 for r in all_reports if r.get("result") == "pass"),
        "failed": sum(1 for r in all_reports if r.get("result") == "fail"),
        "avg_retries": round(sum(r.get("retries", 0) for r in all_reports) / len(all_reports), 2) if all_reports else 0
    }

    if output_format == "json":
        print(json.dumps({"reports": all_reports, "summary": summary}, indent=2))
    else:
        console.print(f"\n[bold]Reports[/bold] ({summary['total']} total)")
        console.print(f"  Passed: {summary['passed']} | Failed: {summary['failed']} | Avg Retries: {summary['avg_retries']}")
        console.print()
        for r in all_reports:
            icon = "[green]✓[/green]" if r.get("result") == "pass" else "[red]✗[/red]"
            retries_str = f" ({r.get('retries', 0)} retries)" if r.get('retries', 0) > 0 else ""
            console.print(f"  {icon} {r.get('task_id', 'unknown')} - {r.get('completed_at', 'unknown')}{retries_str}")


@main.command()
@click.option("--tree", "tree_path", type=click.Path(exists=True, path_type=Path), default=None,
              help="Path to task-tree.json (default: openspec/changes/<spec_id>/task-tree.json)")
@click.option("--log-dir", type=click.Path(path_type=Path), default=None,
              help="Directory for logs (default: next to task tree)")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text",
              help="Output format (text or json)")
@click.option("--task-id", help="Filter by specific task ID")
@click.option("--show", "show_file", default=None, help="Show content of a specific log file")
def logs(tree_path, log_dir, output_format, task_id, show_file):
    """List task execution history (commits + log files)."""
    from agent_arborist.git.state import get_task_commit_history
    from agent_arborist.tree.model import TaskTree

    target = Path(_default_repo()).resolve()
    branch = git_current_branch(target)
    spec_id = spec_id_from_branch(branch)

    if tree_path is None:
        tree_path = Path("openspec") / "changes" / spec_id / "task-tree.json"

    tree_path = Path(tree_path).resolve()

    if log_dir is None:
        log_dir = tree_path.parent / "logs"
    log_dir = Path(log_dir).resolve()

    # --show: print a specific log file and exit
    if show_file:
        log_file = (log_dir / show_file).resolve()
        if not str(log_file).startswith(str(log_dir)):
            console.print("[red]Access denied[/red]")
            sys.exit(1)
        if not log_file.exists():
            console.print(f"[red]Log file not found:[/red] {show_file}")
            sys.exit(1)
        print(log_file.read_text())
        return

    tree = TaskTree.from_dict(json.loads(tree_path.read_text()))

    # Gather commit history per task
    commits_by_task = {}
    for node in tree.leaves():
        tid = node.id
        if task_id is not None and tid != task_id:
            continue
        commits = get_task_commit_history(tid, target, spec_id=spec_id)
        if commits:
            commits_by_task[tid] = commits

    # Gather log files per task by searching for files matching known task IDs
    from agent_arborist.dashboard.logs import scan_log_files

    leaf_ids = [n.id for n in tree.leaves()]
    if task_id is not None:
        leaf_ids = [tid for tid in leaf_ids if tid == task_id]
    files_by_task = scan_log_files(log_dir, leaf_ids)

    # Merge task IDs from both sources
    all_task_ids = sorted(set(commits_by_task) | set(files_by_task))

    summary = {
        "total_tasks": len(all_task_ids),
        "total_commits": sum(len(c) for c in commits_by_task.values()),
        "total_files": sum(len(f) for f in files_by_task.values()),
        "phase_counts": {
            "implement": sum(1 for cs in commits_by_task.values() for c in cs if c["step"] == "implement"),
            "review": sum(1 for cs in commits_by_task.values() for c in cs if c["step"] == "review"),
            "test": sum(1 for cs in commits_by_task.values() for c in cs if c["step"] == "test"),
        }
    }

    if output_format == "json":
        print(json.dumps({
            "commits": commits_by_task,
            "files": files_by_task,
            "summary": summary,
        }, indent=2))
    else:
        console.print(f"\n[bold]Logs[/bold] ({summary['total_tasks']} tasks, {summary['total_commits']} commits, {summary['total_files']} log files)")
        console.print(f"  Implement: {summary['phase_counts']['implement']} | Review: {summary['phase_counts']['review']} | Test: {summary['phase_counts']['test']}")
        console.print()
        for tid in all_task_ids:
            commits = commits_by_task.get(tid, [])
            files = files_by_task.get(tid, [])
            console.print(f"  [cyan]{tid}[/cyan] ({len(commits)} commits, {len(files)} log files)")
            for c in commits:
                # Determine result: use step-specific trailer values
                step = c.get("step", "")
                trailers = c.get("trailers", {})
                result = c.get("result", "")
                # For test/review, check their specific trailer
                if step == "test":
                    result = trailers.get("Arborist-Test", result)
                elif step == "review":
                    rv = trailers.get("Arborist-Review", "")
                    result = "pass" if rv == "approved" else "fail" if rv == "rejected" else result

                if result == "pass" or result == "approved":
                    result_icon = "[green]✓[/green]"
                elif result == "fail" or result == "rejected":
                    result_icon = "[red]✗[/red]"
                else:
                    result_icon = " "

                # Strip the task(...): prefix from subjects
                subject = c['subject']
                if "): " in subject:
                    subject = subject.split("): ", 1)[1]
                console.print(f"    {result_icon} {step:10s} {c['sha']}  {subject[:60]}")
            if files:
                console.print(f"    [dim]Log files:[/dim]")
                for f in files:
                    size_kb = round(f["size"] / 1024, 1)
                    console.print(f"      {f['phase']:10s} {f['timestamp']}  {f['filename']} ({size_kb} KB)")
                    console.print(f"      [dim]  arborist logs --tree {tree_path} --show {f['filename']}[/dim]")


@main.command()
@click.option("--tree", "tree_path", type=click.Path(exists=True, path_type=Path), default=None,
              help="Path to task-tree.json")
@click.option("--port", type=int, default=8484,
              help="Port for dashboard server (default: 8484)")
@click.option("--report-dir", type=click.Path(path_type=Path), default=None,
              help="Directory for reports (default: next to task tree)")
@click.option("--log-dir", type=click.Path(path_type=Path), default=None,
              help="Directory for logs (default: next to task tree)")
def dashboard(tree_path, port, report_dir, log_dir):
    """Start read-only monitoring dashboard for task execution."""
    from agent_arborist.dashboard.server import start_dashboard

    target = Path(_default_repo()).resolve()
    branch = git_current_branch(target)
    spec_id = spec_id_from_branch(branch)

    if tree_path is None:
        tree_path = Path("openspec") / "changes" / spec_id / "task-tree.json"

    tree_path = Path(tree_path).resolve()
    if not tree_path.exists():
        console.print(f"[red]Error:[/red] {tree_path} not found")
        sys.exit(1)

    start_dashboard(tree_path, report_dir, log_dir, port)


def _load_tree(tree_path: Path):
    from agent_arborist.tree.model import TaskTree
    if not tree_path.exists():
        console.print(f"[red]Error:[/red] {tree_path} not found. Run 'arborist build' first.")
        sys.exit(1)
    return TaskTree.from_dict(json.loads(tree_path.read_text()))


def _print_tree(tree):
    rich_tree = RichTree(f"[bold]Task Tree[/bold]")

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
