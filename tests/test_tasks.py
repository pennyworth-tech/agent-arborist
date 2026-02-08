"""Tests for tasks module (git-based sequential execution)."""

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from agent_arborist.tasks import (
    GitResult,
    run_git,
    is_git_repo,
    get_current_branch,
    get_current_commit,
    get_short_commit,
    has_uncommitted_changes,
    get_changed_files,
    stage_all,
    commit,
    stage_and_commit,
    create_branch,
    checkout_branch,
    push_branch,
    get_commit_log,
    get_diff_stat,
    count_changed_files,
    build_commit_message,
    commit_task,
    detect_test_command,
    run_tests,
)


class TestGitResult:
    """Tests for GitResult dataclass."""

    def test_success_result(self):
        """Creates a success result."""
        result = GitResult(
            success=True,
            message="Committed",
            stdout="output",
            stderr="",
        )
        assert result.success is True
        assert result.message == "Committed"
        assert result.error is None

    def test_failure_result(self):
        """Creates a failure result."""
        result = GitResult(
            success=False,
            message="Failed",
            error="Something went wrong",
        )
        assert result.success is False
        assert result.error == "Something went wrong"


class TestRunGit:
    """Tests for run_git helper function."""

    def test_run_git_success(self):
        """Runs git command successfully."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="output",
                stderr="",
            )
            with patch("agent_arborist.tasks.get_git_root", return_value=Path("/tmp")):
                result = run_git("status")
                assert result.returncode == 0
                mock_run.assert_called_once()

    def test_run_git_with_cwd(self):
        """Runs git command with specified working directory."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            run_git("status", cwd=Path("/custom/path"))
            call_kwargs = mock_run.call_args.kwargs
            assert call_kwargs["cwd"] == Path("/custom/path")


class TestRepoDetection:
    """Tests for repository detection."""

    def test_is_git_repo_true(self):
        """Returns True when in a git repo."""
        with patch("agent_arborist.tasks.run_git") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert is_git_repo(Path("/tmp")) is True

    def test_is_git_repo_false(self):
        """Returns False when not in a git repo."""
        with patch("agent_arborist.tasks.run_git") as mock_run:
            mock_run.return_value = MagicMock(returncode=128)
            assert is_git_repo(Path("/tmp")) is False


class TestBranchOperations:
    """Tests for branch operations."""

    def test_get_current_branch(self):
        """Gets current branch name."""
        with patch("agent_arborist.tasks.run_git") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="main\n")
            result = get_current_branch(Path("/tmp"))
            assert result == "main"

    def test_get_current_branch_detached(self):
        """Returns None for detached HEAD."""
        with patch("agent_arborist.tasks.run_git") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="HEAD\n")
            result = get_current_branch(Path("/tmp"))
            assert result is None

    def test_create_branch(self):
        """Creates a new branch."""
        with patch("agent_arborist.tasks.run_git") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = create_branch("feature-branch", cwd=Path("/tmp"))
            assert result.success is True
            assert "feature-branch" in result.message

    def test_checkout_branch(self):
        """Checks out an existing branch."""
        with patch("agent_arborist.tasks.run_git") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = checkout_branch("main", cwd=Path("/tmp"))
            assert result.success is True

    def test_push_branch(self):
        """Pushes branch to remote."""
        with patch("agent_arborist.tasks.run_git") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = push_branch("feature-branch", cwd=Path("/tmp"))
            assert result.success is True


class TestCommitOperations:
    """Tests for commit operations."""

    def test_get_current_commit(self):
        """Gets current commit SHA."""
        with patch("agent_arborist.tasks.run_git") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="abc123def456789\n",
            )
            result = get_current_commit(Path("/tmp"))
            assert result == "abc123def456789"

    def test_get_short_commit(self):
        """Gets short commit SHA."""
        with patch("agent_arborist.tasks.run_git") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="abc123d\n",
            )
            result = get_short_commit(Path("/tmp"))
            assert result == "abc123d"


