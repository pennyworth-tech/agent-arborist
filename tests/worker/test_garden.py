"""Tests for worker/garden.py."""

from agent_arborist.git.repo import git_current_branch, git_log
from agent_arborist.git.state import is_task_complete
from agent_arborist.tree.model import TaskNode, TaskTree, TestCommand, TestType
from agent_arborist.worker.garden import (
    garden, find_next_task, GardenResult,
    _run_tests, _parse_test_counts,
)


def _make_tree():
    """phase1 -> T001, T002 (T002 depends on T001)."""
    tree = TaskTree(spec_id="test")
    tree.nodes["phase1"] = TaskNode(id="phase1", name="Phase 1", children=["T001", "T002"])
    tree.nodes["T001"] = TaskNode(id="T001", name="Create files", parent="phase1", description="Create initial files")
    tree.nodes["T002"] = TaskNode(id="T002", name="Add tests", parent="phase1", depends_on=["T001"], description="Add test files")
    tree.compute_execution_order()
    return tree


def test_find_next_task_returns_first_ready(git_repo):
    tree = _make_tree()
    task = find_next_task(tree, git_repo, branch="main")
    assert task is not None
    assert task.id == "T001"


def test_find_next_task_returns_none_when_all_done(git_repo):
    tree = _make_tree()
    # Manually mark both complete by committing trailers on current branch
    from agent_arborist.git.repo import git_add_all, git_commit
    git_add_all(git_repo)
    git_commit("task(main@T001@complete): complete\n\nArborist-Step: complete\nArborist-Result: pass", git_repo, allow_empty=True)
    git_commit("task(main@T002@complete): complete\n\nArborist-Step: complete\nArborist-Result: pass", git_repo, allow_empty=True)

    task = find_next_task(tree, git_repo, branch="main")
    assert task is None


def test_garden_executes_task_successfully(git_repo, mock_runner_all_pass):
    tree = _make_tree()
    result = garden(tree, git_repo, mock_runner_all_pass, branch="main")

    assert result.success
    assert result.task_id == "T001"
    # Commits land on the current (base) branch — no branch switching
    assert git_current_branch(git_repo) == "main"


def test_garden_commits_on_current_branch(git_repo, mock_runner_all_pass):
    """All commits land on the current branch, no phase branches created."""
    tree = _make_tree()
    from agent_arborist.git.repo import git_branch_exists
    garden(tree, git_repo, mock_runner_all_pass, branch="main")
    # No phase branch should exist
    assert not git_branch_exists("feature/test/phase1", git_repo)
    # Commits should be on main
    log = git_log("main", "%s", git_repo, n=10)
    assert "task(main@T001@" in log


def test_garden_marks_task_complete(git_repo, mock_runner_all_pass):
    tree = _make_tree()
    garden(tree, git_repo, mock_runner_all_pass, branch="main")

    assert is_task_complete("T001", git_repo, current_branch="main")


def test_garden_writes_report(git_repo, mock_runner_all_pass, tmp_path):
    tree = _make_tree()
    report_dir = tmp_path / "reports"
    garden(tree, git_repo, mock_runner_all_pass, report_dir=report_dir, branch="main")

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

    result = garden(tree, git_repo, mock_runner_all_pass, test_command=test_cmd, max_retries=3, branch="main")
    assert result.success


def test_garden_fails_after_max_retries(git_repo, mock_runner_always_reject):
    tree = _make_tree()
    result = garden(tree, git_repo, mock_runner_always_reject, max_retries=2, branch="main")

    assert not result.success
    assert "failed after 2 retries" in result.error
    assert git_current_branch(git_repo) == "main"


