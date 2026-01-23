"""Integration tests for spec detection using real git repos."""

import os
import subprocess
from pathlib import Path

import pytest

from agent_arborist.spec import detect_spec_from_git, get_git_branch


@pytest.fixture
def git_sandbox(tmp_path):
    """Create a temporary directory for git testing."""
    original_cwd = os.getcwd()
    yield tmp_path
    os.chdir(original_cwd)


def init_git_repo(path: Path, branch: str = "main") -> None:
    """Initialize a git repo with an initial commit."""
    os.chdir(path)
    subprocess.run(["git", "init"], capture_output=True, check=True)
    subprocess.run(["git", "checkout", "-b", branch], capture_output=True, check=True)

    # Create initial commit (required for HEAD to exist)
    readme = path / "README.md"
    readme.write_text("# Test repo\n")
    subprocess.run(["git", "add", "."], capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        capture_output=True,
        check=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@test.com",
             "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@test.com"},
    )


def checkout_branch(branch: str) -> None:
    """Create and checkout a new branch."""
    subprocess.run(["git", "checkout", "-b", branch], capture_output=True, check=True)


class TestGetGitBranch:
    def test_returns_branch_name(self, git_sandbox):
        init_git_repo(git_sandbox, branch="main")
        assert get_git_branch() == "main"

    def test_returns_spec_branch(self, git_sandbox):
        init_git_repo(git_sandbox, branch="001-my-feature")
        assert get_git_branch() == "001-my-feature"

    def test_returns_none_outside_git_repo(self, tmp_path):
        """Use tmp_path (outside repo) to test non-git directory."""
        os.chdir(tmp_path)
        assert get_git_branch() is None


class TestDetectSpecFromGitIntegration:
    def test_detects_simple_spec_branch(self, git_sandbox):
        init_git_repo(git_sandbox, branch="001-calculator")

        result = detect_spec_from_git()
        assert result.found
        assert result.spec_id == "001-calculator"  # full string
        assert result.name == "calculator"
        assert result.branch == "001-calculator"
        assert result.source == "git"

    def test_detects_complex_spec_branch(self, git_sandbox):
        init_git_repo(git_sandbox, branch="002-bl-17-rabbitmq-event-bus")

        result = detect_spec_from_git()
        assert result.found
        assert result.spec_id == "002-bl-17-rabbitmq-event-bus"  # full string
        assert result.name == "bl-17-rabbitmq-event-bus"

    def test_detects_spec_in_nested_branch(self, git_sandbox):
        init_git_repo(git_sandbox, branch="main")
        checkout_branch("003-todo-app/phase-1")

        result = detect_spec_from_git()
        assert result.found
        assert result.spec_id == "003-todo-app"  # full string
        assert result.name == "todo-app"
        assert result.branch == "003-todo-app/phase-1"

    def test_detects_spec_in_deeply_nested_branch(self, git_sandbox):
        init_git_repo(git_sandbox, branch="main")
        checkout_branch("004-weather-cli/phase-2/T005")

        result = detect_spec_from_git()
        assert result.found
        assert result.spec_id == "004-weather-cli"  # full string
        assert result.name == "weather-cli"

    def test_detects_spec_with_feature_prefix(self, git_sandbox):
        init_git_repo(git_sandbox, branch="main")
        checkout_branch("feature/005-url-shortener")

        result = detect_spec_from_git()
        assert result.found
        assert result.spec_id == "005-url-shortener"  # full string
        assert result.name == "url-shortener"

    def test_no_spec_on_main(self, git_sandbox):
        init_git_repo(git_sandbox, branch="main")

        result = detect_spec_from_git()
        assert not result.found
        assert result.branch == "main"
        assert "main" in result.error

    def test_no_spec_on_develop(self, git_sandbox):
        init_git_repo(git_sandbox, branch="develop")

        result = detect_spec_from_git()
        assert not result.found
        assert result.branch == "develop"

    def test_no_spec_on_feature_without_number(self, git_sandbox):
        init_git_repo(git_sandbox, branch="main")
        checkout_branch("feature/add-login")

        result = detect_spec_from_git()
        assert not result.found
        assert "add-login" not in (result.spec_id or "")

    def test_not_in_git_repo(self, tmp_path):
        """Use tmp_path (outside repo) to test non-git directory."""
        os.chdir(tmp_path)

        result = detect_spec_from_git()
        assert not result.found
        assert "git" in result.error.lower()

    def test_multiple_specs_uses_first(self, git_sandbox):
        """If branch has multiple spec patterns, use the first one found."""
        init_git_repo(git_sandbox, branch="main")
        checkout_branch("001-first/002-second")

        result = detect_spec_from_git()
        assert result.found
        assert result.spec_id == "001-first"  # full string
        assert result.name == "first"


class TestBranchPatterns:
    """Test various branch naming patterns."""

    @pytest.mark.parametrize("branch,expected_name", [
        ("001-a", "a"),
        ("999-z", "z"),
        ("123-test-branch", "test-branch"),
        ("000-zero-prefix", "zero-prefix"),
        ("042-answer-to-everything", "answer-to-everything"),
    ])
    def test_valid_spec_branches(self, git_sandbox, branch, expected_name):
        init_git_repo(git_sandbox, branch=branch)

        result = detect_spec_from_git()
        assert result.found
        assert result.spec_id == branch  # spec_id is the full branch/segment
        assert result.name == expected_name

    @pytest.mark.parametrize("branch", [
        "main",
        "master",
        "develop",
        "feature/something",
        "bugfix/issue-123",
        "1-not-three-digits",
        "12-not-three-digits",
        "1234-too-many-digits",
        "abc-not-numbers",
    ])
    def test_invalid_spec_branches(self, git_sandbox, branch):
        init_git_repo(git_sandbox, branch="main")
        if branch != "main":
            checkout_branch(branch)

        result = detect_spec_from_git()
        assert not result.found
