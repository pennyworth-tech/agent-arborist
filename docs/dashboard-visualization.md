# Arborist Dashboard Specification

## Overview

The Arborist Dashboard provides an architect's view of DAG execution, displaying hierarchical metrics as interactive dendrograms with aggregated roll-ups. It extracts test results, code quality scores, and task completion metrics from DAG outputs and visualizes them with color-coded status indicators at every level of the task tree.

### Goals

1. **Visibility**: See test metrics (run/pass/skip/fail) at every node in the task hierarchy
2. **Quality tracking**: LLM-graded code quality, task completion, and test coverage metrics
3. **Dendrogram visualization**: Interactive tree view with metrics rolling up from leaves to root
4. **Flexible aggregation**: Support totals (with deduplication), averages, and custom aggregation strategies
5. **CLI-first design**: All core functionality available via CLI commands, not just the dashboard
6. **Simple deployment**: `arborist dashboard` CLI command launches local server

### Non-Goals (V1)

- Real-time WebSocket streaming (use polling instead)
- Multi-user authentication
- Persistent database (use DAG run files directly)
- Deployment to cloud infrastructure

---

## Architecture

The architecture follows a **core library pattern** where all data processing, metrics extraction, aggregation, and visualization generation happens in a shared Python library. Both CLI commands and the dashboard API consume this library.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              INTERFACES                                      │
│  ┌────────────────────────────┐     ┌────────────────────────────────────┐  │
│  │      CLI Commands          │     │         Dashboard API              │  │
│  │  arborist viz tree         │     │         (FastAPI)                  │  │
│  │  arborist viz metrics      │     │  GET /api/runs/{id}/tree           │  │
│  │  arborist viz export       │     │  GET /api/runs/{id}/metrics        │  │
│  │  arborist dashboard        │     │  GET /api/runs/{id}/render         │  │
│  └────────────┬───────────────┘     └──────────────┬─────────────────────┘  │
│               │                                     │                        │
│               └──────────────┬──────────────────────┘                        │
│                              ▼                                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                         CORE LIBRARY                                         │
│                   (agent_arborist.viz)                                       │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────────┐  │
│  │    Metrics      │  │   Aggregation   │  │       Renderers             │  │
│  │    Extractor    │  │     Engine      │  │  (technology-agnostic)      │  │
│  │                 │  │                 │  │                             │  │
│  │  - test results │  │  - totals       │  │  - DendrogramRenderer       │  │
│  │  - quality      │  │  - averages     │  │  - MetricsRenderer          │  │
│  │  - coverage     │  │  - dedupe       │  │  - SummaryRenderer          │  │
│  │  - timing       │  │  - custom       │  │  - TimelineRenderer         │  │
│  └────────┬────────┘  └────────┬────────┘  └──────────────┬──────────────┘  │
│           │                    │                          │                  │
│           └────────────────────┼──────────────────────────┘                  │
│                                ▼                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                        Tree Builder                                   │   │
│  │         (builds MetricsTree from DagRun + extracted metrics)          │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                │                                             │
├────────────────────────────────┼────────────────────────────────────────────┤
│                                ▼                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    DAG Run Loader (existing)                          │   │
│  │                       dagu_runs.py                                    │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                │                                             │
│                                ▼                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                   .arborist/dagu/data/                                │   │
│  │                   (existing DAG run files)                            │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘

                              FRONTEND
┌─────────────────────────────────────────────────────────────────────────────┐
│                     React + D3 Frontend                                      │
│                  (display + configuration only)                              │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────────────────┐ │
│  │  Dendrogram  │  │   Metrics    │  │      Run List / Config             │ │
│  │  Display     │  │   Display    │  │      Controls                      │ │
│  └──────────────┘  └──────────────┘  └────────────────────────────────────┘ │
│                                                                              │
│  Consumes: pre-rendered SVG, JSON data structures, image URLs               │
│  Sends: configuration changes, aggregation preferences                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Design Principles

1. **Core Library First**: All metrics extraction, aggregation, and visualization generation lives in `agent_arborist.viz` module
2. **CLI Parity**: Every capability exposed via API is also available as a CLI command
3. **Technology-Agnostic Renderers**: Visualization renderers output to multiple formats (SVG, PNG, JSON, ASCII)
4. **Thin API Layer**: FastAPI endpoints are thin wrappers that call core library functions
5. **Thin Frontend**: React app focuses on display and configuration, not data processing

### CLI-First Workflow

The CLI is a first-class citizen, not an afterthought. Common workflows:

```bash
# Quick check after a DAG run
arborist viz tree abc123                    # See tree in terminal
arborist viz metrics abc123                 # See test metrics

# CI/CD integration
arborist viz export $RUN_ID --output-dir ./artifacts/
# Creates: tree.svg, tree.png, metrics.json, summary.md

# Generate reports for review
arborist viz summary abc123 --format markdown > report.md
arborist viz compare abc123 def456 --format html > comparison.html

# Scripting
arborist viz metrics abc123 --format json | jq '.summary.passRate'
```

The dashboard is simply an interactive wrapper that calls the same functions:

