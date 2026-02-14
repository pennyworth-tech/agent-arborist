"""Gardener loop — runs garden() repeatedly until all tasks are done or stalled."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agent_arborist.git.repo import git_checkout, git_merge
from agent_arborist.git.state import scan_completed_tasks
from agent_arborist.tree.model import TaskTree
from agent_arborist.worker.garden import garden, find_next_task, GardenResult


@dataclass
class GardenerResult:
    success: bool
    tasks_completed: int = 0
    order: list[str] = field(default_factory=list)
    error: str | None = None


def _check_phase_complete(tree: TaskTree, task_id: str, completed: set[str]) -> str | None:
    """If all siblings of task_id's phase are complete, return the phase branch name."""
    node = tree.nodes[task_id]
    if not node.parent:
        return None
    parent = tree.nodes[node.parent]
    if all(c in completed for c in parent.children):
        return tree.branch_name(node.parent)
    return None


def gardener(
    tree: TaskTree,
    cwd: Path,
    runner,
    *,
    test_command: str = "true",
    max_retries: int = 3,
    base_branch: str = "main",
) -> GardenerResult:
    """Run tasks in order until all complete or stalled."""
    result = GardenerResult(success=False)
    all_leaves = {n.id for n in tree.leaves()}
    max_failures = len(all_leaves)  # prevent infinite loop
    failures = 0

    while True:
        completed = scan_completed_tasks(tree, cwd)

        # All done?
        if all_leaves <= completed:
            result.success = True
            return result

        # Any ready task?
        next_task = find_next_task(tree, cwd)
        if next_task is None:
            result.error = "stalled: no ready tasks"
            return result

        gr = garden(
            tree, cwd, runner,
            test_command=test_command,
            max_retries=max_retries,
            base_branch=base_branch,
        )

        if gr.success:
            result.tasks_completed += 1
            result.order.append(gr.task_id)

            # Check phase completion → merge
            new_completed = scan_completed_tasks(tree, cwd)
            phase_branch = _check_phase_complete(tree, gr.task_id, new_completed)
            if phase_branch:
                git_checkout(base_branch, cwd)
                git_merge(phase_branch, cwd, message=f"merge: {phase_branch} complete")
        else:
            failures += 1
            if failures >= max_failures:
                result.error = f"too many failures ({failures})"
                return result