def _deep_tree():
    """Ragged: phase1 -> group1 -> T001, T002; phase1 -> T003."""
    tree = TaskTree(spec_id="test")
    tree.nodes["phase1"] = TaskNode(id="phase1", name="Phase 1", children=["group1", "T003"])
    tree.nodes["group1"] = TaskNode(id="group1", name="Group 1", parent="phase1", children=["T001", "T002"])
    tree.nodes["T001"] = TaskNode(id="T001", name="Schema", parent="group1", description="Create schema")
    tree.nodes["T002"] = TaskNode(id="T002", name="Models", parent="group1", depends_on=["T001"], description="Create models")
    tree.nodes["T003"] = TaskNode(id="T003", name="Frontend", parent="phase1", description="Create frontend")
    tree.compute_execution_order()
    return tree


def test_deep_tree_all_leaves_complete(git_repo, mock_runner_all_pass):
    """All deep leaves complete after gardening all tasks."""
    tree = _deep_tree()

    # Complete T001
    r1 = garden(tree, git_repo, mock_runner_all_pass, branch="main")
    assert r1.success

    # Complete T003
    r2 = garden(tree, git_repo, mock_runner_all_pass, branch="main")
    assert r2.success

    # Complete T002
    r3 = garden(tree, git_repo, mock_runner_all_pass, branch="main")
    assert r3.success

    # All three tasks should be complete
    assert is_task_complete("T001", git_repo, current_branch="main")
    assert is_task_complete("T002", git_repo, current_branch="main")
    assert is_task_complete("T003", git_repo, current_branch="main")


# --- Feedback passthrough tests ---
# Feedback must be durable (git commits + log files), not in-memory state.


def test_review_log_trailer_in_commit(git_repo, tmp_path):
    """Review commit should include Arborist-Review-Log trailer with log file path."""
    from tests.conftest import TrackingRunner
    from agent_arborist.runner import RunResult
    from agent_arborist.git.repo import git_log

    tree = _make_tree()
    log_dir = tmp_path / "logs"

    runner = TrackingRunner(implement_ok=True, review_ok=True)
    result = garden(tree, git_repo, runner, max_retries=3, log_dir=log_dir, branch="main")
    assert result.success

    # Check the review commit on HEAD has the trailer
    log_output = git_log("HEAD", "%B", git_repo, n=10, grep="review")
    assert "Arborist-Review-Log:" in log_output, (
        f"Review commit should have Arborist-Review-Log trailer, got:\n{log_output}"
    )


def test_test_log_trailer_in_commit(git_repo, tmp_path):
    """Test-fail commit should include Arborist-Test-Log trailer with log file path."""
    from tests.conftest import TrackingRunner
    from agent_arborist.git.repo import git_log

    tree = _make_tree()
    log_dir = tmp_path / "logs"

    runner = TrackingRunner(implement_ok=True, review_ok=True)

    # Test command that fails first, passes second
    counter_file = git_repo / ".test-counter"
    counter_file.write_text("0")
    test_cmd = f'c=$(cat {counter_file}); echo "SOME_TEST_ERROR"; echo $((c+1)) > {counter_file}; [ "$c" -gt "0" ]'

    result = garden(tree, git_repo, runner, test_command=test_cmd, max_retries=3, log_dir=log_dir, branch="main")
    assert result.success

    log_output = git_log("HEAD", "%B", git_repo, n=10, grep="tests fail")
    assert "Arborist-Test-Log:" in log_output, (
        f"Test-fail commit should have Arborist-Test-Log trailer, got:\n{log_output}"
    )


def test_review_body_contains_output(git_repo, tmp_path):
    """Review commit body should contain the actual review output, not be empty."""
    from tests.conftest import TrackingRunner
    from agent_arborist.runner import RunResult
    from agent_arborist.git.repo import git_log

    tree = _make_tree()
    log_dir = tmp_path / "logs"

    review_count = {"n": 0}
    runner = TrackingRunner(implement_ok=True, review_ok=False)

    def patched_run(prompt, **kwargs):
        runner.prompts.append(prompt)
        if "review" in prompt.lower():
            review_count["n"] += 1
            if review_count["n"] >= 2:
                return RunResult(success=True, output="APPROVED: looks good now")
            return RunResult(success=False, output="REJECTED: variable naming is inconsistent")
        return RunResult(success=True, output="Implementation complete")

    runner.run = patched_run

    result = garden(tree, git_repo, runner, max_retries=3, log_dir=log_dir, branch="main")
    assert result.success

    log_output = git_log("HEAD", "%B", git_repo, n=10, grep="review rejected")
    assert "variable naming is inconsistent" in log_output, (
        f"Review commit body should contain review output, got:\n{log_output}"
    )


