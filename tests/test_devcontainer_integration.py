"""Integration tests for devcontainer support.

These tests build and run real devcontainers using the fixtures in
tests/fixtures/devcontainers/. They require Docker and the devcontainer CLI.

Run with: pytest -m container
E2E with AI: pytest -m container -k TestDevcontainerE2E
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from agent_arborist.devcontainer import (
    devcontainer_exec,
    devcontainer_up,
    ensure_container_running,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.container
class TestDevcontainerIntegration:
    """Tests that build and run real devcontainers.

    Requires: docker daemon running, devcontainer CLI installed.
    Uses fixtures from tests/fixtures/devcontainers/
    """

    def test_minimal_container_up_and_exec(self, tmp_path):
        """Build minimal-opencode fixture, exec a command inside."""
        fixture = FIXTURES / "devcontainers" / "minimal-opencode"
        shutil.copytree(fixture, tmp_path / "project", dirs_exist_ok=True)
        project = tmp_path / "project"
        subprocess.run(["git", "init", str(project)], check=True, capture_output=True)

        devcontainer_up(project)
        result = devcontainer_exec(["echo", "hello"], workspace_folder=project)
        assert result.returncode == 0
        assert "hello" in result.stdout

    def test_health_check_git_available(self, tmp_path):
        """Health check passes — git is available in minimal-opencode fixture."""
        fixture = FIXTURES / "devcontainers" / "minimal-opencode"
        shutil.copytree(fixture, tmp_path / "project", dirs_exist_ok=True)
        project = tmp_path / "project"
        subprocess.run(["git", "init", str(project)], check=True, capture_output=True)

        ensure_container_running(project)
        result = devcontainer_exec(["git", "--version"], workspace_folder=project)
        assert result.returncode == 0

    def test_all_runners_fixture_has_runners(self, tmp_path):
        """All-runners fixture has claude CLI and core tools."""
        fixture = FIXTURES / "devcontainers" / "all-runners"
        shutil.copytree(fixture, tmp_path / "project", dirs_exist_ok=True)
        project = tmp_path / "project"
        subprocess.run(["git", "init", str(project)], check=True, capture_output=True)

        devcontainer_up(project)
        for runner_cmd in ["claude", "git", "node"]:
            result = devcontainer_exec(["which", runner_cmd], workspace_folder=project)
            assert result.returncode == 0, f"{runner_cmd} not found in container"

    def test_volume_mount_file_visibility(self, tmp_path):
        """Files created inside container are visible on host via volume mount."""
        fixture = FIXTURES / "devcontainers" / "minimal-opencode"
        shutil.copytree(fixture, tmp_path / "project", dirs_exist_ok=True)
        project = tmp_path / "project"
        subprocess.run(["git", "init", str(project)], check=True, capture_output=True)

        devcontainer_up(project)
        devcontainer_exec(
            ["sh", "-c", "echo 'hello' > test-from-container.txt"],
            workspace_folder=project,
        )
        assert (project / "test-from-container.txt").read_text().strip() == "hello"

    def test_git_commit_inside_container_visible_on_host(self, tmp_path):
        """AI agent commits inside container -> visible to host git."""
        fixture = FIXTURES / "devcontainers" / "minimal-opencode"
        shutil.copytree(fixture, tmp_path / "project", dirs_exist_ok=True)
        project = tmp_path / "project"
        subprocess.run(["git", "init", str(project)], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                        cwd=project, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"],
                        cwd=project, check=True, capture_output=True)
        (project / "README.md").write_text("init")
        subprocess.run(["git", "add", "."], cwd=project, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=project, check=True, capture_output=True)

        devcontainer_up(project)
        devcontainer_exec(
            ["git", "config", "user.email", "test@test.com"],
            workspace_folder=project,
        )
        devcontainer_exec(
            ["git", "config", "user.name", "Test"],
            workspace_folder=project,
        )
        devcontainer_exec(
            "echo 'new file' > newfile.txt && git add . && git commit -m 'from container'",
            workspace_folder=project,
        )
        result = subprocess.run(["git", "log", "--oneline", "-1"],
                                cwd=project, capture_output=True, text=True)
        assert "from container" in result.stdout

    def test_test_command_runs_inside_container(self, tmp_path):
        """Shell test commands execute inside the container."""
        fixture = FIXTURES / "devcontainers" / "minimal-opencode"
        shutil.copytree(fixture, tmp_path / "project", dirs_exist_ok=True)
        project = tmp_path / "project"
        subprocess.run(["git", "init", str(project)], check=True, capture_output=True)

        devcontainer_up(project)
        result = devcontainer_exec("node --version", workspace_folder=project)
        assert result.returncode == 0
        assert result.stdout.strip().startswith("v")


# ---------------------------------------------------------------------------
# E2E: Full garden() with real AI running inside a devcontainer
# ---------------------------------------------------------------------------

def _init_git_repo(path: Path) -> None:
    """Initialize a git repo with an initial commit on main."""
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"],
                    cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"],
                    cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("# Test Repo\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial commit"],
                    cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "branch", "-M", "main"],
                    cwd=path, check=True, capture_output=True)


def _setup_repo_with_tree(repo: Path, tree) -> None:
    """Write task-tree.json and commit it."""
    from agent_arborist.git.repo import git_add_all, git_commit
    tree.compute_execution_order()
    tree_path = repo / "task-tree.json"
    tree_path.write_text(json.dumps(tree.to_dict(), indent=2) + "\n")
    git_add_all(repo)
    git_commit(f"arborist: build task tree for {tree.spec_id}", repo)


def _hello_world_tree():
    """Single phase, single task: create hello.txt."""
    from agent_arborist.tree.model import TaskNode, TaskTree
    tree = TaskTree(spec_id="hello")
    tree.nodes["phase1"] = TaskNode(id="phase1", name="Setup", children=["T001"])
    tree.nodes["T001"] = TaskNode(
        id="T001", name="Create hello world file", parent="phase1",
        description="Create a file called 'hello.txt' containing 'hello world'.",
    )
    return tree


# Runner configs for all-runners fixture
CONTAINER_RUNNER_CONFIGS = [
    pytest.param("claude", "haiku", id="claude-haiku"),
]


@pytest.mark.container
class TestDevcontainerE2E:
    """End-to-end tests: real AI running inside a devcontainer via garden().

    Uses devcontainer fixtures matching each runner (all-runners for claude,
    minimal-opencode for opencode).
    Validates the same commit structure as test_e2e_ai.py but with
    container_workspace set so AI + tests execute inside the container.

    Requires: docker daemon, devcontainer CLI, API keys via remoteEnv.
    """

    @pytest.mark.parametrize("runner_type,model", CONTAINER_RUNNER_CONFIGS)
    def test_garden_hello_world_in_container(self, tmp_path, runner_type, model):
        """AI implements hello.txt inside container; host sees commits + trailers."""
        from agent_arborist.git.repo import git_branch_exists, git_current_branch, git_log
        from agent_arborist.git.state import get_task_trailers
        from agent_arborist.runner import get_runner
        from agent_arborist.worker.garden import garden

        # Set up repo with devcontainer fixture
        fixture = FIXTURES / "devcontainers" / "all-runners"
        project = tmp_path / "project"
        shutil.copytree(fixture, project, dirs_exist_ok=True)
        _init_git_repo(project)
        tree = _hello_world_tree()
        _setup_repo_with_tree(project, tree)

        # Run garden with container_workspace — AI runs inside container
        runner = get_runner(runner_type, model)
        result = garden(
            tree, project, runner,
                        container_workspace=project,
            branch="main",
        )

        assert result.success, f"garden() failed: {result.error}"
        assert result.task_id == "T001"

        # Host stays on main
        assert git_current_branch(project) == "main"

        # Commits follow task(main@T001@...) convention
        log = git_log("main", "%s", project, n=20)
        subjects = [s.strip() for s in log.strip().split("\n") if s.strip()]
        task_commits = [s for s in subjects if s.startswith("task(main@T001@")]
        assert len(task_commits) >= 3, f"Expected implement/test/review/complete commits, got: {task_commits}"

        # Complete trailer present
        trailers = get_task_trailers("HEAD", "T001", project, current_branch="main")
        assert trailers["Arborist-Step"] == "complete"
        assert trailers["Arborist-Result"] == "pass"

    @pytest.mark.parametrize("runner_type,model", CONTAINER_RUNNER_CONFIGS)
    def test_garden_with_test_command_in_container(self, tmp_path, runner_type, model):
        """AI implements + test command runs inside container; test trailers recorded."""
        from agent_arborist.git.repo import git_log
        from agent_arborist.git.state import get_task_trailers
        from agent_arborist.runner import get_runner
        from agent_arborist.tree.model import TaskNode, TaskTree, TestCommand, TestType
        from agent_arborist.worker.garden import garden

        # Tree with a test command that will execute inside the container
        tree = TaskTree(spec_id="hello")
        tree.nodes["phase1"] = TaskNode(id="phase1", name="Setup", children=["T001"])
        tree.nodes["T001"] = TaskNode(
            id="T001", name="Create hello world file", parent="phase1",
            description="Create a file called 'hello.txt' containing 'hello world'.",
            test_commands=[TestCommand(
                type=TestType.UNIT,
                command="test -f hello.txt && echo '1 passed in 0.01s' || echo '1 failed'",
                framework="pytest",
            )],
        )

        fixture = FIXTURES / "devcontainers" / "all-runners"
        project = tmp_path / "project"
        shutil.copytree(fixture, project, dirs_exist_ok=True)
        _init_git_repo(project)
        _setup_repo_with_tree(project, tree)

        runner = get_runner(runner_type, model)
        result = garden(
            tree, project, runner,
                        container_workspace=project,
            branch="main",
        )

        assert result.success, f"garden() failed: {result.error}"

        # Test trailers recorded
        log = git_log("feature/hello/phase1", "%B", project, n=30, grep="tests pass")
        assert "Arborist-Test-Type: unit" in log
        assert "Arborist-Test-Passed: 1" in log
