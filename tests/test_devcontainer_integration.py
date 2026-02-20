# Copyright 2026 Pennyworth Technologies, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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


@pytest.mark.container
class TestDevcontainerTimeouts:
    """Tests that timeout parameters are wired correctly through the container stack.

    Covers: config file loading, env var overrides, merge precedence,
    threading through CLI→gardener→garden→runner→devcontainer, and actual
    subprocess timeout behavior.
    """

    # --- Real subprocess timeout behavior ---

    def test_devcontainer_up_respects_timeout(self, tmp_path):
        """devcontainer_up with a very short timeout raises DevcontainerError."""
        from agent_arborist.devcontainer import DevcontainerError

        fixture = FIXTURES / "devcontainers" / "minimal-opencode"
        project = tmp_path / "project"
        shutil.copytree(fixture, project, dirs_exist_ok=True)
        subprocess.run(["git", "init", str(project)], check=True, capture_output=True)

        with pytest.raises(DevcontainerError, match="timed out"):
            devcontainer_up(project, timeout=0.001)

    def test_is_container_running_timeout_returns_false(self, tmp_path):
        """is_container_running returns False when check times out."""
        from agent_arborist.devcontainer import is_container_running

        bogus = tmp_path / "nonexistent"
        bogus.mkdir()
        result = is_container_running(bogus, timeout=0.001)
        assert result is False

    # --- Config file loading ---

    def test_config_file_container_up_loaded(self, tmp_path):
        """container_up timeout loads from .arborist/config.json."""
        from agent_arborist.config import load_config_file
        arborist_dir = tmp_path / ".arborist"
        arborist_dir.mkdir()
        (arborist_dir / "config.json").write_text(json.dumps({
            "timeouts": {"container_up": 600}
        }))
        cfg = load_config_file(arborist_dir / "config.json")
        assert cfg.timeouts.container_up == 600

    def test_config_file_container_check_loaded(self, tmp_path):
        """container_check timeout loads from .arborist/config.json."""
        from agent_arborist.config import load_config_file
        arborist_dir = tmp_path / ".arborist"
        arborist_dir.mkdir()
        (arborist_dir / "config.json").write_text(json.dumps({
            "timeouts": {"container_check": 10}
        }))
        cfg = load_config_file(arborist_dir / "config.json")
        assert cfg.timeouts.container_check == 10

    def test_config_file_both_container_timeouts_loaded(self, tmp_path):
        """Both container timeouts load together."""
        from agent_arborist.config import load_config_file
        arborist_dir = tmp_path / ".arborist"
        arborist_dir.mkdir()
        (arborist_dir / "config.json").write_text(json.dumps({
            "timeouts": {"container_up": 120, "container_check": 5}
        }))
        cfg = load_config_file(arborist_dir / "config.json")
        assert cfg.timeouts.container_up == 120
        assert cfg.timeouts.container_check == 5

    def test_config_file_missing_container_timeouts_uses_defaults(self, tmp_path):
        """Missing container timeout fields fall back to defaults."""
        from agent_arborist.config import load_config_file
        arborist_dir = tmp_path / ".arborist"
        arborist_dir.mkdir()
        (arborist_dir / "config.json").write_text(json.dumps({
            "timeouts": {"task_run": 900}
        }))
        cfg = load_config_file(arborist_dir / "config.json")
        assert cfg.timeouts.container_up == 300
        assert cfg.timeouts.container_check == 30

    def test_config_file_empty_timeouts_uses_defaults(self, tmp_path):
        """Empty timeouts section falls back to defaults."""
        from agent_arborist.config import load_config_file
        arborist_dir = tmp_path / ".arborist"
        arborist_dir.mkdir()
        (arborist_dir / "config.json").write_text(json.dumps({"timeouts": {}}))
        cfg = load_config_file(arborist_dir / "config.json")
        assert cfg.timeouts.container_up == 300
        assert cfg.timeouts.container_check == 30

    # --- Defaults ---

    def test_config_dataclass_defaults(self):
        """TimeoutConfig defaults match expected values."""
        from agent_arborist.config import TimeoutConfig
        tc = TimeoutConfig()
        assert tc.container_up == 300
        assert tc.container_check == 30

    # --- Env var overrides ---

    def test_env_var_overrides_container_up(self, tmp_path, monkeypatch):
        """ARBORIST_TIMEOUT_CONTAINER_UP env var overrides config."""
        from agent_arborist.config import load_config_file, apply_env_overrides
        arborist_dir = tmp_path / ".arborist"
        arborist_dir.mkdir()
        (arborist_dir / "config.json").write_text(json.dumps({
            "timeouts": {"container_up": 120}
        }))
        cfg = load_config_file(arborist_dir / "config.json")
        monkeypatch.setenv("ARBORIST_TIMEOUT_CONTAINER_UP", "999")
        cfg = apply_env_overrides(cfg)
        assert cfg.timeouts.container_up == 999

    def test_env_var_overrides_container_check(self, tmp_path, monkeypatch):
        """ARBORIST_TIMEOUT_CONTAINER_CHECK env var overrides config."""
        from agent_arborist.config import load_config_file, apply_env_overrides
        arborist_dir = tmp_path / ".arborist"
        arborist_dir.mkdir()
        (arborist_dir / "config.json").write_text(json.dumps({
            "timeouts": {"container_check": 60}
        }))
        cfg = load_config_file(arborist_dir / "config.json")
        monkeypatch.setenv("ARBORIST_TIMEOUT_CONTAINER_CHECK", "7")
        cfg = apply_env_overrides(cfg)
        assert cfg.timeouts.container_check == 7

    def test_env_var_invalid_container_up_raises(self, monkeypatch):
        """Non-integer ARBORIST_TIMEOUT_CONTAINER_UP raises ConfigValidationError."""
        from agent_arborist.config import ArboristConfig, apply_env_overrides, ConfigValidationError
        monkeypatch.setenv("ARBORIST_TIMEOUT_CONTAINER_UP", "not_a_number")
        with pytest.raises(ConfigValidationError, match="must be an integer"):
            apply_env_overrides(ArboristConfig())

    def test_env_var_invalid_container_check_raises(self, monkeypatch):
        """Non-integer ARBORIST_TIMEOUT_CONTAINER_CHECK raises ConfigValidationError."""
        from agent_arborist.config import ArboristConfig, apply_env_overrides, ConfigValidationError
        monkeypatch.setenv("ARBORIST_TIMEOUT_CONTAINER_CHECK", "abc")
        with pytest.raises(ConfigValidationError, match="must be an integer"):
            apply_env_overrides(ArboristConfig())

    # --- Merge precedence ---

    def test_project_config_overrides_global(self, tmp_path):
        """Project config container timeouts override global config."""
        from agent_arborist.config import load_config_file, merge_configs
        global_dir = tmp_path / "global"
        global_dir.mkdir()
        (global_dir / "config.json").write_text(json.dumps({
            "timeouts": {"container_up": 100, "container_check": 10}
        }))
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "config.json").write_text(json.dumps({
            "timeouts": {"container_up": 500}
        }))
        global_cfg = load_config_file(global_dir / "config.json")
        project_cfg = load_config_file(project_dir / "config.json")
        merged = merge_configs(global_cfg, project_cfg)
        assert merged.timeouts.container_up == 500
        assert merged.timeouts.container_check == 10  # kept from global

    def test_env_var_overrides_merged_config(self, tmp_path, monkeypatch):
        """Env vars override both global and project config."""
        from agent_arborist.config import load_config_file, merge_configs, apply_env_overrides
        cfg_dir = tmp_path / "cfg"
        cfg_dir.mkdir()
        (cfg_dir / "config.json").write_text(json.dumps({
            "timeouts": {"container_up": 500, "container_check": 15}
        }))
        cfg = load_config_file(cfg_dir / "config.json")
        monkeypatch.setenv("ARBORIST_TIMEOUT_CONTAINER_UP", "50")
        monkeypatch.setenv("ARBORIST_TIMEOUT_CONTAINER_CHECK", "3")
        cfg = apply_env_overrides(cfg)
        assert cfg.timeouts.container_up == 50
        assert cfg.timeouts.container_check == 3

    # --- Validation ---

    def test_validation_rejects_zero_container_up(self):
        """container_up=0 fails validation."""
        from agent_arborist.config import TimeoutConfig, ConfigValidationError
        tc = TimeoutConfig(container_up=0)
        with pytest.raises(ConfigValidationError, match="container_up"):
            tc.validate()

    def test_validation_rejects_negative_container_check(self):
        """container_check=-1 fails validation."""
        from agent_arborist.config import TimeoutConfig, ConfigValidationError
        tc = TimeoutConfig(container_check=-1)
        with pytest.raises(ConfigValidationError, match="container_check"):
            tc.validate()

    def test_validation_accepts_positive_values(self):
        """Positive container timeouts pass validation."""
        from agent_arborist.config import TimeoutConfig
        tc = TimeoutConfig(container_up=1, container_check=1)
        tc.validate()  # should not raise

    # --- Serialization roundtrip ---

    def test_container_timeouts_roundtrip(self):
        """Container timeouts survive to_dict → from_dict roundtrip."""
        from agent_arborist.config import TimeoutConfig
        original = TimeoutConfig(container_up=450, container_check=20)
        d = original.to_dict()
        restored = TimeoutConfig.from_dict(d)
        assert restored.container_up == 450
        assert restored.container_check == 20

    def test_container_timeouts_in_template(self):
        """Config template includes container timeout fields."""
        from agent_arborist.config import generate_config_template
        template = generate_config_template()
        assert template["timeouts"]["container_up"] == 300
        assert template["timeouts"]["container_check"] == 30

    # --- Threading: config values reach devcontainer functions ---

    def test_ensure_container_running_receives_config_timeouts(self, tmp_path):
        """ensure_container_running receives timeout_up and timeout_check from caller."""
        from unittest.mock import patch
        from agent_arborist.devcontainer import ensure_container_running

        fixture = FIXTURES / "devcontainers" / "minimal-opencode"
        project = tmp_path / "project"
        shutil.copytree(fixture, project, dirs_exist_ok=True)
        subprocess.run(["git", "init", str(project)], check=True, capture_output=True)

        with patch("agent_arborist.devcontainer.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
            ensure_container_running(project, timeout_up=999, timeout_check=42)
            # is_container_running was called with timeout=42
            assert mock_run.call_count == 1
            assert mock_run.call_args.kwargs["timeout"] == 42

    def test_ensure_container_running_up_timeout_threaded(self, tmp_path):
        """When container is not running, devcontainer_up gets timeout_up."""
        from unittest.mock import patch
        from agent_arborist.devcontainer import ensure_container_running

        fixture = FIXTURES / "devcontainers" / "minimal-opencode"
        project = tmp_path / "project"
        shutil.copytree(fixture, project, dirs_exist_ok=True)
        subprocess.run(["git", "init", str(project)], check=True, capture_output=True)

        with patch("agent_arborist.devcontainer.subprocess.run") as mock_run:
            mock_run.side_effect = [
                subprocess.CompletedProcess(args=[], returncode=1),   # not running
                subprocess.CompletedProcess(args=[], returncode=0),   # up succeeds
                subprocess.CompletedProcess(args=[], returncode=0, stdout="git version 2.x"),  # health
            ]
            ensure_container_running(project, timeout_up=777, timeout_check=11)

            # Call 0: is_container_running with timeout_check
            assert mock_run.call_args_list[0].kwargs["timeout"] == 11
            # Call 1: devcontainer_up with timeout_up
            assert mock_run.call_args_list[1].kwargs["timeout"] == 777
            # Call 2: health check with hardcoded 15s
            assert mock_run.call_args_list[2].kwargs["timeout"] == 15

    def test_execute_command_threads_container_timeouts(self):
        """_execute_command passes container timeouts to ensure_container_running."""
        from unittest.mock import patch, call
        from agent_arborist.runner import _execute_command

        with patch("agent_arborist.devcontainer.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="ok", stderr=""
            )
            _execute_command(
                ["echo", "hi"], timeout=30,
                container_workspace=Path("/fake"),
                container_up_timeout=888,
                container_check_timeout=22,
            )
            # First call is is_container_running with timeout=22
            assert mock_run.call_args_list[0].kwargs["timeout"] == 22

    def test_execute_command_none_timeouts_use_defaults(self):
        """_execute_command with None container timeouts uses ensure_container_running defaults."""
        from unittest.mock import patch
        from agent_arborist.runner import _execute_command

        with patch("agent_arborist.devcontainer.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="ok", stderr=""
            )
            _execute_command(
                ["echo", "hi"], timeout=30,
                container_workspace=Path("/fake"),
                container_up_timeout=None,
                container_check_timeout=None,
            )
            # Default timeout_check=30 from ensure_container_running signature
            assert mock_run.call_args_list[0].kwargs["timeout"] == 30

    def test_runner_run_threads_container_timeouts(self):
        """ClaudeRunner.run passes container timeouts through to _execute_command."""
        from unittest.mock import patch
        from agent_arborist.runner import ClaudeRunner

        runner = ClaudeRunner(model="haiku")
        with patch("agent_arborist.devcontainer.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="done", stderr=""
            )
            runner.run(
                "test prompt", timeout=60,
                container_workspace=Path("/fake"),
                container_up_timeout=200,
                container_check_timeout=15,
            )
            assert mock_run.call_args_list[0].kwargs["timeout"] == 15

    # --- Full config file → devcontainer threading ---

    def test_full_config_to_devcontainer_threading(self, tmp_path):
        """Config.json values flow all the way to ensure_container_running calls."""
        from unittest.mock import patch
        from agent_arborist.config import load_config_file
        from agent_arborist.runner import _execute_command

        # Write a config file with custom container timeouts
        arborist_dir = tmp_path / ".arborist"
        arborist_dir.mkdir()
        (arborist_dir / "config.json").write_text(json.dumps({
            "timeouts": {"container_up": 180, "container_check": 8}
        }))
        cfg = load_config_file(arborist_dir / "config.json")

        with patch("agent_arborist.devcontainer.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="ok", stderr=""
            )
            # Simulate what CLI does: pass cfg.timeouts values to _execute_command
            _execute_command(
                ["echo", "hi"], timeout=30,
                container_workspace=Path("/fake"),
                container_up_timeout=cfg.timeouts.container_up,
                container_check_timeout=cfg.timeouts.container_check,
            )
            # is_container_running should get timeout=8 from config
            assert mock_run.call_args_list[0].kwargs["timeout"] == 8

    def test_full_config_to_devcontainer_up_threading(self, tmp_path):
        """Config.json container_up value flows to devcontainer_up when container not running."""
        from unittest.mock import patch
        from agent_arborist.config import load_config_file
        from agent_arborist.runner import _execute_command

        arborist_dir = tmp_path / ".arborist"
        arborist_dir.mkdir()
        (arborist_dir / "config.json").write_text(json.dumps({
            "timeouts": {"container_up": 180, "container_check": 8}
        }))
        cfg = load_config_file(arborist_dir / "config.json")

        with patch("agent_arborist.devcontainer.subprocess.run") as mock_run:
            mock_run.side_effect = [
                subprocess.CompletedProcess(args=[], returncode=1),   # not running
                subprocess.CompletedProcess(args=[], returncode=0),   # up
                subprocess.CompletedProcess(args=[], returncode=0, stdout="git 2.x"),  # health
                subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr=""),  # exec
            ]
            _execute_command(
                ["echo", "hi"], timeout=30,
                container_workspace=Path("/fake"),
                container_up_timeout=cfg.timeouts.container_up,
                container_check_timeout=cfg.timeouts.container_check,
            )
            # Call 0: is_container_running → timeout=8
            assert mock_run.call_args_list[0].kwargs["timeout"] == 8
            # Call 1: devcontainer_up → timeout=180
            assert mock_run.call_args_list[1].kwargs["timeout"] == 180
            # Call 2: health check → timeout=15 (hardcoded)
            assert mock_run.call_args_list[2].kwargs["timeout"] == 15


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
    git_commit("arborist: build task tree", repo)


def _hello_world_tree():
    """Single phase, single task: create hello.txt."""
    from agent_arborist.tree.model import TaskNode, TaskTree
    tree = TaskTree()
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
        tree = TaskTree()
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
