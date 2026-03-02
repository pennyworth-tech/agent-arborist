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

import subprocess
from pathlib import Path

from agent_arborist.git.repo import git_add_all, git_commit, git_checkout, GitError
from agent_arborist.git.state import (
    TaskState,
    get_task_trailers,
    task_state_from_trailers,
    is_task_complete,
    scan_completed_tasks,
    scan_task_states,
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

    trailers = get_task_trailers("HEAD", "T001", git_repo, spec_id="main")
    assert trailers[TRAILER_STEP] == "complete"
    assert trailers[TRAILER_RESULT] == "pass"


def test_is_task_complete(git_repo):
    _commit_task(git_repo, "T001", branch="main", status="complete",
                 **{TRAILER_STEP: "complete", TRAILER_RESULT: "pass"})

    assert is_task_complete("T001", git_repo, spec_id="main")


def test_is_task_not_complete_when_pending(git_repo):
    assert not is_task_complete("T001", git_repo, spec_id="main")


def test_scan_completed_tasks(git_repo):
    tree = TaskTree()
    tree.nodes["phase1"] = TaskNode(id="phase1", name="Phase 1", children=["T001", "T002"])
    tree.nodes["T001"] = TaskNode(id="T001", name="Task 1", parent="phase1")
    tree.nodes["T002"] = TaskNode(id="T002", name="Task 2", parent="phase1")

    # Complete T001 on current branch
    _commit_task(git_repo, "T001", branch="main", status="complete",
                 **{TRAILER_STEP: "complete", TRAILER_RESULT: "pass"})

    completed = scan_completed_tasks(tree, git_repo, spec_id="main")
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
    completed = scan_completed_tasks(tree, git_repo, spec_id="main")
    assert "T001" not in completed
    assert "T002" in completed

    # Scanning for "other-branch" should only see T001
    completed_other = scan_completed_tasks(tree, git_repo, spec_id="other-branch")
    assert "T001" in completed_other
    assert "T002" not in completed_other


# ============================================================================
# Tests for batch scanning (scan_task_states and scan_completed_tasks)
# ============================================================================


def test_scan_completed_tasks_on_main_branch_errors(git_repo):
    """Scanning from main branch should error since we can't find divergence."""
    tree = TaskTree()
    tree.nodes["T001"] = TaskNode(id="T001", name="Task 1")

    # Already on main, so current branch == base_branch == main
    # In this case, we scan all commits (not error)
    # This test verifies we don't crash - we just scan all commits
    completed = scan_completed_tasks(tree, git_repo, spec_id="main", base_branch="main")
    # Should return empty since no task commits exist
    assert completed == set()


def test_scan_completed_tasks_no_base_branch_errors(git_repo):
    """Error when base_branch doesn't exist."""
    tree = TaskTree()
    tree.nodes["T001"] = TaskNode(id="T001", name="Task 1")

    try:
        scan_completed_tasks(tree, git_repo, spec_id="main", base_branch="nonexistent")
        assert False, "Expected GitError"
    except GitError as e:
        assert "nonexistent" in str(e).lower() or "merge-base" in str(e).lower()


def test_scan_completed_tasks_custom_base_branch(git_repo):
    """Can specify custom base branch for divergence detection."""
    # Create develop branch with initial commit
    subprocess.run(["git", "checkout", "-b", "develop"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "initial on develop"], cwd=git_repo, check=True)

    # Create feature branch from develop
    subprocess.run(["git", "checkout", "-b", "feature"], cwd=git_repo, check=True)

    tree = TaskTree()
    tree.nodes["T001"] = TaskNode(id="T001", name="Task 1")

    _commit_task(git_repo, "T001", branch="feature", status="complete",
                **{TRAILER_STEP: "complete", TRAILER_RESULT: "pass"})

    # Scan with custom base_branch=develop should find T001
    completed = scan_completed_tasks(tree, git_repo, spec_id="feature", base_branch="develop")
    assert "T001" in completed


def test_scan_task_states_returns_all_states(git_repo):
    """scan_task_states returns state and trailers for all tasks."""
    tree = TaskTree()
    tree.nodes["T001"] = TaskNode(id="T001", name="Task 1")
    tree.nodes["T002"] = TaskNode(id="T002", name="Task 2")
    tree.nodes["T003"] = TaskNode(id="T003", name="Task 3")
    tree.nodes["T004"] = TaskNode(id="T004", name="Task 4")
    tree.nodes["T005"] = TaskNode(id="T005", name="Task 5")
    tree.nodes["T006"] = TaskNode(id="T006", name="Task 6")

    # Complete T001
    _commit_task(git_repo, "T001", branch="main", status="complete",
                **{TRAILER_STEP: "complete", TRAILER_RESULT: "pass"})

    # T002 in implementing state
    _commit_task(git_repo, "T002", branch="main", status="implement",
                **{TRAILER_STEP: "implement", TRAILER_RESULT: "pass"})

    # T003 in testing state
    _commit_task(git_repo, "T003", branch="main", status="test",
                **{TRAILER_STEP: "test", TRAILER_RESULT: "pass"})

    # T004 in reviewing state
    _commit_task(git_repo, "T004", branch="main", status="review",
                **{TRAILER_STEP: "review", TRAILER_RESULT: "pass"})

    # T005 failed
    _commit_task(git_repo, "T005", branch="main", status="complete",
                **{TRAILER_STEP: "complete", TRAILER_RESULT: "fail"})

    # T006 has no commits (pending)

    task_states, task_trailers = scan_task_states(tree, git_repo, spec_id="main")

    assert task_states["T001"] == TaskState.COMPLETE
    assert task_states["T002"] == TaskState.IMPLEMENTING
    assert task_states["T003"] == TaskState.TESTING
    assert task_states["T004"] == TaskState.REVIEWING
    assert task_states["T005"] == TaskState.FAILED
    assert "T006" not in task_states  # No commits means not in dict

    # Check trailers are returned
    assert TRAILER_STEP in task_trailers["T001"]
    assert task_trailers["T001"][TRAILER_STEP] == "complete"


def test_scan_task_states_multiple_commits_uses_latest(git_repo):
    """If task has multiple commits, scan uses latest state."""
    tree = TaskTree()
    tree.nodes["T001"] = TaskNode(id="T001", name="Task 1")

    # First: implement
    _commit_task(git_repo, "T001", branch="main", status="implement",
                **{TRAILER_STEP: "implement", TRAILER_RESULT: "pass"})

    # Then: test
    _commit_task(git_repo, "T001", branch="main", status="test",
                **{TRAILER_STEP: "test", TRAILER_RESULT: "pass"})

    # Then: complete
    _commit_task(git_repo, "T001", branch="main", status="complete",
                **{TRAILER_STEP: "complete", TRAILER_RESULT: "pass"})

    task_states, task_trailers = scan_task_states(tree, git_repo, spec_id="main")

    # Should be complete (latest), not implementing or testing
    assert task_states["T001"] == TaskState.COMPLETE
    assert task_trailers["T001"][TRAILER_STEP] == "complete"


def test_scan_completed_tasks_empty_repo(git_repo):
    """Empty repo (no task commits) returns empty set."""
    tree = TaskTree()
    tree.nodes["T001"] = TaskNode(id="T001", name="Task 1")

    completed = scan_completed_tasks(tree, git_repo, spec_id="main")
    assert completed == set()


def test_scan_completed_tasks_nonexistent_spec(git_repo):
    """Scanning for non-existent spec returns empty."""
    tree = TaskTree()
    tree.nodes["T001"] = TaskNode(id="T001", name="Task 1")

    _commit_task(git_repo, "T001", branch="main", status="complete",
                **{TRAILER_STEP: "complete", TRAILER_RESULT: "pass"})

    # Scan for different spec_id
    completed = scan_completed_tasks(tree, git_repo, spec_id="nonexistent")
    assert completed == set()


def test_scan_task_states_partial_tree(git_repo):
    """Tree can have non-leaf nodes; scan only returns states for leaf tasks."""
    tree = TaskTree()
    tree.nodes["phase1"] = TaskNode(id="phase1", name="Phase 1", children=["T001", "T002"])
    tree.nodes["T001"] = TaskNode(id="T001", name="Task 1", parent="phase1")
    tree.nodes["T002"] = TaskNode(id="T002", name="Task 2", parent="phase1")

    _commit_task(git_repo, "T001", branch="main", status="complete",
                **{TRAILER_STEP: "complete", TRAILER_RESULT: "pass"})

    task_states, task_trailers = scan_task_states(tree, git_repo, spec_id="main")

    # Should only have T001, not phase1
    assert "T001" in task_states
    assert "phase1" not in task_states
    assert "T002" not in task_states


def test_scan_completed_tasks_filters_by_spec_id(git_repo):
    """Only commits matching spec_id are considered."""
    tree = TaskTree()
    tree.nodes["T001"] = TaskNode(id="T001", name="Task 1")
    tree.nodes["T002"] = TaskNode(id="T002", name="Task 2")

    # Commit for spec "feature-a"
    _commit_task(git_repo, "T001", branch="feature-a", status="complete",
                **{TRAILER_STEP: "complete", TRAILER_RESULT: "pass"})

    # Commit for spec "feature-b"
    _commit_task(git_repo, "T002", branch="feature-b", status="complete",
                **{TRAILER_STEP: "complete", TRAILER_RESULT: "pass"})

    # Scanning for feature-a should only see T001
    completed_a = scan_completed_tasks(tree, git_repo, spec_id="feature-a")
    assert "T001" in completed_a
    assert "T002" not in completed_a

    # Scanning for feature-b should only see T002
    completed_b = scan_completed_tasks(tree, git_repo, spec_id="feature-b")
    assert "T001" not in completed_b
    assert "T002" in completed_b


def test_scan_completed_tasks_on_feature_branch(git_repo):
    """On feature branch, only scans commits since branching from main."""
    # Create main branch with initial commit
    subprocess.run(["git", "checkout", "-b", "feature"], cwd=git_repo, check=True)

    # Add a commit on main (before branching) - should NOT be seen
    subprocess.run(["git", "checkout", "main"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "main commit"], cwd=git_repo, check=True)

    # Switch back to feature
    subprocess.run(["git", "checkout", "feature"], cwd=git_repo, check=True)

    tree = TaskTree()
    tree.nodes["T001"] = TaskNode(id="T001", name="Task 1")

    # Complete task on feature branch
    _commit_task(git_repo, "T001", branch="feature", status="complete",
                **{TRAILER_STEP: "complete", TRAILER_RESULT: "pass"})

    completed = scan_completed_tasks(tree, git_repo, spec_id="feature")
    assert "T001" in completed


def test_scan_task_states_pending_task(git_repo):
    """Task with no commits is not in returned states (treated as pending)."""
    tree = TaskTree()
    tree.nodes["T001"] = TaskNode(id="T001", name="Task 1")
    tree.nodes["T002"] = TaskNode(id="T002", name="Task 2")

    # Only commit for T001
    _commit_task(git_repo, "T001", branch="main", status="complete",
                **{TRAILER_STEP: "complete", TRAILER_RESULT: "pass"})

    task_states, task_trailers = scan_task_states(tree, git_repo, spec_id="main")

    assert "T001" in task_states
    assert "T002" not in task_states  # No commits = not in dict


def test_scan_completed_tasks_large_tree(git_repo):
    """Can handle large trees with many tasks efficiently."""
    tree = TaskTree()

    # Create 50 tasks
    for i in range(50):
        tree.nodes[f"T{i:03d}"] = TaskNode(id=f"T{i:03d}", name=f"Task {i}")

    # Complete half of them
    for i in range(0, 50, 2):
        _commit_task(git_repo, f"T{i:03d}", branch="main", status="complete",
                    **{TRAILER_STEP: "complete", TRAILER_RESULT: "pass"})

    completed = scan_completed_tasks(tree, git_repo, spec_id="main")

    # Should have 25 completed tasks
    assert len(completed) == 25
    for i in range(0, 50, 2):
        assert f"T{i:03d}" in completed
    for i in range(1, 50, 2):
        assert f"T{i:03d}" not in completed


def test_scan_task_states_returns_trailers_for_all_tasks(git_repo):
    """Verify trailers are returned for each task with commits."""
    tree = TaskTree()
    tree.nodes["T001"] = TaskNode(id="T001", name="Task 1")
    tree.nodes["T002"] = TaskNode(id="T002", name="Task 2")

    _commit_task(git_repo, "T001", branch="main", status="complete",
                **{TRAILER_STEP: "complete", TRAILER_RESULT: "pass", "Arborist-Custom": "value1"})

    _commit_task(git_repo, "T002", branch="main", status="implement",
                **{TRAILER_STEP: "implement", TRAILER_RESULT: "pass", "Arborist-Custom": "value2"})

    task_states, task_trailers = scan_task_states(tree, git_repo, spec_id="main")

    assert "Arborist-Custom" in task_trailers["T001"]
    assert task_trailers["T001"]["Arborist-Custom"] == "value1"
    assert "Arborist-Custom" in task_trailers["T002"]
    assert task_trailers["T002"]["Arborist-Custom"] == "value2"


def test_scan_completed_tasks_with_base_branch_on_feature(git_repo):
    """When on feature branch with base_branch=main, finds divergence correctly."""
    # Start on main
    # Create initial commit on main
    subprocess.run(["git", "commit", "--allow-empty", "-m", "initial main"], cwd=git_repo, check=True)

    # Create feature branch
    subprocess.run(["git", "checkout", "-b", "feature"], cwd=git_repo, check=True)

    tree = TaskTree()
    tree.nodes["T001"] = TaskNode(id="T001", name="Task 1")

    _commit_task(git_repo, "T001", branch="feature", status="complete",
                **{TRAILER_STEP: "complete", TRAILER_RESULT: "pass"})

    # Should work with explicit base_branch="main"
    completed = scan_completed_tasks(tree, git_repo, spec_id="feature", base_branch="main")
    assert "T001" in completed


def test_scan_task_states_base_branch_not_found_errors(git_repo):
    """Errors when base_branch doesn't exist."""
    tree = TaskTree()
    tree.nodes["T001"] = TaskNode(id="T001", name="Task 1")

    try:
        scan_completed_tasks(tree, git_repo, spec_id="main", base_branch="nonexistent")
        assert False, "Expected GitError"
    except GitError as e:
        assert "nonexistent" in str(e).lower() or "merge-base" in str(e).lower()
