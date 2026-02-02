"""FastAPI application for the Arborist dashboard.

Provides REST API endpoints for DAG run visualization.
"""

from pathlib import Path
from typing import Optional

try:
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import HTMLResponse, JSONResponse, Response
    from fastapi.staticfiles import StaticFiles
    import uvicorn
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


def create_app(dagu_home: Optional[Path] = None) -> "FastAPI":
    """Create the FastAPI application.

    Args:
        dagu_home: Path to dagu home directory (auto-detected if None)

    Returns:
        Configured FastAPI application
    """
    if not HAS_FASTAPI:
        raise ImportError(
            "Dashboard requires fastapi and uvicorn. "
            "Install with: pip install agent-arborist[dashboard]"
        )

    from agent_arborist.home import get_dagu_home
    from agent_arborist.dagu_runs import list_dag_runs, load_dag_run
    from agent_arborist.viz import (
        build_metrics_tree,
        aggregate_tree,
        render_tree,
        render_metrics,
        AggregationStrategy,
        OutputFormat,
    )

    if dagu_home is None:
        dagu_home = get_dagu_home()

    app = FastAPI(
        title="Arborist Dashboard",
        description="Visualization dashboard for DAG execution metrics",
        version="0.6.0",
    )

    # CORS middleware for local development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Serve static files
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/")
    async def root():
        """Serve the dashboard HTML."""
        html_file = static_dir / "index.html"
        if html_file.exists():
            return HTMLResponse(content=html_file.read_text())
        # Return inline dashboard if no static file
        return HTMLResponse(content=get_inline_dashboard())

    @app.get("/api/status")
    async def status():
        """Get server status."""
        runs = list_dag_runs(dagu_home, limit=100)
        return {
            "status": "ok",
            "version": "0.6.0",
            "dagu_home": str(dagu_home),
            "total_runs": len(runs),
        }

    @app.get("/api/runs")
    async def get_runs(
        dag_name: Optional[str] = Query(None, description="Filter by DAG name"),
        status: Optional[str] = Query(None, description="Filter by status"),
        limit: int = Query(50, description="Maximum results"),
    ):
        """List available DAG runs."""
        runs = list_dag_runs(dagu_home, dag_name=dag_name, limit=limit)

        result = []
        for run in runs:
            # Get status from latest attempt
            run_status = "pending"
            started_at = None
            finished_at = None
            duration_seconds = None

            if run.latest_attempt:
                run_status = run.latest_attempt.status.to_name() if run.latest_attempt.status else "pending"
                started_at = run.latest_attempt.started_at
                finished_at = run.latest_attempt.finished_at
                if started_at and finished_at:
                    duration_seconds = (finished_at - started_at).total_seconds()

            if status and run_status != status:
                continue

            result.append({
                "dag_name": run.dag_name,
                "run_id": run.run_id,
                "status": run_status,
                "started_at": started_at.isoformat() if started_at else None,
                "finished_at": finished_at.isoformat() if finished_at else None,
                "duration_seconds": duration_seconds,
            })

        return {"runs": result}

    @app.get("/api/runs/{dag_name}/{run_id}/tree")
    async def get_tree(
        dag_name: str,
        run_id: str,
        aggregation: str = Query("totals", description="Aggregation strategy"),
        expand: bool = Query(True, description="Expand sub-DAGs"),
    ):
        """Get the metrics tree for a run."""
        try:
            dag_run = load_dag_run(
                dagu_home,
                dag_name,
                run_id,
                expand_subdags=expand,
                include_outputs=True,
            )
        except Exception as e:
            raise HTTPException(status_code=404, detail=f"Run not found: {e}")

        tree = build_metrics_tree(dag_run)
        strategy = AggregationStrategy(aggregation)
        tree = aggregate_tree(tree, strategy=strategy)

        return tree.to_dict()

    @app.get("/api/runs/{dag_name}/{run_id}/render")
    async def render_run(
        dag_name: str,
        run_id: str,
        format: str = Query("svg", description="Output format"),
        aggregation: str = Query("totals", description="Aggregation strategy"),
        color_by: str = Query("status", description="Color scheme"),
        show_metrics: bool = Query(False, description="Show inline metrics"),
        expand: bool = Query(True, description="Expand sub-DAGs"),
    ):
        """Render visualization for a run."""
        try:
            dag_run = load_dag_run(
                dagu_home,
                dag_name,
                run_id,
                expand_subdags=expand,
                include_outputs=True,
            )
        except Exception as e:
            raise HTTPException(status_code=404, detail=f"Run not found: {e}")

        tree = build_metrics_tree(dag_run)
        strategy = AggregationStrategy(aggregation)
        tree = aggregate_tree(tree, strategy=strategy)

        format_map = {
            "svg": OutputFormat.SVG,
            "json": OutputFormat.JSON,
            "ascii": OutputFormat.ASCII,
        }
        fmt = format_map.get(format, OutputFormat.SVG)

        output = render_tree(
            tree,
            format=fmt,
            color_by=color_by,
            show_metrics=show_metrics,
        )

        if format == "svg":
            return Response(content=output, media_type="image/svg+xml")
        elif format == "json":
            return JSONResponse(content=output if isinstance(output, dict) else {"tree": output})
        else:
            return Response(content=output, media_type="text/plain")

    @app.get("/api/runs/{dag_name}/{run_id}/metrics")
    async def get_metrics(
        dag_name: str,
        run_id: str,
        aggregation: str = Query("totals", description="Aggregation strategy"),
        expand: bool = Query(True, description="Expand sub-DAGs"),
    ):
        """Get metrics summary for a run."""
        try:
            dag_run = load_dag_run(
                dagu_home,
                dag_name,
                run_id,
                expand_subdags=expand,
                include_outputs=True,
            )
        except Exception as e:
            raise HTTPException(status_code=404, detail=f"Run not found: {e}")

        tree = build_metrics_tree(dag_run)
        strategy = AggregationStrategy(aggregation)
        tree = aggregate_tree(tree, strategy=strategy)

        return {
            "run_id": run_id,
            "dag_name": dag_name,
            "summary": tree.get_summary(),
        }

    return app


