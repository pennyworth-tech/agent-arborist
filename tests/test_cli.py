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

"""Tests for CLI commands: build, garden, gardener, status, inspect, init."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from agent_arborist.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tree_at(base_dir, branch="my-branch"):
    """Write a minimal task tree at openspec/changes/{spec_id}/task-tree.json and return the path."""
    from agent_arborist.git.repo import spec_id_from_branch
    spec_id = spec_id_from_branch(branch)
    tree_path = base_dir / "openspec" / "changes" / spec_id / "task-tree.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_text(json.dumps({
        "nodes": {
            "phase1": {"id": "phase1", "name": "P1", "children": ["T001"]},
            "T001": {"id": "T001", "name": "Task", "parent": "phase1", "description": "Do it"},
        },
        "execution_order": ["T001"], "spec_files": [],
    }))
    return tree_path


def test_build_no_ai_produces_valid_json(tmp_path):
    output = tmp_path / "tree.json"
    runner = CliRunner()
    with patch("agent_arborist.cli.git_current_branch", return_value="my-branch"), \
         patch("agent_arborist.cli.git_toplevel", return_value=str(tmp_path)):
        result = runner.invoke(main, [
            "build",
            "--no-ai",
            "--spec-dir", str(FIXTURES),
            "--output", str(output),
        ])
    assert result.exit_code == 0, result.output
    data = json.loads(output.read_text())
    assert "nodes" in data
    assert len(data["nodes"]) > 0


def test_build_no_ai_uses_markdown_parser(tmp_path):
    """--no-ai path should use spec_parser, not ai_planner."""
    output = tmp_path / "tree.json"
    runner = CliRunner()
    with patch("agent_arborist.cli.git_current_branch", return_value="my-branch"), \
         patch("agent_arborist.cli.git_toplevel", return_value=str(tmp_path)), \
         patch("agent_arborist.tree.ai_planner.plan_tree") as mock_plan:
        result = runner.invoke(main, [
            "build",
            "--no-ai",
            "--spec-dir", str(FIXTURES),
            "--output", str(output),
        ])
        assert result.exit_code == 0
        mock_plan.assert_not_called()


def test_build_default_uses_ai_planner(tmp_path):
    """Default build (no --no-ai) should call plan_tree."""
    output = tmp_path / "tree.json"
    runner = CliRunner()

    mock_tree = MagicMock()
    mock_tree.to_dict.return_value = {"nodes": {}, "root_ids": [], "execution_order": [], "spec_files": []}
    mock_tree.compute_execution_order.return_value = []
    mock_tree.nodes = {}
    mock_tree.leaves.return_value = []
    mock_tree.execution_order = []

    mock_result = MagicMock()
    mock_result.success = True
    mock_result.tree = mock_tree

    with patch("agent_arborist.cli.git_current_branch", return_value="my-branch"), \
         patch("agent_arborist.cli.git_toplevel", return_value=str(tmp_path)), \
         patch("agent_arborist.cli.plan_tree", mock_result, create=True), \
         patch("agent_arborist.tree.ai_planner.plan_tree", return_value=mock_result) as mock_plan:
        result = runner.invoke(main, [
            "build",
            "--spec-dir", str(FIXTURES),
            "--output", str(output),
        ])
        assert result.exit_code == 0, result.output
        mock_plan.assert_called_once()


# ---------------------------------------------------------------------------
# --base-branch default auto-detection
# ---------------------------------------------------------------------------

class TestBaseBranchDefault:
    """Verify --base-branch defaults to current branch, not 'main'."""

    def test_garden_help_shows_no_main_default(self):
        """--base-branch help text should not show 'main' as default."""
        runner = CliRunner()
        result = runner.invoke(main, ["garden", "--help"])
        assert result.exit_code == 0
        # Should not say default is "main"
        assert "default: main" not in result.output.lower()

    def test_gardener_help_shows_no_main_default(self):
        """--base-branch help text for gardener should not show 'main' as default."""
        runner = CliRunner()
        result = runner.invoke(main, ["gardener", "--help"])
        assert result.exit_code == 0
        assert "default: main" not in result.output.lower()

    def test_garden_auto_detects_current_branch(self, tmp_path):
        """When --base-branch is omitted, garden uses git_current_branch for spec path."""
        runner = CliRunner()
        tree_path = tmp_path / "tree.json"
        tree_path.write_text(json.dumps({
            "nodes": {"phase1": {"id": "phase1", "name": "P1", "children": ["T001"]},
                      "T001": {"id": "T001", "name": "Task", "parent": "phase1", "description": "Do it"}},
            "execution_order": ["T001"], "spec_files": [],
        }))

        with patch("agent_arborist.cli.git_current_branch", return_value="my-feature") as mock_gcb, \
             patch("agent_arborist.cli.git_toplevel", return_value=str(tmp_path)), \
             patch("agent_arborist.worker.garden.garden") as mock_garden:
            mock_garden.return_value = MagicMock(success=True, task_id="T001")
            result = runner.invoke(main, [
                "garden", "--tree", str(tree_path),
            ])
            assert result.exit_code == 0, result.output
            mock_gcb.assert_called_once()
            # branch should be passed to garden_fn
            _, kwargs = mock_garden.call_args
            assert kwargs["branch"] == "my-feature"

    def test_garden_explicit_base_branch_skips_detection(self, tmp_path):
        """When --base-branch is given explicitly, git_current_branch is NOT called."""
        runner = CliRunner()
        tree_path = tmp_path / "tree.json"
        tree_path.write_text(json.dumps({
            "nodes": {"phase1": {"id": "phase1", "name": "P1", "children": ["T001"]},
                      "T001": {"id": "T001", "name": "Task", "parent": "phase1", "description": "Do it"}},
            "execution_order": ["T001"], "spec_files": [],
        }))

        with patch("agent_arborist.cli.git_current_branch") as mock_gcb, \
             patch("agent_arborist.cli.git_toplevel", return_value=str(tmp_path)), \
             patch("agent_arborist.worker.garden.garden") as mock_garden:
            mock_garden.return_value = MagicMock(success=True, task_id="T001")
            result = runner.invoke(main, [
                "garden", "--tree", str(tree_path), "--base-branch", "develop",
            ])
            assert result.exit_code == 0, result.output
            mock_gcb.assert_not_called()


# ---------------------------------------------------------------------------
# Init command tests
# ---------------------------------------------------------------------------

class TestInitCommand:

    def test_init_creates_directory_and_config(self, tmp_path):
        """init creates .arborist/ and config.json."""
        runner = CliRunner()
        with patch("agent_arborist.cli.git_toplevel", return_value=str(tmp_path)):
            result = runner.invoke(main, ["init"], input="y\nclaude\nsonnet\ny\n")

        assert result.exit_code == 0, result.output
        assert (tmp_path / ".arborist").is_dir()
        assert (tmp_path / ".arborist" / "config.json").exists()

        config = json.loads((tmp_path / ".arborist" / "config.json").read_text())
        assert config["defaults"]["runner"] == "claude"
        assert config["defaults"]["model"] == "sonnet"

    def test_init_skips_existing(self, tmp_path):
        """init does not overwrite existing .arborist/ or config.json."""
        arborist_dir = tmp_path / ".arborist"
        arborist_dir.mkdir()
        config_path = arborist_dir / "config.json"
        config_path.write_text('{"version": "1", "defaults": {"runner": "gemini"}}')

        runner = CliRunner()
        with patch("agent_arborist.cli.git_toplevel", return_value=str(tmp_path)):
            result = runner.invoke(main, ["init"])

        assert result.exit_code == 0, result.output
        # Config should NOT be overwritten
        config = json.loads(config_path.read_text())
        assert config["defaults"]["runner"] == "gemini"
        assert "already exists" in result.output

    def test_init_abort_on_no(self, tmp_path):
        """Answering 'n' to create directory aborts."""
        runner = CliRunner()
        with patch("agent_arborist.cli.git_toplevel", return_value=str(tmp_path)):
            result = runner.invoke(main, ["init"], input="n\n")

        assert result.exit_code == 0
        assert not (tmp_path / ".arborist").exists()
        assert "Aborted" in result.output


# ---------------------------------------------------------------------------
# Inspect command tests
# ---------------------------------------------------------------------------

def _make_tree_json(tmp_path):
    """Helper: write a minimal task tree JSON and return the path."""
    tree_path = tmp_path / "tree.json"
    tree_path.write_text(json.dumps({
        "nodes": {
            "phase1": {"id": "phase1", "name": "Phase 1", "children": ["T001", "T002"]},
            "T001": {"id": "T001", "name": "First task", "parent": "phase1",
                     "description": "Do the first thing", "depends_on": []},
            "T002": {"id": "T002", "name": "Second task", "parent": "phase1",
                     "description": "Do the second thing", "depends_on": ["T001"]},
        },
        "execution_order": ["T001", "T002"], "spec_files": [],
    }))
    return tree_path


class TestInspectCommand:

    def test_inspect_unknown_task_id(self, tmp_path):
        """inspect with a bad task ID exits with error."""
        tree_path = _make_tree_json(tmp_path)
        runner = CliRunner()
        with patch("agent_arborist.cli.git_toplevel", return_value=str(tmp_path)), \
             patch("agent_arborist.cli.git_current_branch", return_value="main"):
            result = runner.invoke(main, [
                "inspect", "--tree", str(tree_path), "--task-id", "TXXX",
            ])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_inspect_shows_metadata(self, tmp_path):
        """inspect displays task name, description, deps, and branch."""
        tree_path = _make_tree_json(tmp_path)
        runner = CliRunner()
        with patch("agent_arborist.cli.git_toplevel", return_value=str(tmp_path)), \
             patch("agent_arborist.cli.git_current_branch", return_value="main"), \
             patch("agent_arborist.git.repo.git_branch_exists", return_value=False):
            result = runner.invoke(main, [
                "inspect", "--tree", str(tree_path), "--task-id", "T002",
            ])
        assert result.exit_code == 0, result.output
        assert "T002" in result.output
        assert "Second task" in result.output
        assert "T001" in result.output  # depends_on
        assert "not started" in result.output.lower()  # no commits yet

    def test_inspect_no_commits_yet(self, tmp_path):
        """inspect shows 'not started' when no commits found for the task."""
        tree_path = _make_tree_json(tmp_path)
        runner = CliRunner()
        with patch("agent_arborist.cli.git_toplevel", return_value=str(tmp_path)), \
             patch("agent_arborist.cli.git_current_branch", return_value="main"), \
             patch("agent_arborist.git.state.get_task_trailers", return_value={}):
            result = runner.invoke(main, [
                "inspect", "--tree", str(tree_path), "--task-id", "T001",
            ])
        assert result.exit_code == 0, result.output
        assert "not started" in result.output.lower()

    def test_inspect_shows_state_and_trailers(self, tmp_path):
        """inspect shows state and trailers when commits exist."""
        tree_path = _make_tree_json(tmp_path)
        runner = CliRunner()
        mock_trailers = {
            "Arborist-Step": "review",
            "Arborist-Review": "approve",
        }
        with patch("agent_arborist.cli.git_toplevel", return_value=str(tmp_path)), \
             patch("agent_arborist.cli.git_current_branch", return_value="main"), \
             patch("agent_arborist.git.state.get_task_trailers", return_value=mock_trailers), \
             patch("agent_arborist.git.repo.git_log", return_value="abc1234 task(main@T001@implement-pass): implement\n  Arborist-Step: implement"):
            result = runner.invoke(main, [
                "inspect", "--tree", str(tree_path), "--task-id", "T001",
            ])
        assert result.exit_code == 0, result.output
        assert "reviewing" in result.output
        assert "Arborist-Step" in result.output
        assert "abc1234" in result.output


# ---------------------------------------------------------------------------
# Default tree path: specs/{branch}/task-tree.json
# ---------------------------------------------------------------------------

class TestDefaultTreePath:
    """When --tree is omitted, CLI derives path from current/base branch."""

    def test_build_default_output_uses_branch(self, tmp_path):
        """build without -o writes to openspec/changes/{spec_id}/task-tree.json."""
        runner = CliRunner()
        with patch("agent_arborist.cli.git_current_branch", return_value="my-feature"), \
             patch("agent_arborist.cli.git_toplevel", return_value=str(tmp_path)):
            result = runner.invoke(main, [
                "build", "--no-ai",
                "--spec-dir", str(FIXTURES),
            ])
        assert result.exit_code == 0, result.output
        expected = Path("openspec/changes/my-feature/task-tree.json")
        assert expected.exists()

    def test_build_explicit_output_overrides_default(self, tmp_path):
        """build with -o ignores the branch-based default."""
        output = tmp_path / "custom.json"
        runner = CliRunner()
        with patch("agent_arborist.cli.git_current_branch", return_value="my-branch"), \
             patch("agent_arborist.cli.git_toplevel", return_value=str(tmp_path)):
            result = runner.invoke(main, [
                "build", "--no-ai",
                "--spec-dir", str(FIXTURES),
                "--output", str(output),
            ])
        assert result.exit_code == 0, result.output
        assert output.exists()

    def test_garden_default_tree_from_base_branch(self, tmp_path):
        """garden without --tree uses specs/{base_branch}/task-tree.json."""
        _make_tree_at(tmp_path, "my-branch")
        runner = CliRunner()
        with patch("agent_arborist.cli.git_current_branch", return_value="my-branch"), \
             patch("agent_arborist.cli.git_toplevel", return_value=str(tmp_path)), \
             patch("agent_arborist.worker.garden.garden") as mock_garden:
            mock_garden.return_value = MagicMock(success=True, task_id="T001")
            result = runner.invoke(main, ["garden"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        mock_garden.assert_called_once()

    def test_garden_explicit_tree_overrides_default(self, tmp_path):
        """garden with --tree uses the explicit path."""
        tree_path = _make_tree_json(tmp_path)
        runner = CliRunner()
        with patch("agent_arborist.cli.git_current_branch", return_value="other-branch"), \
             patch("agent_arborist.cli.git_toplevel", return_value=str(tmp_path)), \
             patch("agent_arborist.worker.garden.garden") as mock_garden:
            mock_garden.return_value = MagicMock(success=True, task_id="T001")
            result = runner.invoke(main, ["garden", "--tree", str(tree_path)])
        assert result.exit_code == 0, result.output

    def test_gardener_default_tree_from_base_branch(self, tmp_path):
        """gardener without --tree uses specs/{base_branch}/task-tree.json."""
        _make_tree_at(tmp_path, "spec/feat")
        runner = CliRunner()
        with patch("agent_arborist.cli.git_current_branch", return_value="spec/feat"), \
             patch("agent_arborist.cli.git_toplevel", return_value=str(tmp_path)), \
             patch("agent_arborist.worker.gardener.gardener") as mock_gardener:
            mock_gardener.return_value = MagicMock(success=True, tasks_completed=1, order=["T001"])
            result = runner.invoke(main, ["gardener"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        mock_gardener.assert_called_once()

    def test_gardener_base_branch_override_changes_tree_path(self, tmp_path):
        """gardener --base-branch X uses specs/X/task-tree.json."""
        _make_tree_at(tmp_path, "other")
        runner = CliRunner()
        with patch("agent_arborist.cli.git_current_branch", return_value="main"), \
             patch("agent_arborist.cli.git_toplevel", return_value=str(tmp_path)), \
             patch("agent_arborist.worker.gardener.gardener") as mock_gardener:
            mock_gardener.return_value = MagicMock(success=True, tasks_completed=1, order=["T001"])
            result = runner.invoke(main, ["gardener", "--base-branch", "other"], catch_exceptions=False)
        assert result.exit_code == 0, result.output

    def test_status_default_tree_from_branch(self, tmp_path):
        """status without --tree uses specs/{branch}/task-tree.json."""
        _make_tree_at(tmp_path, "spec/feat")
        runner = CliRunner()
        with patch("agent_arborist.cli.git_current_branch", return_value="spec/feat"), \
             patch("agent_arborist.cli.git_toplevel", return_value=str(tmp_path)), \
             patch("agent_arborist.git.state.get_task_trailers", return_value={}), \
             patch("agent_arborist.git.state.task_state_from_trailers") as mock_state:
            from agent_arborist.git.state import TaskState
            mock_state.return_value = TaskState.PENDING
            result = runner.invoke(main, ["status"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        assert "Task Tree" in result.output

    def test_inspect_default_tree_from_branch(self, tmp_path):
        """inspect without --tree uses specs/{branch}/task-tree.json."""
        _make_tree_at(tmp_path, "spec/feat")
        runner = CliRunner()
        with patch("agent_arborist.cli.git_current_branch", return_value="spec/feat"), \
             patch("agent_arborist.cli.git_toplevel", return_value=str(tmp_path)), \
             patch("agent_arborist.git.repo.git_branch_exists", return_value=False):
            result = runner.invoke(main, ["inspect", "--task-id", "T001"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        assert "T001" in result.output

    def test_garden_missing_default_tree_errors(self, tmp_path):
        """garden without --tree errors when specs/{branch}/task-tree.json doesn't exist."""
        runner = CliRunner()
        with patch("agent_arborist.cli.git_current_branch", return_value="no-such-branch"), \
             patch("agent_arborist.cli.git_toplevel", return_value=str(tmp_path)):
            result = runner.invoke(main, ["garden"])
        assert result.exit_code != 0

    def test_build_with_slash_branch(self, tmp_path):
        """build with a branch like feature/feat/sub extracts spec_id and creates openspec/changes/{spec_id}/."""
        runner = CliRunner()
        with patch("agent_arborist.cli.git_current_branch", return_value="feature/feat/sub"), \
             patch("agent_arborist.cli.git_toplevel", return_value=str(tmp_path)):
            result = runner.invoke(main, [
                "build", "--no-ai",
                "--spec-dir", str(FIXTURES),
            ])
        assert result.exit_code == 0, result.output
        assert Path("openspec/changes/feat/task-tree.json").exists()


