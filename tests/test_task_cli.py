"""Tests for task_cli module."""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from agent_arborist.task_cli import task


class TestTaskGroup:
    """Tests for task command group."""

    def test_task_group_help(self):
        """Shows help text for task group."""
        runner = CliRunner()
        result = runner.invoke(task, ["--help"])
        assert result.exit_code == 0
        assert "Task execution commands" in result.output

    def test_task_group_lists_commands(self):
        """Lists available subcommands."""
        runner = CliRunner()
        result = runner.invoke(task, ["--help"])
        assert result.exit_code == 0
        assert "run" in result.output
        assert "run-test" in result.output
        assert "status" in result.output
        assert "list" in result.output


class TestTaskRun:
    """Tests for task run command."""

    def test_run_help(self):
        """Shows help text."""
        runner = CliRunner()
        result = runner.invoke(task, ["run", "--help"])
        assert result.exit_code == 0
        assert "Run a task and commit changes" in result.output

    def test_run_requires_task_id(self):
        """Errors when no task_id provided."""
        runner = CliRunner()
        result = runner.invoke(task, ["run"])
        assert result.exit_code != 0
        assert "Missing argument" in result.output or "Usage:" in result.output

    def test_run_echo_mode(self):
        """Echoes command in test mode."""
        runner = CliRunner()
        result = runner.invoke(task, ["run", "T001"], obj={"echo_for_testing": True, "output_format": "json"})
        assert result.exit_code == 0
        assert "ECHO: task run" in result.output


class TestTaskRunTest:
    """Tests for task run-test command."""

    def test_run_test_help(self):
        """Shows help text."""
        runner = CliRunner()
        result = runner.invoke(task, ["run-test", "--help"])
        assert result.exit_code == 0
        assert "Run tests for a task" in result.output

    def test_run_test_requires_task_id(self):
        """Errors when no task_id provided."""
        runner = CliRunner()
        result = runner.invoke(task, ["run-test"])
        assert result.exit_code != 0
        assert "Missing argument" in result.output or "Usage:" in result.output

    def test_run_test_echo_mode(self):
        """Echoes command in test mode."""
        runner = CliRunner()
        result = runner.invoke(task, ["run-test", "T001"], obj={"echo_for_testing": True, "output_format": "json"})
        assert result.exit_code == 0
        assert "ECHO: task run-test" in result.output


class TestTaskStatus:
    """Tests for task status command."""

    def test_status_help(self):
        """Shows help text."""
        runner = CliRunner()
        result = runner.invoke(task, ["status", "--help"])
        assert result.exit_code == 0
        assert "Show status of a task" in result.output

    def test_status_requires_task_id(self):
        """Errors when no task_id provided."""
        runner = CliRunner()
        result = runner.invoke(task, ["status"])
        assert result.exit_code != 0
        assert "Missing argument" in result.output or "Usage:" in result.output

    def test_status_not_git_repo(self):
        """Fails when not in a git repo."""
        runner = CliRunner()
        # When not in a git repo, status should fail
        with patch("agent_arborist.home.get_git_root", return_value=None):
            result = runner.invoke(task, ["status", "T001"])
        assert result.exit_code == 1
        assert "git" in result.output.lower() or "repository" in result.output.lower()


class TestTaskList:
    """Tests for task list command."""

    def test_list_help(self):
        """Shows help text."""
        runner = CliRunner()
        result = runner.invoke(task, ["list", "--help"])
        assert result.exit_code == 0
        assert "List tasks from the current spec DAG" in result.output

    def test_list_requires_spec_id(self):
        """Errors when no ARBORIST_SPEC_ID set."""
        runner = CliRunner()
        with patch.dict("os.environ", {}, clear=True):
            result = runner.invoke(task, ["list"])
        # Should fail since no ARBORIST_SPEC_ID
        assert result.exit_code == 1
        assert "ARBORIST_SPEC_ID" in result.output
