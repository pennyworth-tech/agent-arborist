"""Integration tests for runners that require actual CLI tools.

These tests are skipped by default. Run with:
    pytest -m integration

Or run specific runner tests:
    pytest -m claude
    pytest -m opencode
    pytest -m gemini
"""

import shutil

import pytest

from agent_arborist.runner import ClaudeRunner, OpencodeRunner, GeminiRunner


# Skip markers for each CLI
requires_claude = pytest.mark.skipif(
    shutil.which("claude") is None,
    reason="claude CLI not installed",
)
requires_opencode = pytest.mark.skipif(
    shutil.which("opencode") is None,
    reason="opencode CLI not installed",
)
requires_gemini = pytest.mark.skipif(
    shutil.which("gemini") is None,
    reason="gemini CLI not installed",
)


@pytest.mark.integration
@pytest.mark.claude
@requires_claude
class TestClaudeRunnerIntegration:
    """Integration tests for ClaudeRunner with real CLI."""

    def test_is_available(self):
        runner = ClaudeRunner()
        assert runner.is_available()

    def test_run_simple_prompt(self):
        runner = ClaudeRunner()
        result = runner.run("Reply with just the word 'hello'", timeout=30)
        assert result.success
        assert result.exit_code == 0
        assert "hello" in result.output.lower()

    def test_run_returns_output(self):
        runner = ClaudeRunner()
        result = runner.run("What is 2+2? Reply with just the number.", timeout=30)
        assert result.success
        assert "4" in result.output


@pytest.mark.integration
@pytest.mark.opencode
@requires_opencode
class TestOpencodeRunnerIntegration:
    """Integration tests for OpencodeRunner with real CLI."""

    def test_is_available(self):
        runner = OpencodeRunner()
        assert runner.is_available()

    def test_run_simple_prompt(self):
        runner = OpencodeRunner()
        result = runner.run("Reply with just the word 'hello'", timeout=30)
        assert result.success
        assert result.exit_code == 0
        assert "hello" in result.output.lower()

    def test_run_returns_output(self):
        runner = OpencodeRunner()
        result = runner.run("What is 2+2? Reply with just the number.", timeout=30)
        assert result.success
        assert "4" in result.output


@pytest.mark.integration
@pytest.mark.gemini
@requires_gemini
class TestGeminiRunnerIntegration:
    """Integration tests for GeminiRunner with real CLI."""

    def test_is_available(self):
        runner = GeminiRunner()
        assert runner.is_available()

    def test_run_simple_prompt(self):
        runner = GeminiRunner()
        result = runner.run("Reply with just the word 'hello'", timeout=30)
        assert result.success
        assert result.exit_code == 0
        assert "hello" in result.output.lower()

    def test_run_returns_output(self):
        runner = GeminiRunner()
        result = runner.run("What is 2+2? Reply with just the number.", timeout=30)
        assert result.success
        assert "4" in result.output
