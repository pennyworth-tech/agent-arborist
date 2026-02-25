# Integration Plan: PR #54 - Live Dashboard

## Overview

This plan outlines the integration of Nate's live dashboard feature into agent-arborist. The dashboard must be:

1. **Fully integrated into CLI** as `arborist dashboard` command
2. **Read-only** - no control actions (run, restart, etc.)
3. **Parity between CLI and dashboard** - all dashboard data available via CLI with JSON output
4. **Well-structured** - HTML/CSS/JS separated from server logic

## Current State

The PR adds `dashboard/serve-dashboard.py` (1031 lines) with:
- Standalone Python HTTP server
- Inlined 680+ lines of HTML/CSS/JS
- Reads task tree JSON, reports, logs from disk
- Runs jest and arborist status via subprocess
- Auto-refresh every 5 seconds
- Attempts to implement/review/test workflow control

### Issues with Current Implementation

1. **Not integrated in CLI** - runs as standalone script
2. **No JSON output** - commands lack machine-readable format
3. **Hardcoded paths** - assumes `dashboard/` directory structure
4. **Subprocess abuse** - calls `jest` and `arborist` via shell
5. **Write/control features** - dashboard attempts to run tests, restart runs
6. **No test coverage**
7. **HTML inlined** - difficult to maintain

---

## Phase 1: Enhance CLI with JSON Output

### 1.1 Add JSON format to `arborist status`

#### 1.1.1 Modify `status` command
Add `--format` option to support `json` output.

```python
@main.command()
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def status(tree_path, target_repo, output_format):
    """Show current status of all tasks."""
    # ... existing loading logic ...

    if output_format == "json":
        status_data = {
            "tree": tree.to_dict(),
            "branch": branch,
            "completed": list(completed_tasks),
            "tasks": {}
        }

        for node_id, node in tree.nodes.items():
            if node.is_leaf:
                trailers = get_task_trailers("HEAD", node_id, target, current_branch=branch)
                state = task_state_from_trailers(trailers)
                status_data["tasks"][node_id] = {
                    "id": node.id,
                    "name": node.name,
                    "state": state.value,
                    "trailers": trailers
                }

        console.print(json.dumps(status_data, indent=2))
    else:
        # ... existing rich tree output ...
```

#### 1.1.2 JSON Schema
```typescript
interface StatusOutput {
  tree: TaskTree;
  branch: string;
  completed: string[];  // Task IDs
  tasks: {
    [taskId: string]: {
      id: string;
      name: string;
      state: "pending" | "implementing" | "testing" | "reviewing" | "complete" | "failed";
      trailers: { [key: string]: string };
    };
  };
}
```

### 1.2 Create `arborist reports` command

#### 1.2.1 New command
```python
@main.command()
@click.option("--tree", "tree_path", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--report-dir", type=click.Path(path_type=Path), default=None)
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
@click.option("--task-id", help="Filter by specific task ID")
def reports(tree_path, report_dir, output_format, task_id):
    """List and query task execution reports."""
    # Resolve report_dir (next to tree by default)
    tree, report_dir, branch = _resolve_tree_and_report_dirs(tree_path, report_dir)

    if not report_dir.exists():
        console.print("[yellow]No reports directory found[/yellow]")
        return

    # Parse all report JSON files
    all_reports = _parse_reports(report_dir, task_id)

    if output_format == "json":
        console.print(json.dumps(all_reports, indent=2))
    else:
        # Text output - formatted table
        _print_reports_table(all_reports)
```

#### 1.2.2 JSON Schema
```typescript
interface Report {
  task_id: string;
  result: "pass" | "fail";
  retries: number;
  completed_at: string;  // ISO 8601 timestamp
  filename: string;
}

interface ReportsOutput {
  reports: Report[];
  summary: {
    total: number;
    passed: number;
    failed: number;
    avg_retries: number;
  };
}
```

### 1.3 Create `arborist logs` command

#### 1.3.1 New command
```python
@main.command()
@click.option("--tree", "tree_path", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--log-dir", type=click.Path(path_type=Path), default=None)
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
@click.option("--task-id", help="Filter by specific task ID")
def logs(tree_path, log_dir, output_format, task_id):
    """List task execution logs."""
    tree, log_dir, branch = _resolve_tree_and_log_dirs(tree_path, log_dir)

    if not log_dir.exists():
        console.print("[yellow]No logs directory found[/yellow]")
        return

    # Parse log files
    all_logs = _parse_logs(log_dir, task_id)

    if output_format == "json":
        console.print(json.dumps(all_logs, indent=2))
    else:
        _print_logs_table(all_logs)
```