class TestChangesDetection:
    """Tests for detecting changes."""

    def test_has_uncommitted_changes_true(self):
        """Detects uncommitted changes."""
        with patch("agent_arborist.tasks.run_git") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="M file.py\n",
            )
            assert has_uncommitted_changes(Path("/tmp")) is True

    def test_has_uncommitted_changes_false(self):
        """Returns False when working tree clean."""
        with patch("agent_arborist.tasks.run_git") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="",
            )
            assert has_uncommitted_changes(Path("/tmp")) is False

    def test_get_changed_files(self):
        """Gets list of changed files."""
        with patch("agent_arborist.tasks.run_git") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="M  file1.py\nA  file2.py\n",
            )
            files = get_changed_files(Path("/tmp"))
            assert len(files) == 2
            assert "file1.py" in files
            assert "file2.py" in files

    def test_count_changed_files(self):
        """Counts changed files."""
        with patch("agent_arborist.tasks.get_changed_files", return_value=["a.py", "b.py"]):
            assert count_changed_files(Path("/tmp")) == 2


class TestStageAndCommit:
    """Tests for staging and committing."""

    def test_stage_all(self):
        """Stages all changes."""
        with patch("agent_arborist.tasks.run_git") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = stage_all(Path("/tmp"))
            assert result.success is True

    def test_commit_success(self):
        """Creates a commit successfully."""
        with patch("agent_arborist.tasks.run_git") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = commit("Test commit", cwd=Path("/tmp"))
            assert result.success is True

    def test_commit_nothing_to_commit(self):
        """Handles nothing to commit gracefully."""
        with patch("agent_arborist.tasks.run_git") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="nothing to commit, working tree clean",
                stderr="",
            )
            result = commit("Test commit", cwd=Path("/tmp"))
            assert result.success is True
            assert "Nothing to commit" in result.message

    def test_stage_and_commit_success(self):
        """Stages and commits in one operation."""
        with patch("agent_arborist.tasks.stage_all") as mock_stage:
            mock_stage.return_value = GitResult(success=True, message="Staged")
            with patch("agent_arborist.tasks.has_uncommitted_changes", return_value=True):
                with patch("agent_arborist.tasks.commit") as mock_commit:
                    mock_commit.return_value = GitResult(success=True, message="Committed")
                    result = stage_and_commit("Test message", cwd=Path("/tmp"))
                    assert result.success is True

    def test_stage_and_commit_nothing_to_commit(self):
        """Returns success when nothing to commit."""
        with patch("agent_arborist.tasks.stage_all") as mock_stage:
            mock_stage.return_value = GitResult(success=True, message="Staged")
            with patch("agent_arborist.tasks.has_uncommitted_changes", return_value=False):
                result = stage_and_commit("Test message", cwd=Path("/tmp"))
                assert result.success is True
                assert "Nothing to commit" in result.message


class TestCommitLog:
    """Tests for commit log operations."""

    def test_get_commit_log(self):
        """Gets commit log."""
        with patch("agent_arborist.tasks.run_git") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="abc123 First commit\ndef456 Second commit\n",
            )
            commits = get_commit_log(limit=5, cwd=Path("/tmp"))
            assert len(commits) == 2
            assert "abc123 First commit" in commits
            assert "def456 Second commit" in commits

    def test_get_diff_stat(self):
        """Gets diff statistics."""
        with patch("agent_arborist.tasks.run_git") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="file.py | 10 ++++++----",
            )
            stat = get_diff_stat(Path("/tmp"))
            assert "file.py" in stat


