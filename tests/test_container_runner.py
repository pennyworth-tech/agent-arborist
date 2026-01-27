"""Integration tests for DevContainer runner support.

Tests are organized into two categories:
1. Mechanics tests - container lifecycle without API calls (fast)
2. Integration tests - real API calls with OpenCode (slow, requires API key)

Run with:
    pytest -m integration tests/test_container_runner.py  # All tests
    pytest -m "integration and not opencode" tests/test_container_runner.py  # Mechanics only
    pytest -m opencode tests/test_container_runner.py  # With API calls
"""

import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Skip markers
requires_docker = pytest.mark.skipif(
    shutil.which("docker") is None
    or subprocess.run(["docker", "info"], capture_output=True).returncode != 0,
    reason="Docker not available or not running",
)

requires_devcontainer_cli = pytest.mark.skipif(
    shutil.which("devcontainer") is None,
    reason="devcontainer CLI not installed (install: npm install -g @devcontainers/cli)",
)

requires_opencode = pytest.mark.skipif(
    shutil.which("opencode") is None,
    reason="opencode CLI not installed (install: npm install -g opencode-ai)",
)

requires_openai_api_key = pytest.mark.skipif(
    os.environ.get("OPENAI_API_KEY") is None,
    reason="OPENAI_API_KEY not set in environment",
)


# ============================================================
# FIXTURES
# ============================================================


@pytest.fixture
def minimal_opencode_fixture():
    """Path to the minimal-opencode test fixture."""
    return Path(__file__).parent / "fixtures" / "devcontainers" / "minimal-opencode"


@pytest.fixture
def temp_devcontainer_project(tmp_path):
    """Create a temporary project with devcontainer setup."""
    # Create .devcontainer structure
    devcontainer_dir = tmp_path / ".devcontainer"
    devcontainer_dir.mkdir()

    # Minimal Dockerfile
    dockerfile = devcontainer_dir / "Dockerfile"
    dockerfile.write_text(
        """
FROM node:18-slim
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN npm install -g opencode-ai@latest
WORKDIR /workspaces/test-project
"""
    )

    # Minimal devcontainer.json
    devcontainer_json = devcontainer_dir / "devcontainer.json"
    devcontainer_json.write_text(
        """{
  "name": "test-container",
  "build": {"dockerfile": "Dockerfile"},
  "workspaceFolder": "/workspaces/test-project",
  "remoteEnv": {
    "ZAI_API_KEY": "${localEnv:ZAI_API_KEY}"
  },
  "postCreateCommand": "git config --global --add safe.directory /workspaces/test-project"
}"""
    )

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path,
        capture_output=True,
    )

    # Create initial commit
    readme = tmp_path / "README.md"
    readme.write_text("# Test Project\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@test.com",
        },
    )

    return tmp_path


# ============================================================
# MECHANICS TESTS (Fast - No API Calls)
# ============================================================


@pytest.mark.integration
class TestContainerDetection:
    """Tests for devcontainer detection logic."""

    def test_has_devcontainer_with_config(self, temp_devcontainer_project):
        """Should detect devcontainer when devcontainer.json exists."""
        from agent_arborist.container_runner import has_devcontainer

        assert has_devcontainer(temp_devcontainer_project) is True

    def test_has_devcontainer_without_config(self, tmp_path):
        """Should not detect devcontainer when .devcontainer/ missing."""
        from agent_arborist.container_runner import has_devcontainer

        assert has_devcontainer(tmp_path) is False

    def test_should_use_container_auto_mode(self, temp_devcontainer_project):
        """Auto mode should enable containers when devcontainer present."""
        from agent_arborist.container_runner import should_use_container, ContainerMode

        result = should_use_container(ContainerMode.AUTO, temp_devcontainer_project)
        assert result is True

    def test_should_use_container_disabled_mode(self, temp_devcontainer_project):
        """Disabled mode should never use containers."""
        from agent_arborist.container_runner import should_use_container, ContainerMode

        result = should_use_container(ContainerMode.DISABLED, temp_devcontainer_project)
        assert result is False

    def test_should_use_container_enabled_mode_fails_without_devcontainer(
        self, tmp_path
    ):
        """Enabled mode should fail when no devcontainer present."""
        from agent_arborist.container_runner import should_use_container, ContainerMode

        with pytest.raises(RuntimeError, match="no .devcontainer"):
            should_use_container(ContainerMode.ENABLED, tmp_path)


@pytest.mark.integration
@requires_docker
class TestDockerAvailability:
    """Tests for Docker availability checks."""

    def test_check_docker_running(self):
        """Should detect running Docker daemon."""
        from agent_arborist.container_runner import check_docker

        is_running, message = check_docker()
        assert is_running is True
        assert len(message) > 0  # Should return version


@pytest.mark.integration
@requires_devcontainer_cli
class TestDevContainerCLI:
    """Tests for devcontainer CLI availability."""

    def test_check_devcontainer_cli(self):
        """Should detect installed devcontainer CLI."""
        from agent_arborist.container_runner import check_devcontainer_cli

        is_installed, message = check_devcontainer_cli()
        assert is_installed is True
        assert "devcontainer" in message.lower() or len(message) > 0