# ---------------------------------------------------------------------------
# Init: no logs dir, no gitignore
# ---------------------------------------------------------------------------

class TestInitNoLogs:
    """init no longer creates .arborist/logs/ or modifies .gitignore."""

    def test_init_does_not_create_logs_dir(self, tmp_path):
        """init should NOT create .arborist/logs/."""
        runner = CliRunner()
        with patch("agent_arborist.cli.git_toplevel", return_value=str(tmp_path)):
            result = runner.invoke(main, ["init"], input="y\nclaude\nsonnet\ny\n")
        assert result.exit_code == 0, result.output
        assert not (tmp_path / ".arborist" / "logs").exists()

    def test_init_does_not_create_gitignore(self, tmp_path):
        """init should NOT create or modify .gitignore."""
        runner = CliRunner()
        with patch("agent_arborist.cli.git_toplevel", return_value=str(tmp_path)):
            result = runner.invoke(main, ["init"], input="y\nclaude\nsonnet\ny\n")
        assert result.exit_code == 0, result.output
        assert not (tmp_path / ".gitignore").exists()

    def test_init_does_not_mention_logs(self, tmp_path):
        """init output should not reference logs."""
        runner = CliRunner()
        with patch("agent_arborist.cli.git_toplevel", return_value=str(tmp_path)):
            result = runner.invoke(main, ["init"], input="y\nclaude\nsonnet\ny\n")
        assert result.exit_code == 0, result.output
        assert "logs" not in result.output.lower()
        assert "gitignore" not in result.output.lower()

    def test_init_does_not_prompt_for_gitignore(self, tmp_path):
        """init should only prompt for dir creation and config, not gitignore."""
        runner = CliRunner()
        with patch("agent_arborist.cli.git_toplevel", return_value=str(tmp_path)):
            # Only 3 inputs needed: create dir (y), runner, model, confirm config
            result = runner.invoke(main, ["init"], input="y\nclaude\nsonnet\ny\n")
        assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# Config: TestingConfig without command field
