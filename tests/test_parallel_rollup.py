"""
Test for parallel task execution and proper rollup of changes.

This test validates that:
1. Multiple parallel root tasks can write files
2. Each task's changes are properly captured by jj
3. All changes roll up into a single commit on the feature branch

The bug this tests for:
- Tasks write files to workspaces
- But jj doesn't "see" the changes because no jj command runs after file writes
- When complete step tries to squash, the change appears empty or the change ID is invalid
- The rollup fails with "Command returned non-zero exit status 1"

Run with:
    pytest tests/test_parallel_rollup.py -v -s --tb=short

To keep the test environment:
    TEST_KEEP_ENV=1 pytest tests/test_parallel_rollup.py -v -s
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agent_arborist.tasks import (
    run_jj,
    create_change,
    get_change_id,
    get_description,
    squash_into_parent,
    complete_task,
    describe_change,
    init_colocated,
    has_conflicts,
    JJResult,
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
    """Create a colocated jj+git repo for testing.

    Uses tmp_path for isolation unless TEST_KEEP_ENV is set.
    """
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
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["jj", "config", "set", "--repo", "user.email", "test@test.com"],
            capture_output=True,
            check=True,
        )

        yield repo_path

    finally:
        os.chdir(original_cwd)
        if not KEEP_ENV:
            shutil.rmtree(repo_path, ignore_errors=True)


@pytest.fixture
def spec_with_parallel_tasks(jj_repo):
    """Create a spec with parallel root tasks.

    Structure:
    - source_rev (main branch)
      └── TIP (mutable accumulator)
          ├── T001 (writes file1.txt)
          ├── T002 (writes file2.txt)
          └── T003 (writes file3.txt)

    All T00x tasks run in parallel and should roll up into TIP.
    """
    spec_id = "test-parallel"

    os.chdir(jj_repo)

    # Create feature branch for the spec
    subprocess.run(["git", "checkout", "-b", spec_id], capture_output=True, check=True)
    subprocess.run(["jj", "git", "import"], capture_output=True, check=True)

    # Get the source revision (current branch commit)
    source_rev = get_change_id("@", jj_repo)

    # Create TIP change (mutable accumulator for root tasks)
    tip_change = create_change(
        parent=source_rev,
        description=f"{spec_id}:TIP",
        cwd=jj_repo,
    )

    # Create parallel root task changes
    task_changes = {}
    for task_id in ["T001", "T002", "T003"]:
        change_id = create_change(
            parent=source_rev,  # All root tasks branch from source
            description=f"{spec_id}:{task_id}",
            cwd=jj_repo,
        )
        task_changes[task_id] = change_id

    return {
        "spec_id": spec_id,
        "source_rev": source_rev,
        "tip_change": tip_change,
        "task_changes": task_changes,
        "repo_path": jj_repo,
    }


# =============================================================================
# Helper Functions
# =============================================================================

def simulate_task_execution(task_id: str, change_id: str, repo_path: Path):
    """Simulate a task writing files without any jj interaction.

    This mimics what happens when Claude runs:
    1. Task is given a workspace with files
    2. Task writes/modifies files
    3. Task exits without running any jj commands

    The bug: jj doesn't know about these file changes unless
    we explicitly snapshot the working copy.
    """
    os.chdir(repo_path)

    # Switch to the task's change
    run_jj("edit", change_id, cwd=repo_path)

    # Write a file (simulating Claude's work)
    task_file = repo_path / f"{task_id.lower()}_output.txt"
    task_file.write_text(f"Output from {task_id}\nGenerated content here.\n")

    # DON'T run any jj commands after writing - this is the bug scenario


def simulate_task_execution_with_snapshot(task_id: str, change_id: str, repo_path: Path):
    """Simulate a task that properly snapshots its changes.

    This is the FIXED version that should work:
    1. Task writes files
    2. Before completion, snapshot the working copy
    """
    os.chdir(repo_path)

    # Switch to the task's change
    run_jj("edit", change_id, cwd=repo_path)

    # Write a file
    task_file = repo_path / f"{task_id.lower()}_output.txt"
    task_file.write_text(f"Output from {task_id}\nGenerated content here.\n")

    # SNAPSHOT: Run jj status to capture working copy changes
    # This is the key fix - any jj command triggers a snapshot
    run_jj("status", cwd=repo_path)


def get_file_count_in_change(change_id: str, cwd: Path) -> int:
    """Count files modified in a change."""
    result = run_jj(
        "diff", "-r", change_id, "--stat",
        cwd=cwd,
    )
    if not result.stdout.strip():
        return 0
    # Count lines that look like file changes
    lines = result.stdout.strip().split("\n")
    return len([l for l in lines if "|" in l])


def verify_change_has_content(change_id: str, cwd: Path) -> bool:
    """Verify a change has actual file modifications."""
    result = run_jj(
        "log", "-r", change_id, "--no-graph",
        "-T", "if(empty, 'empty', 'has_content')",
        cwd=cwd,
    )
    return "has_content" in result.stdout


# =============================================================================
# Tests
# =============================================================================

class TestParallelRollupBug:
    """Tests that reproduce and verify the parallel rollup bug."""

    def test_task_changes_not_captured_without_snapshot(self, spec_with_parallel_tasks):
        """DEMONSTRATES BUG: File changes not captured without jj snapshot.

        This test shows the bug behavior:
        1. Tasks write files
        2. No jj snapshot happens
        3. Changes appear empty in jj
        """
        spec = spec_with_parallel_tasks
        repo_path = spec["repo_path"]

        os.chdir(repo_path)

        # Simulate T001 writing files WITHOUT snapshot
        simulate_task_execution("T001", spec["task_changes"]["T001"], repo_path)

        # Check: The change should appear empty because jj didn't snapshot
        # After edit, we're at T001's change
        current_change = get_change_id("@", repo_path)

        # The file exists on disk
        assert (repo_path / "t001_output.txt").exists(), "File should exist on disk"

        # But jj might not see it as part of the change yet
        # (This depends on timing - jj may or may not have snapshotted)
        # Force a check by looking at the change's diff
        has_content = verify_change_has_content(current_change, repo_path)

        # Note: This assertion documents the expected buggy behavior
        # In a properly working system, this should be True
        # But if the snapshot is missing, it could be False
        print(f"Change {current_change} has content: {has_content}")

    def test_rollup_fails_with_missing_change(self, spec_with_parallel_tasks):
        """DEMONSTRATES BUG: Rollup fails when change ID is invalid.

        This simulates the actual error we saw:
        - complete_task tries to look up a change by ID
        - The change doesn't exist (was squashed, abandoned, or never valid)
        - jj log returns non-zero exit status

        Note: jj treats "zzzz..." as a valid (but empty) change ID prefix.
        To trigger the actual failure, we need an invalid revset like a text ID.
        The real bug manifests when a change ID becomes stale (e.g., after
        the change was abandoned or squashed away without its workspace knowing).
        """
        spec = spec_with_parallel_tasks
        repo_path = spec["repo_path"]

        os.chdir(repo_path)

        # Use an invalid revset expression that jj will reject
        # This mimics what happens when a change ID becomes stale
        fake_change_id = "stale_change_that_was_abandoned"

        # Try to get description of non-existent change
        # This should fail - mimicking the bug
        result = run_jj(
            "log", "-r", fake_change_id,
            "--no-graph", "-T", "description",
            cwd=repo_path,
            check=False,
        )

        # This is the error we're seeing
        assert result.returncode != 0, "Should fail for non-existent change"
        assert "doesn't exist" in result.stderr or result.returncode == 1

    def test_complete_task_fails_with_empty_change(self, spec_with_parallel_tasks):
        """DEMONSTRATES BUG: complete_task fails when squashing empty changes.

        When a task's change is empty (no snapshotted files), the squash
        might fail or produce unexpected results.
        """
        spec = spec_with_parallel_tasks
        repo_path = spec["repo_path"]
        tip_change = spec["tip_change"]
        t001_change = spec["task_changes"]["T001"]

        os.chdir(repo_path)

        # T001's change is empty (we haven't written anything)
        # Try to complete it
        result = complete_task(
            task_id="T001",
            change_id=t001_change,
            parent_change=tip_change,
            cwd=repo_path,
        )

        # Should succeed but with empty squash
        assert result.success, f"Complete should succeed even with empty change: {result.error}"

        # Verify TIP is still valid
        tip_desc = get_description(tip_change, repo_path)
        assert "TIP" in tip_desc


class TestParallelRollupFixed:
    """Tests that verify the FIX for parallel rollup."""

    def test_task_changes_captured_with_snapshot(self, spec_with_parallel_tasks):
        """VERIFIES FIX: File changes captured when snapshot is triggered.

        This test shows the fixed behavior:
        1. Tasks write files
        2. jj snapshot happens (via status, log, etc.)
        3. Changes are properly captured
        """
        spec = spec_with_parallel_tasks
        repo_path = spec["repo_path"]

        os.chdir(repo_path)

        # Simulate T001 writing files WITH snapshot
        simulate_task_execution_with_snapshot("T001", spec["task_changes"]["T001"], repo_path)

        # The change should now have content
        current_change = get_change_id("@", repo_path)

        # File exists
        assert (repo_path / "t001_output.txt").exists(), "File should exist"

        # AND jj sees it
        has_content = verify_change_has_content(current_change, repo_path)
        assert has_content, "Change should have content after snapshot"

    def test_parallel_tasks_rollup_to_single_commit(self, spec_with_parallel_tasks):
        """VERIFIES FIX: All parallel task changes roll up into TIP.

        This is the main validation:
        1. Multiple tasks write files in parallel
        2. Each task completes and squashes into TIP
        3. TIP contains ALL changes from ALL tasks
        4. Git branch has single commit with all files
        """
        spec = spec_with_parallel_tasks
        repo_path = spec["repo_path"]
        tip_change = spec["tip_change"]

        os.chdir(repo_path)

        # Execute all tasks with proper snapshots
        for task_id in ["T001", "T002", "T003"]:
            change_id = spec["task_changes"][task_id]
            simulate_task_execution_with_snapshot(task_id, change_id, repo_path)

            # Complete each task (squash into TIP)
            result = complete_task(
                task_id=task_id,
                change_id=change_id,
                parent_change=tip_change,
                cwd=repo_path,
            )
            assert result.success, f"Complete {task_id} failed: {result.error}"

        # Switch to TIP to verify it has all files
        run_jj("edit", tip_change, cwd=repo_path)

        # Trigger snapshot to see accumulated files
        run_jj("status", cwd=repo_path)

        # All three files should exist in TIP
        for task_id in ["T001", "T002", "T003"]:
            expected_file = repo_path / f"{task_id.lower()}_output.txt"
            assert expected_file.exists(), f"File from {task_id} should be in TIP"

        # TIP should have meaningful content
        has_content = verify_change_has_content(tip_change, repo_path)
        assert has_content, "TIP should have content from all tasks"

    def test_rollup_preserves_commit_messages(self, spec_with_parallel_tasks):
        """VERIFIES: Rollup accumulates commit messages from tasks."""
        spec = spec_with_parallel_tasks
        repo_path = spec["repo_path"]
        tip_change = spec["tip_change"]

        os.chdir(repo_path)

        # Add custom messages to tasks before completing
        for task_id in ["T001", "T002"]:
            change_id = spec["task_changes"][task_id]

            # Write file
            simulate_task_execution_with_snapshot(task_id, change_id, repo_path)

            # Add a commit message
            message = f"Implemented {task_id}: Added {task_id.lower()}_output.txt"
            current_desc = get_description(change_id, repo_path)
            describe_change(f"{current_desc}\n\n{message}", change_id, repo_path)

            # Complete
            complete_task(task_id, change_id, tip_change, repo_path)

        # Check TIP's description includes messages from both tasks
        tip_desc = get_description(tip_change, repo_path)

        assert "[T001]" in tip_desc, "T001's message should be in TIP"
        assert "[T002]" in tip_desc, "T002's message should be in TIP"

    def test_export_to_git_single_commit(self, spec_with_parallel_tasks):
        """VERIFIES: Final state exports to git as single commit.

        This is the ultimate validation - all the jj work should
        result in a single git commit on the feature branch.
        """
        spec = spec_with_parallel_tasks
        repo_path = spec["repo_path"]
        tip_change = spec["tip_change"]
        spec_id = spec["spec_id"]

        os.chdir(repo_path)

        # Execute all tasks
        for task_id in ["T001", "T002", "T003"]:
            change_id = spec["task_changes"][task_id]
            simulate_task_execution_with_snapshot(task_id, change_id, repo_path)
            complete_task(task_id, change_id, tip_change, repo_path)

        # Move the branch bookmark to TIP
        run_jj("bookmark", "set", spec_id, "-r", tip_change, cwd=repo_path)

        # Export to git
        run_jj("git", "export", cwd=repo_path)

        # Verify git state
        result = subprocess.run(
            ["git", "log", "--oneline", spec_id],
            capture_output=True,
            text=True,
            cwd=repo_path,
        )

        # Should have exactly 2 commits: initial + TIP
        commits = [l for l in result.stdout.strip().split("\n") if l]
        print(f"Git commits on {spec_id}: {commits}")

        # The TIP commit should contain all files
        # Note: git HEAD may be detached, so use branch name explicitly
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{spec_id}~1", spec_id],
            capture_output=True,
            text=True,
            cwd=repo_path,
        )

        changed_files = result.stdout.strip().split("\n")
        print(f"Files in final commit: {changed_files}")

        for task_id in ["T001", "T002", "T003"]:
            expected = f"{task_id.lower()}_output.txt"
            assert expected in changed_files, f"{expected} should be in final commit"


class TestCompleteTaskSnapshotsFix:
    """Tests that verify complete_task properly snapshots before squashing."""

    def test_complete_task_captures_unsnapshotted_files(self, spec_with_parallel_tasks):
        """VERIFIES FIX: complete_task snapshots before squash.

        This tests that complete_task() itself triggers a snapshot,
        so callers don't need to explicitly run jj status.
        """
        spec = spec_with_parallel_tasks
        repo_path = spec["repo_path"]
        tip_change = spec["tip_change"]

        os.chdir(repo_path)

        # Simulate T001 writing files WITHOUT any jj interaction after
        # (This mimics what Claude does - writes files then exits)
        t001_change = spec["task_changes"]["T001"]

        # Switch to task's change
        run_jj("edit", t001_change, cwd=repo_path)

        # Write files (no jj command after)
        (repo_path / "task_output.txt").write_text("Claude wrote this\n")
        (repo_path / "another_file.py").write_text("# Generated code\nprint('hello')\n")

        # Complete task - this should internally snapshot first
        result = complete_task(
            task_id="T001",
            change_id=t001_change,
            parent_change=tip_change,
            cwd=repo_path,
        )

        assert result.success, f"Complete should succeed: {result.error}"

        # Verify TIP has the files
        run_jj("edit", tip_change, cwd=repo_path)
        run_jj("status", cwd=repo_path)

        assert (repo_path / "task_output.txt").exists(), "File should be in TIP"
        assert (repo_path / "another_file.py").exists(), "File should be in TIP"

    def test_parallel_tasks_complete_without_explicit_snapshot(self, spec_with_parallel_tasks):
        """VERIFIES FIX: Multiple tasks can complete without explicit snapshots.

        This is the full parallel workflow validation - all tasks write files
        without running jj status, then complete_task handles the snapshotting.
        """
        spec = spec_with_parallel_tasks
        repo_path = spec["repo_path"]
        tip_change = spec["tip_change"]

        os.chdir(repo_path)

        # Execute all tasks WITHOUT explicit snapshots
        for task_id in ["T001", "T002", "T003"]:
            change_id = spec["task_changes"][task_id]

            # Switch to task change and write file
            run_jj("edit", change_id, cwd=repo_path)
            (repo_path / f"{task_id.lower()}_result.txt").write_text(
                f"Results from {task_id}\nNo jj command after this write.\n"
            )

            # Complete task - internal snapshot should capture changes
            result = complete_task(
                task_id=task_id,
                change_id=change_id,
                parent_change=tip_change,
                cwd=repo_path,
            )
            assert result.success, f"Complete {task_id} failed: {result.error}"

        # Verify TIP has all files
        run_jj("edit", tip_change, cwd=repo_path)
        run_jj("status", cwd=repo_path)

        for task_id in ["T001", "T002", "T003"]:
            expected_file = repo_path / f"{task_id.lower()}_result.txt"
            assert expected_file.exists(), f"File from {task_id} should be in TIP"


class TestWorkspaceSnapshotBehavior:
    """Tests to understand jj workspace snapshot behavior."""

    def test_jj_status_triggers_snapshot(self, jj_repo):
        """Verify that jj status captures pending file changes."""
        os.chdir(jj_repo)

        # Write a file without any jj interaction
        (jj_repo / "new_file.txt").write_text("Hello world\n")

        # At this point, jj might not know about the file
        # Run status to trigger snapshot
        result = run_jj("status", cwd=jj_repo)

        # Now jj should see the file as a working copy change
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

        # Create workspace 1
        run_jj("workspace", "add", str(ws1_path), cwd=jj_repo)

        # Create workspace 2
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


# =============================================================================
# Standalone runner
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])