| CLI Command | Dashboard Equivalent |
|-------------|---------------------|
| `arborist viz tree <id> --format json` | `GET /api/runs/{id}/tree` |
| `arborist viz tree <id> --format svg` | `GET /api/runs/{id}/render?format=svg` |
| `arborist viz metrics <id>` | `GET /api/runs/{id}/metrics` |
| `arborist dag run-list` | `GET /api/runs` |

### Components

| Component | Technology | Responsibility |
|-----------|------------|----------------|
| Core Library | Python | Metrics extraction, aggregation, tree building, rendering |
| CLI Commands | Click | CLI interface to all core functionality |
| Renderers | Matplotlib/Graphviz/SVG | Generate visualizations in multiple formats |
| API Layer | FastAPI | Thin REST wrapper around core library |
| Frontend | React + D3 | Interactive display and configuration UI |

---

## Data Model

### Metrics Schema

Each node in the task tree carries metrics extracted from step outputs:

```python
@dataclass
class NodeMetrics:
    """Metrics for a single task node."""
    task_id: str

    # Test metrics (from RunTestResult)
    tests_run: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    tests_skipped: int = 0

    # Quality metrics (from hooks)
    code_quality_score: float | None = None      # 1-10 LLM grade
    task_completion_score: float | None = None   # 1-10 LLM grade
    test_coverage_delta: float | None = None     # +/- percentage

    # Execution metrics
    duration_seconds: float = 0
    status: str = "pending"  # pending, running, success, failed, skipped

    # Source tracking for deduplication
    test_file_hashes: set[str] = field(default_factory=set)
```

### Aggregated Metrics Schema

Aggregation happens at each non-leaf node:

```python
@dataclass
class AggregatedMetrics:
    """Rolled-up metrics for a subtree."""
    # Direct metrics from this node
    own: NodeMetrics

    # Aggregated from children (totals with deduplication)
    total_tests_run: int = 0
    total_tests_passed: int = 0
    total_tests_failed: int = 0
    total_tests_skipped: int = 0
    total_duration_seconds: float = 0

    # Averages (for quality scores)
    avg_code_quality: float | None = None
    avg_task_completion: float | None = None
    avg_test_coverage_delta: float | None = None

    # Counts for averaging
    child_count: int = 0
    descendant_count: int = 0

    # Status summary
    children_succeeded: int = 0
    children_failed: int = 0
    children_pending: int = 0
```

### Tree Node Schema (API Response)

```typescript
interface DendrogramNode {
  id: string;                    // Task ID (e.g., "T001")
  name: string;                  // Display name
  status: "pending" | "running" | "success" | "failed" | "skipped";

  // Own metrics
  metrics: {
    testsRun: number;
    testsPassed: number;
    testsFailed: number;
    testsSkipped: number;
    codeQualityScore: number | null;
    taskCompletionScore: number | null;
    testCoverageDelta: number | null;
    durationSeconds: number;
  };

  // Aggregated metrics (only for non-leaf nodes)
  aggregated?: {
    totalTestsRun: number;
    totalTestsPassed: number;
    totalTestsFailed: number;
    totalTestsSkipped: number;
    avgCodeQuality: number | null;
    avgTaskCompletion: number | null;
    avgTestCoverageDelta: number | null;
    totalDurationSeconds: number;
    childCount: number;
    descendantCount: number;
    childrenSucceeded: number;
    childrenFailed: number;
    childrenPending: number;
  };

  // Tree structure
  children?: DendrogramNode[];
}
```

---

## Backend API

The API layer is intentionally thin - each endpoint is a simple wrapper around core library functions.

### Design Principle

```python
# Example: /api/runs/{id}/tree endpoint implementation
@router.get("/runs/{run_id}/tree")
async def get_tree(
    run_id: str,
    aggregation: AggregationStrategy = AggregationStrategy.TOTALS,
    format: OutputFormat = OutputFormat.JSON,
):
    # Thin wrapper - all logic is in core library
    from agent_arborist.viz import visualize_run

    result = visualize_run(
        run_id,
        aggregation=aggregation,
        format=format,
    )

    if format == OutputFormat.JSON:
        return JSONResponse(result)
    elif format == OutputFormat.SVG:
        return Response(result, media_type="image/svg+xml")
    # etc.
```

### Endpoints

#### `GET /api/runs`

List available DAG runs.

**Query Parameters:**
- `dag_name` (optional): Filter by DAG name
- `status` (optional): Filter by status
- `limit` (default: 50): Max results

**Response:**
```json
{
  "runs": [
    {
      "dag_name": "002-my-feature",
      "run_id": "abc123",
      "status": "success",
      "started_at": "2025-01-15T10:30:00Z",
      "finished_at": "2025-01-15T11:45:00Z",
      "duration_seconds": 4500
    }
  ]
}
```

#### `GET /api/runs/{run_id}/tree`

Get the full dendrogram tree with metrics.

**Query Parameters:**
- `aggregation` (default: "totals"): Aggregation strategy
  - `totals`: Sum with deduplication
  - `averages`: Average scores only
  - `both`: Include both

