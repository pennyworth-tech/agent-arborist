"""Tests for dag CLI commands (run, run-status, run-show)."""

import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from agent_arborist.cli import main
from agent_arborist.home import ARBORIST_DIR_NAME, DAGU_DIR_NAME


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def fixtures_dir():
    """Path to test fixtures."""
    return Path(__file__).parent / "fixtures"


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
def initialized_repo(git_repo):
    """Create a git repo with arborist initialized."""
    runner = CliRunner()
    result = runner.invoke(main, ["init"])
    assert result.exit_code == 0
    return git_repo


@pytest.fixture
def repo_with_dag(initialized_repo, fixtures_dir):
    """Create a repo with arborist initialized and a DAG installed."""
    # Copy fixture DAG and manifest to dagu home
    dags_dir = initialized_repo / ARBORIST_DIR_NAME / DAGU_DIR_NAME / "dags"

    shutil.copy(fixtures_dir / "dag-simple.yaml", dags_dir / "simple-test.yaml")
    shutil.copy(fixtures_dir / "dag-simple.json", dags_dir / "simple-test.json")

    return initialized_repo


@pytest.fixture
def repo_with_parallel_dag(initialized_repo, fixtures_dir):
    """Create a repo with a parallel DAG installed."""
    dags_dir = initialized_repo / ARBORIST_DIR_NAME / DAGU_DIR_NAME / "dags"

    shutil.copy(fixtures_dir / "dag-parallel.yaml", dags_dir / "parallel-test.yaml")
    shutil.copy(fixtures_dir / "dag-parallel.json", dags_dir / "parallel-test.json")

    return initialized_repo


# -----------------------------------------------------------------------------
# Help and group structure tests
# -----------------------------------------------------------------------------


class TestDagGroup:
    """Tests for dag command group."""

    def test_dag_group_exists(self):
        runner = CliRunner()
        result = runner.invoke(main, ["dag", "--help"])
        assert result.exit_code == 0
        assert "DAG execution and monitoring" in result.output

    def test_dag_group_has_run_command(self):
        runner = CliRunner()
        result = runner.invoke(main, ["dag", "--help"])
        assert result.exit_code == 0
        assert "run " in result.output  # space to avoid matching run-status

    def test_dag_group_has_run_status_command(self):
        runner = CliRunner()
        result = runner.invoke(main, ["dag", "--help"])
        assert result.exit_code == 0
        assert "run-status" in result.output

    def test_dag_group_has_run_show_command(self):
        runner = CliRunner()
        result = runner.invoke(main, ["dag", "--help"])
        assert result.exit_code == 0
        assert "run-show" in result.output


class TestDagRunHelp:
    """Tests for dag run command help."""

    def test_dag_run_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["dag", "run", "--help"])
        assert result.exit_code == 0
        assert "Execute a DAG" in result.output
        assert "--dry-run" in result.output
        assert "--params" in result.output
        assert "--run-id" in result.output

    def test_dag_run_dag_name_is_optional(self):
        runner = CliRunner()
        result = runner.invoke(main, ["dag", "run", "--help"])
        assert result.exit_code == 0
        assert "[DAG_NAME]" in result.output


class TestDagRunStatusHelp:
    """Tests for dag run-status command help."""

    def test_dag_run_status_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["dag", "run-status", "--help"])
        assert result.exit_code == 0
        assert "status" in result.output.lower()
        assert "--run-id" in result.output
        assert "--json" in result.output
        assert "--watch" in result.output


class TestDagRunShowHelp:
    """Tests for dag run-show command help."""

    def test_dag_run_show_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["dag", "run-show", "--help"])
        assert result.exit_code == 0
        assert "details" in result.output.lower()
        assert "--run-id" in result.output
        assert "--logs" in result.output
        assert "--step" in result.output


# -----------------------------------------------------------------------------
# Echo for testing tests
# -----------------------------------------------------------------------------