# ============================================================
# CONTAINER LIFECYCLE TESTS (Medium - Container operations)
# ============================================================


@pytest.mark.integration
@requires_docker
@requires_devcontainer_cli
class TestContainerLifecycle:
    """Tests for container start/stop operations.

    These tests start real containers but don't make API calls.
    """

    def test_container_up_success(self, temp_devcontainer_project):
        """Should successfully start a devcontainer."""
        from agent_arborist.container_runner import DevContainerRunner

        runner = DevContainerRunner()
        result = runner.container_up(temp_devcontainer_project)

        try:
            assert result.success is True
            assert result.exit_code == 0
        finally:
            # Cleanup
            runner.container_down(temp_devcontainer_project)

    def test_container_down_success(self, temp_devcontainer_project):
        """Should successfully stop a devcontainer."""
        from agent_arborist.container_runner import DevContainerRunner

        runner = DevContainerRunner()

        # Start container first
        up_result = runner.container_up(temp_devcontainer_project)
        assert up_result.success is True

        # Stop container
        down_result = runner.container_down(temp_devcontainer_project)
        assert down_result.success is True

    def test_container_down_when_not_running(self, temp_devcontainer_project):
        """Should handle stopping non-existent container gracefully."""
        from agent_arborist.container_runner import DevContainerRunner

        runner = DevContainerRunner()
        result = runner.container_down(temp_devcontainer_project)

        # Should succeed (idempotent)
        assert result.success is True
        assert (
            "already stopped" in result.output.lower()
            or "no container" in result.output.lower()
        )

    def test_exec_simple_command(self, temp_devcontainer_project):
        """Should execute command inside running container."""
        from agent_arborist.container_runner import DevContainerRunner

        runner = DevContainerRunner()

        # Start container
        up_result = runner.container_up(temp_devcontainer_project)
        assert up_result.success is True

        try:
            # Execute command
            exec_result = runner.exec(
                temp_devcontainer_project, ["echo", "hello from container"]
            )

            assert exec_result.success is True
            assert "hello from container" in exec_result.output
        finally:
            # Cleanup
            runner.container_down(temp_devcontainer_project)

    def test_exec_with_environment_variables(self, temp_devcontainer_project):
        """Should pass environment variables to container exec."""
        from agent_arborist.container_runner import DevContainerRunner

        runner = DevContainerRunner()

        # Start container
        up_result = runner.container_up(temp_devcontainer_project)
        assert up_result.success is True

        try:
            # Execute with custom env
            exec_result = runner.exec(
                temp_devcontainer_project,
                ["sh", "-c", "echo $TEST_VAR"],
                env={"TEST_VAR": "test_value_123"},
            )

            assert exec_result.success is True
            assert "test_value_123" in exec_result.output
        finally:
            # Cleanup
            runner.container_down(temp_devcontainer_project)


# ============================================================
# OPENCODE INTEGRATION TESTS (Slow - Real API Calls)
# ============================================================


@pytest.mark.integration
@pytest.mark.opencode
@requires_docker
@requires_devcontainer_cli
@requires_opencode
@requires_openai_api_key
class TestOpencodeInContainer:
    """Integration tests using real OpenCode API calls.

    These tests require:
    - Docker running
    - devcontainer CLI installed
    - opencode CLI installed in container
    - OPENAI_API_KEY environment variable set

    Run with: pytest -m opencode tests/test_container_runner.py
    """

    def test_opencode_available_in_container(self, minimal_opencode_fixture):
        """Should have opencode CLI available inside container."""
        from agent_arborist.container_runner import DevContainerRunner

        runner = DevContainerRunner()

        # Start container
        up_result = runner.container_up(minimal_opencode_fixture)
        assert up_result.success is True, f"Container start failed: {up_result.error}"

        try:
            # Check opencode version
            exec_result = runner.exec(minimal_opencode_fixture, ["opencode", "--version"])

            assert (
                exec_result.success is True
            ), f"opencode --version failed: {exec_result.error}"
            assert len(exec_result.output) > 0
        finally:
            # Cleanup
            runner.container_down(minimal_opencode_fixture)

    def test_opencode_simple_prompt(self, minimal_opencode_fixture):
        """Should execute simple prompt using openai/gpt-4o-mini."""
        from agent_arborist.container_runner import DevContainerRunner

        runner = DevContainerRunner()

        # Start container
        up_result = runner.container_up(minimal_opencode_fixture)
        assert up_result.success is True, f"Container start failed: {up_result.error}"

        try:
            # Run simple prompt (should be fast)
            exec_result = runner.exec(
                minimal_opencode_fixture,
                [
                    "opencode",
                    "run",
                    "-m",
                    "openai/gpt-4o-mini",
                    "Reply with just the word 'hello'",
                ],
                timeout=60,
            )

            assert (
                exec_result.success is True
            ), f"OpenCode run failed: {exec_result.error}"
            assert (
                "hello" in exec_result.output.lower()
            ), f"Unexpected output: {exec_result.output}"
        finally:
            # Cleanup
            runner.container_down(minimal_opencode_fixture)

    def test_opencode_with_file_operations(self, minimal_opencode_fixture):
        """Should execute prompt that creates files inside container."""
        from agent_arborist.container_runner import DevContainerRunner

        runner = DevContainerRunner()

        # Start container
        up_result = runner.container_up(minimal_opencode_fixture)
        assert up_result.success is True

        try:
            # Create a test file
            exec_result = runner.exec(
                minimal_opencode_fixture,
                [
                    "opencode",
                    "run",
                    "-m",
                    "openai/gpt-4o-mini",
                    "Create a file named test.txt with content 'container test'",
                ],
                timeout=60,
            )

            assert (
                exec_result.success is True
            ), f"File creation failed: {exec_result.error}"

            # Verify file exists
            verify_result = runner.exec(minimal_opencode_fixture, ["cat", "test.txt"])

            assert verify_result.success is True
            assert "container test" in verify_result.output
        finally:
            # Cleanup
            runner.container_down(minimal_opencode_fixture)

    def test_container_cleanup_after_failure(self, minimal_opencode_fixture):
        """Should clean up container even if command fails."""
        from agent_arborist.container_runner import DevContainerRunner

        runner = DevContainerRunner()

        # Start container
        up_result = runner.container_up(minimal_opencode_fixture)
        assert up_result.success is True

        # Run command that will fail
        exec_result = runner.exec(minimal_opencode_fixture, ["sh", "-c", "exit 1"])

        assert exec_result.success is False

        # Container should still be stoppable
        down_result = runner.container_down(minimal_opencode_fixture)
        assert down_result.success is True