class TestBuildCommitMessage:
    """Tests for commit message building."""

    def test_build_commit_message_basic(self):
        """Builds basic commit message."""
        message = build_commit_message(
            spec_id="002-feature",
            task_id="T001",
        )
        assert "002-feature:T001" in message

    def test_build_commit_message_with_summary(self):
        """Builds commit message with summary."""
        message = build_commit_message(
            spec_id="002-feature",
            task_id="T001",
            summary="Added new feature",
        )
        assert "002-feature:T001" in message
        assert "Added new feature" in message

    def test_build_commit_message_with_files_changed(self):
        """Builds commit message with files changed."""
        message = build_commit_message(
            spec_id="002-feature",
            task_id="T001",
            files_changed=5,
        )
        assert "Files changed: 5" in message


class TestCommitTask:
    """Tests for commit_task function."""

    def test_commit_task_success(self):
        """Commits task changes successfully."""
        with patch("agent_arborist.tasks.count_changed_files", return_value=3):
            with patch("agent_arborist.tasks.stage_and_commit") as mock_commit:
                mock_commit.return_value = GitResult(success=True, message="Committed")
                result = commit_task(
                    spec_id="002-feature",
                    task_id="T001",
                    summary="Completed task",
                    cwd=Path("/tmp"),
                )
                assert result.success is True


class TestDetectTestCommand:
    """Tests for test command detection."""

    def test_detect_pytest(self, tmp_path):
        """Detects pytest from pyproject.toml."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        assert detect_test_command(tmp_path) == "pytest"

    def test_detect_pytest_ini(self, tmp_path):
        """Detects pytest from pytest.ini."""
        (tmp_path / "pytest.ini").write_text("[pytest]\n")
        assert detect_test_command(tmp_path) == "pytest"

    def test_detect_npm_test(self, tmp_path):
        """Detects npm test from package.json."""
        (tmp_path / "package.json").write_text("{}")
        assert detect_test_command(tmp_path) == "npm test"

    def test_detect_make_test(self, tmp_path):
        """Detects make test from Makefile."""
        (tmp_path / "Makefile").write_text("test:\n\techo test\n")
        assert detect_test_command(tmp_path) == "make test"

    def test_detect_cargo_test(self, tmp_path):
        """Detects cargo test from Cargo.toml."""
        (tmp_path / "Cargo.toml").write_text("[package]\n")
        assert detect_test_command(tmp_path) == "cargo test"

    def test_detect_go_test(self, tmp_path):
        """Detects go test from go.mod."""
        (tmp_path / "go.mod").write_text("module test\n")
        assert detect_test_command(tmp_path) == "go test ./..."

    def test_detect_none(self, tmp_path):
        """Returns None when no test command detected."""
        assert detect_test_command(tmp_path) is None


class TestRunTests:
    """Tests for run_tests function."""

    def test_run_tests_success(self):
        """Runs tests successfully."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="All tests passed",
                stderr="",
            )
            result = run_tests(Path("/tmp"), test_cmd="pytest")
            assert result.success is True
            assert "passed" in result.message.lower()

    def test_run_tests_failure(self):
        """Handles test failure."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="1 test failed",
                stderr="Error details",
            )
            result = run_tests(Path("/tmp"), test_cmd="pytest")
            assert result.success is False
            assert "failed" in result.message.lower()

    def test_run_tests_timeout(self):
        """Handles test timeout."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("pytest", 300)
            result = run_tests(Path("/tmp"), test_cmd="pytest", timeout=300)
            assert result.success is False
            assert "timed out" in result.message.lower()

    def test_run_tests_no_command(self):
        """Skips tests when no command available."""
        with patch("agent_arborist.tasks.detect_test_command", return_value=None):
            result = run_tests(Path("/tmp"))
            assert result.success is True
            assert "skipping" in result.message.lower()

    def test_run_tests_with_container(self):
        """Runs tests with container command prefix."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="Tests passed",
                stderr="",
            )
            result = run_tests(
                Path("/tmp"),
                test_cmd="pytest",
                container_cmd_prefix=["docker", "exec", "container"],
            )
            assert result.success is True
            # Verify container prefix was used
            call_args = mock_run.call_args[0][0]
            assert call_args[0] == "docker"