#### 1.3.2 JSON Schema
```typescript
interface LogEntry {
  task_id: string;
  phase: "implement" | "review" | "test";
  timestamp: string;  # ISO 8601
  filename: string;
  size: number;
}

interface LogsOutput {
  logs: {
    [taskId: string]: LogEntry[];
  };
  summary: {
    total_tasks: number;
    total_entries: number;
    phase_counts: {
      implement: number;
      review: number;
      test: number;
    };
  };
}
```

### 1.4 Add `arborist inspect` JSON output

#### 1.4.1 Enhance existing command
```python
@main.command()
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def inspect(tree_path, task_id, target_repo, output_format):
    """Deep-dive into a single task."""
    # ... existing validation ...

    if output_format == "json":
        inspect_data = {
            "task": {
                "id": node.id,
                "name": node.name,
                "description": node.description,
                "is_leaf": node.is_leaf,
                "parent": node.parent,
                "children": node.children,
                "depends_on": node.depends_on,
                "test_commands": [tc.to_dict() for tc in node.test_commands],
            },
            "state": state.value,
            "trailers": trailers,
            "commits": _get_task_commits(task_id, branch, target)
        }
        console.print(json.dumps(inspect_data, indent=2))
    else:
        # ... existing rich text output ...
```

---

## Phase 2: Create Dashboard Module Structure

### 2.1 Create Module Directory Structure

```
src/agent_arborist/dashboard/
├── __init__.py
├── server.py         # FastAPI application
├── schemas.py        # Pydantic models for API
├── templates/
│   └── dashboard.html
└── static/
    └── dashboard.js  # Extracted JavaScript
```

### 2.2 Create Pydantic Schemas

Create `src/agent_arborist/dashboard/schemas.py`:

```python
"""Pydantic schemas for dashboard API responses."""

from pydantic import BaseModel
from typing import Dict, List, Literal, Optional

class TaskStateData(BaseModel):
    id: str
    name: str
    state: Literal["pending", "implementing", "testing", "reviewing", "complete", "failed"]
    trailers: Dict[str, str] = {}

class StatusOutput(BaseModel):
    tree: dict
    branch: str
    completed: List[str]
    tasks: Dict[str, TaskStateData]
    generated_at: str

class Report(BaseModel):
    task_id: str
    result: Literal["pass", "fail"]
    retries: int
    completed_at: str
    filename: str

class ReportsOutput(BaseModel):
    reports: List[Report]
    summary: dict

class LogEntry(BaseModel):
    task_id: str
    phase: Literal["implement", "review", "test"]
    timestamp: str
    filename: str
    size: int

class LogsOutput(BaseModel):
    logs: Dict[str, List[LogEntry]]
    summary: dict
```

### 2.3 Create FastAPI Server

Create `src/agent_arborist/dashboard/server.py`:

