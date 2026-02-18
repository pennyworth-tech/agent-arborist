"""Gardener loop — runs garden() repeatedly until all tasks are done or stalled."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

from agent_arborist.git.state import scan_completed_tasks
from agent_arborist.tree.model import TaskTree
from agent_arborist.worker.garden import garden, find_next_task


@dataclass
class GardenerResult:
    success: bool
    tasks_completed: int = 0
    order: list[str] = field(default_factory=list)
    error: str | None = None


def gardener(
    tree: TaskTree,
    cwd: Path,
    runner=None,
    *,
    implement_runner=None,
    review_runner=None,
    test_command: str = "true",
    max_retries: int = 3,
    report_dir: Path | None = None,
    log_dir: Path | None = None,
    runner_timeout: int | None = None,
    test_timeout: int | None = None,
    container_workspace: Path | None = None,
    branch: str,
) -> GardenerResult:
    """Run tasks in order until all complete or stalled."""
    result = GardenerResult(success=False)
    all_leaves = {n.id for n in tree.leaves()}

    while True:
        completed = scan_completed_tasks(tree, cwd, branch=branch)
        logger.debug("Completed tasks: %s", completed)

        # All done?
        if all_leaves <= completed:
            result.success = True
            return result

        # Any ready task?
        next_task = find_next_task(tree, cwd, branch=branch)
        if next_task is None:
            logger.info("Stalled: no ready tasks")
            result.error = "stalled: no ready tasks"
            return result

        logger.info("[%d/%d] Running task %s", result.tasks_completed + 1, len(all_leaves), next_task.id)
        gr = garden(
            tree, cwd, runner,
            implement_runner=implement_runner,
            review_runner=review_runner,
            test_command=test_command,
            max_retries=max_retries,
            report_dir=report_dir,
            log_dir=log_dir,
            runner_timeout=runner_timeout,
            test_timeout=test_timeout,
            container_workspace=container_workspace,
            branch=branch,
        )

        if gr.success:
            result.tasks_completed += 1
            result.order.append(gr.task_id)
        else:
            logger.info("Task %s failed, stopping gardener", gr.task_id)
            result.error = f"task {gr.task_id} failed: {gr.error}"
            return result