**Response:**
```json
{
  "run_id": "abc123",
  "dag_name": "002-my-feature",
  "root": {
    "id": "root",
    "name": "002-my-feature",
    "status": "success",
    "metrics": { ... },
    "aggregated": { ... },
    "children": [
      {
        "id": "T001",
        "name": "Implement auth module",
        "status": "success",
        "metrics": { ... },
        "children": [ ... ]
      }
    ]
  }
}
```

#### `GET /api/runs/{run_id}/metrics`

Get flat metrics summary for a run.

**Response:**
```json
{
  "run_id": "abc123",
  "summary": {
    "totalTestsRun": 150,
    "totalTestsPassed": 142,
    "totalTestsFailed": 5,
    "totalTestsSkipped": 3,
    "passRate": 0.947,
    "avgCodeQuality": 7.8,
    "avgTaskCompletion": 8.2,
    "totalDuration": "1h 15m"
  },
  "byTask": {
    "T001": { ... },
    "T002": { ... }
  }
}
```

#### `GET /api/runs/{run_id}/node/{task_id}`

Get detailed metrics for a specific node.

**Response:**
```json
{
  "task_id": "T001",
  "description": "Implement auth module",
  "status": "success",
  "metrics": { ... },
  "aggregated": { ... },
  "steps": [
    {
      "name": "pre-sync",
      "status": "success",
      "duration_seconds": 5.2
    },
    {
      "name": "run",
      "status": "success",
      "duration_seconds": 180.5,
      "output": { ... }
    }
  ]
}
```

#### `GET /api/status`

Server health and current state.

**Response:**
```json
{
  "status": "ok",
  "version": "0.6.0",
  "dagu_home": "/path/to/.arborist/dagu",
  "active_runs": 1,
  "total_runs": 42
}
```

---

## Frontend Visualization

### Dendrogram View

The primary visualization is an interactive dendrogram (tree diagram) rendered with D3.js.

#### Features

1. **Hierarchical Layout**
   - Horizontal tree layout (root on left, leaves on right)
   - Collapsible nodes (click to expand/collapse subtrees)
   - Smooth transitions for expand/collapse

2. **Color Coding**
   - Node fill color based on status:
     - Success: Green (`#22c55e`)
     - Failed: Red (`#ef4444`)
     - Running: Blue (`#3b82f6`)
     - Pending: Gray (`#9ca3af`)
     - Skipped: Yellow (`#eab308`)
   - Quality score gradient:
     - 9-10: Bright green
     - 7-8: Light green
     - 5-6: Yellow
     - 3-4: Orange
     - 1-2: Red

3. **Node Display**
   - Task ID badge
   - Status icon
   - Mini metrics bar showing pass/fail ratio
   - Hover tooltip with full metrics

4. **Aggregation Visualization**
   - Parent nodes show rolled-up totals
   - Optional "heatmap" mode colors by aggregated pass rate
   - Progress bars showing proportion passed/failed/skipped

#### Interaction

```
┌─────────────────────────────────────────────────────────────────┐
│  [002-my-feature] Run: abc123                    Status: ✓      │
│  ─────────────────────────────────────────────────────────────  │
│                                                                  │
│  Aggregation: [Totals ▼]  View: [Tree ▼]  Refresh: [5s ▼]       │
│                                                                  │
│  ┌─ root (150 tests, 94.7% pass)                                │
│  │   ├─ T001 (45 tests, 100% pass)  [Quality: 8.5]              │
│  │   │   ├─ T001a (20 tests, 100%)                              │
│  │   │   └─ T001b (25 tests, 100%)                              │
│  │   ├─ T002 (60 tests, 93% pass)   [Quality: 7.2]              │
│  │   │   ├─ T002a (30 tests, 90%)   ← Click to drill down       │
│  │   │   └─ T002b (30 tests, 97%)                               │
│  │   └─ T003 (45 tests, 93% pass)   [Quality: 8.0]              │
│  │       └─ T003a (45 tests, 93%)                               │
│                                                                  │
│  ─────────────────────────────────────────────────────────────  │
│  Selected: T002a  │  30 tests │ 27 pass │ 3 fail │ Quality: 6.8 │
└─────────────────────────────────────────────────────────────────┘
```

### Metrics Panel

Side panel showing detailed metrics for selected node:

- **Test Results**
  - Bar chart: passed/failed/skipped
  - Test file list (if available)
  - Failure details with error messages

- **Quality Scores**
  - Code quality gauge (1-10)
  - Task completion gauge (1-10)
  - Test coverage delta indicator

- **Timing**
  - Step-by-step duration breakdown
  - Timeline visualization

### Run List Browser

List view for selecting DAG runs:

- Filterable by DAG name, status, date range
- Sortable columns
- Quick status badges
- Click to load into dendrogram view

---

## Metrics Extraction

### From Existing Step Results

The `RunTestResult` dataclass already captures test metrics:

```python
@dataclass
class RunTestResult(StepResult):
    test_command: str
    test_count: int
    passed: int
    failed: int
    skipped: int
    duration: float
    output: str
```

**Extraction Location:** `outputs.json` in each DAG run attempt directory.

### Deduplication Strategy

When aggregating test counts, we need to handle potential duplicates (same tests run in multiple tasks):

