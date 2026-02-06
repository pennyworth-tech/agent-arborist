"""Tests for container context module."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_arborist.container_context import wrap_subprocess_command
from agent_arborist.container_runner import ContainerMode


class TestWrapSubprocessCommand:
    """Tests for wrap_subprocess_command."""

    def test_no_wrap_when_disabled(self, tmp_path):
        """Should return original command when container mode disabled."""
        cmd = ["claude", "-p", "test prompt"]
        result = wrap_subprocess_command(cmd, tmp_path, ContainerMode.DISABLED)
        assert result == cmd

    def test_no_wrap_when_no_devcontainer(self, tmp_path):
        """Should return original command when no devcontainer present."""
        cmd = ["claude", "-p", "test prompt"]
        result = wrap_subprocess_command(cmd, tmp_path, ContainerMode.AUTO)
        assert result == cmd

    def test_wrap_with_devcontainer(self, tmp_path):
        """Should wrap command with devcontainer exec when devcontainer present."""
        # Create .devcontainer
        devcontainer_dir = tmp_path / ".devcontainer"
        devcontainer_dir.mkdir()
        (devcontainer_dir / "devcontainer.json").write_text("{}")

        cmd = ["claude", "-p", "test prompt"]
        result = wrap_subprocess_command(cmd, tmp_path, ContainerMode.AUTO)

        assert result[0] == "devcontainer"
        assert result[1] == "exec"
        assert "--workspace-folder" in result
        assert "claude" in result
        assert "-p" in result
        assert "test prompt" in result

    def test_passes_arborist_env_vars_to_container(self, tmp_path):
        """Should pass ARBORIST_* env vars via --remote-env flags."""
        # Create .devcontainer
        devcontainer_dir = tmp_path / ".devcontainer"
        devcontainer_dir.mkdir()
        (devcontainer_dir / "devcontainer.json").write_text("{}")

        cmd = ["claude", "-p", "test"]

        # Set some ARBORIST_* env vars
        with patch.dict(os.environ, {
            "ARBORIST_SPEC_ID": "002-feature",
            "ARBORIST_SOURCE_REV": "main",
            "ARBORIST_TASK_PATH": "T1:T2",
            "OTHER_VAR": "should_not_be_passed",
        }, clear=False):
            result = wrap_subprocess_command(cmd, tmp_path, ContainerMode.AUTO)

        # Check --remote-env flags are present for ARBORIST_* vars
        result_str = " ".join(result)
        assert "--remote-env" in result_str
        assert "ARBORIST_SPEC_ID=002-feature" in result_str
        assert "ARBORIST_SOURCE_REV=main" in result_str
        assert "ARBORIST_TASK_PATH=T1:T2" in result_str

        # Should NOT include non-ARBORIST vars
        assert "OTHER_VAR" not in result_str

    def test_no_env_vars_when_none_set(self, tmp_path):
        """Should not add --remote-env when no ARBORIST_* vars set."""
        # Create .devcontainer
        devcontainer_dir = tmp_path / ".devcontainer"
        devcontainer_dir.mkdir()
        (devcontainer_dir / "devcontainer.json").write_text("{}")

        cmd = ["claude", "-p", "test"]

        # Clear all ARBORIST_* env vars
        clean_env = {k: v for k, v in os.environ.items() if not k.startswith("ARBORIST_")}
        with patch.dict(os.environ, clean_env, clear=True):
            result = wrap_subprocess_command(cmd, tmp_path, ContainerMode.AUTO)

        # Should still wrap, but no --remote-env flags
        assert result[0] == "devcontainer"
        # Count occurrences of --remote-env
        remote_env_count = result.count("--remote-env")
        assert remote_env_count == 0
