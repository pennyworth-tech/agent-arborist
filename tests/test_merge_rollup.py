"""Tests for merge rollup in hierarchical worktree structure.

These tests verify that child tasks can correctly merge into parent branches
when the parent's worktree is still active (which is the normal case during
DAG execution).
"""

import subprocess
from pathlib import Path

import pytest

from agent_arborist.git_tasks import (
    branch_exists,
    create_task_branch,
    create_worktree,
    find_worktree_for_branch,
    merge_to_parent,
)


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


def get_branch_head(branch: str, cwd: Path) -> str:
    """Get the HEAD commit SHA for a branch."""
    result = subprocess.run(
        ["git", "rev-parse", branch],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def make_commit(message: str, filename: str, content: str, cwd: Path) -> str:
    """Make a commit and return its SHA."""
    (cwd / filename).write_text(content)
    subprocess.run(["git", "add", filename], cwd=cwd, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=cwd,
        capture_output=True,
        check=True,
    )
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def get_commit_log(branch: str, cwd: Path, limit: int = 10) -> list[str]:
    """Get commit messages for a branch."""
    result = subprocess.run(
        ["git", "log", "--oneline", f"-{limit}", branch],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip().split("\n")


class TestMergeToParentWithActiveWorktree:
    """Tests for merging when parent has an active worktree.

    This is the critical scenario during DAG execution:
    - T001 (parent) has worktree on main_a_T001
    - T004 (child of T001) has worktree on main_a_T001_T004
    - T004 finishes and needs to merge into T001's branch
    - But T001's worktree is still active!
    """

    def test_merge_to_parent_uses_existing_worktree(self, git_repo):
        """merge_to_parent should use existing worktree when parent branch has one."""
        main = "main" if branch_exists("main", git_repo) else "master"

        # Create branch hierarchy
        base_branch = f"{main}_a"
        parent_branch = f"{main}_a_T001"
        child_branch = f"{main}_a_T001_T004"

        create_task_branch(base_branch, main, git_repo)
        create_task_branch(parent_branch, base_branch, git_repo)
        create_task_branch(child_branch, parent_branch, git_repo)

        # Create worktrees for both parent and child (simulating DAG execution)
        worktrees_dir = git_repo / ".arborist" / "worktrees" / "test-spec"
        worktrees_dir.mkdir(parents=True, exist_ok=True)

        parent_worktree = worktrees_dir / "T001"
        child_worktree = worktrees_dir / "T004"

        # Create parent worktree first (T001 starts before T004)
        create_worktree(parent_branch, parent_worktree, git_repo)

        # Create child worktree (T004 is a subtask)
        create_worktree(child_branch, child_worktree, git_repo)

        # Make a commit in the child worktree (simulating AI work)
        child_commit = make_commit(
            "task(T004): Add feature from child task",
            "child_feature.txt",
            "Feature implemented by T004\n",
            child_worktree,
        )

        # Verify child branch has the commit
        assert get_branch_head(child_branch, git_repo) == child_commit

        # Now merge child into parent - this should work even though parent has active worktree
        result = merge_to_parent(child_branch, parent_branch, git_repo)

        assert result.success, f"Merge failed: {result.error}"

        # Verify the commit is now in the parent branch
        parent_log = get_commit_log(parent_branch, git_repo)
        assert any("T004" in line for line in parent_log), \
            f"Child commit not found in parent. Log: {parent_log}"

    def test_merge_rollup_through_hierarchy(self, git_repo):
        """Test that merges roll up correctly through the task hierarchy.

        Hierarchy:
        - main_a (base)
          - main_a_T001 (parent task)
            - main_a_T001_T004 (child task)

        T004 merges into T001, then T001 merges into base.
        All branches should contain the original work from T004.
        """
        main = "main" if branch_exists("main", git_repo) else "master"

        # Create branch hierarchy
        base_branch = f"{main}_a"
        parent_branch = f"{main}_a_T001"
        child_branch = f"{main}_a_T001_T004"

        create_task_branch(base_branch, main, git_repo)
        create_task_branch(parent_branch, base_branch, git_repo)
        create_task_branch(child_branch, parent_branch, git_repo)

        # Create worktrees
        worktrees_dir = git_repo / ".arborist" / "worktrees" / "test-spec"
        worktrees_dir.mkdir(parents=True, exist_ok=True)

        parent_worktree = worktrees_dir / "T001"
        child_worktree = worktrees_dir / "T004"

        create_worktree(parent_branch, parent_worktree, git_repo)
        create_worktree(child_branch, child_worktree, git_repo)

        # Make a commit in child
        make_commit(
            "task(T004): Implement child feature",
            "child_file.txt",
            "Child content\n",
            child_worktree,
        )

        # Step 1: Child merges into parent (T004 -> T001)
        result1 = merge_to_parent(child_branch, parent_branch, git_repo)
        assert result1.success, f"Child->Parent merge failed: {result1.error}"

        # Verify parent now has child's file
        assert (parent_worktree / "child_file.txt").exists(), \
            "Child file not found in parent worktree after merge"

        # Step 2: Parent merges into base (T001 -> main_a)
        # Note: base branch has no worktree, so a temporary one is created
        result2 = merge_to_parent(parent_branch, base_branch, git_repo)
        assert result2.success, f"Parent->Base merge failed: {result2.error}"

        # Verify base branch now has the changes
        base_log = get_commit_log(base_branch, git_repo)
        assert any("T001" in line or "T004" in line for line in base_log), \
            f"Merge commits not found in base. Log: {base_log}"

    def test_git_checkout_fails_with_active_worktree(self, git_repo):
        """Verify that git checkout fails when branch has active worktree.

        This test demonstrates why the naive 'git checkout parent' approach
        used in the AI prompt doesn't work.
        """
        main = "main" if branch_exists("main", git_repo) else "master"

        # Create branches
        parent_branch = f"{main}_a_T001"
        child_branch = f"{main}_a_T001_T004"

        create_task_branch(parent_branch, main, git_repo)
        create_task_branch(child_branch, parent_branch, git_repo)

        # Create worktrees
        worktrees_dir = git_repo / ".arborist" / "worktrees" / "test-spec"
        worktrees_dir.mkdir(parents=True, exist_ok=True)

        parent_worktree = worktrees_dir / "T001"
        child_worktree = worktrees_dir / "T004"

        create_worktree(parent_branch, parent_worktree, git_repo)
        create_worktree(child_branch, child_worktree, git_repo)

        # Try to checkout parent branch from child worktree - should fail!
        result = subprocess.run(
            ["git", "checkout", parent_branch],
            cwd=child_worktree,
            capture_output=True,
            text=True,
        )

        # Git should refuse because parent branch is checked out in another worktree
        assert result.returncode != 0, \
            "git checkout should have failed when branch has active worktree"
        assert "already checked out" in result.stderr.lower() or \
               "already used by worktree" in result.stderr.lower(), \
            f"Expected 'already checked out' error, got: {result.stderr}"

    def test_find_worktree_for_branch(self, git_repo):
        """find_worktree_for_branch should find existing worktrees."""
        main = "main" if branch_exists("main", git_repo) else "master"

        branch = f"{main}_a_T001"
        create_task_branch(branch, main, git_repo)

        worktree_path = git_repo / ".arborist" / "worktrees" / "test" / "T001"
        worktree_path.parent.mkdir(parents=True, exist_ok=True)

        # No worktree exists yet
        assert find_worktree_for_branch(branch, git_repo) is None

        # Create worktree
        create_worktree(branch, worktree_path, git_repo)

        # Now it should be found
        found = find_worktree_for_branch(branch, git_repo)
        assert found is not None
        assert found.resolve() == worktree_path.resolve()


class TestMergeToParentWithoutWorktree:
    """Tests for merging when parent branch has no active worktree."""

    def test_merge_creates_temporary_worktree(self, git_repo):
        """merge_to_parent should create temp worktree when parent has none."""
        main = "main" if branch_exists("main", git_repo) else "master"

        base_branch = f"{main}_a"
        child_branch = f"{main}_a_T001"

        create_task_branch(base_branch, main, git_repo)
        create_task_branch(child_branch, base_branch, git_repo)

        # Create worktree only for child
        child_worktree = git_repo / ".arborist" / "worktrees" / "test" / "T001"
        child_worktree.parent.mkdir(parents=True, exist_ok=True)
        create_worktree(child_branch, child_worktree, git_repo)

        # Make a commit in child
        make_commit("task(T001): Feature", "feature.txt", "content\n", child_worktree)

        # Base branch has no worktree
        assert find_worktree_for_branch(base_branch, git_repo) is None

        # Merge should still work (creates temporary worktree)
        result = merge_to_parent(child_branch, base_branch, git_repo)

        assert result.success, f"Merge failed: {result.error}"

        # Verify base branch has the changes
        base_log = get_commit_log(base_branch, git_repo)
        assert any("T001" in line for line in base_log), \
            f"Merge not found in base. Log: {base_log}"


class TestCompleteRollupScenario:
    """End-to-end test of a complete DAG execution rollup scenario."""

    def test_three_level_hierarchy_rollup(self, git_repo):
        """Test rollup through a 3-level task hierarchy.

        Hierarchy:
        - main (source)
          - main_a (base branch for spec)
            - main_a_T001 (parent task)
              - main_a_T001_T004 (grandchild task)

        All work from T004 should eventually be in main_a.
        """
        main = "main" if branch_exists("main", git_repo) else "master"

        # Create full hierarchy
        base_branch = f"{main}_a"
        parent_branch = f"{main}_a_T001"
        grandchild_branch = f"{main}_a_T001_T004"

        create_task_branch(base_branch, main, git_repo)
        create_task_branch(parent_branch, base_branch, git_repo)
        create_task_branch(grandchild_branch, parent_branch, git_repo)

        # Create worktrees (simulating DAG execution order)
        worktrees_dir = git_repo / ".arborist" / "worktrees" / "test-spec"
        worktrees_dir.mkdir(parents=True, exist_ok=True)

        parent_wt = worktrees_dir / "T001"
        grandchild_wt = worktrees_dir / "T004"

        create_worktree(parent_branch, parent_wt, git_repo)
        create_worktree(grandchild_branch, grandchild_wt, git_repo)

        # Grandchild does work
        make_commit(
            "task(T004): Implement grandchild feature",
            "grandchild.txt",
            "Grandchild work\n",
            grandchild_wt,
        )

        # Get initial base branch head
        initial_base_head = get_branch_head(base_branch, git_repo)

        # Step 1: Grandchild -> Parent (while parent worktree active)
        result1 = merge_to_parent(grandchild_branch, parent_branch, git_repo)
        assert result1.success, f"Grandchild->Parent failed: {result1.error}"

        # Verify parent worktree has the file
        assert (parent_wt / "grandchild.txt").exists(), \
            "Grandchild file not in parent worktree"

        # Step 2: Parent -> Base (parent worktree still active, base has none)
        result2 = merge_to_parent(parent_branch, base_branch, git_repo)
        assert result2.success, f"Parent->Base failed: {result2.error}"

        # Verify base branch advanced
        new_base_head = get_branch_head(base_branch, git_repo)
        assert new_base_head != initial_base_head, \
            "Base branch HEAD unchanged after merge"

        # Verify the full history is in base
        base_log = get_commit_log(base_branch, git_repo, 20)
        log_text = "\n".join(base_log)

        # Should have merge commits mentioning both T001 and T004
        assert "T001" in log_text or "T004" in log_text, \
            f"Task references not found in base log: {log_text}"