def test_feedback_from_git_history_on_retry(git_repo, tmp_path):
    """On retry, implement prompt should include feedback extracted from git commit history."""
    from tests.conftest import TrackingRunner
    from agent_arborist.runner import RunResult

    tree = _make_tree()
    log_dir = tmp_path / "logs"

    review_count = {"n": 0}
    runner = TrackingRunner(implement_ok=True, review_ok=False)

    def patched_run(prompt, **kwargs):
        runner.prompts.append(prompt)
        if "review" in prompt.lower():
            review_count["n"] += 1
            if review_count["n"] >= 2:
                return RunResult(success=True, output="APPROVED")
            return RunResult(success=False, output="REJECTED: missing error handling in parser")
        return RunResult(success=True, output="Implementation complete")

    runner.run = patched_run

    result = garden(tree, git_repo, runner, max_retries=3, log_dir=log_dir, branch="main")
    assert result.success

    implement_prompts = [p for p in runner.prompts if p.startswith("Implement")]
    assert len(implement_prompts) >= 2, f"Expected at least 2 implement prompts, got {len(implement_prompts)}"

    second_prompt = implement_prompts[1]
    assert "missing error handling in parser" in second_prompt, (
        f"Retry implement prompt should contain review feedback from git history, got:\n{second_prompt[:500]}"
    )


def test_test_failure_feedback_from_git_on_retry(git_repo, tmp_path):
    """On retry after test failure, implement prompt should include test output from git."""
    from tests.conftest import TrackingRunner

    tree = _make_tree()
    log_dir = tmp_path / "logs"

    runner = TrackingRunner(implement_ok=True, review_ok=True)

    counter_file = git_repo / ".test-counter"
    counter_file.write_text("0")
    test_cmd = f'c=$(cat {counter_file}); echo "SOME_TEST_ERROR: assertion failed"; echo $((c+1)) > {counter_file}; [ "$c" -gt "0" ]'

    result = garden(tree, git_repo, runner, test_command=test_cmd, max_retries=3, log_dir=log_dir, branch="main")
    assert result.success

    implement_prompts = [p for p in runner.prompts if p.startswith("Implement")]
    assert len(implement_prompts) >= 2

    second_prompt = implement_prompts[1]
    assert "SOME_TEST_ERROR" in second_prompt, (
        f"Retry implement prompt should contain test failure output from git, got:\n{second_prompt[:500]}"
    )


def test_runner_timeout_passed_to_runner(git_repo, tmp_path):
    """When runner_timeout is set, it should be passed to runner.run() calls."""
    from tests.conftest import TrackingRunner

    tree = _make_tree()
    runner = TrackingRunner(implement_ok=True, review_ok=True)

    result = garden(tree, git_repo, runner, max_retries=3, runner_timeout=120, branch="main")
    assert result.success
    assert all(t == 120 for t in runner.timeouts), f"Expected all timeouts to be 120, got {runner.timeouts}"


def test_runner_timeout_default_when_none(git_repo, tmp_path):
    """When runner_timeout is None, runner should use its own default."""
    from tests.conftest import TrackingRunner

    tree = _make_tree()
    runner = TrackingRunner(implement_ok=True, review_ok=True)

    result = garden(tree, git_repo, runner, max_retries=3, branch="main")
    assert result.success
    assert all(t == 600 for t in runner.timeouts), f"Expected default timeout 600, got {runner.timeouts}"


