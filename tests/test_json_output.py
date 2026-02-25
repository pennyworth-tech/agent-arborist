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

"""Tests for JSON output format in CLI commands."""

import json
import subprocess
from pathlib import Path
from click.testing import CliRunner


def test_status_json_output(git_repo, minimal_tree):
    """Test that status --format json outputs valid JSON."""
    from agent_arborist.cli import main

    runner = CliRunner()
    tree_path = Path("task-tree.json")

    with runner.isolated_filesystem(temp_dir=git_repo):
        tree_path.write_text(json.dumps(minimal_tree))
        result = runner.invoke(main, ["status", "--tree", str(tree_path), "--format", "json"])

    assert result.exit_code == 0

    data = json.loads(result.output)
    assert "tree" in data
    assert "branch" in data
    assert "completed" in data
    assert "tasks" in data
    assert isinstance(data["completed"], list)


def test_reports_json_output(git_repo):
    """Test that reports --format json outputs valid JSON."""
    from agent_arborist.cli import main

    runner = CliRunner()
    tree_path = Path("specs") / "main" / "task-tree.json"

    with runner.isolated_filesystem(temp_dir=git_repo):
        tree_path.parent.mkdir(parents=True, exist_ok=True)
        tree_path.write_text('{"nodes": {}, "execution_order": [], "spec_files": []}')

        report_dir = tree_path.parent / "reports"
        report_dir.mkdir()

        report_file = report_dir / "T001_run_20250101T120000.json"
        report_file.write_text('{"task_id": "T001", "result": "pass", "retries": 0, "completed_at": "2025-01-01T12:00:00", "filename": "T001_run_20250101T120000.json"}')

        result = runner.invoke(main, ["reports", "--tree", str(tree_path), "--format", "json"])

    assert result.exit_code == 0

    data = json.loads(result.output)
    assert "reports" in data
    assert "summary" in data
    assert len(data["reports"]) == 1
    assert data["reports"][0]["task_id"] == "T001"
    assert data["summary"]["total"] == 1


def test_reports_no_directory(git_repo):
    """Test that reports handles missing directory gracefully."""
    from agent_arborist.cli import main

    runner = CliRunner()
    tree_path = Path("specs") / "main" / "task-tree.json"

    with runner.isolated_filesystem(temp_dir=git_repo):
        tree_path.parent.mkdir(parents=True, exist_ok=True)
        tree_path.write_text('{"nodes": {}, "execution_order": [], "spec_files": []}')

        result = runner.invoke(main, ["reports", "--tree", str(tree_path), "--format", "json"])

    assert result.exit_code == 0

    data = json.loads(result.output)
    assert data["reports"] == []
    assert data["summary"]["total"] == 0


def test_logs_json_output(git_repo):
    """Test that logs --format json outputs valid JSON."""
    from agent_arborist.cli import main

    runner = CliRunner()
    tree_path = Path("specs") / "main" / "task-tree.json"

    with runner.isolated_filesystem(temp_dir=git_repo):
        tree_path.parent.mkdir(parents=True, exist_ok=True)
        tree_path.write_text('{"nodes": {}, "execution_order": [], "spec_files": []}')

        log_dir = tree_path.parent / "logs"
        log_dir.mkdir()

        log_file = log_dir / "T001_implement_20250101T120000.log"
        log_file.write_text("test log content")

        result = runner.invoke(main, ["logs", "--tree", str(tree_path), "--format", "json"])

    assert result.exit_code == 0

    data = json.loads(result.output)
    assert "logs" in data
    assert "summary" in data
    assert "T001" in data["logs"]
    assert len(data["logs"]["T001"]) == 1
    assert data["logs"]["T001"][0]["phase"] == "implement"


def test_logs_no_directory(git_repo):
    """Test that logs handles missing directory gracefully."""
    from agent_arborist.cli import main

    runner = CliRunner()
    tree_path = Path("specs") / "main" / "task-tree.json"

    with runner.isolated_filesystem(temp_dir=git_repo):
        tree_path.parent.mkdir(parents=True, exist_ok=True)
        tree_path.write_text('{"nodes": {}, "execution_order": [], "spec_files": []}')

        result = runner.invoke(main, ["logs", "--tree", str(tree_path), "--format", "json"])

    assert result.exit_code == 0

    data = json.loads(result.output)
    assert data["logs"] == {}
    assert data["summary"]["total_tasks"] == 0


def test_inspect_json_output(git_repo, minimal_tree):
    """Test that inspect --format json outputs valid JSON."""
    from agent_arborist.cli import main

    runner = CliRunner()
    tree_path = Path("task-tree.json")

    with runner.isolated_filesystem(temp_dir=git_repo):
        tree_path.write_text(json.dumps(minimal_tree))
        result = runner.invoke(main, ["inspect", "--tree", str(tree_path), "--task-id", "T001", "--format", "json"])

    assert result.exit_code == 0

    data = json.loads(result.output)
    assert "task" in data
    assert "state" in data
    assert "trailers" in data
    assert data["task"]["id"] == "T001"
    assert "name" in data["task"]
    assert "test_commands" in data["task"]