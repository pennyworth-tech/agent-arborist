"""Tests for task_cli module."""

from pathlib import Path
from unittest.mock import patch, MagicMock
import json

import pytest
from click.testing import CliRunner

from agent_arborist.task_cli import task


class TestJJStatus:
    """Tests for jj status command."""

    def test_status_help(self):
        """Shows help text."""
        runner = CliRunner()
        result = runner.invoke(task, ["status", "--help"])
        assert result.exit_code == 0
        assert "Show status of jj tasks" in result.output

    def test_status_not_jj_repo(self):
        """Errors when not in jj repo."""
        runner = CliRunner()
        with patch("agent_arborist.task_cli.is_jj_repo", return_value=False):
            result = runner.invoke(task, ["status"], obj={})
        assert result.exit_code == 1
        assert "Not in a jj repository" in result.output

    def test_status_no_spec(self):
        """Errors when no spec available."""
        runner = CliRunner()
        with patch("agent_arborist.task_cli.is_jj_repo", return_value=True):
            result = runner.invoke(task, ["status"], obj={})
        assert result.exit_code == 1
        assert "No spec available" in result.output

    def test_status_all_tasks(self):
        """Shows all tasks in spec."""
        runner = CliRunner()
        mock_tasks = [
            MagicMock(task_id="T001", change_id="abc123", status="pending"),
            MagicMock(task_id="T002", change_id="def456", status="done"),
        ]
        with patch("agent_arborist.task_cli.is_jj_repo", return_value=True):
            with patch("agent_arborist.task_cli.find_tasks_by_spec", return_value=mock_tasks):
                result = runner.invoke(task, ["status"], obj={"spec_id": "002-feature"})
        assert result.exit_code == 0
        assert "T001" in result.output
        assert "T002" in result.output

    def test_status_single_task(self):
        """Shows single task details."""
        runner = CliRunner()
        mock_tasks = [
            MagicMock(task_id="T001", change_id="abc123", status="running", has_conflict=False)
        ]

        with patch("agent_arborist.task_cli.is_jj_repo", return_value=True):
            with patch("agent_arborist.task_cli.find_tasks_by_spec", return_value=mock_tasks):
                result = runner.invoke(task, ["status", "T001"], obj={"spec_id": "002-feature"})

        assert result.exit_code == 0
        assert "T001" in result.output
        assert "abc123" in result.output

    def test_status_echo_mode(self):
        """Echoes command in test mode."""
        runner = CliRunner()
        result = runner.invoke(task, ["status", "T001"], obj={"echo_for_testing": True, "spec_id": "002-feature"})
        assert result.exit_code == 0
        assert "ECHO: task status" in result.output


class TestJJSetupSpec:
    """Tests for jj setup-spec command."""

    def test_setup_spec_help(self):
        """Shows help text."""
        runner = CliRunner()
        result = runner.invoke(task, ["setup-spec", "--help"])
        assert result.exit_code == 0
        assert "Initialize jj and validate spec for lazy change creation" in result.output

    def test_setup_spec_no_spec(self):
        """Errors when no spec available."""
        runner = CliRunner()
        result = runner.invoke(task, ["setup-spec"], obj={})
        assert result.exit_code == 1
        assert "No spec available" in result.output

    def test_setup_spec_no_source_rev(self):
        """Errors when no source revision available."""
        runner = CliRunner()
        result = runner.invoke(task, ["setup-spec"], obj={"spec_id": "002-feature"})
        assert result.exit_code == 1
        assert "No source revision" in result.output

    def test_setup_spec_success(self):
        """Validates spec and initializes jj successfully (no change creation)."""
        runner = CliRunner()
        import os

        mock_dag_yaml = "name: test\nsteps:\n  - name: T1"

        with patch.dict(os.environ, {"ARBORIST_SOURCE_REV": "main"}):
            with patch("agent_arborist.task_cli.is_jj_repo", return_value=True):
                with patch("agent_arborist.task_cli.is_colocated", return_value=True):  # Already colocated
                    with patch("agent_arborist.task_cli._find_dag_yaml_path") as mock_find:
                        mock_find.return_value = MagicMock(read_text=MagicMock(return_value=mock_dag_yaml))
                        with patch("agent_arborist.task_cli.run_jj") as mock_run_jj:
                            mock_run_jj.return_value = MagicMock(returncode=0, stdout="", stderr="")
                            result = runner.invoke(task, ["setup-spec"], obj={"spec_id": "002-feature"})

        assert result.exit_code == 0
        # With lazy creation, setup-spec just validates - changes created at pre-sync
        assert "lazily" in result.output.lower() or "setup complete" in result.output.lower()

    def test_setup_spec_echo_mode(self):
        """Echoes command in test mode."""
        runner = CliRunner()
        result = runner.invoke(task, ["setup-spec"], obj={"echo_for_testing": True, "spec_id": "002-feature"})
        assert result.exit_code == 0
        assert "ECHO: task setup-spec" in result.output


