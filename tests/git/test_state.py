"""Tests for git/state.py."""

from agent_arborist.git.repo import git_add_all, git_commit, git_checkout
from agent_arborist.git.state import (
    TaskState,
    get_task_trailers,
    task_state_from_trailers,
    is_task_complete,
    scan_completed_tasks,
)
from agent_arborist.constants import TRAILER_STEP, TRAILER_RESULT
from agent_arborist.tree.model import TaskNode, TaskTree


def _commit_task(repo, task_id, **trailers):
    """Helper: commit with trailers on current branch."""
    trailer_lines = "\n".join(f"{k}: {v}" for k, v in trailers.items())
    msg = f"task({task_id}): step\n\n{trailer_lines}"
    git_add_all(repo)
    git_commit(msg, repo, allow_empty=True)


def test_task_state_from_trailers_pending():
    assert task_state_from_trailers({}) == TaskState.PENDING


def test_task_state_from_trailers_complete():
    assert task_state_from_trailers({TRAILER_STEP: "complete"}) == TaskState.COMPLETE


def test_task_state_from_trailers_failed():
    trailers = {TRAILER_STEP: "complete", TRAILER_RESULT: "fail"}
    assert task_state_from_trailers(trailers) == TaskState.FAILED


def test_task_state_from_trailers_implementing():
    assert task_state_from_trailers({TRAILER_STEP: "implement"}) == TaskState.IMPLEMENTING


def test_task_state_from_trailers_testing():
    assert task_state_from_trailers({TRAILER_STEP: "test"}) == TaskState.TESTING


def test_task_state_from_trailers_reviewing():
    assert task_state_from_trailers({TRAILER_STEP: "review"}) == TaskState.REVIEWING


def test_get_task_trailers_from_branch(git_repo):
    git_checkout("feature/test/phase1", git_repo, create=True)
    _commit_task(git_repo, "T001", **{TRAILER_STEP: "complete", TRAILER_RESULT: "pass"})

    trailers = get_task_trailers("feature/test/phase1", "T001", git_repo)
    assert trailers[TRAILER_STEP] == "complete"
    assert trailers[TRAILER_RESULT] == "pass"


def test_is_task_complete(git_repo):
    git_checkout("feature/test/phase1", git_repo, create=True)
    _commit_task(git_repo, "T001", **{TRAILER_STEP: "complete", TRAILER_RESULT: "pass"})

    assert is_task_complete("feature/test/phase1", "T001", git_repo)


def test_is_task_not_complete_when_pending(git_repo):
    assert not is_task_complete("feature/test/phase1", "T001", git_repo)


def test_scan_completed_tasks(git_repo):
    tree = TaskTree(spec_id="test", namespace="feature")
    tree.root_ids = ["phase1"]
    tree.nodes["phase1"] = TaskNode(id="phase1", name="Phase 1", children=["T001", "T002"])
    tree.nodes["T001"] = TaskNode(id="T001", name="Task 1", parent="phase1")
    tree.nodes["T002"] = TaskNode(id="T002", name="Task 2", parent="phase1")

    # Complete T001 on phase branch
    git_checkout("feature/test/phase1", git_repo, create=True)
    _commit_task(git_repo, "T001", **{TRAILER_STEP: "complete", TRAILER_RESULT: "pass"})
    git_checkout("main", git_repo)

    completed = scan_completed_tasks(tree, git_repo)
    assert "T001" in completed
    assert "T002" not in completed