1. **Hash-based deduplication**: Track test file paths or test names
2. **Conservative approach**: Sum all counts but flag potential overlaps
3. **Configurable**: Allow user to toggle deduplication on/off

```python
def aggregate_tests(nodes: list[NodeMetrics], dedupe: bool = True) -> dict:
    if not dedupe:
        return {
            "total_run": sum(n.tests_run for n in nodes),
            "total_passed": sum(n.tests_passed for n in nodes),
            "total_failed": sum(n.tests_failed for n in nodes),
            "total_skipped": sum(n.tests_skipped for n in nodes),
        }

    # Dedupe by test file hash
    seen_hashes = set()
    totals = {"run": 0, "passed": 0, "failed": 0, "skipped": 0}

    for node in nodes:
        for h in node.test_file_hashes:
            if h not in seen_hashes:
                seen_hashes.add(h)
                totals["run"] += node.tests_per_file.get(h, {}).get("run", 0)
                # ... etc

    return totals
```

---

## Quality Grading Hooks

New hooks to be added for LLM quality evaluation. These integrate with the existing hooks system.

### Hook Definitions

Add to `.arborist/config.json`:

```json
{
  "hooks": {
    "enabled": true,
    "step_definitions": {
      "grade_code_quality": {
        "type": "llm_eval",
        "prompt_file": "prompts/grade_code_quality.md",
        "output_schema": {
          "score": "number",
          "reasoning": "string",
          "suggestions": "array"
        }
      },
      "grade_task_completion": {
        "type": "llm_eval",
        "prompt_file": "prompts/grade_task_completion.md",
        "output_schema": {
          "score": "number",
          "reasoning": "string",
          "gaps": "array"
        }
      },
      "check_test_coverage": {
        "type": "shell",
        "command": "arborist hooks run-coverage-check",
        "output_schema": {
          "coverage_before": "number",
          "coverage_after": "number",
          "delta": "number"
        }
      }
    },
    "injections": {
      "post_task": [
        {"step": "grade_code_quality"},
        {"step": "grade_task_completion"},
        {"step": "check_test_coverage"}
      ]
    }
  }
}
```

### Quality Grading Prompts

#### `prompts/grade_code_quality.md`

```markdown
# Code Quality Evaluation

You are evaluating the quality of code changes in a commit.

## Commit Information
- Task: {{task_id}} - {{task_description}}
- Files changed: {{files_changed}}
- Diff:
```diff
{{git_diff}}
```

## Evaluation Criteria

Rate the code quality from 1-10 based on:

1. **Readability** (0-3 points)
   - Clear variable/function names
   - Logical code organization
   - Appropriate comments where needed

2. **Maintainability** (0-3 points)
   - Follows existing patterns in codebase
   - Avoids code duplication
   - Modular design

3. **Correctness** (0-4 points)
   - Handles edge cases
   - No obvious bugs
   - Appropriate error handling

## Response Format

Respond with JSON:
```json
{
  "score": <1-10>,
  "breakdown": {
    "readability": <0-3>,
    "maintainability": <0-3>,
    "correctness": <0-4>
  },
  "reasoning": "<brief explanation>",
  "suggestions": ["<improvement 1>", "<improvement 2>"]
}
```
```

#### `prompts/grade_task_completion.md`

```markdown
# Task Completion Evaluation

You are evaluating how well a task was completed.

## Task Definition
- ID: {{task_id}}
- Description: {{task_description}}
- Phase: {{phase_name}}

## Implementation Summary
{{commit_message}}

## Files Changed
{{files_changed}}

## Evaluation Criteria

Rate the task completion from 1-10 based on:

1. **Requirements Met** (0-5 points)
   - All described functionality implemented
   - Edge cases considered
   - No missing pieces

2. **Implementation Quality** (0-3 points)
   - Appropriate approach chosen
   - Efficient implementation
   - Well-integrated with existing code

3. **Testing** (0-2 points)
   - Tests added for new functionality
   - Tests pass

## Response Format

Respond with JSON:
```json
{
  "score": <1-10>,
  "breakdown": {
    "requirements_met": <0-5>,
    "implementation_quality": <0-3>,
    "testing": <0-2>
  },
  "reasoning": "<brief explanation>",
  "gaps": ["<missing item 1>", "<missing item 2>"]
}
```
```

### Test Coverage Integration

Shell hook to calculate coverage delta:

```bash
#!/bin/bash
# hooks/check_test_coverage.sh

# Get coverage before changes (from parent branch)
PARENT_BRANCH=$(git rev-parse --abbrev-ref HEAD^)
git stash
git checkout $PARENT_BRANCH
COVERAGE_BEFORE=$(pytest --cov --cov-report=json -q 2>/dev/null | jq '.totals.percent_covered')
git checkout -

git stash pop
COVERAGE_AFTER=$(pytest --cov --cov-report=json -q 2>/dev/null | jq '.totals.percent_covered')

DELTA=$(echo "$COVERAGE_AFTER - $COVERAGE_BEFORE" | bc)

echo "{\"coverage_before\": $COVERAGE_BEFORE, \"coverage_after\": $COVERAGE_AFTER, \"delta\": $DELTA}"
```

