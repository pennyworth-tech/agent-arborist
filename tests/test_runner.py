"""Tests for runner module."""

from unittest.mock import patch, MagicMock
import subprocess

import pytest

from agent_arborist.runner import (
    Runner,
    ClaudeRunner,
    OpencodeRunner,
    GeminiRunner,
    RunResult,
    get_runner,
    DEFAULT_RUNNER,
)


class TestRunResult:
    def test_success_result(self):
        result = RunResult(success=True, output="Hello!", exit_code=0)
        assert result.success
        assert result.output == "Hello!"
        assert result.error is None
        assert result.exit_code == 0

    def test_failure_result(self):
        result = RunResult(success=False, output="", error="Command failed", exit_code=1)
        assert not result.success
        assert result.error == "Command failed"


class TestClaudeRunner:
    def test_name_and_command(self):
        runner = ClaudeRunner()
        assert runner.name == "claude"
        assert runner.command == "claude"

    @patch("shutil.which")
    def test_is_available_when_found(self, mock_which):
        mock_which.return_value = "/usr/bin/claude"
        runner = ClaudeRunner()
        assert runner.is_available()

    @patch("shutil.which")
    def test_is_available_when_not_found(self, mock_which):
        mock_which.return_value = None
        runner = ClaudeRunner()
        assert not runner.is_available()

    @patch("shutil.which")
    def test_run_not_found(self, mock_which):
        mock_which.return_value = None
        runner = ClaudeRunner()
        result = runner.run("test prompt")
        assert not result.success
        assert "not found" in result.error

    @patch("subprocess.run")
    @patch("shutil.which")
    def test_run_success(self, mock_which, mock_run):
        mock_which.return_value = "/usr/bin/claude"
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Here's a joke!",
            stderr="",
        )

        runner = ClaudeRunner()
        result = runner.run("tell me a joke")

        assert result.success
        assert result.output == "Here's a joke!"
        assert result.exit_code == 0

        # Verify CLI args
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[0][0] == ["/usr/bin/claude", "--dangerously-skip-permissions", "-p", "tell me a joke"]

    @patch("subprocess.run")
    @patch("shutil.which")
    def test_run_failure(self, mock_which, mock_run):
        mock_which.return_value = "/usr/bin/claude"
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Error occurred",
        )

        runner = ClaudeRunner()
        result = runner.run("bad prompt")

        assert not result.success
        assert result.error == "Error occurred"
        assert result.exit_code == 1

    @patch("subprocess.run")
    @patch("shutil.which")
    def test_run_timeout(self, mock_which, mock_run):
        mock_which.return_value = "/usr/bin/claude"
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=30)

        runner = ClaudeRunner()
        result = runner.run("slow prompt", timeout=30)

        assert not result.success
        assert "Timeout" in result.error
        assert "30" in result.error

    @patch("subprocess.run")
    @patch("shutil.which")
    def test_run_exception(self, mock_which, mock_run):
        mock_which.return_value = "/usr/bin/claude"
        mock_run.side_effect = OSError("Permission denied")

        runner = ClaudeRunner()
        result = runner.run("test")

        assert not result.success
        assert "Permission denied" in result.error


class TestOpencodeRunner:
    def test_name_and_command(self):
        runner = OpencodeRunner()
        assert runner.name == "opencode"
        assert runner.command == "opencode"

    @patch("subprocess.run")
    @patch("shutil.which")
    def test_run_uses_correct_args(self, mock_which, mock_run):
        mock_which.return_value = "/usr/bin/opencode"
        mock_run.return_value = MagicMock(returncode=0, stdout="output", stderr="")

        runner = OpencodeRunner()
        runner.run("prompt")

        call_args = mock_run.call_args
        assert call_args[0][0] == ["/usr/bin/opencode", "run", "prompt"]


class TestGeminiRunner:
    def test_name_and_command(self):
        runner = GeminiRunner()
        assert runner.name == "gemini"
        assert runner.command == "gemini"

    @patch("subprocess.run")
    @patch("shutil.which")
    def test_run_uses_correct_args(self, mock_which, mock_run):
        mock_which.return_value = "/usr/bin/gemini"
        mock_run.return_value = MagicMock(returncode=0, stdout="output", stderr="")

        runner = GeminiRunner()
        runner.run("prompt")

        call_args = mock_run.call_args
        assert call_args[0][0] == ["/usr/bin/gemini", "--yolo", "prompt"]


class TestGetRunner:
    def test_default_runner(self):
        # Default is now claude (can be overridden via ARBORIST_DEFAULT_RUNNER env var)
        assert DEFAULT_RUNNER == "claude"

    def test_get_claude_runner(self):
        runner = get_runner("claude")
        assert isinstance(runner, ClaudeRunner)

    def test_get_opencode_runner(self):
        runner = get_runner("opencode")
        assert isinstance(runner, OpencodeRunner)

    def test_get_gemini_runner(self):
        runner = get_runner("gemini")
        assert isinstance(runner, GeminiRunner)

    def test_get_default_runner(self):
        # Default is now claude (can be overridden via ARBORIST_DEFAULT_RUNNER env var)
        runner = get_runner()
        assert isinstance(runner, ClaudeRunner)

    def test_unknown_runner_raises(self):
        with pytest.raises(ValueError) as exc_info:
            get_runner("unknown")
        assert "Unknown runner type" in str(exc_info.value)
