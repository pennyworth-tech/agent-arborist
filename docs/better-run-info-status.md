# Plan: DAG Run List and Sub-DAG Expansion CLI Commands

## Summary
Add `dag run-list` command and enhance `dag run-show` with `--expand-subdags` flag to list and inspect historical DAG executions from Dagu's local data directory.

## User Decisions
- **Command structure**: Extend existing `dag` group
- **Sub-DAG depth**: Full recursive tree expansion
- **Data source**: `/tmp/arborist-test-repo/.arborist/dagu` (sample data available)

## Dagu Data Format (from exploration)

**Directory structure:**
```
$DAGU_HOME/data/dag-runs/<dag-name>/dag-runs/YYYY/MM/DD/dag-run_<timestamp>_<run-id>/
├── attempt_<timestamp>_<attempt-id>/status.jsonl
└── children/child_<child-run-id>/attempt_.../status.jsonl
```

**status.jsonl key fields:**
- `dagRunId`, `name`, `status` (0=pending, 1=running, 2=failed, 3=skipped, 4=success)
- `startedAt`, `finishedAt` (ISO timestamps)
- `nodes[]` with step details and `children[].dagRunId` for call steps
- `root`, `parent` references linking child to parent DAGs

## Implementation Steps

### Step 1: Create Data Layer
**New file: `src/agent_arborist/dagu_runs.py`**

Data classes:
- `DaguStatus(IntEnum)` - PENDING=0, RUNNING=1, FAILED=2, SKIPPED=3, SUCCESS=4
- `StepNode` - step name, status, timing, child_dag_name, child_run_ids
- `DagRunAttempt` - attempt_id, status, steps[], timing
- `DagRun` - dag_name, run_id, root/parent refs, latest_attempt, children[]

Functions:
- `parse_status_jsonl(path)` → `DagRunAttempt`
- `load_dag_run(run_dir, expand_subdags=False)` → `DagRun`
- `list_dag_runs(dagu_home, dag_name, status, limit)` → `list[DagRun]`
- `get_dag_run(dagu_home, dag_name, run_id, expand_subdags)` → `DagRun`

### Step 2: Add CLI Commands
**Modify: `src/agent_arborist/cli.py`**

```python
@dag.command("run-list")
@click.option("--limit", "-n", default=20)
@click.option("--dag-name", "-d")
@click.option("--status", "-s", type=click.Choice(["pending", "running", "success", "failed", "skipped"]))
@click.option("--json", "as_json", is_flag=True)
def dag_run_list(ctx, limit, dag_name, status, as_json):
    """List DAG runs with status, timing, and run IDs."""
```

Enhance existing `dag run-show`:
```python
@click.option("--expand-subdags", "-e", is_flag=True, help="Expand sub-DAG tree hierarchy")
@click.option("--json", "as_json", is_flag=True)
```

### Step 3: Add Tests
**Modify: `tests/test_dag_commands.py`** - Echo tests

```python
def test_echo_dag_run_list(self):
    result = runner.invoke(main, ["--echo-for-testing", "dag", "run-list"])
    assert "ECHO: dag run-list" in result.output

def test_echo_dag_run_show_expand_subdags(self):
    result = runner.invoke(main, ["--echo-for-testing", "dag", "run-show", "my-dag", "--expand-subdags"])
    assert "expand_subdags=True" in result.output
```

**New file: `tests/test_dagu_runs.py`** - Unit tests for data layer

### Step 4: Create Fixtures
**New files:**
- `tests/fixtures/status_success.jsonl`
- `tests/fixtures/status_with_children.jsonl`

## Sample Output

### `dag run-list`
```
                         DAG Runs
+--------------------------+----------+---------+-----------------+----------+
| DAG                      | Run ID   | Status  | Started         | Duration |
+--------------------------+----------+---------+-----------------+----------+
| 001_hello_world          | 019bf33d | success | 2026-01-24 20:41| 4m 44s   |
+--------------------------+----------+---------+-----------------+----------+
```

### `dag run-show --expand-subdags`
```
001_hello_world
Run ID: 019bf33d-a303-7af0-91c8-0fa5f28ae023
Status: success
Duration: 4m 44s

Sub-DAG Hierarchy:
001_hello_world
├── T001 success (1m 6s)
├── T002 success (1m 16s)
├── T003 success (1m 7s)
└── T004 success (1m 15s)
```

## Files to Modify
| File | Action |
|------|--------|
| `src/agent_arborist/dagu_runs.py` | Create - data layer |
| `src/agent_arborist/cli.py` | Modify - add run-list, enhance run-show |
| `tests/test_dag_commands.py` | Modify - add echo tests |
| `tests/test_dagu_runs.py` | Create - unit tests |
| `tests/fixtures/status_*.jsonl` | Create - test fixtures |