---

## CLI Integration

The CLI provides full access to all visualization and metrics capabilities. The `viz` command group is the primary interface.

### Command Group: `arborist viz`

#### `arborist viz tree`

Render the metrics dendrogram for a DAG run.

```bash
# ASCII tree to stdout (default)
arborist viz tree <run-id>

# Export as SVG
arborist viz tree <run-id> --format svg --output tree.svg

# Export as PNG (requires optional deps)
arborist viz tree <run-id> --format png --output tree.png

# Show with specific aggregation
arborist viz tree <run-id> --aggregation totals
arborist viz tree <run-id> --aggregation averages

# Color by metric
arborist viz tree <run-id> --color-by quality
arborist viz tree <run-id> --color-by pass-rate
arborist viz tree <run-id> --color-by status
```

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--format` | `ascii` | Output format: `ascii`, `svg`, `png`, `json` |
| `--output` | stdout | Output file path |
| `--aggregation` | `totals` | Aggregation strategy: `totals`, `averages`, `both` |
| `--color-by` | `status` | Color scheme: `status`, `quality`, `pass-rate` |
| `--depth` | unlimited | Max tree depth to render |
| `--collapse` | none | Collapse nodes below threshold |

#### `arborist viz metrics`

Display or export metrics summary for a DAG run.

```bash
# Table to stdout
arborist viz metrics <run-id>

# JSON export
arborist viz metrics <run-id> --format json --output metrics.json

# CSV export (flat)
arborist viz metrics <run-id> --format csv --output metrics.csv

# Filter to specific task subtree
arborist viz metrics <run-id> --task T002

# Show only specific metric types
arborist viz metrics <run-id> --include tests,quality
```

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--format` | `table` | Output format: `table`, `json`, `csv` |
| `--output` | stdout | Output file path |
| `--task` | root | Subtree root task ID |
| `--include` | all | Metric types: `tests`, `quality`, `timing`, `coverage` |
| `--aggregation` | `totals` | Aggregation strategy |

#### `arborist viz summary`

Generate a summary report for a DAG run.

```bash
# Rich console output
arborist viz summary <run-id>

# Markdown report
arborist viz summary <run-id> --format markdown --output report.md

# HTML report
arborist viz summary <run-id> --format html --output report.html
```

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--format` | `rich` | Output format: `rich`, `markdown`, `html`, `json` |
| `--output` | stdout | Output file path |
| `--include-tree` | false | Embed dendrogram in report |
| `--include-failures` | true | Include failure details |

#### `arborist viz export`

Batch export all visualizations for a DAG run.

```bash
# Export everything to a directory
arborist viz export <run-id> --output-dir ./reports/

# Export with specific formats
arborist viz export <run-id> --output-dir ./reports/ --formats svg,png,json
```

**Output Structure:**
```
reports/
├── tree.svg
├── tree.png
├── metrics.json
├── summary.md
└── timeline.svg
```

#### `arborist viz compare`

Compare metrics between two DAG runs.

```bash
# Compare two runs
arborist viz compare <run-id-1> <run-id-2>

# Export comparison
arborist viz compare <run-id-1> <run-id-2> --format markdown --output comparison.md
```

### Command: `arborist dashboard`

Launch the interactive web dashboard.

```python
@cli.command()
@click.option("--port", "-p", default=8080, help="Port to run dashboard on")
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--open/--no-open", default=True, help="Open browser automatically")
def dashboard(port: int, host: str, open: bool):
    """Launch the Arborist visualization dashboard.

    Starts a local web server with interactive DAG run visualization,
    metrics dendrograms, and quality score tracking.
    """
    from agent_arborist.viz.server import run_server

    console.print(f"[cyan]Starting Arborist Dashboard on http://{host}:{port}[/]")

    if open:
        import webbrowser
        webbrowser.open(f"http://{host}:{port}")

    run_server(host=host, port=port)
```

### Usage Examples

```bash
# Launch dashboard with defaults
arborist dashboard

# Custom port
arborist dashboard --port 3000

# No auto-open browser
arborist dashboard --no-open

# Bind to all interfaces (for Docker)
arborist dashboard --host 0.0.0.0

