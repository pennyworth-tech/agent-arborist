"""Integration tests — validate full flows including git history."""

import json
import subprocess

from pathlib import Path

import pytest

from agent_arborist.git.repo import (
    git_branch_exists,
    git_branch_list,
    git_current_branch,
    git_log,
)
from agent_arborist.git.state import scan_completed_tasks, TaskState, get_task_trailers, task_state_from_trailers
from agent_arborist.tree.model import TaskTree, TaskNode, TestCommand, TestType
from agent_arborist.tree.spec_parser import parse_spec
from agent_arborist.worker.garden import garden as garden_fn, find_next_task
from agent_arborist.worker.gardener import gardener
from agent_arborist.runner import RunResult

FIXTURES = Path(__file__).parent / "fixtures"


class _MockRunner:
    """Inline mock runner (avoids conftest import issues)."""
    def __init__(self, implement_ok=True, review_ok=True):
        self.implement_ok = implement_ok
        self.review_ok = review_ok
        self.name = "mock"
        self.model = "mock-model"

    def run(self, prompt, timeout=60, cwd=None, container_workspace=None):
        if "review" in prompt.lower():
            ok = self.review_ok
            return RunResult(success=ok, output="APPROVED" if ok else "REJECTED")
        return RunResult(success=self.implement_ok, output="Implementation complete")


# ---------------------------------------------------------------------------
# 1. Build → verify task-tree.json and execution order
# ---------------------------------------------------------------------------

class TestBuildFromSpec:
    """Parse a real spec, compute execution order, verify structure."""

    def test_calculator_build_produces_valid_tree(self):
        tree = parse_spec(FIXTURES / "tasks-calculator.md", spec_id="calc")
        tree.compute_execution_order()

        # 4 phases, 12 leaf tasks
        assert len(tree.root_ids) == 4
        assert len(tree.leaves()) == 12
        assert len(tree.execution_order) == 12

        # T001 must come before T002 (direct dep)
        order = tree.execution_order
        assert order.index("T001") < order.index("T002")
        # T005 before T006 (direct dep)
        assert order.index("T005") < order.index("T006")
        # T011 before T012 (cross-phase dep)
        assert order.index("T011") < order.index("T012")

    def test_calculator_branch_names(self):
        tree = parse_spec(FIXTURES / "tasks-calculator.md", spec_id="calc")

        # Phase nodes get their own branches
        assert tree.branch_name("phase1") == "arborist/calc/phase1"
        assert tree.branch_name("phase2") == "arborist/calc/phase2"

        # Leaf tasks inherit their parent phase's branch
        assert tree.branch_name("T001") == "arborist/calc/phase1"
        assert tree.branch_name("T005") == "arborist/calc/phase2"
        assert tree.branch_name("T009") == "arborist/calc/phase3"
        assert tree.branch_name("T012") == "arborist/calc/phase4"

    def test_task_tree_json_roundtrip(self):
        tree = parse_spec(FIXTURES / "tasks-calculator.md", spec_id="calc")
        tree.compute_execution_order()
        data = json.dumps(tree.to_dict(), indent=2)

        restored = TaskTree.from_dict(json.loads(data))
        assert restored.execution_order == tree.execution_order
        assert len(restored.leaves()) == 12
        assert restored.branch_name("T005") == tree.branch_name("T005")


# ---------------------------------------------------------------------------
# 2. Garden single task → verify commit trailers in git history
# ---------------------------------------------------------------------------

