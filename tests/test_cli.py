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
