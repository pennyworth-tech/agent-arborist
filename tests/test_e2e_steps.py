"""End-to-end tests for per-step runner/model config with real AI runners.

Validates that implement and review phases are dispatched to separate runners
when configured with different runner/model combinations.

Run with: pytest -m integration tests/test_e2e_steps.py -v
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from agent_arborist.git.repo import (
    git_add_all,
    git_commit,
    git_current_branch,
    git_log,
)
from agent_arborist.git.state import get_task_trailers, scan_completed_tasks
from agent_arborist.runner import get_runner
from agent_arborist.tree.model import TaskNode, TaskTree
from agent_arborist.worker.garden import garden
from agent_arborist.worker.gardener import gardener


# Pairs of (implement_runner, implement_model, review_runner, review_model)
# Each pair uses a different runner for implement vs review.
MIXED_RUNNER_CONFIGS = [
    pytest.param(
        "claude", "haiku", "gemini", "gemini-2.5-flash",
        id="impl-claude-rev-gemini",
    ),
    pytest.param(
        "gemini", "gemini-2.5-flash", "claude", "haiku",
        id="impl-gemini-rev-claude",
    ),
]

# Same runner for both, but different models
SAME_RUNNER_CONFIGS = [
    pytest.param(
        "claude", "haiku", "claude", "haiku",
        id="claude-haiku-both",
    ),
]


def _skip_if_missing(cli_binary: str):
    if not shutil.which(cli_binary):
        pytest.skip(f"{cli_binary} not found on PATH")


def _simple_tree() -> TaskTree:
    tree = TaskTree()
    tree.nodes["phase1"] = TaskNode(id="phase1", name="Setup", children=["T001"])
    tree.nodes["T001"] = TaskNode(
        id="T001", name="Create a greeting file", parent="phase1",
        description="Create a file called 'hello.txt' containing 'hello world'.",
    )
    return tree


def _two_task_tree() -> TaskTree:
    tree = TaskTree()
    tree.nodes["phase1"] = TaskNode(id="phase1", name="Setup", children=["T001", "T002"])
    tree.nodes["T001"] = TaskNode(
        id="T001", name="Create a file", parent="phase1",
        description="Create a file called 'hello.txt' containing 'hello'.",
    )
    tree.nodes["T002"] = TaskNode(
        id="T002", name="Create another file", parent="phase1",
        depends_on=["T001"],
        description="Create a file called 'world.txt' containing 'world'.",
    )
    return tree


def _setup_repo_with_tree(git_repo: Path, tree: TaskTree) -> None:
    tree.compute_execution_order()
    tree_path = git_repo / "task-tree.json"
    tree_path.write_text(json.dumps(tree.to_dict(), indent=2) + "\n")
    git_add_all(git_repo)
    git_commit("arborist: build task tree", git_repo)


# ---------------------------------------------------------------------------
# 1. Mixed runners: different AI for implement vs review
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.parametrize(
    "impl_type,impl_model,rev_type,rev_model", MIXED_RUNNER_CONFIGS,
)
def test_ai_garden_mixed_runners(
    git_repo, impl_type, impl_model, rev_type, rev_model,
):
    """Single task with different runners for implement and review produces valid commits."""
    _skip_if_missing(impl_type)
    _skip_if_missing(rev_type)

    tree = _simple_tree()
    _setup_repo_with_tree(git_repo, tree)

    impl_runner = get_runner(impl_type, impl_model)
    rev_runner = get_runner(rev_type, rev_model)

    result = garden(
        tree, git_repo,
        implement_runner=impl_runner,
        review_runner=rev_runner,
        branch="main",
    )

    assert result.success, f"garden() failed: {result.error}"
    assert result.task_id == "T001"
    assert git_current_branch(git_repo) == "main"

    trailers = get_task_trailers("HEAD", "T001", git_repo, current_branch="main")
    assert trailers["Arborist-Step"] == "complete"
    assert trailers["Arborist-Result"] == "pass"


# ---------------------------------------------------------------------------
# 2. Gardener loop with mixed runners, two tasks
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.parametrize(
    "impl_type,impl_model,rev_type,rev_model", MIXED_RUNNER_CONFIGS,
)
def test_ai_gardener_mixed_runners(
    git_repo, impl_type, impl_model, rev_type, rev_model,
):
    """Two tasks complete with different runners for implement vs review."""
    _skip_if_missing(impl_type)
    _skip_if_missing(rev_type)

    tree = _two_task_tree()
    _setup_repo_with_tree(git_repo, tree)

    impl_runner = get_runner(impl_type, impl_model)
    rev_runner = get_runner(rev_type, rev_model)

    result = gardener(
        tree, git_repo,
        implement_runner=impl_runner,
        review_runner=rev_runner,
        branch="main",
    )

    assert result.success, f"gardener() failed: {result.error}"
    assert result.tasks_completed == 2
    assert result.order == ["T001", "T002"]

    completed = scan_completed_tasks(tree, git_repo, branch="main")
    assert completed == {"T001", "T002"}


# ---------------------------------------------------------------------------
# 3. Same runner for both — baseline sanity with the new two-runner API
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.parametrize(
    "impl_type,impl_model,rev_type,rev_model", SAME_RUNNER_CONFIGS,
)
def test_ai_garden_same_runner_both_steps(
    git_repo, impl_type, impl_model, rev_type, rev_model,
):
    """Same runner for implement and review still works through the two-runner API."""
    _skip_if_missing(impl_type)

    tree = _simple_tree()
    _setup_repo_with_tree(git_repo, tree)

    impl_runner = get_runner(impl_type, impl_model)
    rev_runner = get_runner(rev_type, rev_model)

    result = garden(
        tree, git_repo,
        implement_runner=impl_runner,
        review_runner=rev_runner,
        branch="main",
    )

    assert result.success, f"garden() failed: {result.error}"
    assert result.task_id == "T001"

    trailers = get_task_trailers("HEAD", "T001", git_repo, current_branch="main")
    assert trailers["Arborist-Step"] == "complete"
    assert trailers["Arborist-Result"] == "pass"