class TestDagEchoForTesting:
    """Tests for --echo-for-testing with dag commands."""

    def test_echo_dag_run(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--echo-for-testing", "dag", "run", "my-dag"])
        assert result.exit_code == 0
        assert "ECHO: dag run" in result.output
        assert "dag_name=my-dag" in result.output

    def test_echo_dag_run_with_options(self):
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--echo-for-testing", "dag", "run", "my-dag", "--dry-run", "--params", "FOO=bar"],
        )
        assert result.exit_code == 0
        assert "ECHO: dag run" in result.output
        assert "dry_run=True" in result.output
        assert "params=FOO=bar" in result.output

    def test_echo_dag_run_with_run_id(self):
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--echo-for-testing", "dag", "run", "my-dag", "--run-id", "test-123"],
        )
        assert result.exit_code == 0
        assert "run_id=test-123" in result.output

    def test_echo_dag_run_status(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--echo-for-testing", "dag", "run-status", "my-dag"])
        assert result.exit_code == 0
        assert "ECHO: dag run-status" in result.output
        assert "dag_name=my-dag" in result.output

    def test_echo_dag_run_status_with_options(self):
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--echo-for-testing", "dag", "run-status", "my-dag", "--run-id", "abc123", "--json"],
        )
        assert result.exit_code == 0
        assert "run_id=abc123" in result.output
        assert "json=True" in result.output

    def test_echo_dag_run_show(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--echo-for-testing", "dag", "run-show", "my-dag"])
        assert result.exit_code == 0
        assert "ECHO: dag run-show" in result.output
        assert "dag_name=my-dag" in result.output

    def test_echo_dag_run_show_with_options(self):
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--echo-for-testing", "dag", "run-show", "my-dag", "--logs", "--step", "T001"],
        )
        assert result.exit_code == 0
        assert "logs=True" in result.output
        assert "step=T001" in result.output

    def test_echo_dag_run_defaults_to_spec_id(self):
        """When no dag_name provided, should use spec_id from context."""
        runner = CliRunner()
        result = runner.invoke(main, ["--echo-for-testing", "--spec", "001-my-spec", "dag", "run"])
        assert result.exit_code == 0
        assert "spec_id=001-my-spec" in result.output
        assert "dag_name=001-my-spec" in result.output


# -----------------------------------------------------------------------------
# Error handling tests
# -----------------------------------------------------------------------------