class TestGardenCommitHistory:
    """Run garden() for one task, inspect the actual git log."""

    def test_commit_subjects_follow_convention(self, git_repo):
        tree = _small_tree()
        runner = _MockRunner(implement_ok=True, review_ok=True)

        garden_fn(tree, git_repo, runner, base_branch="main")

        # Check commit history on the phase branch
        log = git_log("feature/test/phase1", "%s", git_repo, n=10)
        subjects = [s.strip() for s in log.strip().split("\n") if s.strip()]

        assert any("task(T001): implement" in s for s in subjects)
        assert any("task(T001): test" in s for s in subjects)
        assert any("task(T001): review" in s for s in subjects)
        assert any("task(T001): complete" in s for s in subjects)

    def test_trailers_present_on_commits(self, git_repo, tmp_path):
        tree = _small_tree()
        runner = _MockRunner(implement_ok=True, review_ok=True)
        report_dir = tmp_path / "reports"

        garden_fn(tree, git_repo, runner, base_branch="main", report_dir=report_dir)

        # The most recent task(T001) commit should be the "complete" one
        trailers = get_task_trailers("feature/test/phase1", "T001", git_repo)
        assert trailers["Arborist-Step"] == "complete"
        assert trailers["Arborist-Result"] == "pass"
        assert "Arborist-Report" in trailers

    def test_report_file_written(self, git_repo, tmp_path):
        tree = _small_tree()
        runner = _MockRunner(implement_ok=True, review_ok=True)
        report_dir = tmp_path / "reports"

        garden_fn(tree, git_repo, runner, base_branch="main", report_dir=report_dir)

        reports = list(report_dir.glob("T001_run_*.json"))
        assert len(reports) == 1
        report = json.loads(reports[0].read_text())
        assert report["task_id"] == "T001"
        assert report["result"] == "pass"

    def test_returns_to_base_branch(self, git_repo):
        tree = _small_tree()
        runner = _MockRunner(implement_ok=True, review_ok=True)

        garden_fn(tree, git_repo, runner, base_branch="main")
        assert git_current_branch(git_repo) == "main"


# ---------------------------------------------------------------------------
# 3. Gardener full loop → verify multi-task history + phase merges
# ---------------------------------------------------------------------------

class TestGardenerFullLoop:
    """Run gardener() across multiple tasks, verify branch/merge structure."""

    def test_two_task_single_phase_full_history(self, git_repo):
        """Two tasks in one phase: both complete, phase merged to main."""
        tree = _two_task_tree()
        runner = _MockRunner(implement_ok=True, review_ok=True)

        result = gardener(tree, git_repo, runner, base_branch="main")

        assert result.success
        assert result.tasks_completed == 2
        assert result.order == ["T001", "T002"]

        # Phase branch should exist with commits for both tasks
        log = git_log("feature/test/phase1", "%s", git_repo, n=20)
        assert "task(T001):" in log
        assert "task(T002):" in log

        # Phase should be merged into main (no-ff merge commit)
        main_log = git_log("main", "%s", git_repo, n=5)
        assert "merge" in main_log.lower()

    def test_multi_phase_creates_separate_branches(self, git_repo):
        """Two phases, each with one task → two separate branches, two merges."""
        tree = TaskTree(spec_id="test", namespace="feature")

        from agent_arborist.tree.model import TaskNode
        tree.nodes["phase1"] = TaskNode(id="phase1", name="Phase 1", children=["T001"])
        tree.nodes["T001"] = TaskNode(id="T001", name="Setup", parent="phase1", description="Setup project")
        tree.nodes["phase2"] = TaskNode(id="phase2", name="Phase 2", children=["T002"])
        tree.nodes["T002"] = TaskNode(id="T002", name="Build", parent="phase2", description="Build feature")
        tree.compute_execution_order()

        runner = _MockRunner(implement_ok=True, review_ok=True)
        result = gardener(tree, git_repo, runner, base_branch="main")

        assert result.success
        assert result.tasks_completed == 2

        # Both phase branches should exist
        assert git_branch_exists("feature/test/phase1", git_repo)
        assert git_branch_exists("feature/test/phase2", git_repo)

        # Main should have merge commits for both phases
        main_log = git_log("main", "%s", git_repo, n=10)
        assert "phase1" in main_log
        assert "phase2" in main_log

    def test_dependency_ordering_verified_in_history(self, git_repo):
        """T002 depends on T001 — verify T001 commits appear before T002 on the branch."""
        tree = _two_task_tree()
        runner = _MockRunner(implement_ok=True, review_ok=True)

        gardener(tree, git_repo, runner, base_branch="main")

        # Get all commits on phase branch, oldest first
        log = git_log("feature/test/phase1", "%s", git_repo, n=20)
        subjects = [s.strip() for s in log.strip().split("\n") if s.strip()]
        # git log is newest-first, so reverse for chronological
        subjects.reverse()

        t001_idx = next(i for i, s in enumerate(subjects) if "task(T001): implement" in s)
        t002_idx = next(i for i, s in enumerate(subjects) if "task(T002): implement" in s)
        assert t001_idx < t002_idx, "T001 should be implemented before T002"

    def test_scan_completed_after_gardener(self, git_repo):
        """After gardener completes, scan_completed_tasks finds all tasks."""
        tree = _two_task_tree()
        runner = _MockRunner(implement_ok=True, review_ok=True)

        gardener(tree, git_repo, runner, base_branch="main")

        completed = scan_completed_tasks(tree, git_repo)
        assert completed == {"T001", "T002"}

    def test_gardener_with_non_main_base_branch(self, git_repo):
        """Gardener works when base branch is not 'main' (e.g. 'develop')."""
        from agent_arborist.git.repo import git_checkout, git_add_all, git_commit

        # Create a 'develop' branch with its own commit
        git_checkout("develop", git_repo, create=True)
        (git_repo / "dev-file.txt").write_text("on develop\n")
        git_add_all(git_repo)
        git_commit("initial develop commit", git_repo)

        tree = _two_task_tree()
        runner = _MockRunner(implement_ok=True, review_ok=True)

        result = gardener(tree, git_repo, runner, base_branch="develop")

        assert result.success
        assert result.tasks_completed == 2

        # Should end on develop, not main
        assert git_current_branch(git_repo) == "develop"

        # Phase branch should have been created from develop
        assert git_branch_exists("feature/test/phase1", git_repo)

        # Merge commit should be on develop
        dev_log = git_log("develop", "%s", git_repo, n=5)
        assert "merge" in dev_log.lower()

        # Main should NOT have the merge
        main_log = git_log("main", "%s", git_repo, n=5)
        assert "merge" not in main_log.lower()

        # The dev-file.txt should still exist (we branched from develop)
        assert (git_repo / "dev-file.txt").exists()


