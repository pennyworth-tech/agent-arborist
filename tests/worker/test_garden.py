"""Tests for worker/garden.py."""

from agent_arborist.git.repo import git_current_branch
from agent_arborist.git.state import is_task_complete
from agent_arborist.tree.model import TaskNode, TaskTree
from agent_arborist.worker.garden import garden, find_next_task, GardenResult


def _make_tree():
    """phase1 -> T001, T002 (T002 depends on T001)."""
    tree = TaskTree(spec_id="test", namespace="feature")
    tree.nodes["phase1"] = TaskNode(id="phase1", name="Phase 1", children=["T001", "T002"])
    tree.nodes["T001"] = TaskNode(id="T001", name="Create files", parent="phase1", description="Create initial files")
    tree.nodes["T002"] = TaskNode(id="T002", name="Add tests", parent="phase1", depends_on=["T001"], description="Add test files")
    tree.compute_execution_order()
    return tree


def test_find_next_task_returns_first_ready(git_repo):
    tree = _make_tree()
    task = find_next_task(tree, git_repo)
    assert task is not None
    assert task.id == "T001"


def test_find_next_task_returns_none_when_all_done(git_repo):
    tree = _make_tree()
    # Manually mark both complete by committing trailers
    from agent_arborist.git.repo import git_checkout, git_add_all, git_commit
    git_checkout("feature/test/phase1", git_repo, create=True)
    git_add_all(git_repo)
    git_commit("task(T001): complete\n\nArborist-Step: complete\nArborist-Result: pass", git_repo, allow_empty=True)
    git_commit("task(T002): complete\n\nArborist-Step: complete\nArborist-Result: pass", git_repo, allow_empty=True)
    git_checkout("main", git_repo)

    task = find_next_task(tree, git_repo)
    assert task is None


def test_garden_executes_task_successfully(git_repo, mock_runner_all_pass):
    tree = _make_tree()
    result = garden(tree, git_repo, mock_runner_all_pass, base_branch="main")

    assert result.success
    assert result.task_id == "T001"
    assert git_current_branch(git_repo) == "main"


def test_garden_creates_phase_branch(git_repo, mock_runner_all_pass):
    tree = _make_tree()
    from agent_arborist.git.repo import git_branch_exists
    assert not git_branch_exists("feature/test/phase1", git_repo)

    garden(tree, git_repo, mock_runner_all_pass, base_branch="main")
    assert git_branch_exists("feature/test/phase1", git_repo)


def test_garden_marks_task_complete(git_repo, mock_runner_all_pass):
    tree = _make_tree()
    garden(tree, git_repo, mock_runner_all_pass, base_branch="main")

    assert is_task_complete("feature/test/phase1", "T001", git_repo)


def test_garden_writes_report(git_repo, mock_runner_all_pass, tmp_path):
    tree = _make_tree()
    report_dir = tmp_path / "reports"
    garden(tree, git_repo, mock_runner_all_pass, base_branch="main", report_dir=report_dir)

    # Report should be written to report_dir
    reports = list(report_dir.glob("T001_run_*.json"))
    assert len(reports) == 1


def test_garden_retries_on_test_failure(git_repo, mock_runner_all_pass):
    """When test fails, garden retries implementation."""
    tree = _make_tree()

    # Use a test command that fails first time, succeeds second
    counter_file = git_repo / ".test-counter"
    counter_file.write_text("0")
    test_cmd = f'c=$(cat {counter_file}); echo $((c+1)) > {counter_file}; [ "$c" -gt "0" ]'

    result = garden(tree, git_repo, mock_runner_all_pass, test_command=test_cmd, max_retries=3, base_branch="main")
    assert result.success


def test_garden_fails_after_max_retries(git_repo, mock_runner_always_reject):
    tree = _make_tree()
    result = garden(tree, git_repo, mock_runner_always_reject, max_retries=2, base_branch="main")

    assert not result.success
    assert "failed after 2 retries" in result.error
    assert git_current_branch(git_repo) == "main"


def _deep_tree():
    """Ragged: phase1 -> group1 -> T001, T002; phase1 -> T003."""
    tree = TaskTree(spec_id="test", namespace="feature")
    tree.nodes["phase1"] = TaskNode(id="phase1", name="Phase 1", children=["group1", "T003"])
    tree.nodes["group1"] = TaskNode(id="group1", name="Group 1", parent="phase1", children=["T001", "T002"])
    tree.nodes["T001"] = TaskNode(id="T001", name="Schema", parent="group1", description="Create schema")
    tree.nodes["T002"] = TaskNode(id="T002", name="Models", parent="group1", depends_on=["T001"], description="Create models")
    tree.nodes["T003"] = TaskNode(id="T003", name="Frontend", parent="phase1", description="Create frontend")
    tree.compute_execution_order()
    return tree


def test_deep_tree_merge_waits_for_all_leaves(git_repo, mock_runner_all_pass):
    """Phase should not merge until ALL deep leaves are complete."""
    tree = _deep_tree()

    # Complete T001 — phase should NOT merge yet
    r1 = garden(tree, git_repo, mock_runner_all_pass, base_branch="main")
    assert r1.success
    from agent_arborist.git.repo import git_log
    main_log = git_log("main", "%s", git_repo, n=5)
    assert "merge" not in main_log.lower()

    # Complete T003
    r2 = garden(tree, git_repo, mock_runner_all_pass, base_branch="main")
    assert r2.success

    # Complete T002 — now all leaves done, phase should merge
    r3 = garden(tree, git_repo, mock_runner_all_pass, base_branch="main")
    assert r3.success
    main_log = git_log("main", "%s", git_repo, n=5)
    assert "merge" in main_log.lower()
