"""Integration tests for runners that require actual CLI tools.

These tests are skipped by default. Run with:
    pytest -m integration

Or run specific runner tests:
    pytest -m claude
    pytest -m opencode
    pytest -m gemini
    pytest -m dagu
"""

import shutil

import pytest
from click.testing import CliRunner

from agent_arborist.runner import ClaudeRunner, OpencodeRunner, GeminiRunner
from agent_arborist.cli import main


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
requires_dagu = pytest.mark.skipif(
    shutil.which("dagu") is None,
    reason="dagu CLI not installed",
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


@pytest.mark.integration
@pytest.mark.dagu
@requires_dagu
class TestDaguIntegration:
    """Integration tests for dagu CLI."""

    def test_check_dagu_command(self):
        runner = CliRunner()
        result = runner.invoke(main, ["doctor", "check-dagu"])
        assert result.exit_code == 0
        assert "All dagu checks passed" in result.output

    def test_check_dagu_shows_version(self):
        runner = CliRunner()
        result = runner.invoke(main, ["doctor", "check-dagu"])
        assert result.exit_code == 0
        assert "dagu version" in result.output


@pytest.fixture
def initialized_git_repo(tmp_path):
    """Create a temp git repo with arborist initialized."""
    import os
    import subprocess

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
    # Initialize arborist
    runner = CliRunner()
    result = runner.invoke(main, ["init"])
    assert result.exit_code == 0

    yield tmp_path
    os.chdir(original_cwd)


@pytest.mark.integration
@pytest.mark.dagu
@requires_dagu
class TestDaguHomeIntegration:
    """Integration tests verifying DAGU_HOME works correctly."""

    def test_check_dagu_with_initialized_repo(self, initialized_git_repo):
        runner = CliRunner()
        result = runner.invoke(main, ["doctor", "check-dagu"])
        assert result.exit_code == 0
        assert "DAGU_HOME=" in result.output
        assert "DAGU_HOME is working correctly" in result.output

    def test_check_dagu_places_test_dag_in_dags_dir(self, initialized_git_repo):
        runner = CliRunner()
        result = runner.invoke(main, ["doctor", "check-dagu"])
        assert result.exit_code == 0
        assert "Placed test DAG in" in result.output
        assert "dags/arborist-test.yaml" in result.output

    def test_dags_directory_created_on_init(self, initialized_git_repo):
        dags_dir = initialized_git_repo / ".arborist" / "dagu" / "dags"
        assert dags_dir.is_dir()
