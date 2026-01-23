"""Tests for CLI commands."""

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from agent_arborist.cli import main
from agent_arborist.checks import DependencyStatus
from agent_arborist.home import ARBORIST_DIR_NAME, DAGU_DIR_NAME, DAGU_HOME_ENV_VAR


class TestVersionCommand:
    def test_version_output(self):
        runner = CliRunner()
        result = runner.invoke(main, ["version"])
        assert result.exit_code == 0
        assert "agent-arborist" in result.output
        assert "0.1.0" in result.output

    @patch("agent_arborist.cli.check_runtimes")
    @patch("agent_arborist.cli.check_dagu")
    def test_version_with_check(self, mock_dagu, mock_runtimes):
        mock_dagu.return_value = DependencyStatus(
            name="dagu",
            installed=True,
            version="1.30.3",
            path="/usr/bin/dagu",
            min_version="1.30.3",
        )
        mock_runtimes.return_value = [
            DependencyStatus(name="claude", installed=True, version="1.0.0", path="/usr/bin/claude"),
            DependencyStatus(name="opencode", installed=False),
            DependencyStatus(name="gemini", installed=False),
        ]

        runner = CliRunner()
        result = runner.invoke(main, ["version", "--check"])
        assert result.exit_code == 0
        assert "agent-arborist" in result.output
        assert "dagu" in result.output


class TestDoctorCommand:
    def test_doctor_group_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["doctor", "--help"])
        assert result.exit_code == 0
        assert "check-runner" in result.output

    @patch("agent_arborist.cli.check_runtimes")
    @patch("agent_arborist.cli.check_dagu")
    def test_doctor_all_ok(self, mock_dagu, mock_runtimes):
        mock_dagu.return_value = DependencyStatus(
            name="dagu",
            installed=True,
            version="1.30.3",
            path="/usr/bin/dagu",
            min_version="1.30.3",
        )
        mock_runtimes.return_value = [
            DependencyStatus(name="claude", installed=True, version="1.0.0", path="/usr/bin/claude"),
            DependencyStatus(name="opencode", installed=False),
            DependencyStatus(name="gemini", installed=False),
        ]

        runner = CliRunner()
        result = runner.invoke(main, ["doctor"])
        assert result.exit_code == 0
        assert "All dependencies OK" in result.output

    @patch("agent_arborist.cli.check_runtimes")
    @patch("agent_arborist.cli.check_dagu")
    def test_doctor_dagu_missing(self, mock_dagu, mock_runtimes):
        mock_dagu.return_value = DependencyStatus(
            name="dagu",
            installed=False,
            min_version="1.30.3",
            error="dagu not found in PATH",
        )
        mock_runtimes.return_value = [
            DependencyStatus(name="claude", installed=True, version="1.0.0", path="/usr/bin/claude"),
            DependencyStatus(name="opencode", installed=False),
            DependencyStatus(name="gemini", installed=False),
        ]

        runner = CliRunner()
        result = runner.invoke(main, ["doctor"])
        assert result.exit_code == 1
        assert "missing or outdated" in result.output

    @patch("agent_arborist.cli.check_runtimes")
    @patch("agent_arborist.cli.check_dagu")
    def test_doctor_no_runtimes(self, mock_dagu, mock_runtimes):
        mock_dagu.return_value = DependencyStatus(
            name="dagu",
            installed=True,
            version="1.30.3",
            path="/usr/bin/dagu",
            min_version="1.30.3",
        )
        mock_runtimes.return_value = [
            DependencyStatus(name="claude", installed=False),
            DependencyStatus(name="opencode", installed=False),
            DependencyStatus(name="gemini", installed=False),
        ]

        runner = CliRunner()
        result = runner.invoke(main, ["doctor"])
        assert result.exit_code == 1
        assert "At least one runtime" in result.output