```python
"""Dashboard FastAPI server - read-only monitoring interface."""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, PlainTextResponse
from pathlib import Path
from typing import Optional
from rich.console import Console

from agent_arborist.git.state import scan_completed_tasks, get_task_trailers, task_state_from_trailers
from agent_arborist.tree.model import TaskTree
from agent_arborist.git.repo import git_current_branch
from agent_arborist.dashboard.schemas import (
    StatusOutput, ReportsOutput, LogsOutput, TaskStateData,
    Report, LogEntry
)

console = Console()

def create_app(tree_path: Path, report_dir: Optional[Path], log_dir: Optional[Path]) -> FastAPI:
    """Create and configure the FastAPI application."""

    app = FastAPI(
        title="Arborist Dashboard",
        description="Read-only monitoring dashboard for task execution",
        version="1.0.0"
    )

    tree = TaskTree.from_dict_json(tree_path.read_text())
    target = Path.cwd()
    branch = git_current_branch(target)

    if report_dir is None:
        report_dir = tree_path.parent / "reports"
    if log_dir is None:
        log_dir = tree_path.parent / "logs"

    @app.get("/", response_class=HTMLResponse)
    async def serve_dashboard():
        """Serve the dashboard HTML page."""
        template_path = Path(__file__).parent / "templates" / "dashboard.html"
        return template_path.read_text()

    @app.get("/api/status", response_model=StatusOutput)
    async def get_status():
        """Get task status data."""
        completed = scan_completed_tasks(tree, target, branch=branch)

        tasks = {}
        for task_id, node in tree.nodes.items():
            if not node.is_leaf:
                continue
            trailers = get_task_trailers("HEAD", task_id, target, current_branch=branch)
            state = task_state_from_trailers(trailers)
            tasks[task_id] = TaskStateData(
                id=task_id,
                name=node.name,
                state=state.value,
                trailers=trailers
            )

        from datetime import datetime
        return StatusOutput(
            tree=tree.to_dict(),
            branch=branch,
            completed=list(completed),
            tasks=tasks,
            generated_at=datetime.now().isoformat()
        )

    @app.get("/api/reports", response_model=ReportsOutput)
    async def get_reports():
        """Get task execution reports."""
        if not report_dir.exists():
            return ReportsOutput(reports=[], summary={})

        reports = []
        for fname in sorted(report_dir.glob("*.json")):
            try:
                import json
                data = json.loads(fname.read_text())
                reports.append(Report(**data))
            except Exception:
                pass

        summary = {
            "total": len(reports),
            "passed": sum(1 for r in reports if r.result == "pass"),
            "failed": sum(1 for r in reports if r.result == "fail"),
            "avg_retries": sum(r.retries for r in reports) / len(reports) if reports else 0
        }

        return ReportsOutput(reports=reports, summary=summary)

    @app.get("/api/logs", response_model=LogsOutput)
    async def get_logs():
        """Get task execution logs metadata."""
        if not log_dir.exists():
            return LogsOutput(logs={}, summary={})

        logs = {}
        for fname in sorted(log_dir.glob("*.log")):
            import re
            m = re.match(r'(?:M\d+-)?(\w\d+)_(\w+)_(\d{8}T\d{6})\.log', fname.name)
            if m:
                task_id, phase, timestamp = m.groups()
                size = fname.stat().st_size
                if task_id not in logs:
                    logs[task_id] = []
                logs[task_id].append(LogEntry(
                    task_id=task_id,
                    phase=phase,
                    timestamp=timestamp,
                    filename=fname.name,
                    size=size
                ))

        # Sort by timestamp
        for task_id in logs:
            logs[task_id].sort(key=lambda e: e.timestamp)

        summary = {
            "total_tasks": len(logs),
            "total_entries": sum(len(entries) for entries in logs.values()),
            "phase_counts": {
                "implement": sum(1 for entries in logs.values() for e in entries if e.phase == "implement"),
                "review": sum(1 for entries in logs.values() for e in entries if e.phase == "review"),
                "test": sum(1 for entries in logs.values() for e in entries if e.phase == "test")
            }
        }

        return LogsOutput(logs=logs, summary=summary)

    @app.get("/api/log/{filename}", response_class=PlainTextResponse)
    async def get_log_file(filename: str):
        """Get individual log file content securely."""
        if not log_dir.exists():
            from fastapi import HTTPException
            raise HTTPException(status_code=404)

        # Security: prevent directory traversal
        log_file = (log_dir / filename).resolve()
        if not str(log_file).startswith(str(log_dir.resolve())):
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Access denied")

        if not log_file.exists():
            from fastapi import HTTPException
            raise HTTPException(status_code=404)

        return log_file.read_text()

    return app


def start_dashboard(tree_path: Path, report_dir: Optional[Path], log_dir: Optional[Path], port: int):
    """Start the dashboard FastAPI server with uvicorn."""
    import uvicorn

    app = create_app(tree_path, report_dir, log_dir)

    console.print(f"[green]Dashboard:[/green] http://localhost:{port}")
    console.print(f"  Tree:    {tree_path}")
    console.print(f"  Reports: {report_dir}")
    console.print(f"  Logs:    {log_dir}")
    console.print(f"\n[dim]Press Ctrl+C to stop[/dim]")

    uvicorn.run(app, host="localhost", port=port, log_level="warning")
```

### 2.4 Update pyproject.toml Dependencies

Add to `pyproject.toml`:

```toml
[project.dependencies]
# ... existing dependencies ...
fastapi = "^0.115.0"
uvicorn = {extras = ["standard"], version = "^0.32.0"}
```

### 2.5 Extract HTML Template

**Remove write/control features:**
- Remove "Run Tests" button and associated JavaScript
- Remove any restart/control functionality
- Make dashboard distinctly read-only

**Updated endpoints:**
- `/api/status` - Task status data (from CLI functions)
- `/api/reports` - Report summaries
- `/api/logs` - Log metadata
- `/api/log/<filename>` - Individual log file content

---

## Phase 3: Integrate Dashboard into CLI

