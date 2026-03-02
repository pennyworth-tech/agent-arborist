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

"""Gardener loop — runs garden() repeatedly until all tasks are done or stalled."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

from agent_arborist.git.state import get_run_start_sha, scan_completed_tasks
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
    container_up_timeout: int | None = None,
    container_check_timeout: int | None = None,
    spec_id: str,
) -> GardenerResult:
    """Run tasks in order until all complete or stalled."""
    result = GardenerResult(success=False)
    all_leaves = {n.id for n in tree.leaves()}

    # Create run-start marker once for the entire gardener run
    run_start_sha = get_run_start_sha(cwd, spec_id=spec_id)

    while True:
        completed = scan_completed_tasks(tree, cwd, spec_id=spec_id)
        logger.debug("Completed tasks: %s", completed)

        # All done?
        if all_leaves <= completed:
            result.success = True
            return result

        # Any ready task?
        next_task = find_next_task(tree, cwd, spec_id=spec_id)
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
            container_up_timeout=container_up_timeout,
            container_check_timeout=container_check_timeout,
            spec_id=spec_id,
            run_start_sha=run_start_sha,
        )

        if gr.success:
            result.tasks_completed += 1
            result.order.append(gr.task_id)
        else:
            logger.info("Task %s failed, stopping gardener", gr.task_id)
            result.error = f"task {gr.task_id} failed: {gr.error}"
            return result