class TestDagRunErrors:
    """Tests for dag run error handling."""

    def test_dag_run_requires_dagu_home(self, git_repo):
        """dag run should fail if arborist not initialized."""
        runner = CliRunner()
        result = runner.invoke(main, ["dag", "run", "nonexistent"])
        assert result.exit_code != 0
        assert "DAGU_HOME" in result.output or "init" in result.output.lower()

    def test_dag_run_dag_not_found(self, initialized_repo):
        """dag run should fail if DAG file doesn't exist."""
        runner = CliRunner()
        result = runner.invoke(main, ["dag", "run", "nonexistent-dag"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_dag_run_no_dag_name_no_spec(self, initialized_repo):
        """dag run without dag_name should fail if no spec available."""
        runner = CliRunner()
        result = runner.invoke(main, ["dag", "run"])
        assert result.exit_code != 0
        assert "No DAG" in result.output or "spec" in result.output.lower()


class TestDagRunStatusErrors:
    """Tests for dag run-status error handling."""

    def test_dag_run_status_requires_dagu_home(self, git_repo):
        """dag run-status should fail if arborist not initialized."""
        runner = CliRunner()
        result = runner.invoke(main, ["dag", "run-status", "nonexistent"])
        assert result.exit_code != 0

    def test_dag_run_status_dag_not_found(self, initialized_repo):
        """dag run-status should fail if DAG doesn't exist."""
        runner = CliRunner()
        result = runner.invoke(main, ["dag", "run-status", "nonexistent-dag"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()


class TestDagRunShowErrors:
    """Tests for dag run-show error handling."""

    def test_dag_run_show_requires_dagu_home(self, git_repo):
        """dag run-show should fail if arborist not initialized."""
        runner = CliRunner()
        result = runner.invoke(main, ["dag", "run-show", "nonexistent"])
        assert result.exit_code != 0

    def test_dag_run_show_dag_not_found(self, initialized_repo):
        """dag run-show should fail if DAG doesn't exist."""
        runner = CliRunner()
        result = runner.invoke(main, ["dag", "run-show", "nonexistent-dag"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()


# -----------------------------------------------------------------------------
# Mocked dagu execution tests
# -----------------------------------------------------------------------------


def mock_subprocess_run_for_dagu(original_run):
    """Create a mock that only intercepts dagu commands, passes through git commands."""
    def side_effect(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args", [])
        # If it's a git command, let it through
        if cmd and (cmd[0] == "git" or "git" in str(cmd[0])):
            return original_run(*args, **kwargs)
        # Otherwise return mocked dagu response
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout="Succeeded", stderr=""
        )
    return side_effect


class TestDagRunWithMockedDagu:
    """Tests for dag run with mocked dagu subprocess."""

    def test_dag_run_calls_dagu_start(self, repo_with_dag):
        """dag run should call dagu start with correct arguments."""
        original_run = subprocess.run
        with patch("agent_arborist.cli.shutil.which", return_value="/usr/bin/dagu"):
            with patch("agent_arborist.cli.subprocess.run", side_effect=mock_subprocess_run_for_dagu(original_run)) as mock_run:
                runner = CliRunner()
                result = runner.invoke(main, ["dag", "run", "simple-test"])

                assert result.exit_code == 0, f"Failed: {result.output}"
                # Verify dagu start was called
                calls = [c for c in mock_run.call_args_list if "start" in str(c)]
                assert len(calls) > 0

    def test_dag_run_dry_run_calls_dagu_dry(self, repo_with_dag):
        """dag run --dry-run should call dagu dry instead of start."""
        original_run = subprocess.run
        with patch("agent_arborist.cli.shutil.which", return_value="/usr/bin/dagu"):
            with patch("agent_arborist.cli.subprocess.run", side_effect=mock_subprocess_run_for_dagu(original_run)) as mock_run:
                runner = CliRunner()
                result = runner.invoke(main, ["dag", "run", "simple-test", "--dry-run"])

                assert result.exit_code == 0, f"Failed: {result.output}"
                # Verify dagu dry was called
                calls = [c for c in mock_run.call_args_list if "dry" in str(c)]
                assert len(calls) > 0

    def test_dag_run_passes_params(self, repo_with_dag):
        """dag run --params should pass parameters to dagu."""
        original_run = subprocess.run
        with patch("agent_arborist.cli.shutil.which", return_value="/usr/bin/dagu"):
            with patch("agent_arborist.cli.subprocess.run", side_effect=mock_subprocess_run_for_dagu(original_run)) as mock_run:
                runner = CliRunner()
                result = runner.invoke(main, ["dag", "run", "simple-test", "--params", "FOO=bar"])

                assert result.exit_code == 0, f"Failed: {result.output}"
                # Verify params were passed
                call_args = str(mock_run.call_args_list)
                assert "FOO=bar" in call_args

    def test_dag_run_passes_run_id(self, repo_with_dag):
        """dag run --run-id should pass run ID to dagu."""
        original_run = subprocess.run
        with patch("agent_arborist.cli.shutil.which", return_value="/usr/bin/dagu"):
            with patch("agent_arborist.cli.subprocess.run", side_effect=mock_subprocess_run_for_dagu(original_run)) as mock_run:
                runner = CliRunner()
                result = runner.invoke(main, ["dag", "run", "simple-test", "--run-id", "my-run-123"])

                assert result.exit_code == 0, f"Failed: {result.output}"
                call_args = str(mock_run.call_args_list)
                assert "my-run-123" in call_args

    def test_dag_run_sets_manifest_env(self, repo_with_dag):
        """dag run should set ARBORIST_MANIFEST environment variable."""
        original_run = subprocess.run
        with patch("agent_arborist.cli.shutil.which", return_value="/usr/bin/dagu"):
            with patch("agent_arborist.cli.subprocess.run", side_effect=mock_subprocess_run_for_dagu(original_run)) as mock_run:
                runner = CliRunner()
                result = runner.invoke(main, ["dag", "run", "simple-test"])

                assert result.exit_code == 0, f"Failed: {result.output}"
                # Check that env was passed with ARBORIST_MANIFEST
                for call in mock_run.call_args_list:
                    if "start" in str(call):
                        env = call.kwargs.get("env", {})
                        if "ARBORIST_MANIFEST" in env:
                            assert "simple-test.json" in env["ARBORIST_MANIFEST"]
                            break

    def test_dag_run_dagu_not_found(self, repo_with_dag):
        """dag run should fail gracefully if dagu not installed."""
        with patch("agent_arborist.cli.shutil.which", return_value=None):
            runner = CliRunner()
            result = runner.invoke(main, ["dag", "run", "simple-test"])

            assert result.exit_code != 0
            assert "dagu" in result.output.lower()


class TestDagRunStatusWithMockedDagu:
    """Tests for dag run-status with mocked dagu subprocess."""

    def test_dag_run_status_calls_dagu_status(self, repo_with_dag):
        """dag run-status should call dagu status."""
        original_run = subprocess.run
        def mock_side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if cmd and (cmd[0] == "git" or "git" in str(cmd[0])):
                return original_run(*args, **kwargs)
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="Status: running\nPID: 12345", stderr=""
            )

        with patch("agent_arborist.cli.shutil.which", return_value="/usr/bin/dagu"):
            with patch("agent_arborist.cli.subprocess.run", side_effect=mock_side_effect) as mock_run:
                runner = CliRunner()
                result = runner.invoke(main, ["dag", "run-status", "simple-test"])

                assert result.exit_code == 0, f"Failed: {result.output}"
                calls = [c for c in mock_run.call_args_list if "status" in str(c)]
                assert len(calls) > 0

    def test_dag_run_status_with_run_id(self, repo_with_dag):
        """dag run-status --run-id should pass run ID to dagu."""
        original_run = subprocess.run
        def mock_side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if cmd and (cmd[0] == "git" or "git" in str(cmd[0])):
                return original_run(*args, **kwargs)
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="Status: completed", stderr=""
            )

        with patch("agent_arborist.cli.shutil.which", return_value="/usr/bin/dagu"):
            with patch("agent_arborist.cli.subprocess.run", side_effect=mock_side_effect) as mock_run:
                runner = CliRunner()
                result = runner.invoke(main, ["dag", "run-status", "simple-test", "--run-id", "abc123"])

                assert result.exit_code == 0, f"Failed: {result.output}"
                call_args = str(mock_run.call_args_list)
                assert "abc123" in call_args

    def test_dag_run_status_json_output(self, repo_with_dag):
        """dag run-status --json should output JSON format."""
        original_run = subprocess.run
        def mock_side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if cmd and (cmd[0] == "git" or "git" in str(cmd[0])):
                return original_run(*args, **kwargs)
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout='{"status": "running", "pid": 12345}', stderr=""
            )

        with patch("agent_arborist.cli.shutil.which", return_value="/usr/bin/dagu"):
            with patch("agent_arborist.cli.subprocess.run", side_effect=mock_side_effect):
                runner = CliRunner()
                result = runner.invoke(main, ["dag", "run-status", "simple-test", "--json"])

                assert result.exit_code == 0, f"Failed: {result.output}"
                # Output should be valid JSON or contain JSON
                assert "{" in result.output


class TestDagRunShowWithMockedDagu:
    """Tests for dag run-show with mocked dagu subprocess."""

    def test_dag_run_show_displays_run_details(self, repo_with_dag):
        """dag run-show should display run details."""
        original_run = subprocess.run
        def mock_side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if cmd and (cmd[0] == "git" or "git" in str(cmd[0])):
                return original_run(*args, **kwargs)
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="Status: completed\nSteps: 5/5", stderr=""
            )

        with patch("agent_arborist.cli.shutil.which", return_value="/usr/bin/dagu"):
            with patch("agent_arborist.cli.subprocess.run", side_effect=mock_side_effect):
                runner = CliRunner()
                result = runner.invoke(main, ["dag", "run-show", "simple-test"])

                assert result.exit_code == 0, f"Failed: {result.output}"

    def test_dag_run_show_with_step_filter(self, repo_with_dag):
        """dag run-show --step should filter to specific step."""
        original_run = subprocess.run
        def mock_side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if cmd and (cmd[0] == "git" or "git" in str(cmd[0])):
                return original_run(*args, **kwargs)
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="Step T001: completed", stderr=""
            )

        with patch("agent_arborist.cli.shutil.which", return_value="/usr/bin/dagu"):
            with patch("agent_arborist.cli.subprocess.run", side_effect=mock_side_effect):
                runner = CliRunner()
                result = runner.invoke(main, ["dag", "run-show", "simple-test", "--step", "T001"])

                assert result.exit_code == 0, f"Failed: {result.output}"


# -----------------------------------------------------------------------------
# Real dagu integration tests (skipped if dagu not available)
# -----------------------------------------------------------------------------


def dagu_available():
    """Check if dagu is available."""
    return shutil.which("dagu") is not None


@pytest.mark.skipif(not dagu_available(), reason="dagu not available")
class TestDagRunIntegration:
    """Integration tests with real dagu execution."""

    def test_dag_run_dry_run_succeeds(self, repo_with_dag):
        """dag run --dry-run should succeed with real dagu."""
        runner = CliRunner()
        result = runner.invoke(main, ["dag", "run", "simple-test", "--dry-run"])

        assert result.exit_code == 0
        assert "Succeeded" in result.output or "OK" in result.output

    def test_dag_run_parallel_dry_run(self, repo_with_parallel_dag):
        """dag run --dry-run should handle parallel tasks."""
        runner = CliRunner()
        result = runner.invoke(main, ["dag", "run", "parallel-test", "--dry-run"])

        assert result.exit_code == 0

    def test_dag_run_status_no_runs(self, repo_with_dag):
        """dag run-status should handle case with no previous runs."""
        runner = CliRunner()
        result = runner.invoke(main, ["dag", "run-status", "simple-test"])

        # Should either show "no runs" or exit cleanly
        assert result.exit_code == 0 or "no" in result.output.lower()

    def test_dag_run_show_no_runs(self, repo_with_dag):
        """dag run-show should handle case with no previous runs."""
        runner = CliRunner()
        result = runner.invoke(main, ["dag", "run-show", "simple-test"])

        # Should either show "no runs" or exit cleanly
        assert result.exit_code == 0 or "no" in result.output.lower()


@pytest.mark.skipif(not dagu_available(), reason="dagu not available")
class TestDagRunFullCycle:
    """Integration tests for full run cycle."""

    def test_run_then_status(self, repo_with_dag):
        """Run a DAG and then check its status."""
        runner = CliRunner()

        # Run the DAG (dry-run for speed)
        run_result = runner.invoke(main, ["dag", "run", "simple-test", "--dry-run"])
        assert run_result.exit_code == 0

        # Check status
        status_result = runner.invoke(main, ["dag", "run-status", "simple-test"])
        # Should succeed (may show no runs since dry-run doesn't create a run)
        assert status_result.exit_code == 0

    def test_run_with_custom_run_id(self, repo_with_dag):
        """Run a DAG with custom run ID (mocked to avoid actual execution)."""
        original_run = subprocess.run

        def mock_side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if cmd and (cmd[0] == "git" or "git" in str(cmd[0])):
                return original_run(*args, **kwargs)
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="Started with run ID", stderr=""
            )

        run_id = "test-run-001"

        with patch("agent_arborist.cli.shutil.which", return_value="/usr/bin/dagu"):
            with patch("agent_arborist.cli.subprocess.run", side_effect=mock_side_effect) as mock_run:
                runner = CliRunner()
                run_result = runner.invoke(
                    main, ["dag", "run", "simple-test", "--run-id", run_id]
                )
                assert run_result.exit_code == 0, f"Failed: {run_result.output}"

                # Verify run-id was passed to dagu
                call_args = str(mock_run.call_args_list)
                assert run_id in call_args