### 3.1 Add `arborist dashboard` Command

Add to `src/agent_arborist/cli.py`:

```python
@main.command()
@click.option("--tree", "tree_path", type=click.Path(exists=True, path_type=Path), default=None,
              help="Path to task-tree.json")
@click.option("--port", type=int, default=8484,
              help="Port for dashboard server (default: 8484)")
@click.option("--report-dir", type=click.Path(path_type=Path), default=None,
              help="Directory for reports (default: next to task tree)")
@click.option("--log-dir", type=click.Path(path_type=Path), default=None,
              help="Directory for logs (default: next to task tree)")
def dashboard(tree_path, port, report_dir, log_dir):
    """Start read-only monitoring dashboard for task execution."""
    from agent_arborist.dashboard.server import start_dashboard

    # Resolve tree path
    target = target_repo.resolve() if target_repo else Path(_default_repo()).resolve()
    branch = git_current_branch(target)
    if tree_path is None:
        tree_path = Path("specs") / branch / "task-tree.json"

    tree_path = Path(tree_path).resolve()
    if not tree_path.exists():
        console.print(f"[red]Error:[/red] {tree_path} not found")
        sys.exit(1)

    start_dashboard(tree_path, report_dir, log_dir, port)
```

### 3.2 Update Help Text

Add `dashboard` to `arborist --help` output:

```
Commands:
  init        Initialize .arborist/ directory
  build       Build task tree from spec
  garden      Execute a single task
  gardener    Run the gardener loop
  status      Show task status (--format json available)
  inspect     Inspect a single task (--format json available)
  reports     List task execution reports (--format json available)
  logs        List task execution logs (--format json available)
  dashboard   Start read-only monitoring dashboard
```

---

## Phase 4: Create Tests

### 4.1 Test JSON Output Format

Create `tests/test_json_output.py`:

```python
def test_status_json_output(tmp_path, fixture_tree):
    """Test that status --format json outputs valid JSON."""
    # Setup git repo with some commits
    # Run arborist status --format json
    # Parse output
    # Assert structure matches schema

def test_reports_json_output(tmp_path, fixture_tree):
    """Test that reports --format json outputs valid JSON."""
    # Create report files
    # Run arborist reports --format json
    # Assert structure

def test_logs_json_output(tmp_path, fixture_tree):
    """Test that logs --format json outputs valid JSON."""
    # Create log files
    # Run arborist logs --format json
    # Assert structure
```

### 4.2 Test Dashboard HTTP Server

Create `tests/test_dashboard.py`:

```python
from fastapi.testclient import TestClient
from agent_arborist.dashboard.server import create_app

def test_dashboard_serves_html(tmp_path, fixture_tree):
    """Test that dashboard serves HTML page."""
    tree_path = tmp_path / "task-tree.json"
    # Write fixture tree to tree_path

    app = create_app(tree_path, None, None)
    client = TestClient(app)

    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Arborist Run Dashboard" in response.text

def test_dashboard_status_endpoint(tmp_path, fixture_tree):
    """Test /api/status endpoint returns valid JSON."""
    tree_path = tmp_path / "task-tree.json"
    # Write fixture tree

    # Create some git commits with trailers
    # ...

    app = create_app(tree_path, None, None)
    client = TestClient(app)

    response = client.get("/api/status")
    assert response.status_code == 200

    data = response.json()
    assert "tree" in data
    assert "branch" in data
    assert "completed" in data
    assert isinstance(data["tasks"], dict)

def test_dashboard_reports_endpoint(tmp_path, fixture_tree):
    """Test /api/reports endpoint."""
    tree_path = tmp_path / "task-tree.json"
    report_dir = tmp_path / "reports"
    report_dir.mkdir()

    # Create sample report
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

def test_dashboard_log_file_security(tmp_path, fixture_tree):
    """Test that log file serving prevents directory traversal."""
    tree_path = tmp_path / "task-tree.json"
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    # Create a log file
    log_file = log_dir / "T001_implement_20250101T120000.log"
    log_file.write_text("test log content")

    app = create_app(tree_path, None, log_dir)
    client = TestClient(app)

    # Valid log file should work
    response = client.get("/api/log/T001_implement_20250101T120000.log")
    assert response.status_code == 200
    assert "test log content" in response.text

    # Directory traversal attempts should fail
    response = client.get("/api/log/../etc/passwd")
    assert response.status_code == 403

    response = client.get("/api/log/../../test.txt")
    assert response.status_code == 403
```

---

## Phase 5: Documentation

### 5.1 Update README