def run_server(host: str = "127.0.0.1", port: int = 8080, dagu_home: Optional[Path] = None):
    """Run the dashboard server.

    Args:
        host: Host to bind to
        port: Port to run on
        dagu_home: Path to dagu home (auto-detected if None)
    """
    if not HAS_FASTAPI:
        raise ImportError(
            "Dashboard requires fastapi and uvicorn. "
            "Install with: pip install agent-arborist[dashboard]"
        )

    app = create_app(dagu_home)
    uvicorn.run(app, host=host, port=port)


def get_inline_dashboard() -> str:
    """Return inline HTML dashboard content."""
    return '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Arborist Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <style>
        .run-card:hover { transform: translateY(-2px); transition: transform 0.2s; }
        .status-badge { padding: 2px 8px; border-radius: 9999px; font-size: 12px; }
        .status-success { background: #dcfce7; color: #166534; }
        .status-failed { background: #fee2e2; color: #991b1b; }
        .status-running { background: #dbeafe; color: #1e40af; }
        .status-pending { background: #f3f4f6; color: #4b5563; }
        .tree-container { overflow: auto; background: #f8fafc; border-radius: 8px; }
        .node-tooltip { position: absolute; background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); z-index: 100; }
    </style>
</head>
<body class="bg-gray-100 min-h-screen">
    <div class="container mx-auto px-4 py-8">
        <header class="mb-8">
            <h1 class="text-3xl font-bold text-gray-900">Arborist Dashboard</h1>
            <p class="text-gray-600 mt-2">DAG execution visualization and metrics</p>
        </header>

        <div class="grid grid-cols-12 gap-6">
            <!-- Run List Panel -->
            <div class="col-span-4 bg-white rounded-lg shadow p-4">
                <h2 class="text-lg font-semibold mb-4">DAG Runs</h2>
                <div id="run-list" class="space-y-2">
                    <p class="text-gray-500">Loading...</p>
                </div>
            </div>

            <!-- Visualization Panel -->
            <div class="col-span-8 bg-white rounded-lg shadow p-4">
                <div class="flex justify-between items-center mb-4">
                    <h2 class="text-lg font-semibold">Dendrogram</h2>
                    <div class="flex gap-2">
                        <select id="color-by" class="text-sm border rounded px-2 py-1">
                            <option value="status">Color by Status</option>
                            <option value="quality">Color by Quality</option>
                            <option value="pass-rate">Color by Pass Rate</option>
                        </select>
                        <label class="flex items-center text-sm">
                            <input type="checkbox" id="show-metrics" class="mr-1">
                            Show Metrics
                        </label>
                    </div>
                </div>
                <div id="tree-container" class="tree-container h-96">
                    <p class="text-gray-500 p-4">Select a run to view its tree</p>
                </div>

                <!-- Metrics Summary -->
                <div id="metrics-panel" class="mt-4 hidden">
                    <h3 class="text-md font-semibold mb-2">Summary</h3>
                    <div id="metrics-content" class="grid grid-cols-4 gap-4 text-sm"></div>
                </div>
            </div>
        </div>

        <!-- Tooltip -->
        <div id="tooltip" class="node-tooltip hidden"></div>
    </div>

    <script>
        let currentRun = null;

        // Fetch and display run list
        async function loadRuns() {
            const response = await fetch('/api/runs');
            const data = await response.json();

            const container = document.getElementById('run-list');
            container.innerHTML = '';

            data.runs.forEach(run => {
                const card = document.createElement('div');
                card.className = 'run-card p-3 border rounded-lg cursor-pointer hover:border-blue-500';
                card.innerHTML = `
                    <div class="flex justify-between items-center">
                        <span class="font-medium">${run.dag_name}</span>
                        <span class="status-badge status-${run.status}">${run.status}</span>
                    </div>
                    <div class="text-xs text-gray-500 mt-1">
                        ${run.run_id.substring(0, 8)} | ${formatDuration(run.duration_seconds)}
                    </div>
                `;
                card.onclick = () => loadTree(run.dag_name, run.run_id);
                container.appendChild(card);
            });
        }

        // Load and display tree
        async function loadTree(dagName, runId) {
            currentRun = { dagName, runId };

            const colorBy = document.getElementById('color-by').value;
            const showMetrics = document.getElementById('show-metrics').checked;

            // Fetch SVG
            const svgUrl = `/api/runs/${dagName}/${runId}/render?format=svg&color_by=${colorBy}&show_metrics=${showMetrics}`;
            const response = await fetch(svgUrl);
            const svg = await response.text();

            const container = document.getElementById('tree-container');
            container.innerHTML = svg;

            // Add interactivity
            setupTreeInteractivity();

            // Load metrics
            await loadMetrics(dagName, runId);
        }

        // Setup tree interactivity
        function setupTreeInteractivity() {
            const nodes = document.querySelectorAll('.node');
            const tooltip = document.getElementById('tooltip');

            nodes.forEach(node => {
                node.style.cursor = 'pointer';

                node.addEventListener('mouseenter', (e) => {
                    const id = node.getAttribute('data-id');
                    tooltip.innerHTML = `<strong>${id}</strong>`;
                    tooltip.classList.remove('hidden');
                    tooltip.style.left = e.pageX + 10 + 'px';
                    tooltip.style.top = e.pageY + 10 + 'px';
                });

                node.addEventListener('mouseleave', () => {
                    tooltip.classList.add('hidden');
                });
            });
        }

        // Load metrics summary
        async function loadMetrics(dagName, runId) {
            const response = await fetch(`/api/runs/${dagName}/${runId}/metrics`);
            const data = await response.json();

            const panel = document.getElementById('metrics-panel');
            const content = document.getElementById('metrics-content');

            const summary = data.summary || {};
            content.innerHTML = `
                <div class="bg-gray-50 p-2 rounded">
                    <div class="text-gray-500">Tests</div>
                    <div class="font-bold">${summary.total_tests_run || 0}</div>
                </div>
                <div class="bg-green-50 p-2 rounded">
                    <div class="text-gray-500">Passed</div>
                    <div class="font-bold text-green-600">${summary.total_tests_passed || 0}</div>
                </div>
                <div class="bg-red-50 p-2 rounded">
                    <div class="text-gray-500">Failed</div>
                    <div class="font-bold text-red-600">${summary.total_tests_failed || 0}</div>
                </div>
                <div class="bg-blue-50 p-2 rounded">
                    <div class="text-gray-500">Duration</div>
                    <div class="font-bold">${summary.total_duration || '-'}</div>
                </div>
            `;

            panel.classList.remove('hidden');
        }

        // Format duration
        function formatDuration(seconds) {
            if (!seconds) return '-';
            if (seconds < 60) return `${Math.floor(seconds)}s`;
            const mins = Math.floor(seconds / 60);
            const secs = Math.floor(seconds % 60);
            return `${mins}m ${secs}s`;
        }

        // Event listeners
        document.getElementById('color-by').addEventListener('change', () => {
            if (currentRun) loadTree(currentRun.dagName, currentRun.runId);
        });

        document.getElementById('show-metrics').addEventListener('change', () => {
            if (currentRun) loadTree(currentRun.dagName, currentRun.runId);
        });

        // Initial load
        loadRuns();
    </script>
</body>
</html>'''