# -----------------------------------------------------------------------------
# Output format tests
# -----------------------------------------------------------------------------


class TestDagOutputFormats:
    """Tests for dag command output formats."""

    def test_dag_run_quiet_mode(self, repo_with_dag):
        """dag run with --quiet should suppress non-essential output."""
        original_run = subprocess.run
        with patch("agent_arborist.cli.shutil.which", return_value="/usr/bin/dagu"):
            with patch("agent_arborist.cli.subprocess.run", side_effect=mock_subprocess_run_for_dagu(original_run)):
                runner = CliRunner()
                result = runner.invoke(main, ["--quiet", "dag", "run", "simple-test", "--dry-run"])

                assert result.exit_code == 0, f"Failed: {result.output}"
                # Output should be minimal
                assert len(result.output.strip()) < 100 or result.output.strip() == ""

    def test_dag_run_status_shows_step_progress(self, repo_with_dag):
        """dag run-status should show step progress."""
        original_run = subprocess.run
        def mock_side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if cmd and (cmd[0] == "git" or "git" in str(cmd[0])):
                return original_run(*args, **kwargs)
            return subprocess.CompletedProcess(
                args=cmd, returncode=0,
                stdout="T001-setup: completed\nT002-build: running\nT003-test: pending",
                stderr=""
            )

        with patch("agent_arborist.cli.shutil.which", return_value="/usr/bin/dagu"):
            with patch("agent_arborist.cli.subprocess.run", side_effect=mock_side_effect):
                runner = CliRunner()
                result = runner.invoke(main, ["dag", "run-status", "simple-test"])

                assert result.exit_code == 0, f"Failed: {result.output}"
                # Should show some status info
                assert "T001" in result.output or "completed" in result.output.lower() or "running" in result.output.lower()


