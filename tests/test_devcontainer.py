"""Tests for devcontainer detection, mode resolution, and CLI wrapper."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_arborist.devcontainer import (
    DevcontainerError,
    DevcontainerNotFoundError,
    devcontainer_exec,
    ensure_container_running,
    has_devcontainer,
    is_container_running,
    should_use_container,
)


# --- Detection ---


def test_detect_devcontainer_present(tmp_path):
    (tmp_path / ".devcontainer").mkdir()
    (tmp_path / ".devcontainer/devcontainer.json").write_text("{}")
    assert has_devcontainer(tmp_path) is True


def test_detect_devcontainer_absent(tmp_path):
    assert has_devcontainer(tmp_path) is False


def test_detect_devcontainer_dir_without_json(tmp_path):
    (tmp_path / ".devcontainer").mkdir()
    assert has_devcontainer(tmp_path) is False


# --- Mode resolution ---


def test_mode_auto_with_devcontainer(tmp_path):
    (tmp_path / ".devcontainer").mkdir()
    (tmp_path / ".devcontainer/devcontainer.json").write_text("{}")
    assert should_use_container("auto", tmp_path) is True


def test_mode_auto_without_devcontainer(tmp_path):
    assert should_use_container("auto", tmp_path) is False


def test_mode_enabled_with_devcontainer(tmp_path):
    (tmp_path / ".devcontainer").mkdir()
    (tmp_path / ".devcontainer/devcontainer.json").write_text("{}")
    assert should_use_container("enabled", tmp_path) is True


def test_mode_enabled_without_devcontainer_raises(tmp_path):
    with pytest.raises(DevcontainerNotFoundError):
        should_use_container("enabled", tmp_path)


def test_mode_disabled_ignores_devcontainer(tmp_path):
    (tmp_path / ".devcontainer").mkdir()
    (tmp_path / ".devcontainer/devcontainer.json").write_text("{}")
    assert should_use_container("disabled", tmp_path) is False


# --- CLI wrapper (mocked subprocess) ---


@pytest.fixture
def mock_subprocess():
    with patch("agent_arborist.devcontainer.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        yield mock_run


def test_devcontainer_exec_list_cmd(mock_subprocess):
    devcontainer_exec(["pytest", "tests/"], workspace_folder=Path("/repo"))
    args = mock_subprocess.call_args[0][0]
    assert args == ["devcontainer", "exec", "--workspace-folder", "/repo", "pytest", "tests/"]


def test_devcontainer_exec_string_cmd_wraps_in_shell(mock_subprocess):
    devcontainer_exec("pytest tests/ && echo done", workspace_folder=Path("/repo"))
    args = mock_subprocess.call_args[0][0]
    assert args == ["devcontainer", "exec", "--workspace-folder", "/repo",
                    "sh", "-c", "pytest tests/ && echo done"]


def test_devcontainer_exec_with_timeout(mock_subprocess):
    devcontainer_exec(["echo", "hi"], workspace_folder=Path("/repo"), timeout=30)
    assert mock_subprocess.call_args.kwargs["timeout"] == 30


def test_ensure_container_running_calls_up_when_not_running(mock_subprocess):
    mock_subprocess.side_effect = [
        subprocess.CompletedProcess(args=[], returncode=1),  # not running
        subprocess.CompletedProcess(args=[], returncode=0),  # up succeeds
        subprocess.CompletedProcess(args=[], returncode=0, stdout="git version 2.x"),  # health
    ]
    ensure_container_running(Path("/repo"))


def test_ensure_container_health_check_fails_without_git(mock_subprocess):
    mock_subprocess.side_effect = [
        subprocess.CompletedProcess(args=[], returncode=1),  # not running
        subprocess.CompletedProcess(args=[], returncode=0),  # up succeeds
        subprocess.CompletedProcess(args=[], returncode=1),  # git not found
    ]
    with pytest.raises(DevcontainerError, match="git is not available"):
        ensure_container_running(Path("/repo"))


def test_ensure_container_noop_when_already_running(mock_subprocess):
    mock_subprocess.return_value = subprocess.CompletedProcess(args=[], returncode=0)
    ensure_container_running(Path("/repo"))
    assert mock_subprocess.call_count == 1


def test_is_container_running_returns_true(mock_subprocess):
    mock_subprocess.return_value = subprocess.CompletedProcess(args=[], returncode=0)
    assert is_container_running(Path("/repo")) is True


def test_is_container_running_returns_false(mock_subprocess):
    mock_subprocess.return_value = subprocess.CompletedProcess(args=[], returncode=1)
    assert is_container_running(Path("/repo")) is False