class TestTaskCommands:
    def test_task_group_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["task", "--help"])
        assert result.exit_code == 0
        assert "run" in result.output
        assert "status" in result.output
        assert "deps" in result.output
        assert "mark" in result.output

    def test_task_run_requires_prompt(self):
        runner = CliRunner()
        result = runner.invoke(main, ["task", "run", "T001"])
        assert result.exit_code != 0
        assert "Missing option" in result.output or "required" in result.output.lower()

    def test_task_run_placeholder(self):
        runner = CliRunner()
        result = runner.invoke(main, ["task", "run", "T001", "--prompt", "test.md"])
        assert result.exit_code == 0
        assert "T001" in result.output

    def test_task_status_placeholder(self):
        runner = CliRunner()
        result = runner.invoke(main, ["task", "status", "T001"])
        assert result.exit_code == 0
        assert "T001" in result.output

    def test_task_deps_placeholder(self):
        runner = CliRunner()
        result = runner.invoke(main, ["task", "deps", "T001"])
        assert result.exit_code == 0
        assert "T001" in result.output

    def test_task_mark_requires_status(self):
        runner = CliRunner()
        result = runner.invoke(main, ["task", "mark", "T001"])
        assert result.exit_code != 0

    def test_task_mark_validates_status(self):
        runner = CliRunner()
        result = runner.invoke(main, ["task", "mark", "T001", "--status", "invalid"])
        assert result.exit_code != 0

    def test_task_mark_placeholder(self):
        runner = CliRunner()
        result = runner.invoke(main, ["task", "mark", "T001", "--status", "completed"])
        assert result.exit_code == 0
        assert "T001" in result.output
        assert "completed" in result.output


class TestSpecCommands:
    def test_spec_group_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["spec", "--help"])
        assert result.exit_code == 0
        assert "whoami" in result.output

    @patch("agent_arborist.cli.detect_spec_from_git")
    def test_spec_whoami_found(self, mock_detect):
        from agent_arborist.spec import SpecInfo

        mock_detect.return_value = SpecInfo(
            spec_id="002",
            name="my-feature",
            source="git",
            branch="002-my-feature",
        )

        runner = CliRunner()
        result = runner.invoke(main, ["spec", "whoami"])
        assert result.exit_code == 0
        assert "002-my-feature" in result.output
        assert "git" in result.output

    @patch("agent_arborist.cli.detect_spec_from_git")
    def test_spec_whoami_not_found(self, mock_detect):
        from agent_arborist.spec import SpecInfo

        mock_detect.return_value = SpecInfo(
            error="Branch 'main' does not contain spec pattern",
            source="git",
            branch="main",
        )

        runner = CliRunner()
        result = runner.invoke(main, ["spec", "whoami"])
        assert result.exit_code == 0
        assert "Not detected" in result.output
        assert "--spec" in result.output or "-s" in result.output


class TestCheckRunnerCommand:
    @patch("agent_arborist.cli.get_runner")
    def test_check_runner_success(self, mock_get_runner):
        from agent_arborist.runner import RunResult

        mock_runner = mock_get_runner.return_value
        mock_runner.is_available.return_value = True
        mock_runner.command = "claude"
        mock_runner.run.return_value = RunResult(
            success=True,
            output="Why did the programmer quit? Because he didn't get arrays!",
            exit_code=0,
        )

        runner = CliRunner()
        result = runner.invoke(main, ["doctor", "check-runner"])
        assert result.exit_code == 0
        assert "OK" in result.output
        assert "arrays" in result.output

    @patch("agent_arborist.cli.get_runner")
    def test_check_runner_not_found(self, mock_get_runner):
        mock_runner = mock_get_runner.return_value
        mock_runner.is_available.return_value = False

        runner = CliRunner()
        result = runner.invoke(main, ["doctor", "check-runner"])
        assert result.exit_code == 1
        assert "FAIL" in result.output
        assert "not found" in result.output

    @patch("agent_arborist.cli.get_runner")
    def test_check_runner_execution_failure(self, mock_get_runner):
        from agent_arborist.runner import RunResult

        mock_runner = mock_get_runner.return_value
        mock_runner.is_available.return_value = True
        mock_runner.command = "claude"
        mock_runner.run.return_value = RunResult(
            success=False,
            output="",
            error="Timeout after 30 seconds",
            exit_code=-1,
        )

        runner = CliRunner()
        result = runner.invoke(main, ["doctor", "check-runner"])
        assert result.exit_code != 0
        assert "FAIL" in result.output
        assert "Timeout" in result.output

    @patch("agent_arborist.cli.get_runner")
    def test_check_runner_with_runner_option(self, mock_get_runner):
        from agent_arborist.runner import RunResult

        mock_runner = mock_get_runner.return_value
        mock_runner.is_available.return_value = True
        mock_runner.command = "opencode"
        mock_runner.run.return_value = RunResult(
            success=True,
            output="A joke from opencode",
            exit_code=0,
        )

        runner = CliRunner()
        result = runner.invoke(main, ["doctor", "check-runner", "--runner", "opencode"])
        assert result.exit_code == 0
        mock_get_runner.assert_called_with("opencode")

    def test_check_runner_invalid_runner(self):
        runner = CliRunner()
        result = runner.invoke(main, ["doctor", "check-runner", "--runner", "invalid"])
        assert result.exit_code != 0


