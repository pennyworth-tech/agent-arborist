"""Tests for CLI --no-ai flag and basic build command."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from click.testing import CliRunner

from agent_arborist.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


def test_build_no_ai_produces_valid_json(tmp_path):
    output = tmp_path / "tree.json"
    runner = CliRunner()
    result = runner.invoke(main, [
        "build",
        "--no-ai",
        "--spec-dir", str(FIXTURES),
        "--output", str(output),
        "--spec-id", "test",
    ])
    assert result.exit_code == 0, result.output
    data = json.loads(output.read_text())
    assert "nodes" in data
    assert "spec_id" in data
    assert data["spec_id"] == "test"
    assert len(data["nodes"]) > 0


def test_build_no_ai_uses_markdown_parser(tmp_path):
    """--no-ai path should use spec_parser, not ai_planner."""
    output = tmp_path / "tree.json"
    runner = CliRunner()
    with patch("agent_arborist.tree.ai_planner.plan_tree") as mock_plan:
        result = runner.invoke(main, [
            "build",
            "--no-ai",
            "--spec-dir", str(FIXTURES),
            "--output", str(output),
            "--spec-id", "test",
        ])
        assert result.exit_code == 0
        mock_plan.assert_not_called()


def test_build_default_uses_ai_planner(tmp_path):
    """Default build (no --no-ai) should call plan_tree."""
    output = tmp_path / "tree.json"
    runner = CliRunner()

    mock_tree = MagicMock()
    mock_tree.to_dict.return_value = {"spec_id": "test", "nodes": {}, "root_ids": [], "execution_order": [], "spec_files": []}
    mock_tree.compute_execution_order.return_value = []
    mock_tree.nodes = {}
    mock_tree.leaves.return_value = []
    mock_tree.execution_order = []
    mock_tree.namespace = "feature"
    mock_tree.spec_id = "test"

    mock_result = MagicMock()
    mock_result.success = True
    mock_result.tree = mock_tree

    with patch("agent_arborist.cli.plan_tree", mock_result, create=True):
        # We patch at the import location inside cli.build
        with patch("agent_arborist.tree.ai_planner.plan_tree", return_value=mock_result) as mock_plan:
            result = runner.invoke(main, [
                "build",
                "--spec-dir", str(FIXTURES),
                "--output", str(output),
                "--spec-id", "test",
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
        """When --base-branch is omitted, garden() should call git_current_branch."""
        runner = CliRunner()
        tree_path = tmp_path / "tree.json"
        tree_path.write_text(json.dumps({
            "spec_id": "test", "namespace": "feature",
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
            # garden_fn should have been called with base_branch="my-feature"
            _, kwargs = mock_garden.call_args
            assert kwargs["base_branch"] == "my-feature"

    def test_garden_explicit_base_branch_skips_detection(self, tmp_path):
        """When --base-branch is given explicitly, git_current_branch is NOT called."""
        runner = CliRunner()
        tree_path = tmp_path / "tree.json"
        tree_path.write_text(json.dumps({
            "spec_id": "test", "namespace": "feature",
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
            _, kwargs = mock_garden.call_args
            assert kwargs["base_branch"] == "develop"


# ---------------------------------------------------------------------------
# Init command tests
# ---------------------------------------------------------------------------

class TestInitCommand:

    def test_init_creates_directory_and_config(self, tmp_path):
        """init creates .arborist/, logs/, config.json, and updates .gitignore."""
        runner = CliRunner()
        with patch("agent_arborist.cli.git_toplevel", return_value=str(tmp_path)):
            result = runner.invoke(main, ["init"], input="y\ny\nclaude\nsonnet\ny\n")

        assert result.exit_code == 0, result.output
        assert (tmp_path / ".arborist").is_dir()
        assert (tmp_path / ".arborist" / "logs").is_dir()
        assert (tmp_path / ".arborist" / "config.json").exists()

        config = json.loads((tmp_path / ".arborist" / "config.json").read_text())
        assert config["defaults"]["runner"] == "claude"
        assert config["defaults"]["model"] == "sonnet"

        gitignore = (tmp_path / ".gitignore").read_text()
        assert ".arborist/logs/" in gitignore

    def test_init_skips_existing(self, tmp_path):
        """init does not overwrite existing .arborist/ or config.json."""
        arborist_dir = tmp_path / ".arborist"
        arborist_dir.mkdir()
        (arborist_dir / "logs").mkdir()
        config_path = arborist_dir / "config.json"
        config_path.write_text('{"version": "1", "defaults": {"runner": "gemini"}}')
        (tmp_path / ".gitignore").write_text(".arborist/logs/\n")

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