# Quick CLI visualization workflow
arborist dag run-list                           # Find run ID
arborist viz tree abc123                        # View tree in terminal
arborist viz metrics abc123                     # View metrics table
arborist viz export abc123 --output-dir ./      # Export all formats
```

---

## File Structure

```
src/agent_arborist/
├── viz/                            # CORE LIBRARY (primary location)
│   ├── __init__.py                 # Public API exports
│   │
│   ├── models/                     # Data models
│   │   ├── __init__.py
│   │   ├── metrics.py              # NodeMetrics, AggregatedMetrics
│   │   ├── tree.py                 # MetricsTree, MetricsNode
│   │   └── report.py               # SummaryReport, ComparisonReport
│   │
│   ├── extraction/                 # Metrics extraction
│   │   ├── __init__.py
│   │   ├── extractor.py            # MetricsExtractor base class
│   │   ├── test_metrics.py         # Extract from RunTestResult
│   │   ├── quality_metrics.py      # Extract from quality hooks
│   │   ├── timing_metrics.py       # Extract duration/timing
│   │   └── coverage_metrics.py     # Extract coverage delta
│   │
│   ├── aggregation/                # Aggregation engine
│   │   ├── __init__.py
│   │   ├── aggregator.py           # Aggregator base class + registry
│   │   ├── totals.py               # Sum aggregation with dedupe
│   │   ├── averages.py             # Weighted average aggregation
│   │   └── custom.py               # Custom aggregation support
│   │
│   ├── tree/                       # Tree building
│   │   ├── __init__.py
│   │   ├── builder.py              # TreeBuilder - DagRun → MetricsTree
│   │   └── traversal.py            # Tree traversal utilities
│   │
│   ├── renderers/                  # Visualization renderers
│   │   ├── __init__.py
│   │   ├── base.py                 # Renderer protocol/base class
│   │   ├── ascii.py                # ASCII tree renderer (Rich)
│   │   ├── svg.py                  # SVG dendrogram renderer
│   │   ├── png.py                  # PNG renderer (via SVG + cairosvg)
│   │   ├── json_renderer.py        # JSON export renderer
│   │   ├── markdown.py             # Markdown report renderer
│   │   ├── html.py                 # HTML report renderer
│   │   └── graphviz.py             # Graphviz DOT renderer (optional)
│   │
│   ├── cli/                        # CLI command implementations
│   │   ├── __init__.py
│   │   ├── tree_cmd.py             # `arborist viz tree` implementation
│   │   ├── metrics_cmd.py          # `arborist viz metrics` implementation
│   │   ├── summary_cmd.py          # `arborist viz summary` implementation
│   │   ├── export_cmd.py           # `arborist viz export` implementation
│   │   └── compare_cmd.py          # `arborist viz compare` implementation
│   │
│   └── server/                     # Dashboard server (thin API layer)
│       ├── __init__.py
│       ├── app.py                  # FastAPI app setup
│       ├── routes/
│       │   ├── __init__.py
│       │   ├── runs.py             # /api/runs endpoints
│       │   ├── tree.py             # /api/runs/{id}/tree endpoint
│       │   ├── metrics.py          # /api/runs/{id}/metrics endpoint
│       │   └── render.py           # /api/runs/{id}/render endpoint
│       └── static/                 # Built frontend assets
│           └── ...
│
├── cli.py                          # Add `viz` command group + `dashboard`
└── ...

dashboard-ui/                       # Frontend source (thin display layer)
├── package.json
├── vite.config.ts
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── api/
│   │   └── client.ts               # API client (typed)
│   ├── components/
│   │   ├── Dendrogram/
│   │   │   ├── index.tsx           # Displays SVG from API or renders JSON
│   │   │   ├── InteractiveTree.tsx # D3 interactive overlay
│   │   │   └── NodeTooltip.tsx     # Hover details
│   │   ├── MetricsPanel/
│   │   │   ├── index.tsx
│   │   │   ├── TestResults.tsx
│   │   │   ├── QualityScores.tsx
│   │   │   └── Timing.tsx
│   │   ├── RunList/
│   │   │   ├── index.tsx
│   │   │   └── RunCard.tsx
│   │   ├── ConfigPanel/            # Configuration controls
│   │   │   ├── index.tsx
│   │   │   ├── AggregationSelect.tsx
│   │   │   ├── ColorBySelect.tsx
│   │   │   └── RefreshInterval.tsx
│   │   └── common/
│   │       ├── StatusBadge.tsx
│   │       ├── ProgressBar.tsx
│   │       └── Tooltip.tsx
│   ├── hooks/
│   │   ├── useApi.ts
│   │   ├── usePolling.ts
│   │   └── useConfig.ts            # User preferences
│   ├── types/
│   │   └── index.ts
│   └── styles/
│       └── index.css
├── tailwind.config.js
└── tsconfig.json
```

### Core Library Public API

The `agent_arborist.viz` module exposes a clean public API:

```python
# High-level API
from agent_arborist.viz import (
    # Tree building
    build_metrics_tree,       # DagRun → MetricsTree

    # Metrics extraction
    extract_metrics,          # DagRun → dict of metrics by task

    # Aggregation
    aggregate_tree,           # MetricsTree → MetricsTree (with aggregated values)

    # Rendering
    render_tree,              # MetricsTree → str/bytes (format-dependent)
    render_metrics,           # MetricsTree → str/bytes
    render_summary,           # MetricsTree → str/bytes

    # Convenience
    visualize_run,            # run_id → rendered output (all-in-one)
)

# Configuration
from agent_arborist.viz import (
    AggregationStrategy,      # Enum: TOTALS, AVERAGES, BOTH
    ColorScheme,              # Enum: STATUS, QUALITY, PASS_RATE
    OutputFormat,             # Enum: ASCII, SVG, PNG, JSON, MARKDOWN, HTML
)

# Models (for programmatic use)
from agent_arborist.viz.models import (
    NodeMetrics,
    AggregatedMetrics,
    MetricsTree,
    MetricsNode,
)
```

### Example Usage

```python
from agent_arborist.viz import (
    build_metrics_tree,
    aggregate_tree,
    render_tree,
    AggregationStrategy,
    OutputFormat,
)
from agent_arborist.dagu_runs import load_dag_run

