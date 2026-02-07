"""
Test for parallel task execution and merge-based rollup.

This test validates the merge-based approach where:
1. Parallel children each do their work independently
2. Parent creates a merge commit from all children: `jj new child1 child2 child3`
3. Conflicts resolved once in the merge, not via rebasing

Run with:
    pytest tests/test_parallel_rollup.py -v -s --tb=short

To keep the test environment:
    TEST_KEEP_ENV=1 pytest tests/test_parallel_rollup.py -v -s
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agent_arborist.tasks import (
    run_jj,
    create_change,
    get_change_id,
    describe_change,
    mark_task_done,
    create_merge_commit,
)


# =============================================================================
# Skip conditions
# =============================================================================

def check_jj_available():
    """Check if jj CLI is available."""
    return shutil.which("jj") is not None


pytestmark = [
    pytest.mark.skipif(not check_jj_available(), reason="jj CLI not available"),
]


# =============================================================================
# Test Fixtures
# =============================================================================

TEST_DIR = Path("/tmp/rollup-test")
KEEP_ENV = os.environ.get("TEST_KEEP_ENV", "0") == "1"


@pytest.fixture
def jj_repo(tmp_path):
    """Create a colocated jj+git repo for testing."""
    if KEEP_ENV:
        repo_path = TEST_DIR
        if repo_path.exists():
            shutil.rmtree(repo_path)
        repo_path.mkdir(parents=True)
    else:
        repo_path = tmp_path / "repo"
        repo_path.mkdir()

    original_cwd = os.getcwd()
    os.chdir(repo_path)

    try:
        # Initialize git
        subprocess.run(["git", "init"], capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], capture_output=True)

        # Create initial file and commit
        (repo_path / "README.md").write_text("# Test Repo\n")
        subprocess.run(["git", "add", "."], capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], capture_output=True, check=True)

        # Initialize jj colocated
        subprocess.run(["jj", "git", "init", "--colocate"], capture_output=True, check=True)

        # Configure jj user
        subprocess.run(
            ["jj", "config", "set", "--repo", "user.name", "Test User"],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["jj", "config", "set", "--repo", "user.email", "test@test.com"],
            capture_output=True, check=True,
        )

        yield repo_path

    finally:
        os.chdir(original_cwd)
        if not KEEP_ENV:
            shutil.rmtree(repo_path, ignore_errors=True)


# =============================================================================
# Helper Functions
# =============================================================================

def verify_change_has_content(change_id: str, cwd: Path) -> bool:
    """Verify a change has actual file modifications."""
    result = run_jj(
        "log", "-r", change_id, "--no-graph",
        "-T", "if(empty, 'empty', 'has_content')",
        cwd=cwd,
    )
    return "has_content" in result.stdout


# =============================================================================
# Tests: Merge-Based Rollup
# =============================================================================

class TestMergeBasedRollup:
    """Tests for the merge-based rollup approach.

    Instead of squashing children into parents, we:
    1. Children mark themselves [DONE]
    2. Parent creates merge: `jj new child1 child2 -m "parent"`
    """

    def test_parallel_children_merge_into_parent(self, jj_repo):
        """
        Example: Merge-based rollup of parallel children.

        Structure:
            source_rev (main)
                ├── T001 (writes file1.txt) [DONE]
                ├── T002 (writes file2.txt) [DONE]
                └── ROOT merge (jj new T001 T002)

        Flow:
        1. Create child changes from source
        2. Each child writes a file and marks [DONE]
        3. Parent creates merge commit from all children
        4. Merge has all children's files
        """
        spec_id = "test-merge"
        os.chdir(jj_repo)

        # Get source revision
        source_rev = get_change_id("@", jj_repo)

        # Create two parallel child changes
        t001 = create_change(parent=source_rev, description=f"{spec_id}:T001", cwd=jj_repo)
        t002 = create_change(parent=source_rev, description=f"{spec_id}:T002", cwd=jj_repo)

        # T001 does its work
        run_jj("edit", t001, cwd=jj_repo)
        (jj_repo / "file1.txt").write_text("Content from T001\n")
        run_jj("status", cwd=jj_repo)  # Snapshot
        mark_task_done("T001", t001, jj_repo)

        # T002 does its work
        run_jj("edit", t002, cwd=jj_repo)
        (jj_repo / "file2.txt").write_text("Content from T002\n")
        run_jj("status", cwd=jj_repo)  # Snapshot
        mark_task_done("T002", t002, jj_repo)

        # Parent creates merge from both children
        merge_change_id = create_merge_commit(
            parent_changes=[t001, t002],
            description=f"{spec_id}:ROOT",
            cwd=jj_repo,
        )

        assert merge_change_id, "Merge should return a change ID"

        # Verify merge has content from both children
        run_jj("edit", merge_change_id, cwd=jj_repo)

        assert (jj_repo / "file1.txt").exists(), "Merge should have file1.txt from T001"
        assert (jj_repo / "file2.txt").exists(), "Merge should have file2.txt from T002"
        assert (jj_repo / "file1.txt").read_text() == "Content from T001\n"
        assert (jj_repo / "file2.txt").read_text() == "Content from T002\n"


# =============================================================================
# Tests: Workspace Snapshot Behavior
# =============================================================================

class TestWorkspaceSnapshotBehavior:
    """Tests to understand jj workspace snapshot behavior."""

    def test_jj_status_triggers_snapshot(self, jj_repo):
        """Verify that jj status captures pending file changes."""
        os.chdir(jj_repo)

        # Write a file without any jj interaction
        (jj_repo / "new_file.txt").write_text("Hello world\n")

        # Run status to trigger snapshot
        result = run_jj("status", cwd=jj_repo)

        # Now jj should see the file
        assert "new_file.txt" in result.stdout

    def test_jj_log_triggers_snapshot(self, jj_repo):
        """Verify that jj log also captures pending changes."""
        os.chdir(jj_repo)

        # Write file
        (jj_repo / "another_file.txt").write_text("Content\n")

        # Run log (this should also snapshot)
        run_jj("log", "--limit", "1", cwd=jj_repo)

        # Verify via diff
        result = run_jj("diff", cwd=jj_repo)
        assert "another_file.txt" in result.stdout

    def test_workspace_isolation(self, jj_repo):
        """Verify workspaces have isolated working copies."""
        os.chdir(jj_repo)

        # Create two workspaces
        ws1_path = jj_repo / "ws1"
        ws2_path = jj_repo / "ws2"
        ws1_path.mkdir()
        ws2_path.mkdir()

        run_jj("workspace", "add", str(ws1_path), cwd=jj_repo)
        run_jj("workspace", "add", str(ws2_path), cwd=jj_repo)

        # Write different files in each workspace
        (ws1_path / "ws1_file.txt").write_text("From workspace 1\n")
        (ws2_path / "ws2_file.txt").write_text("From workspace 2\n")

        # Snapshot each
        run_jj("status", cwd=ws1_path)
        run_jj("status", cwd=ws2_path)

        # Verify they're independent
        ws1_diff = run_jj("diff", cwd=ws1_path)
        ws2_diff = run_jj("diff", cwd=ws2_path)

        assert "ws1_file.txt" in ws1_diff.stdout
        assert "ws2_file.txt" not in ws1_diff.stdout

        assert "ws2_file.txt" in ws2_diff.stdout
        assert "ws1_file.txt" not in ws2_diff.stdout


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])