# ---------------------------------------------------------------------------

class TestTestingConfigNoCommand:
    """TestingConfig no longer has a command field."""

    def test_testing_config_has_no_command_attr(self):
        from agent_arborist.config import TestingConfig
        tc = TestingConfig()
        assert not hasattr(tc, "command")

    def test_testing_config_to_dict_no_command(self):
        from agent_arborist.config import TestingConfig
        tc = TestingConfig(timeout=30)
        d = tc.to_dict()
        assert "command" not in d
        assert d["timeout"] == 30

    def test_testing_config_strict_rejects_unknown_fields(self):
        from agent_arborist.config import TestingConfig, ConfigValidationError
        with pytest.raises(ConfigValidationError, match="Unknown fields"):
            TestingConfig.from_dict({"bogus": True}, strict=True)

    def test_config_template_has_no_test_command(self):
        from agent_arborist.config import generate_config_template
        template = generate_config_template()
        assert "command" not in template.get("test", {})

    def test_env_override_no_test_command(self):
        """ARBORIST_TEST_COMMAND env var should have no effect."""
        import os
        from agent_arborist.config import ArboristConfig, apply_env_overrides
        cfg = ArboristConfig()
        with patch.dict(os.environ, {"ARBORIST_TEST_COMMAND": "pytest -v"}):
            result = apply_env_overrides(cfg)
        assert not hasattr(result.test, "command")
