"""Crash recovery tests for garden() and gardener()."""

from agent_arborist.git.repo import (
    git_add_all,
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
    tree = TaskTree()
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
        garden(tree, git_repo, crasher, branch="main")
    except RuntimeError:
        pass

    # Should still be on main (no branch switching)
    assert git_current_branch(git_repo) == "main"

    # Task should NOT be complete
    assert not is_task_complete("T001", git_repo, current_branch="main")

    # Restart with a good runner — should pick up T001 again
    runner = MockRunner()
    result = garden(tree, git_repo, runner, branch="main")
    assert result.success
    assert result.task_id == "T001"


# --- Scenario 2: Dirty working tree on restart ---

def test_dirty_working_tree_recovers(git_repo):
    """Uncommitted files don't block restart."""
    tree = _make_tree()

    # Leave dirty files
    (git_repo / "leftover.txt").write_text("crash debris\n")

    # garden() should handle gracefully
    runner = MockRunner()
    result = garden(tree, git_repo, runner, branch="main")
    assert result.success
    assert result.task_id == "T001"
    assert git_current_branch(git_repo) == "main"


# --- Scenario 3: Crash after complete commit ---

def test_crash_after_complete_commit(git_repo):
    """Complete trailer committed. Restart should see T001 as done and pick up T002."""
    tree = _make_tree()

    # Simulate: complete commit exists on current branch
    git_add_all(git_repo)
    git_commit(
        "task(main@T001@complete): complete\n\nArborist-Step: complete\nArborist-Result: pass\nArborist-Report: spec/reports/T001.json",
        git_repo,
        allow_empty=True,
    )

    # garden() should see T001 as done and pick up T002
    runner = MockRunner()
    result = garden(tree, git_repo, runner, branch="main")
    assert result.success
    assert result.task_id == "T002"


# --- Scenario 4: All tasks complete, no phase marker yet ---

def test_all_tasks_complete_no_phase_marker(git_repo):
    """All leaves complete. garden() should return no-ready-task."""
    tree = _make_tree()

    # Complete both tasks on current branch
    git_commit(
        "task(main@T001@complete): complete\n\nArborist-Step: complete\nArborist-Result: pass",
        git_repo,
        allow_empty=True,
    )
    git_commit(
        "task(main@T002@complete): complete\n\nArborist-Step: complete\nArborist-Result: pass",
        git_repo,
        allow_empty=True,
    )

    # Next garden() call should see no tasks left
    runner = MockRunner()
    result = garden(tree, git_repo, runner, branch="main")
    assert not result.success
    assert result.error == "no ready task"

    # Verify the tasks ARE seen as complete
    assert find_next_task(tree, git_repo, branch="main") is None


# --- Scenario 5: Gardener crash between tasks ---

def test_gardener_crash_between_tasks(git_repo):
    """Gardener crashes on 2nd task. Restart completes remaining work."""
    tree = _make_tree()

    # CrashingRunner: implement(1), review(2) succeed for T001,
    # then T002 implement(3) crashes.
    crasher = CrashingRunner(crash_after=2)
    try:
        gardener(tree, git_repo, crasher, branch="main")
    except RuntimeError:
        pass

    # T001 should be complete
    assert is_task_complete("T001", git_repo, current_branch="main")
    assert git_current_branch(git_repo) == "main"

    # Restart with a good runner — should pick up T002
    runner = MockRunner()
    result = gardener(tree, git_repo, runner, branch="main")
    assert result.success
    assert result.tasks_completed == 1
    assert result.order == ["T002"]
