"""Tests for CLI commands."""

from unittest.mock import patch, MagicMock
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