def test_no_feedback_on_first_attempt(git_repo, tmp_path):
    """First implement prompt should NOT contain any previous feedback."""
    from tests.conftest import TrackingRunner

    tree = _make_tree()
    log_dir = tmp_path / "logs"

    runner = TrackingRunner(implement_ok=True, review_ok=True)

    result = garden(tree, git_repo, runner, max_retries=3, log_dir=log_dir, branch="main")
    assert result.success

    implement_prompts = [p for p in runner.prompts if p.startswith("Implement")]
    assert len(implement_prompts) >= 1

    first_prompt = implement_prompts[0]
    assert "Previous feedback" not in first_prompt, (
        f"First implement prompt should not contain previous feedback section"
    )


# --- Test command parsing tests ---


def test_parse_pytest_output():
    output = "===== 5 passed, 2 failed, 1 skipped in 3.45s ====="
    counts = _parse_test_counts(output, "pytest")
    assert counts == {"passed": 5, "failed": 2, "skipped": 1}


def test_parse_pytest_output_pass_only():
    output = "===== 10 passed in 1.23s ====="
    counts = _parse_test_counts(output, "pytest")
    assert counts == {"passed": 10, "failed": 0, "skipped": 0}


def test_parse_jest_output():
    output = "Tests:  3 passed, 1 failed, 4 total"
    counts = _parse_test_counts(output, "jest")
    assert counts == {"passed": 3, "failed": 1, "skipped": 0}


def test_parse_go_output():
    output = "ok  \tpkg/foo\t0.123s\nFAIL\tpkg/bar\t0.456s\n"
    counts = _parse_test_counts(output, "go")
    assert counts == {"passed": 1, "failed": 1, "skipped": 0}


def test_parse_unknown_output_returns_none():
    counts = _parse_test_counts("some random output", "pytest")
    assert counts is None


def test_parse_auto_detect():
    output = "===== 3 passed in 0.5s ====="
    counts = _parse_test_counts(output, None)
    assert counts is not None
    assert counts["passed"] == 3


# --- Per-node test commands tests ---


def test_run_tests_uses_node_commands(git_repo):
    node = TaskNode(
        id="T001", name="Test",
        test_commands=[TestCommand(type=TestType.UNIT, command="echo '3 passed in 0.1s'", framework="pytest")],
    )
    results = _run_tests(node, git_repo, "false", None)
    assert len(results) == 1
    assert results[0].passed is True
    assert results[0].test_type == "unit"


def test_run_tests_fallback_global(git_repo):
    node = TaskNode(id="T001", name="Test")
    results = _run_tests(node, git_repo, "echo ok", None)
    assert len(results) == 1
    assert results[0].passed is True
    assert results[0].test_type == "unit"


def test_run_tests_respects_timeout(git_repo):
    node = TaskNode(
        id="T001", name="Test",
        test_commands=[TestCommand(type=TestType.UNIT, command="sleep 10", timeout=1)],
    )
    results = _run_tests(node, git_repo, "true", None)
    assert results[0].passed is False
    assert "timed out" in results[0].stderr


def test_run_tests_config_timeout_used(git_repo):
    node = TaskNode(
        id="T001", name="Test",
        test_commands=[TestCommand(type=TestType.UNIT, command="sleep 10")],
    )
    results = _run_tests(node, git_repo, "true", config_timeout=1)
    assert results[0].passed is False


def test_trailers_include_test_metadata(git_repo, mock_runner_all_pass):
    tree = _make_tree()
    tree.nodes["T001"].test_commands = [
        TestCommand(type=TestType.UNIT, command="echo '5 passed in 0.3s'", framework="pytest"),
    ]
    result = garden(tree, git_repo, mock_runner_all_pass, branch="main")
    assert result.success

    log_output = git_log("HEAD", "%B", git_repo, n=20, grep="tests pass")
    assert "Arborist-Test-Type: unit" in log_output
    assert "Arborist-Test-Passed: 5" in log_output
    assert "Arborist-Test-Runtime:" in log_output
