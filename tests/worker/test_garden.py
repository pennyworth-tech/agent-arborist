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
    result = garden(tree, git_repo, runner, max_retries=3, base_branch="main", log_dir=log_dir)
    assert result.success

    # Check the review commit on the phase branch has the trailer
    branch = tree.branch_name("T001")
    log_output = git_log(branch, "%B", git_repo, n=10, grep="review")
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

    result = garden(tree, git_repo, runner, test_command=test_cmd, max_retries=3, base_branch="main", log_dir=log_dir)
    assert result.success

    branch = tree.branch_name("T001")
    log_output = git_log(branch, "%B", git_repo, n=10, grep="tests fail")
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

    result = garden(tree, git_repo, runner, max_retries=3, base_branch="main", log_dir=log_dir)
    assert result.success

    branch = tree.branch_name("T001")
    log_output = git_log(branch, "%B", git_repo, n=10, grep="review rejected")
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

    result = garden(tree, git_repo, runner, max_retries=3, base_branch="main", log_dir=log_dir)
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

    result = garden(tree, git_repo, runner, test_command=test_cmd, max_retries=3, base_branch="main", log_dir=log_dir)
    assert result.success

    implement_prompts = [p for p in runner.prompts if p.startswith("Implement")]
    assert len(implement_prompts) >= 2

    second_prompt = implement_prompts[1]
    assert "SOME_TEST_ERROR" in second_prompt, (
        f"Retry implement prompt should contain test failure output from git, got:\n{second_prompt[:500]}"
    )


def test_no_feedback_on_first_attempt(git_repo, tmp_path):
    """First implement prompt should NOT contain any previous feedback."""
    from tests.conftest import TrackingRunner

    tree = _make_tree()
    log_dir = tmp_path / "logs"

    runner = TrackingRunner(implement_ok=True, review_ok=True)

    result = garden(tree, git_repo, runner, max_retries=3, base_branch="main", log_dir=log_dir)
    assert result.success

    implement_prompts = [p for p in runner.prompts if p.startswith("Implement")]
    assert len(implement_prompts) >= 1

    first_prompt = implement_prompts[0]
    assert "Previous feedback" not in first_prompt, (
        f"First implement prompt should not contain previous feedback section"
    )
