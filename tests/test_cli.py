"""Tests for CLI commands."""

from unittest.mock import patch
from click.testing import CliRunner

from agent_arborist.cli import main
from agent_arborist.checks import DependencyStatus


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