# -----------------------------------------------------------------------------
# Dashboard command tests
# -----------------------------------------------------------------------------


class TestDagDashboardHelp:
    """Tests for dag dashboard command help."""

    def test_dag_group_has_dashboard_command(self):
        runner = CliRunner()
        result = runner.invoke(main, ["dag", "--help"])
        assert result.exit_code == 0
        assert "dashboard" in result.output

    def test_dag_dashboard_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["dag", "dashboard", "--help"])
        assert result.exit_code == 0
        assert "Launch the Dagu web dashboard" in result.output
        assert "--port" in result.output
        assert "--host" in result.output


class TestDagDashboardEchoForTesting:
    """Tests for --echo-for-testing with dag dashboard."""

    def test_echo_dag_dashboard(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--echo-for-testing", "dag", "dashboard"])
        assert result.exit_code == 0
        assert "ECHO: dag dashboard" in result.output
        assert "port=8080" in result.output  # default port
        assert "host=127.0.0.1" in result.output  # default host

    def test_echo_dag_dashboard_with_options(self):
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--echo-for-testing", "dag", "dashboard", "--port", "9999", "--host", "0.0.0.0"],
        )
        assert result.exit_code == 0
        assert "ECHO: dag dashboard" in result.output
        assert "port=9999" in result.output
        assert "host=0.0.0.0" in result.output