# Load a DAG run
dag_run = load_dag_run("abc123", expand_subdags=True)

# Build metrics tree
tree = build_metrics_tree(dag_run)

# Aggregate with totals strategy
tree = aggregate_tree(tree, strategy=AggregationStrategy.TOTALS)

# Render to different formats
ascii_output = render_tree(tree, format=OutputFormat.ASCII)
svg_output = render_tree(tree, format=OutputFormat.SVG)
png_bytes = render_tree(tree, format=OutputFormat.PNG)

# Or use the convenience function
svg = visualize_run(
    "abc123",
    format=OutputFormat.SVG,
    aggregation=AggregationStrategy.TOTALS,
)
```

---

## Implementation Plan

### Phase 1: Core Library - Data Models & Extraction

1. **Create `viz` package structure**
   - Set up module hierarchy under `src/agent_arborist/viz/`
   - Define public API in `__init__.py`
   - Add optional dependencies to pyproject.toml

2. **Implement data models**
   - `NodeMetrics` dataclass with all metric fields
   - `AggregatedMetrics` dataclass for roll-ups
   - `MetricsTree` and `MetricsNode` for tree structure

3. **Implement metrics extraction**
   - `MetricsExtractor` base class with plugin pattern
   - `TestMetricsExtractor` - parse `RunTestResult` from outputs
   - `TimingMetricsExtractor` - extract duration from steps
   - Handle missing/partial data gracefully

4. **Implement tree builder**
   - `TreeBuilder` class: `DagRun` → `MetricsTree`
   - Recursive traversal of sub-DAGs
   - Attach extracted metrics to each node

### Phase 2: Core Library - Aggregation & CLI

1. **Implement aggregation engine**
   - `Aggregator` base class with strategy pattern
   - `TotalsAggregator` - sum with deduplication support
   - `AveragesAggregator` - weighted averages for quality scores
   - Tree traversal for bottom-up aggregation

2. **Implement ASCII renderer**
   - Rich-based tree display with colors
   - Status indicators and metric badges
   - Configurable depth and collapse options

3. **Implement CLI commands**
   - `arborist viz tree` - ASCII tree output
   - `arborist viz metrics` - table/JSON output
   - Add `viz` command group to `cli.py`

4. **Add tests**
   - Unit tests for extractors
   - Unit tests for aggregators
   - Integration tests for CLI commands

### Phase 3: Core Library - Renderers

1. **Implement SVG renderer**
   - Dendrogram layout algorithm (or use graphviz)
   - Color scales for status/quality/pass-rate
   - Node styling with metric badges

2. **Implement PNG renderer**
   - SVG → PNG conversion via cairosvg
   - Resolution/DPI options

3. **Implement report renderers**
   - Markdown report generator
   - HTML report generator (with embedded SVG)
   - JSON export (structured tree data)

4. **Implement export command**
   - `arborist viz export` - batch export to directory
   - `arborist viz summary` - generate reports

### Phase 4: Quality Hooks Integration

1. **Define hook schemas**
   - Add step definitions to config schema
   - Create prompt templates for quality grading

2. **Implement quality grading hooks**
   - `grade_code_quality` LLM eval hook
   - `grade_task_completion` LLM eval hook
   - `check_test_coverage` shell hook

3. **Integrate with DAG builder**
   - Inject hooks at `post_task` point
   - Capture outputs in standard format

4. **Add quality metrics extraction**
   - `QualityMetricsExtractor` - parse LLM eval outputs
   - `CoverageMetricsExtractor` - parse coverage hook output
   - Include in tree builder pipeline

### Phase 5: Dashboard API & Frontend

1. **Implement FastAPI server**
   - Thin wrapper routes calling core library
   - `/api/runs` - list runs (uses existing `list_dag_runs`)
   - `/api/runs/{id}/tree` - returns JSON tree or SVG
   - `/api/runs/{id}/metrics` - returns metrics summary
   - `/api/runs/{id}/render` - returns rendered visualization

2. **Set up React + Vite project**
   - Configure TypeScript, Tailwind CSS
   - Set up API client with types

3. **Build frontend components**
   - Run list browser with filtering
   - Dendrogram display (renders SVG from API or JSON with D3)
   - Metrics panel for selected node
   - Configuration controls (aggregation, color scheme, refresh)

4. **Build & bundle**
   - Build frontend to static assets
   - Bundle into Python package
   - `arborist dashboard` command

### Phase 6: Polish & Documentation

1. **Comparison feature**
   - `arborist viz compare` command
   - Side-by-side or diff view

2. **Polling refresh**
   - Auto-refresh interval in dashboard
   - Visual indicator of refresh state

3. **Documentation**
   - CLI command reference
   - Core library API docs
   - Example workflows

4. **Optional: Graphviz renderer**
   - DOT file generation
   - Alternative layout algorithm

---

## Configuration

Add to `.arborist/config.json`:

```json
{
  "dashboard": {
    "port": 8080,
    "host": "127.0.0.1",
    "refresh_interval_seconds": 5,
    "default_aggregation": "totals",
    "quality_hooks_enabled": true
  }
}
```

---

## Dependencies

### Core Library (Python)

The core library uses only standard dependencies plus Rich (already a dependency):

```toml
# No additional required dependencies for core viz functionality
# Rich is already used for CLI output
```

### Optional Dependencies (Python)

```toml
[project.optional-dependencies]
# SVG/PNG rendering
viz-render = [
    "cairosvg>=2.7.0",      # SVG to PNG conversion
    "svgwrite>=1.4.0",      # SVG generation (alternative to manual)
]

