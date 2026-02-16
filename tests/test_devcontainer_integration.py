"""Integration tests for devcontainer support.

These tests build and run real devcontainers using the fixtures in
tests/fixtures/devcontainers/. They require Docker and the devcontainer CLI.

Run with: pytest -m container
"""

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
        """All-runners fixture has claude, opencode, gemini CLIs."""
        fixture = FIXTURES / "devcontainers" / "all-runners"
        shutil.copytree(fixture, tmp_path / "project", dirs_exist_ok=True)
        project = tmp_path / "project"
        subprocess.run(["git", "init", str(project)], check=True, capture_output=True)

        devcontainer_up(project)
        for runner_cmd in ["claude", "opencode", "gemini"]:
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
            ["sh", "-c", "echo 'hello' > /workspaces/project/test-from-container.txt"],
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