class TestDagDashboardErrors:
    """Tests for dag dashboard error handling."""

    def test_dag_dashboard_requires_dagu_home(self, git_repo):
        """dag dashboard should fail if arborist not initialized."""
        runner = CliRunner()
        result = runner.invoke(main, ["dag", "dashboard"])
        assert result.exit_code != 0
        assert "DAGU_HOME" in result.output or "init" in result.output.lower()

    def test_dag_dashboard_dagu_not_found(self, initialized_repo):
        """dag dashboard should fail gracefully if dagu not installed."""
        with patch("agent_arborist.cli.shutil.which", return_value=None):
            runner = CliRunner()
            result = runner.invoke(main, ["dag", "dashboard"])

            assert result.exit_code != 0
            assert "dagu" in result.output.lower()


def mock_popen_for_dagu(original_popen):
    """Create a mock that only intercepts dagu commands, passes through other Popen calls."""
    mock_process = MagicMock()
    mock_process.wait.return_value = 0

    def side_effect(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args", [])
        # If it's a dagu command (server), return mock
        if cmd and "server" in cmd:
            return mock_process
        # Otherwise use real Popen
        return original_popen(*args, **kwargs)
    return side_effect, mock_process


class TestDagDashboardWithMockedDagu:
    """Tests for dag dashboard with mocked dagu subprocess."""

    def test_dag_dashboard_calls_dagu_server(self, initialized_repo):
        """dag dashboard should call dagu server with correct arguments."""
        original_popen = subprocess.Popen
        side_effect, mock_process = mock_popen_for_dagu(original_popen)

        with patch("agent_arborist.cli.shutil.which", return_value="/usr/bin/dagu"):
            with patch("agent_arborist.cli.subprocess.Popen", side_effect=side_effect) as mock_popen:
                runner = CliRunner()
                result = runner.invoke(main, ["dag", "dashboard"])

                assert result.exit_code == 0, f"Failed: {result.output}"
                # Verify dagu server was called
                calls = [c for c in mock_popen.call_args_list if "server" in str(c)]
                assert len(calls) > 0
                call_args = calls[0][0][0]
                assert "server" in call_args
                assert "--port" in call_args
                assert "--host" in call_args

    def test_dag_dashboard_custom_port(self, initialized_repo):
        """dag dashboard --port should pass port to dagu server."""
        original_popen = subprocess.Popen
        side_effect, _ = mock_popen_for_dagu(original_popen)

        with patch("agent_arborist.cli.shutil.which", return_value="/usr/bin/dagu"):
            with patch("agent_arborist.cli.subprocess.Popen", side_effect=side_effect) as mock_popen:
                runner = CliRunner()
                result = runner.invoke(main, ["dag", "dashboard", "--port", "9999"])

                assert result.exit_code == 0, f"Failed: {result.output}"
                calls = [c for c in mock_popen.call_args_list if "server" in str(c)]
                call_args = str(calls[0])
                assert "9999" in call_args

    def test_dag_dashboard_custom_host(self, initialized_repo):
        """dag dashboard --host should pass host to dagu server."""
        original_popen = subprocess.Popen
        side_effect, _ = mock_popen_for_dagu(original_popen)

        with patch("agent_arborist.cli.shutil.which", return_value="/usr/bin/dagu"):
            with patch("agent_arborist.cli.subprocess.Popen", side_effect=side_effect) as mock_popen:
                runner = CliRunner()
                result = runner.invoke(main, ["dag", "dashboard", "--host", "0.0.0.0"])

                assert result.exit_code == 0, f"Failed: {result.output}"
                calls = [c for c in mock_popen.call_args_list if "server" in str(c)]
                call_args = str(calls[0])
                assert "0.0.0.0" in call_args

    def test_dag_dashboard_sets_dagu_home_env(self, initialized_repo):
        """dag dashboard should set DAGU_HOME environment variable."""
        original_popen = subprocess.Popen
        side_effect, _ = mock_popen_for_dagu(original_popen)

        with patch("agent_arborist.cli.shutil.which", return_value="/usr/bin/dagu"):
            with patch("agent_arborist.cli.subprocess.Popen", side_effect=side_effect) as mock_popen:
                runner = CliRunner()
                result = runner.invoke(main, ["dag", "dashboard"])

                assert result.exit_code == 0, f"Failed: {result.output}"
                calls = [c for c in mock_popen.call_args_list if "server" in str(c)]
                env = calls[0][1].get("env", {})
                assert "DAGU_HOME" in env

    def test_dag_dashboard_nonzero_exit(self, initialized_repo):
        """dag dashboard should handle non-zero exit from dagu server."""
        original_popen = subprocess.Popen
        mock_process = MagicMock()
        mock_process.wait.return_value = 1  # Non-zero exit

        def side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if cmd and "server" in cmd:
                return mock_process
            return original_popen(*args, **kwargs)

        with patch("agent_arborist.cli.shutil.which", return_value="/usr/bin/dagu"):
            with patch("agent_arborist.cli.subprocess.Popen", side_effect=side_effect):
                runner = CliRunner()
                result = runner.invoke(main, ["dag", "dashboard"])

                assert result.exit_code != 0
                assert "Error" in result.output or "exited" in result.output


# -----------------------------------------------------------------------------
# Dashboard integration test (real dagu)
# -----------------------------------------------------------------------------


@pytest.mark.skipif(not dagu_available(), reason="dagu not available")
class TestDagDashboardIntegration:
    """Integration tests for dag dashboard with real dagu."""

    def test_dag_dashboard_launches_and_responds(self, initialized_repo):
        """dag dashboard should launch and respond on the configured port."""
        import socket
        import time

        # Find an available port dynamically
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()

        # Get dagu home from initialized repo
        dagu_home = initialized_repo / ARBORIST_DIR_NAME / DAGU_DIR_NAME
        dags_dir = dagu_home / "dags"

        # Build environment
        env = os.environ.copy()
        env["DAGU_HOME"] = str(dagu_home)

        # Find dagu
        dagu_path = shutil.which("dagu")
        assert dagu_path is not None

        # Launch dashboard directly (not via CLI to have control over process)
        cmd = [
            dagu_path,
            "server",
            "--host", "127.0.0.1",
            "--port", str(port),
            "--dags", str(dags_dir),
        ]

        process = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        try:
            # Poll for availability (max 3 seconds)
            import urllib.request
            import urllib.error

            url = f"http://127.0.0.1:{port}/"
            available = False
            start_time = time.time()

            while time.time() - start_time < 3.0:
                try:
                    response = urllib.request.urlopen(url, timeout=0.5)
                    if response.status == 200:
                        available = True
                        break
                except (urllib.error.URLError, ConnectionRefusedError, TimeoutError):
                    time.sleep(0.1)
                    continue

            assert available, f"Dashboard did not become available on port {port} within 3 seconds"

        finally:
            # Clean shutdown - use SIGKILL for immediate termination
            # SIGTERM may leave the port in use if dagu doesn't handle it gracefully
            process.kill()
            process.wait()
            # Small delay to ensure OS releases the port
            time.sleep(0.1)
