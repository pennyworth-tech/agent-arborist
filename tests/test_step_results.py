"""Tests for step result JSON schemas."""

import json
import pytest
from datetime import datetime

from agent_arborist.step_results import (
    StepResultBase,
    PreSyncResult,
    RunResult,
    CommitResult,
    RunTestResult,
    PostMergeResult,
    PostCleanupResult,
)


class TestStepResultBase:
    """Tests for StepResultBase."""

    def test_to_json_success(self):
        result = StepResultBase(success=True)
        data = json.loads(result.to_json())
        assert data["success"] is True
        assert "timestamp" in data
        assert data["error"] is None

    def test_to_json_failure(self):
        result = StepResultBase(success=False, error="Something went wrong")
        data = json.loads(result.to_json())
        assert data["success"] is False
        assert data["error"] == "Something went wrong"

    def test_to_dict(self):
        result = StepResultBase(success=True)
        d = result.to_dict()
        assert isinstance(d, dict)
        assert d["success"] is True

    def test_timestamp_is_iso_format(self):
        result = StepResultBase(success=True)
        # Should be parseable as ISO format
        datetime.fromisoformat(result.timestamp)


class TestPreSyncResult:
    """Tests for PreSyncResult."""

    def test_to_json_success(self):
        result = PreSyncResult(
            success=True,
            worktree_path="/path/to/worktree",
            branch="spec_T001",
            parent_branch="spec_base",
            created_worktree=True,
            synced_from_parent=True,
        )
        data = json.loads(result.to_json())
        assert data["success"] is True
        assert data["worktree_path"] == "/path/to/worktree"
        assert data["branch"] == "spec_T001"
        assert data["parent_branch"] == "spec_base"
        assert data["created_worktree"] is True
        assert data["synced_from_parent"] is True

    def test_to_json_failure(self):
        result = PreSyncResult(
            success=False,
            error="Branch not found",
        )
        data = json.loads(result.to_json())
        assert data["success"] is False
        assert data["error"] == "Branch not found"


class TestRunResult:
    """Tests for RunResult."""

    def test_to_json_with_metrics(self):
        result = RunResult(
            success=True,
            files_changed=5,
            commit_message="task(T001): implement feature",
            summary="Added new API endpoint",
            runner="claude",
            model="sonnet",
            duration_seconds=45.5,
        )
        data = json.loads(result.to_json())
        assert data["files_changed"] == 5
        assert data["commit_message"] == "task(T001): implement feature"
        assert data["summary"] == "Added new API endpoint"
        assert data["runner"] == "claude"
        assert data["model"] == "sonnet"
        assert data["duration_seconds"] == 45.5

    def test_to_json_failure(self):
        result = RunResult(
            success=False,
            error="Timeout after 1800s",
        )
        data = json.loads(result.to_json())
        assert data["success"] is False
        assert data["error"] == "Timeout after 1800s"


class TestCommitResult:
    """Tests for CommitResult."""

    def test_to_json_with_commit(self):
        result = CommitResult(
            success=True,
            commit_sha="abc123def456789012345678901234567890abcd",
            message="task(T001): implement feature",
            files_staged=3,
            was_fallback=False,
        )
        data = json.loads(result.to_json())
        assert data["success"] is True
        assert data["commit_sha"] == "abc123def456789012345678901234567890abcd"
        assert data["message"] == "task(T001): implement feature"
        assert data["files_staged"] == 3
        assert data["was_fallback"] is False

    def test_to_json_fallback_commit(self):
        result = CommitResult(
            success=True,
            commit_sha="abc123def456789012345678901234567890abcd",
            message="task(T001): fallback",
            files_staged=1,
            was_fallback=True,
        )
        data = json.loads(result.to_json())
        assert data["was_fallback"] is True


class TestRunTestResult:
    """Tests for RunTestResult."""

    def test_to_json_with_test_counts(self):
        result = RunTestResult(
            success=True,
            test_command="pytest tests/",
            test_count=50,
            passed=48,
            failed=0,
            skipped=2,
            output_summary="All tests passed",
        )
        data = json.loads(result.to_json())
        assert data["test_command"] == "pytest tests/"
        assert data["test_count"] == 50
        assert data["passed"] == 48
        assert data["failed"] == 0
        assert data["skipped"] == 2

    def test_to_json_no_tests(self):
        result = RunTestResult(
            success=True,
            test_command=None,
            output_summary="No test command detected",
        )
        data = json.loads(result.to_json())
        assert data["test_command"] is None

    def test_to_json_test_failure(self):
        result = RunTestResult(
            success=False,
            test_command="pytest tests/",
            failed=3,
            error="3 tests failed",
        )
        data = json.loads(result.to_json())
        assert data["success"] is False
        assert data["failed"] == 3


class TestPostMergeResult:
    """Tests for PostMergeResult."""

    def test_to_json_success(self):
        result = PostMergeResult(
            success=True,
            merged_into="main_a_T001",
            source_branch="main_a_T001_T002",
            commit_sha="abc123def456789012345678901234567890abcd",
            conflicts=[],
            conflict_resolved=False,
        )
        data = json.loads(result.to_json())
        assert data["merged_into"] == "main_a_T001"
        assert data["source_branch"] == "main_a_T001_T002"
        assert data["commit_sha"] == "abc123def456789012345678901234567890abcd"
        assert data["conflicts"] == []

    def test_to_json_with_resolved_conflicts(self):
        result = PostMergeResult(
            success=True,
            merged_into="main",
            source_branch="feature",
            conflicts=["file.py"],
            conflict_resolved=True,
        )
        data = json.loads(result.to_json())
        assert data["conflicts"] == ["file.py"]
        assert data["conflict_resolved"] is True


class TestPostCleanupResult:
    """Tests for PostCleanupResult."""

    def test_to_json_full_cleanup(self):
        result = PostCleanupResult(
            success=True,
            worktree_removed=True,
            branch_deleted=True,
            cleaned_up=True,
        )
        data = json.loads(result.to_json())
        assert data["worktree_removed"] is True
        assert data["branch_deleted"] is True
        assert data["cleaned_up"] is True

    def test_to_json_keep_branch(self):
        result = PostCleanupResult(
            success=True,
            worktree_removed=True,
            branch_deleted=False,
            cleaned_up=True,
        )
        data = json.loads(result.to_json())
        assert data["branch_deleted"] is False


class TestJsonRoundTrip:
    """Test that results can be serialized and deserialized."""

    @pytest.mark.parametrize("result_class,kwargs", [
        (PreSyncResult, {"success": True, "worktree_path": "/path", "branch": "b"}),
        (RunResult, {"success": True, "files_changed": 5, "runner": "claude"}),
        (CommitResult, {"success": True, "commit_sha": "abc123"}),
        (RunTestResult, {"success": True, "test_command": "pytest"}),
        (PostMergeResult, {"success": True, "merged_into": "main"}),
        (PostCleanupResult, {"success": True, "cleaned_up": True}),
    ])
    def test_json_is_valid(self, result_class, kwargs):
        """Verify all result types produce valid JSON."""
        result = result_class(**kwargs)
        json_str = result.to_json()
        # Should be valid JSON
        data = json.loads(json_str)
        # Should contain base fields
        assert "success" in data
        assert "timestamp" in data