# ---------------------------------------------------------------------------
# 4. garden() called repeatedly == gardener()
# ---------------------------------------------------------------------------

class TestGardenRepeatedEquivalence:
    """Calling garden() in a loop must produce the same result as gardener()."""

    def test_repeated_garden_completes_all_tasks(self, git_repo):
        """Calling garden() twice completes both tasks, same as gardener()."""
        tree = _two_task_tree()
        runner = _MockRunner(implement_ok=True, review_ok=True)

        r1 = garden_fn(tree, git_repo, runner, base_branch="main")
        assert r1.success
        assert r1.task_id == "T001"

        r2 = garden_fn(tree, git_repo, runner, base_branch="main")
        assert r2.success
        assert r2.task_id == "T002"

        # Both tasks complete
        completed = scan_completed_tasks(tree, git_repo)
        assert completed == {"T001", "T002"}

    def test_repeated_garden_merges_phase(self, git_repo):
        """garden() merges the phase branch when the last sibling completes."""
        tree = _two_task_tree()
        runner = _MockRunner(implement_ok=True, review_ok=True)

        garden_fn(tree, git_repo, runner, base_branch="main")
        garden_fn(tree, git_repo, runner, base_branch="main")

        # Phase should be merged to main
        main_log = git_log("main", "%s", git_repo, n=5)
        assert "merge" in main_log.lower()
        assert "phase1" in main_log.lower()

    def test_repeated_garden_returns_to_base(self, git_repo):
        """Each garden() call returns to the base branch."""
        tree = _two_task_tree()
        runner = _MockRunner(implement_ok=True, review_ok=True)

        garden_fn(tree, git_repo, runner, base_branch="main")
        assert git_current_branch(git_repo) == "main"

        garden_fn(tree, git_repo, runner, base_branch="main")
        assert git_current_branch(git_repo) == "main"

    def test_repeated_garden_no_task_returns_gracefully(self, git_repo):
        """garden() returns no-ready-task when all tasks are done."""
        tree = _two_task_tree()
        runner = _MockRunner(implement_ok=True, review_ok=True)

        garden_fn(tree, git_repo, runner, base_branch="main")
        garden_fn(tree, git_repo, runner, base_branch="main")

        r3 = garden_fn(tree, git_repo, runner, base_branch="main")
        assert not r3.success
        assert "no ready task" in r3.error

    def test_repeated_garden_multi_phase(self, git_repo):
        """Two phases, each with one task — garden() called twice merges both."""
        from agent_arborist.tree.model import TaskNode
        tree = TaskTree(spec_id="test", namespace="feature")
        tree.nodes["phase1"] = TaskNode(id="phase1", name="P1", children=["T001"])
        tree.nodes["T001"] = TaskNode(id="T001", name="Task 1", parent="phase1", description="Do 1")
        tree.nodes["phase2"] = TaskNode(id="phase2", name="P2", children=["T002"])
        tree.nodes["T002"] = TaskNode(id="T002", name="Task 2", parent="phase2", description="Do 2")
        tree.compute_execution_order()

        runner = _MockRunner(implement_ok=True, review_ok=True)
        garden_fn(tree, git_repo, runner, base_branch="main")
        garden_fn(tree, git_repo, runner, base_branch="main")

        assert git_current_branch(git_repo) == "main"
        main_log = git_log("main", "%s", git_repo, n=10)
        assert "phase1" in main_log
        assert "phase2" in main_log


