# Dashboard

The read-only monitoring dashboard provides real-time visibility into task execution progress.

## Starting the Dashboard

```bash
arborist dashboard
```

Options:
- `--tree PATH`: Path to task-tree.json file (default: `specs/<branch>/task-tree.json`)
- `--port PORT`: Port to serve on (default: 8080)
- `--report-dir DIR`: Path to reports directory (default: `<tree-parent>/reports`)
- `--log-dir DIR`: Path to logs directory (default: `<tree-parent>/logs`)

Example:

```bash
arborist dashboard --tree specs/main/task-tree.json --port 9000
```

Once started, access the dashboard at `http://localhost:8080`.

Press `Ctrl+C` to stop the dashboard.

## Dashboard Features

The dashboard provides read-only access to:

- **Task Status**: View progress of all tasks in the tree
- **Execution Reports**: Test results and retry counts
- **Log Files**: Browse implementation, review, and test logs

## CLI-First Monitoring

All data visible in the dashboard is also available via CLI commands with JSON output:

```bash
arborist status --format json
arborist reports --format json
arborist logs --format json
arborist inspect T001 --format json
```

These commands return structured JSON that can be consumed by scripts or other tools.

## API Endpoints

The dashboard uses FastAPI and exposes the following endpoints:

- `GET /` - Dashboard HTML interface
- `GET /api/status` - Task status data
- `GET /api/reports` - Execution reports
- `GET /api/logs` - Log metadata
- `GET /api/log/{filename}` - Individual log file (with path security)

## Security

- The dashboard is read-only (no control actions)
- Log file access includes path traversal protection
- Runs on localhost by default