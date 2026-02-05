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
        mock_manifest = MagicMock()
        mock_manifest.get_task.return_value = MagicMock(
            change_id="abc123",
            parent_change="main",
            children=["T002"],
        )
        mock_tasks = [MagicMock(task_id="T001", change_id="abc123", status="running")]

        with patch("agent_arborist.task_cli.is_jj_repo", return_value=True):
            with patch("agent_arborist.task_cli._get_manifest", return_value=mock_manifest):
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
        assert "Setup jj changes" in result.output

    def test_setup_spec_no_spec(self):
        """Errors when no spec available."""
        runner = CliRunner()
        result = runner.invoke(task, ["setup-spec"], obj={})
        assert result.exit_code == 1
        assert "No spec available" in result.output

    def test_setup_spec_success(self):
        """Creates changes successfully."""
        runner = CliRunner()
        mock_manifest = MagicMock()
        mock_result = {"verified": ["a", "b"], "created": ["c"], "errors": []}

        with patch("agent_arborist.task_cli._get_manifest", return_value=mock_manifest):
            with patch("agent_arborist.task_cli.create_all_changes_from_manifest", return_value=mock_result):
                result = runner.invoke(task, ["setup-spec"], obj={"spec_id": "002-feature"})

        assert result.exit_code == 0
        assert "Verified:" in result.output
        assert "Created:" in result.output

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
        assert "Prepare task for execution" in result.output

    def test_pre_sync_no_spec(self):
        """Errors when no spec available."""
        runner = CliRunner()
        result = runner.invoke(task, ["pre-sync", "T001"], obj={})
        assert result.exit_code == 1

    def test_pre_sync_success(self):
        """Syncs task successfully."""
        runner = CliRunner()
        mock_manifest = MagicMock()
        mock_manifest.get_task.return_value = MagicMock(
            change_id="abc123",
            parent_change="main",
        )
        mock_setup_result = MagicMock(success=True)

        with patch("agent_arborist.task_cli._get_manifest", return_value=mock_manifest):
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
        assert "Complete a task" in result.output

    def test_complete_echo_mode(self):
        """Echoes command in test mode."""
        runner = CliRunner()
        result = runner.invoke(task, ["complete", "T001"], obj={"echo_for_testing": True, "spec_id": "002-feature"})
        assert result.exit_code == 0
        assert "ECHO: task complete" in result.output


class TestJJSyncParent:
    """Tests for jj sync-parent command."""

    def test_sync_parent_help(self):
        """Shows help text."""
        runner = CliRunner()
        result = runner.invoke(task, ["sync-parent", "--help"])
        assert result.exit_code == 0
        assert "Sync parent task" in result.output

    def test_sync_parent_echo_mode(self):
        """Echoes command in test mode."""
        runner = CliRunner()
        result = runner.invoke(task, ["sync-parent", "T001"], obj={"echo_for_testing": True, "spec_id": "002-feature"})
        assert result.exit_code == 0
        assert "ECHO: task sync-parent" in result.output


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
