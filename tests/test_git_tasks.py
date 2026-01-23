"""Tests for git_tasks module."""

import subprocess
from pathlib import Path

import pytest

from agent_arborist.git_tasks import (
    find_parent_branch,
    branch_exists,
    create_task_branch,
    get_worktree_path,
    detect_test_command,
    create_all_branches_from_manifest,
    sync_task,
)
from agent_arborist.branch_manifest import (
    BranchManifest,
    TaskBranchInfo,
    generate_manifest,
    topological_sort,
)
from agent_arborist.task_state import TaskTree, TaskNode


class TestWorktreePath:
    """Tests for worktree path generation."""

    def test_worktree_path(self, tmp_path, monkeypatch):
        """Worktree path for a task."""
        from agent_arborist import git_tasks
        monkeypatch.setattr(git_tasks, "get_arborist_home", lambda: tmp_path)

        path = get_worktree_path("002-feature", "T001")
        expected = tmp_path / "worktrees" / "002-feature" / "T001"
        assert path == expected

    def test_worktree_path_child_task(self, tmp_path, monkeypatch):
        """Worktree path for a child task (same structure)."""
        from agent_arborist import git_tasks
        monkeypatch.setattr(git_tasks, "get_arborist_home", lambda: tmp_path)

        path = get_worktree_path("002-feature", "T004")
        expected = tmp_path / "worktrees" / "002-feature" / "T004"
        assert path == expected


