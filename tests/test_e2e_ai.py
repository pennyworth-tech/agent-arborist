"""End-to-end tests using real AI runners.

Validates git structure: commits with correct format, changed files, phase merges
rolled up to the base branch. Does NOT check specific file contents or outputs.

Each test is parametrized across runner configs:
  - claude/haiku
  - opencode/cerebras
  - gemini/flash

Run with: pytest -m integration tests/test_e2e_ai.py -v
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from agent_arborist.git.repo import (
    _run,
    git_branch_exists,
    git_current_branch,
    git_log,
)
from agent_arborist.git.state import get_task_trailers, scan_completed_tasks
from agent_arborist.runner import get_runner
from agent_arborist.tree.ai_planner import plan_tree
from agent_arborist.tree.model import TaskNode, TaskTree, TestCommand, TestType
from agent_arborist.worker.garden import garden
from agent_arborist.worker.gardener import gardener

FIXTURES = Path(__file__).parent / "fixtures"

# Runner configurations: (runner_type, model, cli_binary)
RUNNER_CONFIGS = [
    pytest.param("claude", "haiku", "claude", id="claude-haiku"),
    pytest.param("opencode", "cerebras/zai-glm-4.7", "opencode", id="opencode-cerebras"),
    pytest.param("gemini", "gemini-2.5-flash", "gemini", id="gemini-flash"),
]

# Planner configurations (need strong reasoning)
PLANNER_CONFIGS = [
    pytest.param("claude", "opus", "claude", id="claude-opus"),
    pytest.param("gemini", "gemini-2.5-pro", "gemini", id="gemini-pro"),
]


def _skip_if_missing(cli_binary: str):
    """Skip test if the runner CLI is not installed."""
    if not shutil.which(cli_binary):
        pytest.skip(f"{cli_binary} not found on PATH")


def _setup_repo_with_tree(git_repo: Path, tree: TaskTree) -> None:
    """Write task-tree.json and commit it, simulating `arborist build`."""
    from agent_arborist.git.repo import git_add_all, git_commit
    tree.compute_execution_order()
    tree_path = git_repo / "task-tree.json"
    tree_path.write_text(json.dumps(tree.to_dict(), indent=2) + "\n")
    git_add_all(git_repo)
    git_commit(f"arborist: build task tree for {tree.spec_id}", git_repo)


def _simple_tree() -> TaskTree:
    """Single phase, single trivial task."""
    tree = TaskTree(spec_id="hello", namespace="feature")
    tree.nodes["phase1"] = TaskNode(id="phase1", name="Setup", children=["T001"])
    tree.nodes["T001"] = TaskNode(
        id="T001", name="Create project structure", parent="phase1",
        description="Create a file called 'hello.txt' containing 'hello world'.",
    )
    return tree


def _two_task_tree() -> TaskTree:
    """Single phase, two tasks, T002 depends on T001."""
    tree = TaskTree(spec_id="hello", namespace="feature")
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


# ---------------------------------------------------------------------------
# 1. AI-planned tree from real spec
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.parametrize("runner_type,model,cli_binary", PLANNER_CONFIGS)
def test_ai_builds_valid_tree(tmp_path, runner_type, model, cli_binary):
    """AI reads hello-world spec and produces a structurally valid TaskTree."""
    _skip_if_missing(cli_binary)

    # Copy only the hello-world spec into an isolated directory
    import shutil as _shutil
    spec_dir = tmp_path / "spec"
    spec_dir.mkdir()
    _shutil.copy(FIXTURES / "tasks-hello-world.md", spec_dir / "tasks-hello-world.md")

    result = plan_tree(
        spec_dir=spec_dir,
        spec_id="hello",
        namespace="feature",
        runner_type=runner_type,
        model=model,
        timeout=300,
    )

    assert result.success, f"AI planner failed: {result.error}"
    tree = result.tree

    assert len(tree.root_ids) >= 1
    leaves = tree.leaves()
    assert len(leaves) >= 3

    order = tree.compute_execution_order()
    assert len(order) == len(leaves)

    restored = TaskTree.from_dict(json.loads(json.dumps(tree.to_dict())))
    assert len(restored.leaves()) == len(leaves)

    # Source back-references populated by AI
    assert len(tree.spec_files) >= 1
    nodes_with_source = [n for n in tree.nodes.values() if n.source_file]
    assert len(nodes_with_source) >= 1


# ---------------------------------------------------------------------------
# 2. Garden one task: verify commit structure
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.parametrize("runner_type,model,cli_binary", RUNNER_CONFIGS)
def test_ai_garden_creates_commits_with_trailers(git_repo, runner_type, model, cli_binary):
    """Single task produces commits with correct subjects and trailers."""
    _skip_if_missing(cli_binary)

    tree = _simple_tree()
    _setup_repo_with_tree(git_repo, tree)

    runner = get_runner(runner_type, model)
    result = garden(tree, git_repo, runner, base_branch="main")

    assert result.success, f"garden() failed: {result.error}"
    assert result.task_id == "T001"

    # Back on base branch
    assert git_current_branch(git_repo) == "main"

    # Phase branch exists
    assert git_branch_exists("feature/hello/phase1", git_repo)

    # Commits follow task(TXXX): convention
    log = git_log("feature/hello/phase1", "%s", git_repo, n=20)
    subjects = [s.strip() for s in log.strip().split("\n") if s.strip()]
    task_commits = [s for s in subjects if s.startswith("task(T001):")]
    assert len(task_commits) >= 3, f"Expected implement/test/review/complete commits, got: {task_commits}"

    # Most recent commit has complete trailer
    trailers = get_task_trailers("feature/hello/phase1", "T001", git_repo)
    assert trailers["Arborist-Step"] == "complete"
    assert trailers["Arborist-Result"] == "pass"

    # At least one commit changed files
    numstat = _run(["log", "feature/hello/phase1", "--format=", "--numstat", "-n", "20"], git_repo)
    assert len(numstat.strip()) > 0, "Expected at least one commit with file changes"


# ---------------------------------------------------------------------------
# 3. Gardener two tasks: verify order, merge rollup to base branch
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.parametrize("runner_type,model,cli_binary", RUNNER_CONFIGS)
def test_ai_gardener_merges_phase_to_base(git_repo, runner_type, model, cli_binary):
    """Two tasks complete in order, phase merges back to base branch."""
    _skip_if_missing(cli_binary)

    tree = _two_task_tree()
    _setup_repo_with_tree(git_repo, tree)

    runner = get_runner(runner_type, model)
    result = gardener(tree, git_repo, runner, base_branch="main")

    assert result.success, f"gardener() failed: {result.error}"
    assert result.tasks_completed == 2
    assert result.order == ["T001", "T002"]

    # Ends on base branch
    assert git_current_branch(git_repo) == "main"

    # Both tasks have complete trailers on the phase branch
    completed = scan_completed_tasks(tree, git_repo)
    assert completed == {"T001", "T002"}

    # Phase branch has commits for both tasks
    log = git_log("feature/hello/phase1", "%s", git_repo, n=30)
    assert "task(T001):" in log
    assert "task(T002):" in log

    # T001 commits come before T002 commits (chronologically)
    subjects = [s.strip() for s in log.strip().split("\n") if s.strip()]
    subjects.reverse()  # oldest first
    first_t001 = next(i for i, s in enumerate(subjects) if "task(T001):" in s)
    first_t002 = next(i for i, s in enumerate(subjects) if "task(T002):" in s)
    assert first_t001 < first_t002

    # Main has a merge commit rolling up the phase
    main_log = git_log("main", "%s", git_repo, n=5)
    assert "merge" in main_log.lower()
    assert "phase1" in main_log.lower()

    # File changes from the phase branch are now on main
    numstat = _run(["diff", "--numstat", "HEAD~1", "HEAD"], git_repo)
    assert len(numstat.strip()) > 0, "Merge commit should bring file changes to main"


# ---------------------------------------------------------------------------
# 4. Per-node test commands with real AI: verify trailers + phase gating
# ---------------------------------------------------------------------------

def _tree_with_test_commands() -> TaskTree:
    """Single phase, one task with a per-node unit test command."""
    tree = TaskTree(spec_id="hello", namespace="feature")
    tree.nodes["phase1"] = TaskNode(
        id="phase1", name="Setup", children=["T001"],
        test_commands=[TestCommand(
            type=TestType.INTEGRATION,
            command="echo 'integration suite ok'; exit 0",
        )],
    )
    tree.nodes["T001"] = TaskNode(
        id="T001", name="Create project structure", parent="phase1",
        description="Create a file called 'hello.txt' containing 'hello world'.",
        test_commands=[TestCommand(
            type=TestType.UNIT,
            command="echo '1 passed in 0.01s'; exit 0",
            framework="pytest",
        )],
    )
    return tree


@pytest.mark.integration
@pytest.mark.parametrize("runner_type,model,cli_binary", RUNNER_CONFIGS)
def test_ai_garden_with_test_commands_and_trailers(git_repo, runner_type, model, cli_binary):
    """Real AI implements a task; per-node test command runs; trailers include test metadata."""
    _skip_if_missing(cli_binary)

    tree = _tree_with_test_commands()
    _setup_repo_with_tree(git_repo, tree)

    runner = get_runner(runner_type, model)
    result = garden(tree, git_repo, runner, base_branch="main")

    assert result.success, f"garden() failed: {result.error}"
    assert result.task_id == "T001"

    # Phase branch exists
    assert git_branch_exists("feature/hello/phase1", git_repo)

    # Test trailers recorded
    log = git_log("feature/hello/phase1", "%B", git_repo, n=30, grep="tests pass")
    assert "Arborist-Test-Type: unit" in log
    assert "Arborist-Test-Passed: 1" in log
    assert "Arborist-Test-Runtime:" in log

    # Phase integration test passed → merged to main
    main_log = git_log("main", "%s", git_repo, n=5)
    assert "merge" in main_log.lower()


@pytest.mark.integration
@pytest.mark.parametrize("runner_type,model,cli_binary", RUNNER_CONFIGS)
def test_ai_garden_phase_gating_blocks_on_failure(git_repo, runner_type, model, cli_binary):
    """Real AI implements; phase integration test fails; merge blocked."""
    _skip_if_missing(cli_binary)

    tree = TaskTree(spec_id="hello", namespace="feature")
    tree.nodes["phase1"] = TaskNode(
        id="phase1", name="Setup", children=["T001"],
        test_commands=[TestCommand(
            type=TestType.INTEGRATION,
            command="echo 'INTEGRATION FAILED'; exit 1",
        )],
    )
    tree.nodes["T001"] = TaskNode(
        id="T001", name="Create project structure", parent="phase1",
        description="Create a file called 'hello.txt' containing 'hello world'.",
    )
    _setup_repo_with_tree(git_repo, tree)

    runner = get_runner(runner_type, model)
    result = garden(tree, git_repo, runner, base_branch="main")

    assert not result.success
    assert "Phase test failed" in result.error

    main_log = git_log("main", "%s", git_repo, n=5)
    assert "merge" not in main_log.lower()