# ---------------------------------------------------------------------------
# 5. Deep tree (ragged hierarchy) integration
# ---------------------------------------------------------------------------

class TestDeepTreeIntegration:
    """Verify that ragged hierarchies work end-to-end."""

    def test_deep_tree_gardener_completes_all(self, git_repo):
        """Gardener completes all tasks in a 3-level ragged tree."""
        from agent_arborist.tree.model import TaskNode
        tree = TaskTree(spec_id="test", namespace="feature")
        tree.nodes["phase1"] = TaskNode(id="phase1", name="Phase 1", children=["group1", "T003"])
        tree.nodes["group1"] = TaskNode(id="group1", name="Group 1", parent="phase1", children=["T001", "T002"])
        tree.nodes["T001"] = TaskNode(id="T001", name="Schema", parent="group1", description="Create schema")
        tree.nodes["T002"] = TaskNode(id="T002", name="Models", parent="group1", depends_on=["T001"], description="Create models")
        tree.nodes["T003"] = TaskNode(id="T003", name="Frontend", parent="phase1", description="Create frontend")
        tree.compute_execution_order()

        runner = _MockRunner(implement_ok=True, review_ok=True)
        result = gardener(tree, git_repo, runner, base_branch="main")

        assert result.success
        assert result.tasks_completed == 3
        completed = scan_completed_tasks(tree, git_repo)
        assert completed == {"T001", "T002", "T003"}

        # All tasks share one branch
        assert git_branch_exists("feature/test/phase1", git_repo)

        # Phase merged to main
        main_log = git_log("main", "%s", git_repo, n=10)
        assert "merge" in main_log.lower()

    def test_deep_tree_from_spec_fixture(self):
        """Parse the 3-level fixture and verify structure."""
        tree = parse_spec(FIXTURES / "tasks-deep-tree.md", spec_id="deep")
        tree.compute_execution_order()

        assert len(tree.leaves()) == 4
        # All phase1 leaves share branch
        assert tree.branch_name("T001") == "arborist/deep/phase1"
        assert tree.branch_name("T002") == "arborist/deep/phase1"
        assert tree.branch_name("T003") == "arborist/deep/phase1"
        # phase2 leaf has own branch
        assert tree.branch_name("T004") == "arborist/deep/phase2"


# ---------------------------------------------------------------------------
# 6. Base branch auto-detection integration
# ---------------------------------------------------------------------------

