"""Tests for structured logging across modules."""

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock

from click.testing import CliRunner

from agent_arborist.cli import main
from agent_arborist.tree.spec_parser import parse_spec
from agent_arborist.tree.model import TaskNode, TaskTree
from agent_arborist.worker.garden import garden, find_next_task
from agent_arborist.worker.gardener import gardener

FIXTURES = Path(__file__).parent / "fixtures"


def test_cli_log_level_option_configures_logging(tmp_path):
    """--log-level INFO should cause INFO messages to appear."""
    output = tmp_path / "tree.json"
    runner = CliRunner()
    result = runner.invoke(main, [
        "--log-level", "INFO",
        "build",
        "--no-ai",
        "--spec-dir", str(FIXTURES),
        "--output", str(output),
        "--spec-id", "test",
    ])
    assert result.exit_code == 0, result.output


def test_cli_log_level_default_is_warning(tmp_path):
    """Default log level should be WARNING — no INFO in output."""
    output = tmp_path / "tree.json"
    runner = CliRunner()
    result = runner.invoke(main, [
        "build",
        "--no-ai",
        "--spec-dir", str(FIXTURES),
        "--output", str(output),
        "--spec-id", "test",
    ])
    assert result.exit_code == 0
    # INFO-level messages should not appear with default WARNING level
    assert "Parsed spec:" not in result.output


def test_cli_log_level_case_insensitive(tmp_path):
    """--log-level should accept lowercase."""
    output = tmp_path / "tree.json"
    runner = CliRunner()
    result = runner.invoke(main, [
        "--log-level", "debug",
        "build",
        "--no-ai",
        "--spec-dir", str(FIXTURES),
        "--output", str(output),
        "--spec-id", "test",
    ])
    assert result.exit_code == 0


def test_spec_parser_logs_info(caplog):
    """parse_spec should emit INFO with node count."""
    with caplog.at_level(logging.INFO, logger="agent_arborist.tree.spec_parser"):
        parse_spec(FIXTURES / "tasks-hello-world.md", spec_id="test")
    assert any("Parsed spec:" in r.message for r in caplog.records)


def test_spec_parser_logs_debug_phases(caplog):
    """parse_spec should emit DEBUG for each phase."""
    with caplog.at_level(logging.DEBUG, logger="agent_arborist.tree.spec_parser"):
        parse_spec(FIXTURES / "tasks-hello-world.md", spec_id="test")
    assert any("Phase" in r.message for r in caplog.records)


def test_git_repo_logs_debug(caplog, git_repo):
    """git operations should emit DEBUG logs."""
    from agent_arborist.git.repo import git_current_branch
    with caplog.at_level(logging.DEBUG, logger="agent_arborist.git.repo"):
        git_current_branch(git_repo)
    assert any("git" in r.message for r in caplog.records)


def test_git_state_scan_logs_debug(caplog, git_repo):
    """scan_completed_tasks should emit DEBUG."""
    from agent_arborist.git.state import scan_completed_tasks
    tree = TaskTree(spec_id="test", namespace="feature")
    tree.nodes["T001"] = TaskNode(id="T001", name="Task 1")
    tree.compute_execution_order()
    with caplog.at_level(logging.DEBUG, logger="agent_arborist.git.state"):
        scan_completed_tasks(tree, git_repo)
    assert any("Scan found" in r.message for r in caplog.records)


def test_runner_logs_info(caplog):
    """_execute_command should log INFO for command execution."""
    from agent_arborist.runner import _execute_command
    with caplog.at_level(logging.INFO, logger="agent_arborist.runner"):
        _execute_command(["echo", "hello"], timeout=10)
    assert any("Running" in r.message for r in caplog.records)


def test_runner_logs_warning_on_timeout(caplog):
    """_execute_command should log WARNING on timeout."""
    from agent_arborist.runner import _execute_command
    with caplog.at_level(logging.WARNING, logger="agent_arborist.runner"):
        _execute_command(["sleep", "10"], timeout=1)
    assert any("timed out" in r.message for r in caplog.records)


def _make_tree():
    tree = TaskTree(spec_id="test", namespace="feature")
    tree.nodes["phase1"] = TaskNode(id="phase1", name="Phase 1", children=["T001"])
    tree.nodes["T001"] = TaskNode(id="T001", name="Task", parent="phase1", description="Do stuff")
    tree.compute_execution_order()
    return tree


def test_garden_logs_task_start(caplog, git_repo):
    """garden should log INFO when starting a task."""
    tree = _make_tree()
    mock_runner = MagicMock()
    mock_runner.run.return_value = MagicMock(success=True, output="APPROVED")

    with caplog.at_level(logging.INFO, logger="agent_arborist.worker.garden"):
        garden(tree, git_repo, mock_runner, max_retries=1)
    assert any("Starting task T001" in r.message for r in caplog.records)


def test_gardener_logs_progress(caplog, git_repo):
    """gardener should log progress like [1/N]."""
    tree = _make_tree()
    mock_runner = MagicMock()
    mock_runner.run.return_value = MagicMock(success=True, output="APPROVED")

    with caplog.at_level(logging.INFO, logger="agent_arborist.worker.gardener"):
        gardener(tree, git_repo, mock_runner, max_retries=1)
    assert any("[1/" in r.message for r in caplog.records)
