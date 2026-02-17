"""Tests for worker/gardener.py."""

from agent_arborist.git.repo import git_log
from agent_arborist.tree.model import TaskNode, TaskTree
from agent_arborist.worker.gardener import gardener, GardenerResult


def _make_tree():
    """phase1 -> T001, T002 (T002 depends on T001)."""
    tree = TaskTree(spec_id="test")
    tree.nodes["phase1"] = TaskNode(id="phase1", name="Phase 1", children=["T001", "T002"])
    tree.nodes["T001"] = TaskNode(id="T001", name="Create files", parent="phase1", description="Create initial files")
    tree.nodes["T002"] = TaskNode(id="T002", name="Add tests", parent="phase1", depends_on=["T001"], description="Add test files")
    tree.compute_execution_order()
    return tree


def test_gardener_completes_all_tasks(git_repo, mock_runner_all_pass):
    tree = _make_tree()
    result = gardener(tree, git_repo, mock_runner_all_pass)

    assert result.success
    assert result.tasks_completed == 2
    assert result.order == ["T001", "T002"]


def test_gardener_commits_phase_marker_on_completion(git_repo, mock_runner_all_pass):
    tree = _make_tree()
    gardener(tree, git_repo, mock_runner_all_pass)

    # Phase-complete marker should be on main
    log = git_log("main", "%s", git_repo, n=15)
    assert "phase(phase1): complete" in log


def test_gardener_handles_failure(git_repo, mock_runner_always_reject):
    tree = _make_tree()
    result = gardener(tree, git_repo, mock_runner_always_reject, max_retries=1)

    assert not result.success


def test_gardener_respects_dependencies(git_repo, mock_runner_all_pass):
    tree = _make_tree()
    result = gardener(tree, git_repo, mock_runner_all_pass)

    # T001 must come before T002
    assert result.order.index("T001") < result.order.index("T002")


def test_gardener_multi_phase(git_repo, mock_runner_all_pass):
    """Two phases, each with one task."""
    tree = TaskTree(spec_id="test")
    tree.nodes["phase1"] = TaskNode(id="phase1", name="Phase 1", children=["T001"])
    tree.nodes["T001"] = TaskNode(id="T001", name="Task 1", parent="phase1", description="Do thing 1")
    tree.nodes["phase2"] = TaskNode(id="phase2", name="Phase 2", children=["T002"])
    tree.nodes["T002"] = TaskNode(id="T002", name="Task 2", parent="phase2", description="Do thing 2")
    tree.compute_execution_order()

    result = gardener(tree, git_repo, mock_runner_all_pass)
    assert result.success
    assert result.tasks_completed == 2
