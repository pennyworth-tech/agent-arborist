"""Tests for richer commit messages with runner output."""

import subprocess

import pytest

from agent_arborist.tree.model import TaskNode, TaskTree
from agent_arborist.worker.garden import (
    _truncate_output,
    _truncate_name,
    _build_trailers,
    _commit_with_trailers,
    garden,
)


# ── Unit tests: _truncate_output ──


def test_truncate_output_short():
    assert _truncate_output("hello") == "hello"


def test_truncate_output_long():
    text = "A" * 3000
    result = _truncate_output(text, max_chars=2000)
    assert result.startswith("[...truncated]\n")
    assert result.endswith("A" * 2000)
    assert len(result) == len("[...truncated]\n") + 2000


def test_truncate_output_empty():
    assert _truncate_output("") == ""
    assert _truncate_output(None) == ""


# ── Unit tests: _truncate_name ──


def test_truncate_name_short():
    assert _truncate_name("short name") == "short name"


def test_truncate_name_long():
    name = "A" * 60
    result = _truncate_name(name, max_len=50)
    assert len(result) == 50
    assert result.endswith("...")


# ── Unit tests: commit message assembly ──


def test_build_commit_message_with_body(git_repo):
    """Subject + body + trailers all present."""
    sha = _commit_with_trailers(
        "T001", 'implement "Create files"', git_repo,
        body="Runner output:\nsome output here",
        **{"Arborist-Step": "implement", "Arborist-Result": "pass"},
    )
    msg = subprocess.run(
        ["git", "log", "-1", "--format=%B", sha],
        cwd=git_repo, capture_output=True, text=True, check=True,
    ).stdout
    assert 'task(T001): implement "Create files"' in msg
    assert "Runner output:\nsome output here" in msg
    assert "Arborist-Step: implement" in msg


def test_build_commit_message_without_body(git_repo):
    """No body → subject directly followed by trailers (no double blank lines)."""
    sha = _commit_with_trailers(
        "T001", "complete", git_repo,
        **{"Arborist-Step": "complete"},
    )
    msg = subprocess.run(
        ["git", "log", "-1", "--format=%B", sha],
        cwd=git_repo, capture_output=True, text=True, check=True,
    ).stdout
    assert "task(T001): complete" in msg
    assert "\n\n\n" not in msg  # no triple newline from empty body


# ── Integration tests ──


def _make_tree():
    tree = TaskTree(spec_id="test")
    tree.nodes["phase1"] = TaskNode(id="phase1", name="Phase 1", children=["T001"])
    tree.nodes["T001"] = TaskNode(
        id="T001", name="Create user auth module", parent="phase1",
        description="Create auth module",
    )
    tree.compute_execution_order()
    return tree


def _get_all_commits(cwd, branch="HEAD", n=20):
    """Return list of full commit messages on branch."""
    result = subprocess.run(
        ["git", "log", f"-{n}", "--format=%B---COMMIT_SEP---", branch],
        cwd=cwd, capture_output=True, text=True, check=True,
    )
    return [m.strip() for m in result.stdout.split("---COMMIT_SEP---") if m.strip()]


def _get_all_subjects(cwd, branch="HEAD", n=20):
    result = subprocess.run(
        ["git", "log", f"-{n}", "--format=%s", branch],
        cwd=cwd, capture_output=True, text=True, check=True,
    )
    return result.stdout


def _find_commit_containing(commits, substring):
    for msg in commits:
        if substring in msg:
            return msg
    return None


@pytest.mark.integration
def test_implement_commit_contains_runner_output(git_repo, mock_runner_all_pass):
    tree = _make_tree()
    garden(tree, git_repo, mock_runner_all_pass)
    commits = _get_all_commits(git_repo)
    msg = _find_commit_containing(commits, "implement")
    assert msg is not None
    assert "Implementation complete" in msg
    assert "Runner output" in msg


@pytest.mark.integration
def test_test_commit_contains_stdout(git_repo, mock_runner_all_pass):
    tree = _make_tree()
    garden(tree, git_repo, mock_runner_all_pass, test_command="echo 'all tests passed'")
    commits = _get_all_commits(git_repo)
    msg = _find_commit_containing(commits, "tests pass")
    assert msg is not None
    assert "all tests passed" in msg


@pytest.mark.integration
def test_review_commit_contains_review_text(git_repo, mock_runner_all_pass):
    tree = _make_tree()
    garden(tree, git_repo, mock_runner_all_pass)
    commits = _get_all_commits(git_repo)
    msg = _find_commit_containing(commits, "review approved")
    assert msg is not None
    assert "APPROVED" in msg


@pytest.mark.integration
def test_failed_implement_commit_contains_error(git_repo):
    from tests.conftest import MockRunner
    runner = MockRunner(implement_ok=False)
    tree = _make_tree()
    garden(tree, git_repo, runner, max_retries=1)
    commits = _get_all_commits(git_repo)
    msg = _find_commit_containing(commits, "implement")
    assert msg is not None
    assert "Runner error" in msg
    assert "failed" in msg.lower()


@pytest.mark.integration
def test_commit_subjects_include_task_name(git_repo, mock_runner_all_pass):
    tree = _make_tree()
    garden(tree, git_repo, mock_runner_all_pass)
    subjects = _get_all_subjects(git_repo)
    assert "Create user auth module" in subjects


@pytest.mark.integration
def test_retry_commits_show_attempt_number(git_repo):
    from tests.conftest import MockRunner
    runner = MockRunner(implement_ok=True, review_sequence=[False, True])
    tree = _make_tree()
    garden(tree, git_repo, runner)
    subjects = _get_all_subjects(git_repo)
    assert "attempt 1/" in subjects


@pytest.mark.integration
def test_long_output_truncated_in_commit(git_repo):
    from dataclasses import dataclass
    from agent_arborist.runner import RunResult

    @dataclass
    class BigOutputRunner:
        name: str = "big"
        command: str = "mock"
        def run(self, prompt, **kw):
            if "review" in prompt.lower():
                return RunResult(success=True, output="APPROVED")
            return RunResult(success=True, output="X" * 5000)
        def is_available(self):
            return True

    tree = _make_tree()
    runner = BigOutputRunner()
    garden(tree, git_repo, runner)
    commits = _get_all_commits(git_repo)
    msg = _find_commit_containing(commits, "implement")
    assert msg is not None
    assert "[...truncated]" in msg


@pytest.mark.integration
def test_trailers_still_parseable(git_repo, mock_runner_all_pass):
    tree = _make_tree()
    garden(tree, git_repo, mock_runner_all_pass)
    # Check trailers on complete commit
    result = subprocess.run(
        ["git", "log", "--format=%(trailers)", "--all"],
        cwd=git_repo, capture_output=True, text=True, check=True,
    )
    trailers = result.stdout
    assert "Arborist-Step: complete" in trailers
    assert "Arborist-Result: pass" in trailers
    assert "Arborist-Step: implement" in trailers
    assert "Arborist-Step: test" in trailers
    assert "Arborist-Step: review" in trailers
