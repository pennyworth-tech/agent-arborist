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
from agent_arborist.tree.model import TaskTree
from agent_arborist.tree.spec_parser import parse_spec
from agent_arborist.worker.garden import garden, find_next_task
from agent_arborist.worker.gardener import gardener
from agent_arborist.runner import RunResult

FIXTURES = Path(__file__).parent / "fixtures"


class _MockRunner:
    """Inline mock runner (avoids conftest import issues)."""
    def __init__(self, implement_ok=True, review_ok=True):
        self.implement_ok = implement_ok
        self.review_ok = review_ok
        self.name = "mock"

    def run(self, prompt, timeout=60, cwd=None, container_cmd_prefix=None):
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
        assert tree.branch_name("phase1") == "feature/calc/phase1"
        assert tree.branch_name("phase2") == "feature/calc/phase2"

        # Leaf tasks inherit their parent phase's branch
        assert tree.branch_name("T001") == "feature/calc/phase1"
        assert tree.branch_name("T005") == "feature/calc/phase2"
        assert tree.branch_name("T009") == "feature/calc/phase3"
        assert tree.branch_name("T012") == "feature/calc/phase4"

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

        garden(tree, git_repo, runner, base_branch="main")

        # Check commit history on the phase branch
        log = git_log("feature/test/phase1", "%s", git_repo, n=10)
        subjects = [s.strip() for s in log.strip().split("\n") if s.strip()]

        assert any("task(T001): implement" in s for s in subjects)
        assert any("task(T001): test" in s for s in subjects)
        assert any("task(T001): review" in s for s in subjects)
        assert any("task(T001): complete" in s for s in subjects)

    def test_trailers_present_on_commits(self, git_repo):
        tree = _small_tree()
        runner = _MockRunner(implement_ok=True, review_ok=True)

        garden(tree, git_repo, runner, base_branch="main")

        # The most recent task(T001) commit should be the "complete" one
        trailers = get_task_trailers("feature/test/phase1", "T001", git_repo)
        assert trailers["Arborist-Step"] == "complete"
        assert trailers["Arborist-Result"] == "pass"
        assert "Arborist-Report" in trailers

    def test_report_file_written(self, git_repo):
        tree = _small_tree()
        runner = _MockRunner(implement_ok=True, review_ok=True)

        garden(tree, git_repo, runner, base_branch="main")

        # Switch to phase branch to see the report
        subprocess.run(["git", "checkout", "feature/test/phase1"],
                       cwd=git_repo, capture_output=True, check=True)
        report_path = git_repo / "spec" / "reports" / "T001.json"
        assert report_path.exists()
        report = json.loads(report_path.read_text())
        assert report["task_id"] == "T001"
        assert report["result"] == "pass"

    def test_returns_to_base_branch(self, git_repo):
        tree = _small_tree()
        runner = _MockRunner(implement_ok=True, review_ok=True)

        garden(tree, git_repo, runner, base_branch="main")
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
        tree.root_ids = ["phase1", "phase2"]

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
# Helpers
# ---------------------------------------------------------------------------

def _small_tree() -> TaskTree:
    """Single phase, single task."""
    from agent_arborist.tree.model import TaskNode
    tree = TaskTree(spec_id="test", namespace="feature")
    tree.root_ids = ["phase1"]
    tree.nodes["phase1"] = TaskNode(id="phase1", name="Phase 1", children=["T001"])
    tree.nodes["T001"] = TaskNode(id="T001", name="Create files", parent="phase1", description="Create initial files")
    tree.compute_execution_order()
    return tree


def _two_task_tree() -> TaskTree:
    """Single phase, two tasks with dependency T001 → T002."""
    from agent_arborist.tree.model import TaskNode
    tree = TaskTree(spec_id="test", namespace="feature")
    tree.root_ids = ["phase1"]
    tree.nodes["phase1"] = TaskNode(id="phase1", name="Phase 1", children=["T001", "T002"])
    tree.nodes["T001"] = TaskNode(id="T001", name="Create files", parent="phase1", description="Create initial files")
    tree.nodes["T002"] = TaskNode(id="T002", name="Add tests", parent="phase1", depends_on=["T001"], description="Add test files")
    tree.compute_execution_order()
    return tree
