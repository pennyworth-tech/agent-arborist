"""Read trailers from git commits to determine task state."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from agent_arborist.constants import (
    TRAILER_STEP,
    TRAILER_RESULT,
    TRAILER_TEST,
    TRAILER_REVIEW,
    TRAILER_RETRY,
    TRAILER_REPORT,
)
from agent_arborist.git.repo import git_log, GitError


class TaskState(Enum):
    PENDING = "pending"
    IMPLEMENTING = "implementing"
    TESTING = "testing"
    REVIEWING = "reviewing"
    COMPLETE = "complete"
    FAILED = "failed"


def get_task_trailers(branch: str, task_id: str, cwd: Path) -> dict[str, str]:
    """Get the most recent trailers for a task on a branch."""
    try:
        out = git_log(
            branch,
            "%(trailers)",
            cwd,
            n=1,
            grep=f"task({task_id}):",
        )
    except GitError:
        return {}

    if not out.strip():
        return {}

    # Parse trailers from the most recent matching commit
    trailers: dict[str, str] = {}
    for line in out.split("\n"):
        line = line.strip()
        if ": " in line:
            key, _, val = line.partition(": ")
            if key.startswith("Arborist-"):
                trailers[key] = val.strip()
    return trailers


def task_state_from_trailers(trailers: dict[str, str]) -> TaskState:
    """Determine task state from its trailers."""
    step = trailers.get(TRAILER_STEP, "pending")

    if step == "complete":
        result = trailers.get(TRAILER_RESULT, "pass")
        return TaskState.FAILED if result == "fail" else TaskState.COMPLETE
    if step == "review":
        return TaskState.REVIEWING
    if step == "test":
        return TaskState.TESTING
    if step == "implement":
        return TaskState.IMPLEMENTING
    return TaskState.PENDING


def is_task_complete(branch: str, task_id: str, cwd: Path) -> bool:
    trailers = get_task_trailers(branch, task_id, cwd)
    state = task_state_from_trailers(trailers)
    return state == TaskState.COMPLETE


def scan_completed_tasks(tree, cwd: Path) -> set[str]:
    """Scan all leaf tasks across the tree and return IDs of completed ones."""
    completed = set()
    for node in tree.leaves():
        branch = tree.branch_name(node.id)
        try:
            if is_task_complete(branch, node.id, cwd):
                completed.add(node.id)
        except GitError:
            pass
    return completed
