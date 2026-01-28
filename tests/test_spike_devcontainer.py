"""Spike test to validate devcontainer assumptions before refactoring.

This test validates:
1. Environment variables from .env are available at devcontainer exec time
2. Claude Code CLI works without bash -lc wrapper
3. Commands execute in correct working directory
4. backlit-devpod devcontainer provides required tools

Run with:
    pytest tests/test_spike_devcontainer.py -v -s
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

# Skip markers for test requirements
requires_docker = pytest.mark.skipif(
    shutil.which("docker") is None
    or subprocess.run(["docker", "info"], capture_output=True).returncode != 0,
    reason="Docker not available or not running",
)

requires_devcontainer_cli = pytest.mark.skipif(
    shutil.which("devcontainer") is None,
    reason="devcontainer CLI not installed (install: npm install -g @devcontainers/cli)",
)

requires_claude_code_oauth_token = pytest.mark.skipif(
    os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") is None,
    reason="CLAUDE_CODE_OAUTH_TOKEN not set in environment",
)


@pytest.fixture
def spike_project(tmp_path, backlit_devcontainer):
    """Create minimal test project with backlit devcontainer and .env file."""
    project_dir = tmp_path / "spike-test"
    project_dir.mkdir()

    # Copy backlit devcontainer
    shutil.copytree(backlit_devcontainer, project_dir / ".devcontainer")

    # Create .env file with OAuth token from host environment
    env_file = project_dir / ".env"
    oauth_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
    if not oauth_token:
        pytest.skip("CLAUDE_CODE_OAUTH_TOKEN not set in environment")

    env_file.write_text(
        f"# Test environment\n"
        f"CLAUDE_CODE_OAUTH_TOKEN={oauth_token}\n"
        f"TEST_VAR=hello_from_env\n"
    )

    # Modify devcontainer.json to use .env file
    dc_json = project_dir / ".devcontainer" / "devcontainer.json"
    with open(dc_json, "r") as f:
        config = json.load(f)

    # Add runArgs to pass .env file to Docker
    config["runArgs"] = config.get("runArgs", []) + [
        "--env-file",
        "${localWorkspaceFolder}/.env",
    ]

    with open(dc_json, "w") as f:
        json.dump(config, f, indent=2)

    # Initialize git repo (required for some operations)
    subprocess.run(["git", "init"], cwd=project_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=project_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=project_dir,
        check=True,
        capture_output=True,
    )

    # Create initial commit
    (project_dir / "README.md").write_text("# Spike Test Project\n")
    subprocess.run(
        ["git", "add", "."], cwd=project_dir, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=project_dir,
        check=True,
        capture_output=True,
    )

    yield project_dir

    # Cleanup: stop container
    try:
        # Find container by label
        find_result = subprocess.run(
            [
                "docker",
                "ps",
                "-q",
                "--filter",
                f"label=devcontainer.local_folder={project_dir.resolve()}",
            ],
            capture_output=True,
            text=True,
        )
        if container_id := find_result.stdout.strip():
            subprocess.run(["docker", "stop", container_id], capture_output=True)
            print(f"\n✓ Cleaned up container: {container_id}")
    except Exception as e:
        print(f"\n⚠ Container cleanup warning: {e}")


@pytest.mark.spike
@requires_docker
@requires_devcontainer_cli
class TestDevContainerSpike:
    """Spike tests to validate devcontainer approach before refactoring."""

    def test_1_env_vars_available_at_exec_time(self, spike_project):
        """Verify .env variables are available during devcontainer exec.

        This validates that:
        - runArgs with --env-file works
        - Variables set at container-up are inherited by exec commands
        - No bash -lc wrapper needed for environment access
        """
        print(f"\n→ Testing with project: {spike_project}")

        # Start container (reads .env file)
        print("→ Starting devcontainer...")
        up_result = subprocess.run(
            ["devcontainer", "up", "--workspace-folder", str(spike_project)],
            capture_output=True,
            text=True,
            timeout=300,
        )

        print(f"  Container up exit code: {up_result.returncode}")
        if up_result.returncode != 0:
            print(f"  STDOUT: {up_result.stdout}")
            print(f"  STDERR: {up_result.stderr}")

        assert up_result.returncode == 0, f"Container startup failed: {up_result.stderr}"

        # Test: Read TEST_VAR without bash -lc wrapper
        print("→ Testing environment variable access...")
        exec_result = subprocess.run(
            [
                "devcontainer",
                "exec",
                "--workspace-folder",
                str(spike_project),
                "bash",
                "-c",
                "echo $TEST_VAR",
            ],
            capture_output=True,
            text=True,
        )

        print(f"  TEST_VAR value: {exec_result.stdout.strip()}")
        assert (
            exec_result.stdout.strip() == "hello_from_env"
        ), "Environment variable not available at exec time"

    @requires_claude_code_oauth_token
    def test_2_claude_code_works_without_wrapper(self, spike_project):
        """Verify Claude Code CLI works without bash -lc wrapper.

        This validates that:
        - Claude Code is available in PATH
        - CLAUDE_CODE_OAUTH_TOKEN is accessible
        - Commands work in correct working directory
        - No login shell (-lc) needed
        """
        # Container should already be running from test_1
        # If not, start it
        up_check = subprocess.run(
            [
                "docker",
                "ps",
                "-q",
                "--filter",
                f"label=devcontainer.local_folder={spike_project.resolve()}",
            ],
            capture_output=True,
            text=True,
        )

        if not up_check.stdout.strip():
            print("→ Container not running, starting...")
            subprocess.run(
                ["devcontainer", "up", "--workspace-folder", str(spike_project)],
                check=True,
                capture_output=True,
                timeout=300,
            )

        # Test: Verify claude is in PATH (without -lc)
        print("→ Checking if claude command is available...")
        which_result = subprocess.run(
            [
                "devcontainer",
                "exec",
                "--workspace-folder",
                str(spike_project),
                "which",
                "claude",
            ],
            capture_output=True,
            text=True,
        )

        print(f"  which claude: {which_result.stdout.strip()}")
        assert which_result.returncode == 0, "claude not found in PATH"

        # Test: Verify CLAUDE_CODE_OAUTH_TOKEN is available
        print("→ Checking if CLAUDE_CODE_OAUTH_TOKEN is available...")
        token_check = subprocess.run(
            [
                "devcontainer",
                "exec",
                "--workspace-folder",
                str(spike_project),
                "bash",
                "-c",
                "[ -n \"$CLAUDE_CODE_OAUTH_TOKEN\" ] && echo 'TOKEN_SET' || echo 'TOKEN_NOT_SET'",
            ],
            capture_output=True,
            text=True,
        )

        print(f"  OAuth token status: {token_check.stdout.strip()}")
        assert token_check.stdout.strip() == "TOKEN_SET", "CLAUDE_CODE_OAUTH_TOKEN not set"

        # Test: Run simple claude command (--version doesn't need API key)
        print("→ Running claude --version...")
        version_result = subprocess.run(
            [
                "devcontainer",
                "exec",
                "--workspace-folder",
                str(spike_project),
                "claude",
                "--version",
            ],
            capture_output=True,
            text=True,
        )

        print(f"  Claude version: {version_result.stdout.strip()}")
        assert version_result.returncode == 0, "claude --version failed"

    def test_3_working_directory_correct(self, spike_project):
        """Verify commands execute in correct working directory.

        This validates that:
        - devcontainer exec defaults to correct workspace folder
        - No cd command needed in wrapper
        - Files created by commands appear in expected location
        """
        # Container should already be running
        up_check = subprocess.run(
            [
                "docker",
                "ps",
                "-q",
                "--filter",
                f"label=devcontainer.local_folder={spike_project.resolve()}",
            ],
            capture_output=True,
            text=True,
        )

        if not up_check.stdout.strip():
            print("→ Container not running, starting...")
            subprocess.run(
                ["devcontainer", "up", "--workspace-folder", str(spike_project)],
                check=True,
                capture_output=True,
                timeout=300,
            )

        # Test: Check current working directory
        print("→ Checking working directory...")
        pwd_result = subprocess.run(
            [
                "devcontainer",
                "exec",
                "--workspace-folder",
                str(spike_project),
                "pwd",
            ],
            capture_output=True,
            text=True,
        )

        working_dir = pwd_result.stdout.strip()
        print(f"  Working directory: {working_dir}")

        # Should be /workspaces/<folder-name> (devcontainer default)
        assert "workspaces" in working_dir, f"Unexpected working directory: {working_dir}"

        # Test: Create file and verify it appears in workspace
        print("→ Creating test file...")
        touch_result = subprocess.run(
            [
                "devcontainer",
                "exec",
                "--workspace-folder",
                str(spike_project),
                "touch",
                "test_file.txt",
            ],
            capture_output=True,
            text=True,
        )

        assert touch_result.returncode == 0, "Failed to create file"

        # Verify file exists
        ls_result = subprocess.run(
            [
                "devcontainer",
                "exec",
                "--workspace-folder",
                str(spike_project),
                "ls",
                "test_file.txt",
            ],
            capture_output=True,
            text=True,
        )

        assert ls_result.returncode == 0, "Created file not found"
        print("  ✓ File created successfully in workspace")
