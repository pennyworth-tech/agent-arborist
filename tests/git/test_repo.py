"""Tests for git/repo.py."""

import pytest

from agent_arborist.git.repo import (
    GitError,
    git_init,
    git_checkout,
    git_branch_exists,
    git_add_all,
    git_commit,
    git_last_commit_for_file,
    git_log,
    git_current_branch,
    git_merge,
    git_diff,
    git_branch_list,
)


def test_git_init(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git_init(repo)
    assert (repo / ".git").is_dir()


def test_git_commit_and_log(git_repo):
    (git_repo / "hello.txt").write_text("hello")
    git_add_all(git_repo)
    sha = git_commit("add hello", git_repo)
    assert len(sha) == 40

    log = git_log("main", "%s", git_repo, n=1)
    assert log == "add hello"


def test_git_branch_exists(git_repo):
    assert git_branch_exists("main", git_repo)
    assert not git_branch_exists("nonexistent", git_repo)


def test_git_checkout_create(git_repo):
    git_checkout("feature/test", git_repo, create=True)
    assert git_current_branch(git_repo) == "feature/test"
    assert git_branch_exists("feature/test", git_repo)


def test_git_checkout_with_start_point(git_repo):
    git_checkout("feature/branch", git_repo, create=True, start_point="main")
    assert git_current_branch(git_repo) == "feature/branch"


def test_git_merge(git_repo):
    # Create a branch with a commit
    git_checkout("feature/merge-test", git_repo, create=True)
    (git_repo / "new.txt").write_text("new")
    git_add_all(git_repo)
    git_commit("add new", git_repo)

    # Merge back
    git_checkout("main", git_repo)
    git_merge("feature/merge-test", git_repo, message="merge feature")

    log = git_log("main", "%s", git_repo, n=1)
    assert "merge feature" in log


def test_git_diff(git_repo):
    git_checkout("feature/diff-test", git_repo, create=True)
    (git_repo / "diff.txt").write_text("diff content")
    git_add_all(git_repo)
    git_commit("add diff", git_repo)

    diff = git_diff("main", "feature/diff-test", git_repo)
    assert "diff content" in diff


def test_git_branch_list(git_repo):
    branches = git_branch_list(git_repo)
    assert "main" in branches


def test_git_commit_allow_empty(git_repo):
    sha = git_commit("empty commit", git_repo, allow_empty=True)
    assert len(sha) == 40


def test_git_error_on_bad_command(git_repo):
    with pytest.raises(GitError):
        git_checkout("nonexistent-branch", git_repo)


def test_git_log_with_grep(git_repo):
    (git_repo / "a.txt").write_text("a")
    git_add_all(git_repo)
    git_commit("task(T001): implement", git_repo)

    log = git_log("main", "%s", git_repo, n=10, grep="task(T001)")
    assert "T001" in log


def test_git_last_commit_for_file(git_repo):
    (git_repo / "tree.json").write_text("{}")
    git_add_all(git_repo)
    sha = git_commit("add tree", git_repo)
    assert git_last_commit_for_file("tree.json", git_repo) == sha

    # A later commit that doesn't touch tree.json shouldn't change the result
    git_commit("unrelated", git_repo, allow_empty=True)
    assert git_last_commit_for_file("tree.json", git_repo) == sha


def test_git_last_commit_for_file_missing(git_repo):
    assert git_last_commit_for_file("nonexistent.json", git_repo) is None
