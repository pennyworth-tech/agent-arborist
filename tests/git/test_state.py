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

"""Tests for git/state.py."""

from agent_arborist.git.repo import git_add_all, git_commit, git_checkout
from agent_arborist.git.state import (
    TaskState,
    get_task_trailers,
    task_state_from_trailers,
    is_task_complete,
    scan_completed_tasks,
)
from agent_arborist.constants import TRAILER_STEP, TRAILER_RESULT
from agent_arborist.tree.model import TaskNode, TaskTree


def _commit_task(repo, task_id, *, branch="main", status="complete", **trailers):
    """Helper: commit with trailers using new branch-scoped format."""
    trailer_lines = "\n".join(f"{k}: {v}" for k, v in trailers.items())
    msg = f"task({branch}@{task_id}@{status}): step\n\n{trailer_lines}"
    git_add_all(repo)
    git_commit(msg, repo, allow_empty=True)


def test_task_state_from_trailers_pending():
    assert task_state_from_trailers({}) == TaskState.PENDING


def test_task_state_from_trailers_complete():
    assert task_state_from_trailers({TRAILER_STEP: "complete"}) == TaskState.COMPLETE


def test_task_state_from_trailers_failed():
    trailers = {TRAILER_STEP: "complete", TRAILER_RESULT: "fail"}
    assert task_state_from_trailers(trailers) == TaskState.FAILED


def test_task_state_from_trailers_implementing():
    assert task_state_from_trailers({TRAILER_STEP: "implement"}) == TaskState.IMPLEMENTING


def test_task_state_from_trailers_testing():
    assert task_state_from_trailers({TRAILER_STEP: "test"}) == TaskState.TESTING


def test_task_state_from_trailers_reviewing():
    assert task_state_from_trailers({TRAILER_STEP: "review"}) == TaskState.REVIEWING


def test_get_task_trailers_from_head(git_repo):
    _commit_task(git_repo, "T001", branch="main", status="complete",
                 **{TRAILER_STEP: "complete", TRAILER_RESULT: "pass"})

    trailers = get_task_trailers("HEAD", "T001", git_repo, current_branch="main")
    assert trailers[TRAILER_STEP] == "complete"
    assert trailers[TRAILER_RESULT] == "pass"


def test_is_task_complete(git_repo):
    _commit_task(git_repo, "T001", branch="main", status="complete",
                 **{TRAILER_STEP: "complete", TRAILER_RESULT: "pass"})

    assert is_task_complete("T001", git_repo, current_branch="main")


def test_is_task_not_complete_when_pending(git_repo):
    assert not is_task_complete("T001", git_repo, current_branch="main")


def test_scan_completed_tasks(git_repo):
    tree = TaskTree()
    tree.nodes["phase1"] = TaskNode(id="phase1", name="Phase 1", children=["T001", "T002"])
    tree.nodes["T001"] = TaskNode(id="T001", name="Task 1", parent="phase1")
    tree.nodes["T002"] = TaskNode(id="T002", name="Task 2", parent="phase1")

    # Complete T001 on current branch
    _commit_task(git_repo, "T001", branch="main", status="complete",
                 **{TRAILER_STEP: "complete", TRAILER_RESULT: "pass"})

    completed = scan_completed_tasks(tree, git_repo, branch="main")
    assert "T001" in completed
    assert "T002" not in completed


def test_scan_scoped_by_branch_name(git_repo):
    """Commits with task(other-branch@T001) are invisible when scanning for main."""
    tree = TaskTree()
    tree.nodes["phase1"] = TaskNode(id="phase1", name="Phase 1", children=["T001", "T002"])
    tree.nodes["T001"] = TaskNode(id="T001", name="Task 1", parent="phase1")
    tree.nodes["T002"] = TaskNode(id="T002", name="Task 2", parent="phase1")

    # Complete T001 on "other-branch" (different branch name in commit prefix)
    _commit_task(git_repo, "T001", branch="other-branch", status="complete",
                 **{TRAILER_STEP: "complete", TRAILER_RESULT: "pass"})

    # Complete T002 on "main"
    _commit_task(git_repo, "T002", branch="main", status="complete",
                 **{TRAILER_STEP: "complete", TRAILER_RESULT: "pass"})

    # Scanning for "main" should only see T002
    completed = scan_completed_tasks(tree, git_repo, branch="main")
    assert "T001" not in completed
    assert "T002" in completed

    # Scanning for "other-branch" should only see T001
    completed_other = scan_completed_tasks(tree, git_repo, branch="other-branch")
    assert "T001" in completed_other
    assert "T002" not in completed_other
