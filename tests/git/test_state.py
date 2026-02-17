"""Tests for git/state.py."""

from agent_arborist.git.repo import git_add_all, git_commit
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


def test_get_task_trailers_from_head(git_repo):
    _commit_task(git_repo, "T001", **{TRAILER_STEP: "complete", TRAILER_RESULT: "pass"})

    trailers = get_task_trailers("HEAD", "T001", git_repo)
    assert trailers[TRAILER_STEP] == "complete"
    assert trailers[TRAILER_RESULT] == "pass"


def test_is_task_complete(git_repo):
    _commit_task(git_repo, "T001", **{TRAILER_STEP: "complete", TRAILER_RESULT: "pass"})

    assert is_task_complete("HEAD", "T001", git_repo)


def test_is_task_not_complete_when_pending(git_repo):
    assert not is_task_complete("HEAD", "T001", git_repo)


def test_scan_completed_tasks(git_repo):
    tree = TaskTree(spec_id="test")
    tree.nodes["phase1"] = TaskNode(id="phase1", name="Phase 1", children=["T001", "T002"])
    tree.nodes["T001"] = TaskNode(id="T001", name="Task 1", parent="phase1")
    tree.nodes["T002"] = TaskNode(id="T002", name="Task 2", parent="phase1")

    # Complete T001 on current branch
    _commit_task(git_repo, "T001", **{TRAILER_STEP: "complete", TRAILER_RESULT: "pass"})

    completed = scan_completed_tasks(tree, git_repo)
    assert "T001" in completed
    assert "T002" not in completed


def test_scan_ignores_commits_before_anchor(git_repo):
    """Commits before the anchor SHA should be invisible to scan_completed_tasks."""
    tree = TaskTree(spec_id="test")
    tree.nodes["phase1"] = TaskNode(id="phase1", name="Phase 1", children=["T001", "T002"])
    tree.nodes["T001"] = TaskNode(id="T001", name="Task 1", parent="phase1")
    tree.nodes["T002"] = TaskNode(id="T002", name="Task 2", parent="phase1")

    # Old run: complete T001 *before* the anchor
    _commit_task(git_repo, "T001", **{TRAILER_STEP: "complete", TRAILER_RESULT: "pass"})

    # Write the tree file (this commit becomes the anchor)
    (git_repo / "task-tree.json").write_text("{}")
    git_add_all(git_repo)
    anchor_sha = git_commit("add task tree", git_repo)

    # New run: complete T002 *after* the anchor
    _commit_task(git_repo, "T002", **{TRAILER_STEP: "complete", TRAILER_RESULT: "pass"})

    # With anchor, only T002 should be seen as complete
    completed = scan_completed_tasks(tree, git_repo, since=anchor_sha)
    assert "T001" not in completed
    assert "T002" in completed

    # Without anchor (backward compat), both are seen
    completed_all = scan_completed_tasks(tree, git_repo)
    assert "T001" in completed_all
    assert "T002" in completed_all