# Graphviz support (alternative renderer)
viz-graphviz = [
    "graphviz>=0.20.0",     # DOT file generation and rendering
]

# Dashboard server
dashboard = [
    "fastapi>=0.109.0",
    "uvicorn[standard]>=0.27.0",
]

# All visualization features
viz = [
    "agent-arborist[viz-render,dashboard]",
]
```

### Dependency Strategy

| Feature | Required Dependencies | Optional Dependencies |
|---------|----------------------|----------------------|
| ASCII tree (`arborist viz tree`) | Rich (existing) | None |
| JSON/CSV export | None (stdlib) | None |
| SVG rendering | None (manual SVG) | svgwrite |
| PNG rendering | - | cairosvg |
| Graphviz DOT | - | graphviz |
| Dashboard | - | fastapi, uvicorn |
| Markdown/HTML reports | None (string templates) | None |

The design ensures basic visualization works with zero additional dependencies, while richer features are opt-in.

### Frontend (Node.js)

```json
{
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "d3": "^7.8.0",
    "@tanstack/react-query": "^5.0.0"
  },
  "devDependencies": {
    "vite": "^5.0.0",
    "typescript": "^5.3.0",
    "tailwindcss": "^3.4.0",
    "@types/d3": "^7.4.0"
  }
}
```

---

## Renderer Architecture

The rendering system uses a protocol-based design for technology-agnostic visualization generation.

### Renderer Protocol

```python
from typing import Protocol, Union
from agent_arborist.viz.models import MetricsTree

class TreeRenderer(Protocol):
    """Protocol for tree renderers."""

    format: str  # e.g., "svg", "png", "ascii"

    def render(
        self,
        tree: MetricsTree,
        *,
        color_by: str = "status",
        depth: int | None = None,
        **options,
    ) -> Union[str, bytes]:
        """Render the tree to the target format."""
        ...

    def supports_format(self, format: str) -> bool:
        """Check if this renderer supports the given format."""
        ...
```

### Built-in Renderers

| Renderer | Formats | Dependencies | Description |
|----------|---------|--------------|-------------|
| `ASCIIRenderer` | `ascii`, `text` | Rich | Terminal tree with colors |
| `SVGRenderer` | `svg` | None | Hand-crafted SVG generation |
| `PNGRenderer` | `png` | cairosvg | SVG → PNG conversion |
| `JSONRenderer` | `json` | None | Structured tree data |
| `MarkdownRenderer` | `md`, `markdown` | None | Markdown report |
| `HTMLRenderer` | `html` | None | HTML report with embedded SVG |
| `GraphvizRenderer` | `dot`, `pdf` | graphviz | DOT graph + PDF export |

### Renderer Registry

```python
from agent_arborist.viz.renderers import register_renderer, get_renderer

# Register a custom renderer
@register_renderer("custom")
class CustomRenderer:
    format = "custom"

    def render(self, tree, **options):
        # Custom rendering logic
        return "..."

# Get a renderer by format
renderer = get_renderer("svg")
output = renderer.render(tree, color_by="quality")
```

### Color Schemes

All renderers share common color scheme definitions:

```python
class ColorScheme:
    STATUS = {
        "success": "#22c55e",  # green-500
        "failed": "#ef4444",   # red-500
        "running": "#3b82f6",  # blue-500
        "pending": "#9ca3af",  # gray-400
        "skipped": "#eab308",  # yellow-500
    }

    QUALITY_GRADIENT = [
        (1, "#ef4444"),   # 1-2: red
        (3, "#f97316"),   # 3-4: orange
        (5, "#eab308"),   # 5-6: yellow
        (7, "#84cc16"),   # 7-8: lime
        (9, "#22c55e"),   # 9-10: green
    ]

    PASS_RATE_GRADIENT = [
        (0.0, "#ef4444"),   # 0%: red
        (0.5, "#eab308"),   # 50%: yellow
        (0.8, "#84cc16"),   # 80%: lime
        (1.0, "#22c55e"),   # 100%: green
    ]
```

---

## Future Enhancements (Post-V1)

1. **WebSocket real-time updates** - Stream status changes during active runs
2. **Historical trends** - Track quality scores over time, show regressions
3. **Export functionality** - PDF/PNG export of dendrograms
4. **Notifications** - Slack/email alerts on failures or quality drops
5. **Comparison view** - Side-by-side dendrograms for different runs
6. **Custom metrics** - User-defined metric extraction from outputs
7. **Database persistence** - Store historical data beyond DAG run files
