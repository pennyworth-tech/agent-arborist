"""Read trailers from git commits to determine task state."""

from __future__ import annotations

import logging
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

from agent_arborist.constants import (
    TRAILER_STEP,
    TRAILER_RESULT,
    TRAILER_TEST,
    TRAILER_REVIEW,
    TRAILER_RETRY,
    TRAILER_REPORT,
)
from agent_arborist.git.repo import git_log, git_commit, GitError


def get_run_start_sha(cwd: Path, *, branch: str, create: bool = True) -> str | None:
    """Find or create a run-start marker commit on the current branch."""
    grep_pattern = f"task({branch}@@run-start)"
    try:
        sha = git_log(
            "HEAD", "%H", cwd,
            n=1, grep=grep_pattern, fixed_strings=True,
        )
        if sha.strip():
            logger.debug("Found existing run-start commit: %s", sha.strip())
            return sha.strip()
    except GitError:
        pass

    if not create:
        return None

    msg = (
        f"task({branch}@@run-start): run started\n\n"
        f"Arborist-Step: run-start"
    )
    sha = git_commit(msg, cwd, allow_empty=True)
    logger.info("Created run-start commit: %s", sha)
    return sha


class TaskState(Enum):
    PENDING = "pending"
    IMPLEMENTING = "implementing"
    TESTING = "testing"
    REVIEWING = "reviewing"
    COMPLETE = "complete"
    FAILED = "failed"


def get_task_trailers(rev: str, task_id: str, cwd: Path, *, current_branch: str) -> dict[str, str]:
    """Get the most recent trailers for a task on a branch.

    Greps for ``task({current_branch}@{task_id}`` so commits on other branches
    are invisible.
    """
    grep_pattern = f"task({current_branch}@{task_id}"
    try:
        out = git_log(
            rev,
            "%(trailers)",
            cwd,
            n=1,
            grep=grep_pattern,
            fixed_strings=True,
        )
    except GitError:
        return {}

    if not out.strip():
        return {}

    logger.debug("Parsing trailers for %s on %s", task_id, current_branch)
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


def is_task_complete(task_id: str, cwd: Path, *, current_branch: str) -> bool:
    trailers = get_task_trailers("HEAD", task_id, cwd, current_branch=current_branch)
    state = task_state_from_trailers(trailers)
    return state == TaskState.COMPLETE


def scan_completed_tasks(tree, cwd: Path, *, branch: str) -> set[str]:
    """Scan all leaf tasks on HEAD and return IDs of completed ones.

    Commits are scoped by *branch* name embedded in the commit prefix,
    so only commits for the current branch are considered.
    """
    completed = set()
    for node in tree.leaves():
        try:
            if is_task_complete(node.id, cwd, current_branch=branch):
                completed.add(node.id)
        except GitError:
            pass
    logger.debug("Scan found %d completed tasks", len(completed))
    return completed
