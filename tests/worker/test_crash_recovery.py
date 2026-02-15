"""Crash recovery tests for garden() and gardener()."""

import subprocess

from agent_arborist.git.repo import (
    git_add_all,
    git_checkout,
    git_commit,
    git_current_branch,
)
from agent_arborist.git.state import is_task_complete
from agent_arborist.tree.model import TaskNode, TaskTree
from agent_arborist.worker.garden import garden, find_next_task
from agent_arborist.worker.gardener import gardener
from tests.conftest import CrashingRunner, MockRunner


def _make_tree():
    """phase1 -> T001, T002 (T002 depends on T001)."""
    tree = TaskTree(spec_id="test", namespace="feature")
    tree.root_ids = ["phase1"]
    tree.nodes["phase1"] = TaskNode(id="phase1", name="Phase 1", children=["T001", "T002"])
    tree.nodes["T001"] = TaskNode(id="T001", name="Create files", parent="phase1", description="Create initial files")
    tree.nodes["T002"] = TaskNode(id="T002", name="Add tests", parent="phase1", depends_on=["T001"], description="Add test files")
    tree.compute_execution_order()
    return tree


# --- Scenario 1: Crash mid-pipeline (after implement, before complete) ---

def test_crash_mid_pipeline_recovers(git_repo):
    """Runner crashes during 1st call. Restart picks up the same task."""
    tree = _make_tree()

    # CrashingRunner: succeeds on call 1 (implement), crashes on call 2 (review)
    crasher = CrashingRunner(crash_after=1)
    try:
        garden(tree, git_repo, crasher, base_branch="main")
    except RuntimeError:
        pass

    # Should be back on main thanks to the try/except hardening
    assert git_current_branch(git_repo) == "main"

    # Task should NOT be complete
    assert not is_task_complete("feature/test/phase1", "T001", git_repo)

    # Restart with a good runner — should pick up T001 again
    runner = MockRunner()
    result = garden(tree, git_repo, runner, base_branch="main")
    assert result.success
    assert result.task_id == "T001"


# --- Scenario 2: Dirty working tree on restart ---

def test_dirty_working_tree_recovers(git_repo):
    """Uncommitted files on phase branch don't block restart."""
    tree = _make_tree()

    # Manually create the phase branch and leave dirty files
    branch = "feature/test/phase1"
    git_checkout(branch, git_repo, create=True, start_point="main")
    (git_repo / "leftover.txt").write_text("crash debris\n")
    git_checkout("main", git_repo)

    # garden() should handle the dirty branch gracefully
    runner = MockRunner()
    result = garden(tree, git_repo, runner, base_branch="main")
    assert result.success
    assert result.task_id == "T001"
    assert git_current_branch(git_repo) == "main"


# --- Scenario 3: Crash after complete commit, before checkout to base ---

def test_crash_after_complete_before_checkout(git_repo):
    """Complete trailer committed but repo left on phase branch."""
    tree = _make_tree()
    branch = "feature/test/phase1"

    # Simulate: complete commit exists on phase branch, repo still on phase branch
    git_checkout(branch, git_repo, create=True, start_point="main")
    git_add_all(git_repo)
    git_commit(
        "task(T001): complete\n\nArborist-Step: complete\nArborist-Result: pass\nArborist-Report: spec/reports/T001.json",
        git_repo,
        allow_empty=True,
    )
    # Intentionally stay on phase branch (simulating crash before checkout)
    assert git_current_branch(git_repo) == branch

    # Go back to main to restart
    git_checkout("main", git_repo)

    # garden() should see T001 as done and pick up T002
    runner = MockRunner()
    result = garden(tree, git_repo, runner, base_branch="main")
    assert result.success
    assert result.task_id == "T002"


# --- Scenario 4: Crash after checkout to base, before phase merge ---

def test_crash_before_phase_merge(git_repo):
    """All leaves complete, on base, but merge didn't happen yet."""
    tree = _make_tree()
    branch = "feature/test/phase1"

    # Complete both tasks on the phase branch
    git_checkout(branch, git_repo, create=True, start_point="main")
    git_commit(
        "task(T001): complete\n\nArborist-Step: complete\nArborist-Result: pass",
        git_repo,
        allow_empty=True,
    )
    git_commit(
        "task(T002): complete\n\nArborist-Step: complete\nArborist-Result: pass",
        git_repo,
        allow_empty=True,
    )
    git_checkout("main", git_repo)
    # Merge was skipped (simulating crash)

    # Next garden() call should see no tasks left and report "no ready task"
    # But internally find_next_task returns None since all are complete
    runner = MockRunner()
    result = garden(tree, git_repo, runner, base_branch="main")
    assert not result.success
    assert result.error == "no ready task"

    # Verify the tasks ARE seen as complete
    assert find_next_task(tree, git_repo) is None


# --- Scenario 5: Gardener crash between tasks ---

def test_gardener_crash_between_tasks(git_repo):
    """Gardener crashes on 2nd task. Restart completes remaining work."""
    tree = _make_tree()

    # CrashingRunner: T001 needs 3 calls (implement, review, then impl commit stuff)
    # Actually: implement (1), review (2) -> crash on call 3 won't work since
    # review is call 2 and complete happens internally.
    # Let's use crash_after=2: implement(1), review(2) succeed for T001,
    # then T002 implement(3) crashes.
    crasher = CrashingRunner(crash_after=2)
    try:
        gardener(tree, git_repo, crasher, base_branch="main")
    except RuntimeError:
        pass

    # T001 should be complete
    assert is_task_complete("feature/test/phase1", "T001", git_repo)
    assert git_current_branch(git_repo) == "main"

    # Restart with a good runner — should pick up T002
    runner = MockRunner()
    result = gardener(tree, git_repo, runner, base_branch="main")
    assert result.success
    assert result.tasks_completed == 1
    assert result.order == ["T002"]


# --- Scenario 6: Merge conflict during phase merge ---

def test_merge_conflict_surfaces_error(git_repo):
    """Conflicting content on base causes merge failure that can be recovered."""
    import pytest
    from agent_arborist.git.repo import GitError

    tree = _make_tree()
    branch = "feature/test/phase1"

    # Complete T001 normally
    runner = MockRunner()
    garden(tree, git_repo, runner, base_branch="main")

    # Create a conflicting file on main before T002 completes
    (git_repo / "conflict.txt").write_text("main version\n")
    git_add_all(git_repo)
    git_commit("add conflict file on main", git_repo)

    # Also add the same file on the phase branch with different content
    git_checkout(branch, git_repo)
    (git_repo / "conflict.txt").write_text("phase version\n")
    git_add_all(git_repo)
    git_commit("add conflict file on phase", git_repo)
    git_checkout("main", git_repo)

    # Complete T002 — triggers phase merge which conflicts.
    # The GitError from merge propagates out of garden().
    with pytest.raises(GitError):
        garden(tree, git_repo, runner, base_branch="main")

    # Repo should be on main (the try/except hardening returns to base)
    assert git_current_branch(git_repo) == "main"

    # Verify we can abort the failed merge and repo is usable
    # (merge --abort only needed if merge left conflict markers;
    # since we checked out main in the except block, we're clean)
    subprocess.run(["git", "merge", "--abort"], cwd=git_repo, capture_output=True)
    assert git_current_branch(git_repo) == "main"