Add section on monitoring:

```markdown
## Monitoring

### Dashboard

Start a read-only monitoring dashboard:

```bash
arborist dashboard [--port 8484] [--tree PATH]
```

The dashboard shows:
- Overall progress
- Milestone completion
- Task attempt counts
- Duration distribution
- Full task tree with status
- Timeline view

Open http://localhost:8484 in your browser.

### Command-Line Monitoring

All monitoring data is also available via CLI commands:

```bash
# Task status
arborist status --format json

# Execution reports
arborist reports --format json

# Execution logs
arborist logs --format json

# Detailed task inspection
arborist inspect T003 --format json
```
```

### 5.2 Create `docs/manual/dashboard.md`

Document:
- Dashboard features
- API endpoints
- CLI equivalents
- Security notes (read-only design)
```

---

## Implementation Order

1. **Phase 1** - Add JSON output to existing CLI commands (2 days)
   - 1.1: `status --format json`
   - 1.2: `reports` command
   - 1.3: `logs` command
   - 1.4: `inspect --format json`

2. **Phase 2** - Create dashboard module (3 days)
   - 2.1: Create module structure
   - 2.2: Extract HTML template
   - 2.3: Create HTTP server
   - 2.4: Remove write features, make read-only

3. **Phase 3** - Integrate into CLI (1 day)
   - 3.1: Add `arborist dashboard` command

4. **Phase 4** - Test coverage (2 days)
   - 4.1: Test JSON outputs
   - 4.2: Test dashboard server

5. **Phase 5** - Documentation (1 day)
   - 5.1: Update README
   - 5.2: Create manual page

**Total estimated effort: 9 days**

---

## Key Design Decisions

### Decision 1: Use FastAPI for Dashboard Server

**Choice:** Use FastAPI + Uvicorn for the dashboard HTTP server.

**Reasoning:**
- Automatic JSON serialization with Pydantic models
- Type-safe API with runtime validation
- Clean, declarative routing with decorators
- Built-in OpenAPI documentation
- Industry standard, well-maintained
- Much simpler code than manual stdlib HTTP handling
- Easy testing with TestClient

**Trade-off:**
- Adds 2 dependencies: `fastapi` and `uvicorn[standard]`
- But significantly improves code quality and maintainability

### Decision 2: CLI-First Data Access

**Choice:** All dashboard data must be available via CLI with `--format json`.

**Reasoning:**
- Enables automation and scripting
- No hidden data sources
- Dashboard is just another client of CLI data

### Decision 3: Read-Only Dashboard

**Choice:** Dashboard cannot trigger actions (run tests, restart, etc.)

**Reasoning:**
- Separation of concerns: CLI = control, Dashboard = observation
- Simplifies security model
- Prevents accidental actions via web UI

### Decision 4: HTML Template as Separate File

**Choice:** Extract HTML from Python string to template file.

**Reasoning:**
- Easier to maintain and edit UI
- Better for code review
- Potential for future theming/customization

### Decision 5: No Real-Time Execution Control

**Choice:** Dashboard does not interact with running `gardener` process.

**Reasoning:**
- `gardener` runs independently
- Dashboard reads from git commit trailers, reports, logs
- Simple, decoupled architecture

---

## Open Questions

1. Should the dashboard auto-refresh periodically? (Current PR does every 5s)
2. Should we use Jinja2 for templates or simple string formatting?
3. Should log file serving require authentication? (Currently runs on localhost only)
4. Should the dashboard serve static assets (CSS, JS) as separate files?

---

## Testing Strategy

### Unit Tests
- JSON output validators
- Report parsing logic
- Log parsing logic
- HTTP handler logic

### Integration Tests
- Full CLI command execution with JSON output
- Dashboard server startup/shutdown
- HTTP endpoint responses
- Log file security

### Manual Testing
- Visual inspection of dashboard
- Cross-browser compatibility
- Load testing with many tasks/logs

---

## Success Criteria

- [ ] CLI commands support `--format json` output
- [ ] `arborist reports` and `arborist logs` commands exist and work
- [ ] `arborist dashboard` starts successfully
- [ ] Dashboard displays all relevant data (progress, milestones, attempts, etc.)
- [ ] Dashboard is read-only (no write actions)
- [ ] All tests pass
- [ ] Documentation complete
- [ ] Dashboard uses FastAPI with proper Pydantic schemas
- [ ] Dashboard uses same functions as CLI (no subprocess abuse)
- [ ] Added `fastapi` and `uvicorn[standard]` dependencies