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


def test_dashboard_serves_html(tmp_path, minimal_tree):
    """Test that dashboard serves HTML page."""
    from agent_arborist.dashboard.server import create_app

    tree_path = tmp_path / "task-tree.json"
    tree_path.write_text(json.dumps(minimal_tree))

    # Create dummy git repo for branch detection
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

    # Create template
    template_dir = tmp_path / "dashboard" / "templates"
    template_dir.mkdir(parents=True)
    (template_dir / "dashboard.html").write_text("<html><body>Test Dashboard</body></html>")

    app = create_app(tree_path, None, None)
    client = TestClient(app)

    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_dashboard_status_endpoint(tmp_path, minimal_tree):
    """Test /api/status endpoint returns valid JSON."""
    from agent_arborist.dashboard.server import create_app

    tree_path = tmp_path / "task-tree.json"
    tree_path.write_text(json.dumps(minimal_tree))

    # Create dummy git repo
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

    # Create template
    template_dir = tmp_path / "dashboard" / "templates"
    template_dir.mkdir(parents=True)
    (template_dir / "dashboard.html").write_text("<html><body>Test Dashboard</body></html>")

    app = create_app(tree_path, None, None)
    client = TestClient(app)

    response = client.get("/api/status")
    assert response.status_code == 200

    data = response.json()
    assert "tree" in data
    assert "branch" in data
    assert "completed" in data
    assert isinstance(data["tasks"], dict)


def test_dashboard_reports_endpoint(tmp_path):
    """Test /api/reports endpoint."""
    from agent_arborist.dashboard.server import create_app

    tree_path = tmp_path / "task-tree.json"
    minimal_tree = {
        "nodes": {},
        "execution_order": [],
        "spec_files": []
    }
    tree_path.write_text(json.dumps(minimal_tree))

    # Create git repo
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

    # Create template
    template_dir = tmp_path / "dashboard" / "templates"
    template_dir.mkdir(parents=True)
    (template_dir / "dashboard.html").write_text("<html><body>Test Dashboard</body></html>")

    # Create report directory with sample report
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    report_file = report_dir / "T001_run_20250101T120000.json"
    report_file.write_text('{"task_id": "T001", "result": "pass", "retries": 0, "completed_at": "2025-01-01T12:00:00", "filename": "T001_run_20250101T120000.json"}')

    app = create_app(tree_path, report_dir, None)
    client = TestClient(app)

    response = client.get("/api/reports")
    assert response.status_code == 200

    data = response.json()
    assert "reports" in data
    assert "summary" in data
    assert len(data["reports"]) == 1
    assert data["reports"][0]["task_id"] == "T001"


def test_dashboard_log_file_security(tmp_path):
    """Test that log file serving prevents directory traversal."""
    from agent_arborist.dashboard.server import create_app

    tree_path = tmp_path / "task-tree.json"
    minimal_tree = {
        "nodes": {},
        "execution_order": [],
        "spec_files": []
    }
    tree_path.write_text(json.dumps(minimal_tree))

    # Create git repo
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

    # Create template
    template_dir = tmp_path / "dashboard" / "templates"
    template_dir.mkdir(parents=True)
    (template_dir / "dashboard.html").write_text("<html><body>Test Dashboard</body></html>")

    # Create log file
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    log_file = log_dir / "T001_implement_20250101T120000.log"
    log_file.write_text("test log content")

    app = create_app(tree_path, None, log_dir)
    client = TestClient(app)

    # Valid log file should work
    response = client.get("/api/log/T001_implement_20250101T120000.log")
    assert response.status_code == 200
    assert "test log content" in response.text

    # Directory traversal attempts should fail (either 403 for access denied or 404 for not found)
    response = client.get("/api/log/../etc/passwd")
    assert response.status_code in (403, 404)

    response = client.get("/api/log/../../test.txt")
    assert response.status_code in (403, 404)


def test_dashboard_logs_endpoint(tmp_path):
    """Test /api/logs endpoint."""
    from agent_arborist.dashboard.server import create_app

    tree_path = tmp_path / "task-tree.json"
    minimal_tree = {
        "nodes": {},
        "execution_order": [],
        "spec_files": []
    }
    tree_path.write_text(json.dumps(minimal_tree))

    # Create git repo
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

    # Create template
    template_dir = tmp_path / "dashboard" / "templates"
    template_dir.mkdir(parents=True)
    (template_dir / "dashboard.html").write_text("<html><body>Test Dashboard</body></html>")

    # Create log files
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    log_file = log_dir / "T001_implement_20250101T120000.log"
    log_file.write_text("test log content")

    app = create_app(tree_path, None, log_dir)
    client = TestClient(app)

    response = client.get("/api/logs")
    assert response.status_code == 200

    data = response.json()
    assert "logs" in data
    assert "summary" in data
    assert "T001" in data["logs"]
    assert len(data["logs"]["T001"]) == 1