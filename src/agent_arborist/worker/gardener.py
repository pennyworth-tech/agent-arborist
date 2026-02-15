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
    runner,
    *,
    test_command: str = "true",
    max_retries: int = 3,
    base_branch: str = "main",
    report_dir: Path | None = None,
    log_dir: Path | None = None,
) -> GardenerResult:
    """Run tasks in order until all complete or stalled."""
    result = GardenerResult(success=False)
    all_leaves = {n.id for n in tree.leaves()}
    max_failures = len(all_leaves)  # prevent infinite loop
    failures = 0

    while True:
        completed = scan_completed_tasks(tree, cwd)
        logger.debug("Completed tasks: %s", completed)

        # All done?
        if all_leaves <= completed:
            result.success = True
            return result

        # Any ready task?
        next_task = find_next_task(tree, cwd)
        if next_task is None:
            logger.info("Stalled: no ready tasks")
            result.error = "stalled: no ready tasks"
            return result

        logger.info("[%d/%d] Running task %s", result.tasks_completed + 1, len(all_leaves), next_task.id)
        gr = garden(
            tree, cwd, runner,
            test_command=test_command,
            max_retries=max_retries,
            base_branch=base_branch,
            report_dir=report_dir,
            log_dir=log_dir,
        )

        if gr.success:
            result.tasks_completed += 1
            result.order.append(gr.task_id)
        else:
            failures += 1
            logger.info("Task %s failed (%d failures so far)", gr.task_id, failures)
            if failures >= max_failures:
                result.error = f"too many failures ({failures})"
                return result