# ============================================================
# DAG BUILDER INTEGRATION
# ============================================================
# NOTE: These tests are for future DAG builder integration with container mode.
# They are commented out until DagConfig.container_mode is implemented.


# @pytest.mark.integration
# class TestDAGBuilderContainerMode:
#     """Tests for DAG builder with container mode."""
#
#     def test_dag_includes_container_steps_when_enabled(self):
#         """DAG should include container-up/down steps when devcontainer present."""
#         from agent_arborist.dag_builder import DagConfig, SubDagBuilder
#         from agent_arborist.container_runner import ContainerMode
#         from agent_arborist.task_spec import TaskSpec, Task, Phase
#         from agent_arborist.task_state import build_task_tree_from_spec
#
#         # Create minimal spec
#         task = Task(id="T001", description="Test task")
#         phase = Phase(name="Phase 1", tasks=[task])
#         spec = TaskSpec(
#             project="Test Project",
#             total_tasks=1,
#             phases=[phase],
#             dependencies={},
#         )
#
#         task_tree = build_task_tree_from_spec(spec)
#
#         # Build with AUTO mode (mocked to return True)
#         with patch("agent_arborist.container_runner.has_devcontainer", return_value=True):
#             config = DagConfig(name="test", spec_id="test", container_mode=ContainerMode.AUTO)
#             builder = SubDagBuilder(config)
#             bundle = builder.build(spec, task_tree)
#
#             # Find the T001 subdag
#             t001_subdag = next(s for s in bundle.subdags if s.name == "T001")
#             step_names = [step.name for step in t001_subdag.steps]
#
#             # Should have container lifecycle steps
#             assert "container-up" in step_names
#             assert "container-down" in step_names
#
#             # Verify step order
#             assert step_names[0] == "container-up"
#             assert step_names[-2] == "container-down"
#             assert step_names[-1] == "post-cleanup"
#
#     def test_dag_excludes_container_steps_when_disabled(self):
#         """DAG should NOT include container steps when disabled."""
#         from agent_arborist.dag_builder import DagConfig, SubDagBuilder
#         from agent_arborist.container_runner import ContainerMode
#         from agent_arborist.task_spec import TaskSpec, Task, Phase
#         from agent_arborist.task_state import build_task_tree_from_spec
#
#         # Create minimal spec
#         task = Task(id="T001", description="Test task")
#         phase = Phase(name="Phase 1", tasks=[task])
#         spec = TaskSpec(
#             project="Test Project",
#             total_tasks=1,
#             phases=[phase],
#             dependencies={},
#         )
#
#         task_tree = build_task_tree_from_spec(spec)
#
#         # Build with DISABLED mode
#         config = DagConfig(name="test", spec_id="test", container_mode=ContainerMode.DISABLED)
#         builder = SubDagBuilder(config)
#         bundle = builder.build(spec, task_tree)
#
#         # Find the T001 subdag
#         t001_subdag = next(s for s in bundle.subdags if s.name == "T001")
#         step_names = [step.name for step in t001_subdag.steps]
#
#         # Should NOT have container lifecycle steps
#         assert "container-up" not in step_names
#         assert "container-down" not in step_names