class TestDetectTestCommand:
    """Tests for test command auto-detection."""

    def test_detect_pytest_from_pyproject(self, tmp_path):
        """Detects pytest from pyproject.toml."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        assert detect_test_command(tmp_path) == "pytest"

    def test_detect_pytest_from_pytest_ini(self, tmp_path):
        """Detects pytest from pytest.ini."""
        (tmp_path / "pytest.ini").write_text("[pytest]\n")
        assert detect_test_command(tmp_path) == "pytest"

    def test_detect_npm_test(self, tmp_path):
        """Detects npm test from package.json."""
        (tmp_path / "package.json").write_text('{"name": "test"}\n')
        assert detect_test_command(tmp_path) == "npm test"

    def test_detect_make_test(self, tmp_path):
        """Detects make test from Makefile with test target."""
        (tmp_path / "Makefile").write_text("test:\n\tpytest\n")
        assert detect_test_command(tmp_path) == "make test"

    def test_no_test_makefile_without_target(self, tmp_path):
        """Does not detect make test if no test target."""
        (tmp_path / "Makefile").write_text("build:\n\tgcc main.c\n")
        assert detect_test_command(tmp_path) is None

    def test_detect_cargo_test(self, tmp_path):
        """Detects cargo test from Cargo.toml."""
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "test"\n')
        assert detect_test_command(tmp_path) == "cargo test"

    def test_detect_go_test(self, tmp_path):
        """Detects go test from go.mod."""
        (tmp_path / "go.mod").write_text("module test\n")
        assert detect_test_command(tmp_path) == "go test ./..."

    def test_no_detection_empty_dir(self, tmp_path):
        """Returns None for empty directory."""
        assert detect_test_command(tmp_path) is None


@pytest.fixture
def git_repo(tmp_path):
    """Create a temporary git repository."""
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    # Create initial commit
    (tmp_path / "README.md").write_text("# Test\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    return tmp_path


class TestBranchOperations:
    """Tests for branch operations (require git repo)."""

    def test_branch_exists_main(self, git_repo):
        """Main branch should exist after init."""
        # Could be 'main' or 'master' depending on git version
        assert branch_exists("main", git_repo) or branch_exists("master", git_repo)

    def test_branch_exists_false(self, git_repo):
        """Non-existent branch returns False."""
        assert branch_exists("nonexistent-branch", git_repo) is False

    def test_create_task_branch(self, git_repo):
        """Can create a new branch."""
        main = "main" if branch_exists("main", git_repo) else "master"
        result = create_task_branch("feature_a_T001", main, git_repo)
        assert result.success
        assert branch_exists("feature_a_T001", git_repo)

    def test_create_task_branch_idempotent(self, git_repo):
        """Creating existing branch is a no-op."""
        main = "main" if branch_exists("main", git_repo) else "master"
        create_task_branch("feature_a_T001", main, git_repo)
        result = create_task_branch("feature_a_T001", main, git_repo)
        assert result.success
        assert "already exists" in result.message


class TestFindParentBranch:
    """Tests for finding parent branch."""

    def test_find_parent_from_task_branch(self, git_repo):
        """Finds parent by walking up hierarchy (underscore naming)."""
        main = "main" if branch_exists("main", git_repo) else "master"

        # Create base branch
        create_task_branch("main_a", main, git_repo)

        # Find parent of task branch (main_a_T001 -> main_a)
        parent = find_parent_branch("main_a_T001", git_repo)
        assert parent == "main_a"

    def test_find_parent_from_nested_task(self, git_repo):
        """Finds parent from deeply nested task (underscore naming)."""
        main = "main" if branch_exists("main", git_repo) else "master"

        # Create hierarchy with underscore naming
        create_task_branch("main_a", main, git_repo)
        create_task_branch("main_a_T001", "main_a", git_repo)

        # Verify hierarchy was created
        assert branch_exists("main_a", git_repo)
        assert branch_exists("main_a_T001", git_repo)

        # Find parent of deeply nested task (T004 under T001)
        # main_a_T001_T004 -> main_a_T001
        parent = find_parent_branch("main_a_T001_T004", git_repo)
        assert parent == "main_a_T001"

    def test_find_parent_falls_back_to_main(self, git_repo):
        """Falls back to main if no intermediate branch exists."""
        parent = find_parent_branch("nonexistent_a_T001", git_repo)
        assert parent in ("main", "master")


class TestCreateAllBranches:
    """Tests for bulk branch creation from manifest."""

    def test_create_all_branches(self, git_repo):
        """Creates all branches from manifest in correct order."""
        main = "main" if branch_exists("main", git_repo) else "master"

        manifest = BranchManifest(
            source_branch=main,
            base_branch=f"{main}_a",
            spec_id="002-feature",
            created_at="2025-01-01T00:00:00Z",
            tasks={
                "T001": TaskBranchInfo(
                    task_id="T001",
                    branch=f"{main}_a_T001",
                    parent_branch=f"{main}_a",
                    parent_task=None,
                    children=["T004"],
                ),
                "T004": TaskBranchInfo(
                    task_id="T004",
                    branch=f"{main}_a_T001_T004",
                    parent_branch=f"{main}_a_T001",
                    parent_task="T001",
                    children=[],
                ),
            },
        )

        result = create_all_branches_from_manifest(manifest, git_repo)
        assert result.success

        # Verify all branches exist
        assert branch_exists(f"{main}_a", git_repo)
        assert branch_exists(f"{main}_a_T001", git_repo)
        assert branch_exists(f"{main}_a_T001_T004", git_repo)

    def test_create_all_branches_idempotent(self, git_repo):
        """Creating branches that already exist succeeds."""
        main = "main" if branch_exists("main", git_repo) else "master"

        manifest = BranchManifest(
            source_branch=main,
            base_branch=f"{main}_a",
            spec_id="002-feature",
            created_at="2025-01-01T00:00:00Z",
            tasks={
                "T001": TaskBranchInfo(
                    task_id="T001",
                    branch=f"{main}_a_T001",
                    parent_branch=f"{main}_a",
                    parent_task=None,
                    children=[],
                ),
            },
        )

        # Create twice
        result1 = create_all_branches_from_manifest(manifest, git_repo)
        result2 = create_all_branches_from_manifest(manifest, git_repo)

        assert result1.success
        assert result2.success


class TestBranchManifest:
    """Tests for branch manifest generation."""

    def test_generate_manifest_basic(self):
        """Generates manifest with correct branch names."""
        tree = TaskTree(spec_id="002-feature")
        tree.tasks["T001"] = TaskNode(
            task_id="T001",
            description="First task",
            parent_id=None,
            children=["T004"],
        )
        tree.tasks["T004"] = TaskNode(
            task_id="T004",
            description="Child task",
            parent_id="T001",
            children=[],
        )
        tree.root_tasks = ["T001"]

        manifest = generate_manifest("002-feature", tree, "feature-auth")

        assert manifest.source_branch == "feature-auth"
        assert manifest.base_branch == "feature-auth_a"
        assert manifest.spec_id == "002-feature"

        assert manifest.tasks["T001"].branch == "feature-auth_a_T001"
        assert manifest.tasks["T001"].parent_branch == "feature-auth_a"

        assert manifest.tasks["T004"].branch == "feature-auth_a_T001_T004"
        assert manifest.tasks["T004"].parent_branch == "feature-auth_a_T001"

    def test_topological_sort_simple(self):
        """Sorts tasks with parents before children."""
        tasks = {
            "T001": TaskBranchInfo(
                task_id="T001",
                branch="main_a_T001",
                parent_branch="main_a",
                parent_task=None,
                children=["T004"],
            ),
            "T004": TaskBranchInfo(
                task_id="T004",
                branch="main_a_T001_T004",
                parent_branch="main_a_T001",
                parent_task="T001",
                children=[],
            ),
        }

        order = topological_sort(tasks)
        assert order.index("T001") < order.index("T004")

    def test_topological_sort_multiple_roots(self):
        """Handles multiple root tasks."""
        tasks = {
            "T001": TaskBranchInfo(
                task_id="T001",
                branch="main_a_T001",
                parent_branch="main_a",
                parent_task=None,
                children=[],
            ),
            "T002": TaskBranchInfo(
                task_id="T002",
                branch="main_a_T002",
                parent_branch="main_a",
                parent_task=None,
                children=[],
            ),
        }

        order = topological_sort(tasks)
        assert len(order) == 2
        assert set(order) == {"T001", "T002"}
