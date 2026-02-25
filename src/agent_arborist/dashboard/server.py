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

"""Dashboard FastAPI server - read-only monitoring interface."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi import HTTPException
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
import json

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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    tree = TaskTree.from_dict(json.loads(tree_path.read_text()))
    target = Path.cwd()
    branch = git_current_branch(target)

    if report_dir is None:
        report_dir = tree_path.parent / "reports"
    if log_dir is None:
        log_dir = tree_path.parent / "logs"

    # Make sure they're absolute paths
    report_dir = report_dir.resolve() if report_dir else None
    log_dir = log_dir.resolve() if log_dir else None

    @app.get("/", response_class=HTMLResponse)
    async def serve_dashboard():
        """Serve the dashboard HTML page."""
        template_path = Path(__file__).parent / "templates" / "dashboard.html"
        if not template_path.exists():
            return "<html><body><h1>Dashboard template not found</h1></body></html>"
        return template_path.read_text()

    @app.get("/api/status", response_model=StatusOutput)
    async def get_status() -> StatusOutput:
        """Get task status data."""
        completed = scan_completed_tasks(tree, target, branch=branch)

        tasks: Dict[str, TaskStateData] = {}
        for node_id, node in tree.nodes.items():
            trailers = get_task_trailers("HEAD", node_id, target, current_branch=branch)
            state = task_state_from_trailers(trailers)
            tasks[node_id] = TaskStateData(
                id=node_id,
                name=node.name,
                state=state.value,
                trailers=trailers
            )

        return StatusOutput(
            tree=tree.to_dict(),
            branch=branch,
            completed=list(completed),
            tasks=tasks,
            generated_at=datetime.now().isoformat()
        )

    @app.get("/api/reports", response_model=ReportsOutput)
    async def get_reports() -> ReportsOutput:
        """Get task execution reports."""
        if not report_dir.exists():
            return ReportsOutput(reports=[], summary={"total": 0, "passed": 0, "failed": 0, "avg_retries": 0})

        reports: List[Report] = []
        for fname in sorted(report_dir.glob("*.json")):
            try:
                data = json.loads(fname.read_text())
                reports.append(Report(**data))
            except Exception:
                pass

        summary = {
            "total": len(reports),
            "passed": sum(1 for r in reports if r.result == "pass"),
            "failed": sum(1 for r in reports if r.result == "fail"),
            "avg_retries": round(sum(r.retries for r in reports) / len(reports), 2) if reports else 0
        }

        return ReportsOutput(reports=reports, summary=summary)

    @app.get("/api/logs", response_model=LogsOutput)
    async def get_logs() -> LogsOutput:
        """Get task execution logs metadata."""
        import re

        if not log_dir.exists():
            return LogsOutput(
                logs={},
                summary={
                    "total_tasks": 0,
                    "total_entries": 0,
                    "implement": 0,
                    "review": 0,
                    "test": 0
                }
            )

        logs: Dict[str, List[LogEntry]] = {}
        for fname in sorted(log_dir.glob("*.log")):
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

        for task_id in logs:
            logs[task_id].sort(key=lambda e: e.timestamp)

        summary = {
            "total_tasks": len(logs),
            "total_entries": sum(len(entries) for entries in logs.values()),
            "implement": sum(1 for entries in logs.values() for e in entries if e.phase == "implement"),
            "review": sum(1 for entries in logs.values() for e in entries if e.phase == "review"),
            "test": sum(1 for entries in logs.values() for e in entries if e.phase == "test")
        }

        return LogsOutput(logs=logs, summary=summary)

    @app.get("/api/log/{filename:path}", response_class=PlainTextResponse)
    async def get_log_file(filename: str) -> str:
        """Get individual log file content securely."""
        if not log_dir.exists():
            raise HTTPException(status_code=404, detail="Logs directory not found")

        log_file = (log_dir / filename).resolve()
        log_dir_resolved = str(log_dir.resolve())

        if not str(log_file).startswith(log_dir_resolved):
            raise HTTPException(status_code=403, detail="Access denied: path traversal not allowed")

        if not log_file.exists() or not log_file.is_file():
            raise HTTPException(status_code=404, detail="Log file not found")

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
    console.print("\n[dim]Press Ctrl+C to stop[/dim]")

    uvicorn.run(app, host="localhost", port=port, log_level="warning")