class TestBaseBranchAutoDetect:
    """Verify garden works relative to current branch when --base-branch is omitted."""

    def test_garden_from_non_main_branch(self, git_repo):
        """garden() on a feature branch creates phase branch from it and returns to it."""
        from agent_arborist.git.repo import git_checkout, git_add_all, git_commit

        # Create and switch to a non-main branch
        git_checkout("my-feature", git_repo, create=True)
        (git_repo / "feature-file.txt").write_text("on my-feature\n")
        git_add_all(git_repo)
        git_commit("feature commit", git_repo)

        assert git_current_branch(git_repo) == "my-feature"

        tree = _small_tree()
        runner = _MockRunner(implement_ok=True, review_ok=True)

        # Use base_branch=current branch (simulating CLI auto-detection)
        result = garden_fn(tree, git_repo, runner, base_branch="my-feature")

        assert result.success
        assert result.task_id == "T001"

        # Should return to my-feature, not main
        assert git_current_branch(git_repo) == "my-feature"

        # Phase branch should exist
        assert git_branch_exists("feature/test/phase1", git_repo)

        # feature-file.txt should be accessible from the phase branch
        # (since it branched from my-feature)
        subprocess.run(["git", "checkout", "feature/test/phase1"],
                       cwd=git_repo, capture_output=True, check=True)
        assert (git_repo / "feature-file.txt").exists()


# ---------------------------------------------------------------------------
# 7. Separate implement/review runners — dispatch routing
# ---------------------------------------------------------------------------

