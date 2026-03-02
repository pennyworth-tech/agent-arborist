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
from agent_arborist.git.repo import git_log, git_commit, git_merge_base, git_log_since, git_current_branch, GitError


def get_run_start_sha(cwd: Path, *, spec_id: str, create: bool = True) -> str | None:
    """Find or create a run-start marker commit for this spec_id."""
    grep_pattern = f"task({spec_id}@@run-start)"
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
        f"task({spec_id}@@run-start): run started\n\n"
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


def get_task_trailers(rev: str, task_id: str, cwd: Path, *, spec_id: str) -> dict[str, str]:
    """Get the most recent trailers for a task on a spec_id.

    Greps for ``task({spec_id}@{task_id}`` so commits for other specs
    are invisible.
    """
    grep_pattern = f"task({spec_id}@{task_id}"
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

    logger.debug("Parsing trailers for %s on %s", task_id, spec_id)
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


def is_task_complete(task_id: str, cwd: Path, *, spec_id: str) -> bool:
    trailers = get_task_trailers("HEAD", task_id, cwd, spec_id=spec_id)
    state = task_state_from_trailers(trailers)
    return state == TaskState.COMPLETE


def get_task_commit_history(task_id: str, cwd: Path, *, spec_id: str) -> list[dict[str, str]]:
    """Get all commits for a task, each as a dict of trailers + commit metadata."""
    grep_pattern = f"task({spec_id}@{task_id}"
    try:
        raw = git_log(
            "HEAD",
            "%h%n%s%n%(trailers)%n---COMMIT_SEP---",
            cwd,
            n=50,
            grep=grep_pattern,
            fixed_strings=True,
        )
    except GitError:
        return []

    commits = []
    for block in raw.split("---COMMIT_SEP---"):
        block = block.strip()
        if not block:
            continue
        lines = block.split("\n")
        if len(lines) < 2:
            continue
        sha = lines[0].strip()
        subject = lines[1].strip()
        trailers: dict[str, str] = {}
        for line in lines[2:]:
            line = line.strip()
            if ": " in line and line.startswith("Arborist-"):
                key, _, val = line.partition(": ")
                trailers[key] = val.strip()
        commits.append({
            "sha": sha,
            "subject": subject,
            "step": trailers.get(TRAILER_STEP, ""),
            "result": trailers.get(TRAILER_RESULT, ""),
            "retry": trailers.get(TRAILER_RETRY, ""),
            "trailers": trailers,
        })
    return commits


def scan_task_states(
    tree, cwd: Path, *, spec_id: str, base_branch: str = "main"
) -> tuple[dict[str, TaskState], dict[str, dict[str, str]]]:
    """Scan all leaf tasks on HEAD and return states and trailers for each.

    Uses a single git log call to fetch all task commits since branching,
    then parses to determine state.

    Returns:
        Tuple of (task_states, task_trailers) where:
        - task_states: dict mapping task_id -> TaskState
        - task_trailers: dict mapping task_id -> trailers dict

    Commits are scoped by *spec_id* embedded in the commit prefix,
    so only commits for the current spec are considered.
    """
    from agent_arborist.git.repo import GitError

    merge_base = git_merge_base(base_branch, "HEAD", cwd)
    if not merge_base:
        raise GitError(
            f"Cannot find merge-base between {base_branch} and HEAD. "
            f"Are you on branch {base_branch}?"
        )

    branch_point = merge_base.strip()
    if not branch_point:
        raise GitError(f"Merge-base for {base_branch} is empty")

    current_branch = git_current_branch(cwd)

    is_on_base_branch = (current_branch == base_branch)

    if is_on_base_branch:
        logger.debug("On base branch %s, scanning all commits", base_branch)
        range_spec = "HEAD"
    else:
        logger.debug("Scanning task status since branching from %s", base_branch)
        range_spec = f"{base_branch}..HEAD"

    try:
        raw = git_log(
            range_spec,
            "%s%n%(trailers)%n---COMMIT_SEP---",
            cwd,
            n=500,
            grep=f"task({spec_id}@",
            fixed_strings=True,
        )
    except GitError:
        logger.debug("No task commits found")
        return {}, {}

    task_states: dict[str, TaskState] = {}
    task_trailers: dict[str, dict[str, str]] = {}

    for block in raw.split("---COMMIT_SEP---"):
        block = block.strip()
        if not block:
            continue
        lines = block.split("\n")
        if len(lines) < 2:
            continue
        subject = lines[0].strip()

        if not subject.startswith(f"task({spec_id}@"):
            continue

        try:
            rest = subject[len(f"task({spec_id}@"):]
            task_id, _, _ = rest.partition("@")
        except Exception:
            continue

        if task_id in task_states:
            continue

        trailers: dict[str, str] = {}
        for line in lines[1:]:
            line = line.strip()
            if ": " in line and line.startswith("Arborist-"):
                key, _, val = line.partition(": ")
                trailers[key] = val.strip()

        state = task_state_from_trailers(trailers)
        task_states[task_id] = state
        task_trailers[task_id] = trailers

    logger.debug("Scanned %d tasks", len(task_states))
    return task_states, task_trailers


def scan_completed_tasks(
    tree, cwd: Path, *, spec_id: str, base_branch: str = "main"
) -> set[str]:
    """Scan all leaf tasks on HEAD and return IDs of completed ones.

    Uses a single git log call to fetch all task commits since branching,
    then parses to determine completion status.

    Commits are scoped by *spec_id* embedded in the commit prefix,
    so only commits for the current spec are considered.
    """
    task_states, _ = scan_task_states(tree, cwd, spec_id=spec_id, base_branch=base_branch)

    completed = {
        task_id for task_id, state in task_states.items()
        if state == TaskState.COMPLETE
    }

    logger.debug("Scan found %d completed tasks", len(completed))
    return completed
