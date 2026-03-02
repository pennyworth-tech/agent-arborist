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

"""Tests for dashboard HTTP server."""

import json
from fastapi.testclient import TestClient


def _init_git(tmp_path):
    """Helper to create a minimal git repo."""
    import subprocess
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"],
                   cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"],
                   cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "README.md").write_text("# Test")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "branch", "-M", "main"],
                   cwd=tmp_path, check=True, capture_output=True)


def test_dashboard_serves_html(tmp_path, minimal_tree):
    """Test that dashboard serves HTML page."""
    from agent_arborist.dashboard.server import create_app

    tree_path = tmp_path / "task-tree.json"
    tree_path.write_text(json.dumps(minimal_tree))
    _init_git(tmp_path)

    app = create_app(tree_path, None, None)
    client = TestClient(app)

    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_dashboard_status_endpoint(tmp_path, minimal_tree):
    """Test /api/status endpoint returns valid JSON with commits field."""
    from agent_arborist.dashboard.server import create_app

    tree_path = tmp_path / "task-tree.json"
    tree_path.write_text(json.dumps(minimal_tree))
    _init_git(tmp_path)

    app = create_app(tree_path, None, None)
    client = TestClient(app)

    response = client.get("/api/status")
    assert response.status_code == 200

    data = response.json()
    assert "tree" in data
    assert "spec_id" in data
    assert "completed" in data
    assert isinstance(data["tasks"], dict)
    for task_id, task_data in data["tasks"].items():
        assert "commits" in task_data
        assert isinstance(task_data["commits"], list)


def test_dashboard_reports_endpoint(tmp_path):
    """Test /api/reports endpoint."""
    from agent_arborist.dashboard.server import create_app

    tree_path = tmp_path / "task-tree.json"
    minimal_tree = {"nodes": {}, "execution_order": [], "spec_files": []}
    tree_path.write_text(json.dumps(minimal_tree))
    _init_git(tmp_path)

    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    report_file = report_dir / "T001_run_20250101T120000.json"
    report_file.write_text('{"task_id": "T001", "result": "pass", "retries": 0}')

    app = create_app(tree_path, report_dir, None)
    client = TestClient(app)

    response = client.get("/api/reports")
    assert response.status_code == 200

    data = response.json()
    assert len(data["reports"]) == 1
    assert data["reports"][0]["task_id"] == "T001"


def test_dashboard_logs_endpoint(tmp_path, minimal_tree):
    """Test /api/logs returns log file listing."""
    from agent_arborist.dashboard.server import create_app

    tree_path = tmp_path / "task-tree.json"
    tree_path.write_text(json.dumps(minimal_tree))
    _init_git(tmp_path)

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "T001_implement_20250101T120000.log").write_text("test log content")

    app = create_app(tree_path, None, log_dir)
    client = TestClient(app)

    response = client.get("/api/logs")
    assert response.status_code == 200

    data = response.json()
    assert "T001" in data["logs"]
    assert len(data["logs"]["T001"]) == 1
    assert data["logs"]["T001"][0]["phase"] == "implement"


def test_dashboard_log_file_security(tmp_path):
    """Test that log file serving prevents directory traversal."""
    from agent_arborist.dashboard.server import create_app

    tree_path = tmp_path / "task-tree.json"
    minimal_tree = {"nodes": {}, "execution_order": [], "spec_files": []}
    tree_path.write_text(json.dumps(minimal_tree))
    _init_git(tmp_path)

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "T001_implement_20250101T120000.log").write_text("test log content")

    app = create_app(tree_path, None, log_dir)
    client = TestClient(app)

    response = client.get("/api/log/T001_implement_20250101T120000.log")
    assert response.status_code == 200
    assert "test log content" in response.text

    response = client.get("/api/log/../etc/passwd")
    assert response.status_code in (403, 404)

    response = client.get("/api/log/../../test.txt")
    assert response.status_code in (403, 404)