class TestSeparateRunnerDispatch:
    """Verify implement prompts go to implement_runner, review prompts to review_runner."""

    def test_garden_uses_separate_runners(self, git_repo):
        """Different TrackingRunners for implement vs review — no cross-contamination."""
        from tests.conftest import TrackingRunner

        tree = _small_tree()
        impl_runner = TrackingRunner(name="claude", model="sonnet")
        rev_runner = TrackingRunner(name="gemini", model="pro")

        result = garden_fn(
            tree, git_repo,
            implement_runner=impl_runner,
            review_runner=rev_runner,
            base_branch="main",
        )

        assert result.success
        assert any("Implement" in p for p in impl_runner.prompts)
        assert not any("Review" in p for p in impl_runner.prompts)
        assert any("Review" in p for p in rev_runner.prompts)
        assert not any("Implement" in p for p in rev_runner.prompts)

    def test_gardener_uses_separate_runners(self, git_repo):
        """Full gardener loop with separate runners, all tasks complete with correct dispatch."""
        from tests.conftest import TrackingRunner

        tree = _two_task_tree()
        impl_runner = TrackingRunner(name="claude", model="sonnet")
        rev_runner = TrackingRunner(name="gemini", model="pro")

        result = gardener(
            tree, git_repo,
            implement_runner=impl_runner,
            review_runner=rev_runner,
            base_branch="main",
        )

        assert result.success
        assert result.tasks_completed == 2
        impl_prompts = [p for p in impl_runner.prompts if "Implement" in p]
        assert len(impl_prompts) == 2
        rev_prompts = [p for p in rev_runner.prompts if "Review" in p]
        assert len(rev_prompts) == 2
        assert not any("Review" in p for p in impl_runner.prompts)
        assert not any("Implement" in p for p in rev_runner.prompts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _small_tree() -> TaskTree:
    """Single phase, single task."""
    from agent_arborist.tree.model import TaskNode
    tree = TaskTree(spec_id="test", namespace="feature")
    tree.nodes["phase1"] = TaskNode(id="phase1", name="Phase 1", children=["T001"])
    tree.nodes["T001"] = TaskNode(id="T001", name="Create files", parent="phase1", description="Create initial files")
    tree.compute_execution_order()
    return tree


def _two_task_tree() -> TaskTree:
    """Single phase, two tasks with dependency T001 → T002."""
    tree = TaskTree(spec_id="test", namespace="feature")
    tree.nodes["phase1"] = TaskNode(id="phase1", name="Phase 1", children=["T001", "T002"])
    tree.nodes["T001"] = TaskNode(id="T001", name="Create files", parent="phase1", description="Create initial files")
    tree.nodes["T002"] = TaskNode(id="T002", name="Add tests", parent="phase1", depends_on=["T001"], description="Add test files")
    tree.compute_execution_order()
    return tree


# ---------------------------------------------------------------------------
# 8. Test Commands E2E — per-node tests, trailers, parsing, phase gating
# ---------------------------------------------------------------------------

class TestTestCommandsE2E:
    """End-to-end tests for first-class test commands through the full pipeline."""

    def test_per_node_test_command_runs_and_trailers_recorded(self, git_repo):
        """Leaf with test_commands=[unit pytest] → trailers include type/counts/runtime."""
        tree = TaskTree(spec_id="test", namespace="feature")
        tree.nodes["phase1"] = TaskNode(id="phase1", name="Phase 1", children=["T001"])
        tree.nodes["T001"] = TaskNode(
            id="T001", name="Create files", parent="phase1",
            description="Create initial files",
            test_commands=[TestCommand(
                type=TestType.UNIT,
                command="echo '5 passed, 1 failed in 0.42s'; exit 0",
                framework="pytest",
            )],
        )
        tree.compute_execution_order()

        runner = _MockRunner(implement_ok=True, review_ok=True)
        result = garden_fn(tree, git_repo, runner, base_branch="main")
        assert result.success

        # Check trailers on test commit
        branch = tree.branch_name("T001")
        log_output = git_log(branch, "%B", git_repo, n=20, grep="tests pass")
        assert "Arborist-Test-Type: unit" in log_output
        assert "Arborist-Test-Passed: 5" in log_output
        assert "Arborist-Test-Failed: 1" in log_output
        assert "Arborist-Test-Runtime:" in log_output

    def test_global_fallback_when_no_test_commands(self, git_repo):
        """Node without test_commands falls back to global test_command."""
        tree = TaskTree(spec_id="test", namespace="feature")
        tree.nodes["phase1"] = TaskNode(id="phase1", name="Phase 1", children=["T001"])
        tree.nodes["T001"] = TaskNode(
            id="T001", name="Create files", parent="phase1",
            description="Create initial files",
            # No test_commands — should use global
        )
        tree.compute_execution_order()

        runner = _MockRunner(implement_ok=True, review_ok=True)
        result = garden_fn(
            tree, git_repo, runner,
            test_command="echo 'all good'; exit 0",
            base_branch="main",
        )
        assert result.success

        branch = tree.branch_name("T001")
        log_output = git_log(branch, "%B", git_repo, n=20, grep="tests pass")
        # Fallback should still emit test type trailer as "unit"
        assert "Arborist-Test-Type: unit" in log_output

    def test_test_command_failure_triggers_retry(self, git_repo):
        """Per-node test command that fails first → retry → then passes."""
        counter_file = git_repo / ".test-counter"
        counter_file.write_text("0")

        tree = TaskTree(spec_id="test", namespace="feature")
        tree.nodes["phase1"] = TaskNode(id="phase1", name="Phase 1", children=["T001"])
        tree.nodes["T001"] = TaskNode(
            id="T001", name="Flaky task", parent="phase1",
            description="Task with flaky test",
            test_commands=[TestCommand(
                type=TestType.UNIT,
                command=f'c=$(cat {counter_file}); echo $((c+1)) > {counter_file}; [ "$c" -gt "0" ]',
            )],
        )
        tree.compute_execution_order()

        runner = _MockRunner(implement_ok=True, review_ok=True)
        result = garden_fn(tree, git_repo, runner, max_retries=3, base_branch="main")
        assert result.success

        # Should have at least 2 implement prompts (initial + retry)
        branch = tree.branch_name("T001")
        log_output = git_log(branch, "%s", git_repo, n=30)
        subjects = [s.strip() for s in log_output.strip().split("\n") if s.strip()]
        impl_commits = [s for s in subjects if "implement" in s]
        assert len(impl_commits) >= 2, f"Expected retry, got commits: {subjects}"

    def test_multiple_test_commands_on_one_node(self, git_repo):
        """Node with two test commands — both must pass."""
        tree = TaskTree(spec_id="test", namespace="feature")
        tree.nodes["phase1"] = TaskNode(id="phase1", name="Phase 1", children=["T001"])
        tree.nodes["T001"] = TaskNode(
            id="T001", name="Multi-test task", parent="phase1",
            description="Task with multiple test commands",
            test_commands=[
                TestCommand(type=TestType.UNIT, command="echo 'unit ok'; exit 0"),
                TestCommand(type=TestType.INTEGRATION, command="echo 'integration ok'; exit 0"),
            ],
        )
        tree.compute_execution_order()

        runner = _MockRunner(implement_ok=True, review_ok=True)
        result = garden_fn(tree, git_repo, runner, base_branch="main")
        assert result.success

    def test_multiple_test_commands_one_fails(self, git_repo):
        """If any test command in the list fails, the whole test step fails."""
        tree = TaskTree(spec_id="test", namespace="feature")
        tree.nodes["phase1"] = TaskNode(id="phase1", name="Phase 1", children=["T001"])
        tree.nodes["T001"] = TaskNode(
            id="T001", name="Partial fail", parent="phase1",
            description="First test passes, second fails",
            test_commands=[
                TestCommand(type=TestType.UNIT, command="exit 0"),
                TestCommand(type=TestType.INTEGRATION, command="exit 1"),
            ],
        )
        tree.compute_execution_order()

        runner = _MockRunner(implement_ok=True, review_ok=True)
        result = garden_fn(tree, git_repo, runner, max_retries=1, base_branch="main")
        assert not result.success
        assert "failed after 1 retries" in result.error

    def test_phase_gating_blocks_merge_on_integration_failure(self, git_repo):
        """Parent node integration test fails → phase does NOT merge to base."""
        tree = TaskTree(spec_id="test", namespace="feature")
        tree.nodes["phase1"] = TaskNode(
            id="phase1", name="Phase 1", children=["T001"],
            test_commands=[TestCommand(
                type=TestType.INTEGRATION,
                command="echo 'integration FAIL'; exit 1",
            )],
        )
        tree.nodes["T001"] = TaskNode(
            id="T001", name="Leaf task", parent="phase1",
            description="Simple leaf",
        )
        tree.compute_execution_order()

        runner = _MockRunner(implement_ok=True, review_ok=True)
        result = garden_fn(tree, git_repo, runner, base_branch="main")

        assert not result.success
        assert "Phase test failed" in result.error

        # Main should NOT have a merge commit
        main_log = git_log("main", "%s", git_repo, n=5)
        assert "merge" not in main_log.lower()

    def test_phase_gating_passes_allows_merge(self, git_repo):
        """Parent node integration test passes → phase merges to base."""
        tree = TaskTree(spec_id="test", namespace="feature")
        tree.nodes["phase1"] = TaskNode(
            id="phase1", name="Phase 1", children=["T001"],
            test_commands=[TestCommand(
                type=TestType.INTEGRATION,
                command="echo 'integration OK'; exit 0",
            )],
        )
        tree.nodes["T001"] = TaskNode(
            id="T001", name="Leaf task", parent="phase1",
            description="Simple leaf",
        )
        tree.compute_execution_order()

        runner = _MockRunner(implement_ok=True, review_ok=True)
        result = garden_fn(tree, git_repo, runner, base_branch="main")
        assert result.success

        main_log = git_log("main", "%s", git_repo, n=5)
        assert "merge" in main_log.lower()

    def test_phase_gating_only_runs_integration_e2e_not_unit(self, git_repo):
        """Parent with unit test_commands should NOT gate the merge."""
        tree = TaskTree(spec_id="test", namespace="feature")
        tree.nodes["phase1"] = TaskNode(
            id="phase1", name="Phase 1", children=["T001"],
            test_commands=[TestCommand(
                type=TestType.UNIT,
                command="exit 1",  # Would fail, but should be skipped for phase gating
            )],
        )
        tree.nodes["T001"] = TaskNode(
            id="T001", name="Leaf task", parent="phase1",
            description="Simple leaf",
        )
        tree.compute_execution_order()

        runner = _MockRunner(implement_ok=True, review_ok=True)
        result = garden_fn(tree, git_repo, runner, base_branch="main")
        assert result.success

        main_log = git_log("main", "%s", git_repo, n=5)
        assert "merge" in main_log.lower()

    def test_gardener_full_loop_with_test_commands(self, git_repo):
        """Full gardener loop: two tasks with per-node tests + phase integration test."""
        tree = TaskTree(spec_id="test", namespace="feature")
        tree.nodes["phase1"] = TaskNode(
            id="phase1", name="Phase 1", children=["T001", "T002"],
            test_commands=[TestCommand(
                type=TestType.INTEGRATION,
                command="echo 'integration ok'; exit 0",
            )],
        )
        tree.nodes["T001"] = TaskNode(
            id="T001", name="Create API", parent="phase1",
            description="Build the API",
            test_commands=[TestCommand(
                type=TestType.UNIT,
                command="echo '3 passed in 0.1s'; exit 0",
                framework="pytest",
            )],
        )
        tree.nodes["T002"] = TaskNode(
            id="T002", name="Add auth", parent="phase1",
            depends_on=["T001"],
            description="Add authentication",
            test_commands=[TestCommand(
                type=TestType.UNIT,
                command="echo '2 passed in 0.2s'; exit 0",
                framework="pytest",
            )],
        )
        tree.compute_execution_order()

        runner = _MockRunner(implement_ok=True, review_ok=True)
        result = gardener(tree, git_repo, runner, base_branch="main")

        assert result.success
        assert result.tasks_completed == 2
        assert result.order == ["T001", "T002"]

        # Both tasks complete
        completed = scan_completed_tasks(tree, git_repo)
        assert completed == {"T001", "T002"}

        # Phase merged to main (integration test passed)
        main_log = git_log("main", "%s", git_repo, n=5)
        assert "merge" in main_log.lower()

        # Verify test trailers on the phase branch
        branch = tree.branch_name("T001")
        t001_log = git_log(branch, "%B", git_repo, n=30, grep="tests pass.*Create API")
        # At minimum, some test trailer should be present
        full_log = git_log(branch, "%B", git_repo, n=30, grep="tests pass")
        assert "Arborist-Test-Type: unit" in full_log
        assert "Arborist-Test-Passed:" in full_log

    def test_task_tree_json_roundtrip_with_test_commands(self):
        """task-tree.json with test_commands survives serialization."""
        tree = TaskTree(spec_id="test", namespace="feature")
        tree.nodes["phase1"] = TaskNode(
            id="phase1", name="Phase 1", children=["T001"],
            test_commands=[TestCommand(type=TestType.INTEGRATION, command="pytest tests/integration/")],
        )
        tree.nodes["T001"] = TaskNode(
            id="T001", name="Task", parent="phase1",
            test_commands=[
                TestCommand(type=TestType.UNIT, command="pytest -x", framework="pytest", timeout=60),
            ],
        )
        tree.compute_execution_order()

        # Serialize → deserialize
        data = json.dumps(tree.to_dict(), indent=2)
        restored = TaskTree.from_dict(json.loads(data))

        assert len(restored.nodes["T001"].test_commands) == 1
        tc = restored.nodes["T001"].test_commands[0]
        assert tc.type == TestType.UNIT
        assert tc.command == "pytest -x"
        assert tc.framework == "pytest"
        assert tc.timeout == 60

        assert len(restored.nodes["phase1"].test_commands) == 1
        ptc = restored.nodes["phase1"].test_commands[0]
        assert ptc.type == TestType.INTEGRATION

    def test_test_timeout_from_config_used(self, git_repo):
        """test_timeout parameter is used when per-command timeout is not set."""
        tree = TaskTree(spec_id="test", namespace="feature")
        tree.nodes["phase1"] = TaskNode(id="phase1", name="Phase 1", children=["T001"])
        tree.nodes["T001"] = TaskNode(
            id="T001", name="Slow test", parent="phase1",
            description="Task with slow test",
            test_commands=[TestCommand(
                type=TestType.UNIT,
                command="sleep 10",
                # No per-command timeout — should use test_timeout param
            )],
        )
        tree.compute_execution_order()

        runner = _MockRunner(implement_ok=True, review_ok=True)
        result = garden_fn(
            tree, git_repo, runner,
            max_retries=1, base_branch="main",
            test_timeout=1,  # 1 second timeout
        )
        assert not result.success  # sleep 10 > 1s timeout