@pytest.fixture
def git_repo(tmp_path):
    """Create a temporary git repository."""
    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    subprocess.run(["git", "init"], capture_output=True, check=True)
    readme = tmp_path / "README.md"
    readme.write_text("# Test\n")
    subprocess.run(["git", "add", "."], capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        capture_output=True,
        check=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@test.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@test.com",
        },
    )
    yield tmp_path
    os.chdir(original_cwd)


@pytest.fixture
def non_git_dir(tmp_path):
    """Create a temporary directory that is not a git repo."""
    original_cwd = os.getcwd()
    # Create a subdirectory to ensure we're not in a git repo
    test_dir = tmp_path / "not_git"
    test_dir.mkdir()
    os.chdir(test_dir)
    yield test_dir
    os.chdir(original_cwd)


class TestInitCommand:
    def test_init_creates_arborist_directory(self, git_repo):
        runner = CliRunner()
        result = runner.invoke(main, ["init"])
        assert result.exit_code == 0
        assert "Initialized" in result.output

        arborist_dir = git_repo / ARBORIST_DIR_NAME
        assert arborist_dir.is_dir()

    def test_init_adds_to_gitignore(self, git_repo):
        runner = CliRunner()
        result = runner.invoke(main, ["init"])
        assert result.exit_code == 0

        gitignore = git_repo / ".gitignore"
        assert gitignore.exists()
        content = gitignore.read_text()
        assert f"{ARBORIST_DIR_NAME}/" in content

    def test_init_fails_outside_git_repo(self, non_git_dir):
        runner = CliRunner()
        result = runner.invoke(main, ["init"])
        assert result.exit_code == 1
        assert "git repository" in result.output.lower()

    def test_init_fails_if_already_initialized(self, git_repo):
        # First init
        runner = CliRunner()
        result = runner.invoke(main, ["init"])
        assert result.exit_code == 0

        # Second init should fail
        result = runner.invoke(main, ["init"])
        assert result.exit_code == 1
        assert "already initialized" in result.output.lower()

    def test_init_shows_path_in_output(self, git_repo):
        runner = CliRunner()
        result = runner.invoke(main, ["init"])
        assert result.exit_code == 0
        assert ARBORIST_DIR_NAME in result.output

    def test_init_creates_dagu_subdirectory(self, git_repo):
        runner = CliRunner()
        result = runner.invoke(main, ["init"])
        assert result.exit_code == 0

        dagu_dir = git_repo / ARBORIST_DIR_NAME / DAGU_DIR_NAME
        assert dagu_dir.is_dir()


class TestDaguHomeEnvVar:
    def test_dagu_home_set_when_initialized(self, git_repo):
        # First initialize
        runner = CliRunner()
        result = runner.invoke(main, ["init"])
        assert result.exit_code == 0

        # Run any command and check env var is set
        # We use version as a simple command
        result = runner.invoke(main, ["version"])
        assert result.exit_code == 0

        # Check the env var was set
        expected_dagu_home = str(git_repo / ARBORIST_DIR_NAME / DAGU_DIR_NAME)
        assert os.environ.get(DAGU_HOME_ENV_VAR) == expected_dagu_home

    def test_dagu_home_not_set_when_not_initialized(self, git_repo, monkeypatch):
        # Ensure env var is not set
        monkeypatch.delenv(DAGU_HOME_ENV_VAR, raising=False)

        runner = CliRunner()
        result = runner.invoke(main, ["version"])
        assert result.exit_code == 0

        # DAGU_HOME should not be set since we didn't init
        assert os.environ.get(DAGU_HOME_ENV_VAR) is None