class TestJJPreSync:
    """Tests for jj pre-sync command."""

    def test_pre_sync_help(self):
        """Shows help text."""
        runner = CliRunner()
        result = runner.invoke(task, ["pre-sync", "--help"])
        assert result.exit_code == 0
        assert "Prepare task for execution with lazy change creation" in result.output

    def test_pre_sync_no_spec(self):
        """Errors when no spec available."""
        runner = CliRunner()
        result = runner.invoke(task, ["pre-sync", "T001"], obj={})
        assert result.exit_code == 1
        assert "No spec available" in result.output

    def test_pre_sync_no_task_path(self):
        """Errors when no task path available."""
        runner = CliRunner()
        result = runner.invoke(task, ["pre-sync", "T001"], obj={"spec_id": "002-feature"})
        assert result.exit_code == 1
        assert "No task path available" in result.output

    def test_pre_sync_success(self):
        """Syncs task successfully."""
        import os
        runner = CliRunner()
        mock_setup_result = MagicMock(success=True)

        with patch.dict(os.environ, {"ARBORIST_TASK_PATH": "T1:T001", "ARBORIST_SOURCE_REV": "main"}):
            with patch("agent_arborist.task_cli.find_change_by_description", return_value="abc123"):
                with patch("agent_arborist.task_cli._find_parent_change", return_value="parent123"):
                    with patch("agent_arborist.task_cli.get_workspace_path", return_value=Path("/tmp/ws")):
                        with patch("agent_arborist.task_cli.setup_task_workspace", return_value=mock_setup_result):
                            with patch("agent_arborist.task_cli.describe_change"):
                                result = runner.invoke(task, ["pre-sync", "T001"], obj={"spec_id": "002-feature"})

        assert result.exit_code == 0
        assert "Pre-sync complete" in result.output

    def test_pre_sync_echo_mode(self):
        """Echoes command in test mode."""
        runner = CliRunner()
        result = runner.invoke(task, ["pre-sync", "T001"], obj={"echo_for_testing": True, "spec_id": "002-feature"})
        assert result.exit_code == 0
        assert "ECHO: task pre-sync" in result.output


class TestJJRun:
    """Tests for jj run command."""

    def test_run_help(self):
        """Shows help text."""
        runner = CliRunner()
        result = runner.invoke(task, ["run", "--help"])
        assert result.exit_code == 0
        assert "Execute the AI runner" in result.output

    def test_run_echo_mode(self):
        """Echoes command in test mode."""
        runner = CliRunner()
        result = runner.invoke(task, ["run", "T001"], obj={"echo_for_testing": True, "spec_id": "002-feature"})
        assert result.exit_code == 0
        assert "ECHO: task run" in result.output


class TestJJRunTest:
    """Tests for jj run-test command."""

    def test_run_test_help(self):
        """Shows help text."""
        runner = CliRunner()
        result = runner.invoke(task, ["run-test", "--help"])
        assert result.exit_code == 0
        assert "Run tests" in result.output

    def test_run_test_echo_mode(self):
        """Echoes command in test mode."""
        runner = CliRunner()
        result = runner.invoke(task, ["run-test", "T001"], obj={"echo_for_testing": True, "spec_id": "002-feature"})
        assert result.exit_code == 0
        assert "ECHO: task run-test" in result.output


class TestJJComplete:
    """Tests for jj complete command."""

    def test_complete_help(self):
        """Shows help text."""
        runner = CliRunner()
        result = runner.invoke(task, ["complete", "--help"])
        assert result.exit_code == 0
        assert "Mark a task as complete" in result.output

    def test_complete_echo_mode(self):
        """Echoes command in test mode."""
        runner = CliRunner()
        result = runner.invoke(task, ["complete", "T001"], obj={"echo_for_testing": True, "spec_id": "002-feature"})
        assert result.exit_code == 0
        assert "ECHO: task complete" in result.output


class TestJJCleanup:
    """Tests for jj cleanup command."""

    def test_cleanup_help(self):
        """Shows help text."""
        runner = CliRunner()
        result = runner.invoke(task, ["cleanup", "--help"])
        assert result.exit_code == 0
        assert "Clean up task workspace" in result.output

    def test_cleanup_echo_mode(self):
        """Echoes command in test mode."""
        runner = CliRunner()
        result = runner.invoke(task, ["cleanup", "T001"], obj={"echo_for_testing": True, "spec_id": "002-feature"})
        assert result.exit_code == 0
        assert "ECHO: task cleanup" in result.output


class TestJJContainerUp:
    """Tests for jj container-up command."""

    def test_container_up_help(self):
        """Shows help text."""
        runner = CliRunner()
        result = runner.invoke(task, ["container-up", "--help"])
        assert result.exit_code == 0
        assert "Start devcontainer" in result.output

    def test_container_up_echo_mode(self):
        """Echoes command in test mode."""
        runner = CliRunner()
        result = runner.invoke(task, ["container-up", "T001"], obj={"echo_for_testing": True, "spec_id": "002-feature"})
        assert result.exit_code == 0
        assert "ECHO: task container-up" in result.output


class TestJJContainerStop:
    """Tests for jj container-stop command."""

    def test_container_stop_help(self):
        """Shows help text."""
        runner = CliRunner()
        result = runner.invoke(task, ["container-stop", "--help"])
        assert result.exit_code == 0
        assert "Stop devcontainer" in result.output

    def test_container_stop_echo_mode(self):
        """Echoes command in test mode."""
        runner = CliRunner()
        result = runner.invoke(task, ["container-stop", "T001"], obj={"echo_for_testing": True, "spec_id": "002-feature"})
        assert result.exit_code == 0
        assert "ECHO: task container-stop" in result.output
