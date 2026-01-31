# Plan: Comprehensive DAG Observability Enhancement

## Summary
Improve `dag run-show` to provide rich, detailed information about DAG runs:
- **V1 (This PR)**: Outputs support, proper recursive tree traversal, error diagnostics
- **V2 (Deferred)**: Log content display, log file path discovery

### V1 Scope
- Full JSON output with complete run details and recursive children
- Proper recursive sub-DAG expansion (fix current 2-level limitation)
- Step outputs from `outputs.json` files
- Exit codes and error messages for failures
- Enhanced dataclasses with `run_dir` and `outputs_file` fields

### Deferred to V2
- `--log-content` flag (inline log display)
- Log file path discovery and display
- Raw log file parsing

## Current Issues

### Issue 1: Incomplete Sub-DAG Expansion (CRITICAL)
The `--expand-subdags/-e` flag exists but **only traverses 2 levels deep**:
- `_print_dag_tree()` doesn't recursively call itself for grandchildren DAGs
- JSON output only iterates `dag_run.children` without recursion
- **Fix**: Make both tree display and JSON output fully recursive

### Issue 2: Missing Outputs Information
No mechanism to read step outputs from `outputs.json` files.
- `outputs.json` contains captured step outputs (different from raw logs)
- Raw logs remain in Dagu's standard locations - no changes needed there

### Issue 3: Missing Error Details
Current output doesn't show:
- Exit codes for failed steps
- Error messages from status.jsonl
- Clear failure diagnostics

## Dagu Data Structure

### Directory Structure
```
$DAGU_HOME/
├── data/
│   └── dag-runs/
│       └── {dag-name}/
│           └── dag-runs/
│               └── YYYY/MM/DD/
│                   └── dag-run_{timestamp}_{run-id}/
│                       ├── attempt_{timestamp}_{msZ}_{short-id}/
│                       │   ├── status.jsonl     # Run status & step details
│                       │   └── outputs.json     # Captured step outputs (V1 focus)
│                       └── children/
│                           └── child_{child-run-id}/
│                               └── attempt_.../
│                                   ├── status.jsonl
│                                   └── outputs.json
└── logs/                            # Raw logs (V2 - leave as-is for now)
```

**Note**: `outputs.json` contains captured step outputs (variables). Raw logs (stdout/stderr) are stored separately in the `logs/` directory - this is standard Dagu behavior and doesn't need changes for V1.

### status.jsonl Format (Single line JSON)
```json
{
  "dagRunId": "019bf33d-a303-7af0-91c8-0fa5f28ae023",
  "name": "001_hello_world",
  "attemptId": "att123",
  "status": 4,
  "startedAt": "2026-01-25T03:41:01-07:00",
  "finishedAt": "2026-01-25T03:45:45-07:00",
  "root": {"name": "001_hello_world", "id": "root123"},
  "parent": {"name": "parent-name", "id": "parent123"},
  "nodes": [
    {
      "step": {"name": "step-name"},
      "status": 4,
      "startedAt": "2026-01-25T03:41:01-07:00",
      "finishedAt": "2026-01-25T03:41:10-07:00",
      "childDag": {"name": "T001"},
      "children": [{"dagRunId": "child123"}]
    }
  ]
}
```

### outputs.json Format (if captured)
```json
{
  "metadata": {
    "dagName": "my-dag",
    "dagRunId": "abc123",
    "attemptId": "attempt_id",
    "status": "succeeded",
    "completedAt": "2024-01-15T10:30:00Z",
    "params": "{\"env\":\"prod\"}"
  },
  "outputs": {"variableName": "value"}
}
```

## Implementation Plan (V1)

### Phase 1: Enhanced Data Layer

#### 1.1 Add Output/Error Support to Data Classes
**File: `src/agent_arborist/dagu_runs.py`**

Add new fields to existing dataclasses:

```python
@dataclass
class StepNode:
    name: str
    status: DaguStatus
    started_at: datetime | None
    finished_at: datetime | None
    child_dag_name: str | None
    child_run_ids: list[str]
    # V1 additions:
    output: dict | None = None      # Captured output from outputs.json
    exit_code: int | None = None    # Exit code for failed steps
    error: str | None = None        # Error message for failed steps

@dataclass
class DagRunAttempt:
    attempt_id: str
    status: DaguStatus
    steps: list[StepNode]
    started_at: datetime | None
    finished_at: datetime | None
    # V1 additions:
    outputs: dict | None = None     # Full outputs.json content
    error: str | None = None        # DAG-level error message

@dataclass
class DagRun:
    dag_name: str
    run_id: str
    root_dag_name: str | None
    root_dag_id: str | None
    parent_dag_name: str | None
    parent_dag_id: str | None
    latest_attempt: DagRunAttempt | None
    children: list["DagRun"]
    # V1 additions:
    run_dir: Path | None = None         # Path to run directory
    outputs_file: Path | None = None    # Path to outputs.json if exists
```

#### 1.2 Add Outputs Parsing

```python
def parse_outputs_json(path: Path) -> dict:
    """Parse outputs.json file and return output data."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, IOError):
        return {}

def load_step_output(outputs: dict, step_name: str) -> dict | None:
    """Extract step output from parsed outputs.json."""
    return outputs.get("outputs", {}).get(step_name)
```

#### 1.3 Enhance parse_status_jsonl() for Errors

```python
def parse_status_jsonl(path: Path) -> DagRunAttempt:
    """Parse status.jsonl with error and exit code extraction."""
    # ... existing parsing ...

    # Extract DAG-level error
    dag_error = data.get("error")

    steps = []
    for node in data.get("nodes", []):
        # ... existing step parsing ...

        # V1: Extract exit code and error
        exit_code = node.get("exitCode")
        step_error = node.get("error")

        step = StepNode(
            name=step_name,
            status=step_status,
            started_at=step_started,
            finished_at=step_finished,
            child_dag_name=child_dag_name,
            child_run_ids=child_run_ids,
            output=None,        # Populated later if include_outputs=True
            exit_code=exit_code,
            error=step_error,
        )
        steps.append(step)

    return DagRunAttempt(
        attempt_id=attempt_id,
        status=status,
        steps=steps,
        started_at=started_at,
        finished_at=finished_at,
        outputs=None,  # Populated later if include_outputs=True
        error=dag_error,
    )
```

#### 1.4 Enhance load_dag_run() with Outputs Support

```python
def load_dag_run(
    dagu_home: Path,
    dag_name: str,
    run_id: str,
    expand_subdags: bool = False,
    include_outputs: bool = False,  # V1 addition
) -> DagRun | None:
    """Load a DAG run with optional expansions."""
    run_dir = _find_run_dir(dagu_home, dag_name, run_id)
    if not run_dir:
        return None

    # ... existing attempt loading ...

    # V1: Load outputs.json if requested
    outputs_file = next(run_dir.glob("attempt_*/outputs.json"), None)
    if include_outputs and outputs_file:
        outputs_data = parse_outputs_json(outputs_file)
        attempt.outputs = outputs_data
        # Populate per-step outputs
        for step in attempt.steps:
            step.output = load_step_output(outputs_data, step.name)

    # Load children recursively (V1: pass include_outputs through)
    children = []
    if expand_subdags:
        children = _load_children(dagu_home, run_dir, status_data, expand_subdags=True, include_outputs=include_outputs)

    return DagRun(
        dag_name=dag_name,
        run_id=status_data.get("dagRunId", run_id),
        # ... existing fields ...
        run_dir=run_dir,
        outputs_file=outputs_file,
    )
```

#### 1.5 Fix _load_children() for Proper Recursion

Current `_load_children()` needs to pass `include_outputs` through and ensure recursive loading works correctly:

```python
def _load_children(
    dagu_home: Path,
    parent_run_dir: Path,
    parent_status: dict,
    expand_subdags: bool = False,
    include_outputs: bool = False,  # V1 addition
) -> list[DagRun]:
    """Load child DAGs recursively."""
    children_dir = parent_run_dir / "children"
    if not children_dir.exists():
        return []

    children = []
    for child_dir in children_dir.iterdir():
        # ... existing child loading ...

        # V1: Load outputs for child
        child_outputs_file = next(child_dir.glob("attempt_*/outputs.json"), None)
        if include_outputs and child_outputs_file:
            outputs_data = parse_outputs_json(child_outputs_file)
            attempt.outputs = outputs_data
            for step in attempt.steps:
                step.output = load_step_output(outputs_data, step.name)

        # Recursive grandchildren loading
        grandchildren = []
        if expand_subdags:
            grandchildren = _load_children(
                dagu_home, child_dir, child_data,
                expand_subdags=True, include_outputs=include_outputs
            )

        child_run = DagRun(
            # ... existing fields ...
            children=grandchildren,
            run_dir=child_dir,
            outputs_file=child_outputs_file,
        )
        children.append(child_run)

    return children
```

### Phase 2: Recursive JSON Output

#### 2.1 Fix JSON Output to be Fully Recursive
**File: `src/agent_arborist/cli.py`**

Current code only handles one level of children. Replace with recursive helper:

```python
def _dag_run_to_json(dag_run: dagu_runs.DagRun) -> dict:
    """Convert DagRun to JSON-serializable dict (fully recursive)."""
    attempt = dag_run.latest_attempt

    result = {
        "dag_name": dag_run.dag_name,
        "run_id": dag_run.run_id,
        "status": attempt.status.to_name() if attempt else "unknown",
        "status_code": attempt.status.value if attempt else None,
        "started_at": attempt.started_at.isoformat() if attempt and attempt.started_at else None,
        "finished_at": attempt.finished_at.isoformat() if attempt and attempt.finished_at else None,
        "root_dag_name": dag_run.root_dag_name,
        "root_dag_id": dag_run.root_dag_id,
        "parent_dag_name": dag_run.parent_dag_name,
        "parent_dag_id": dag_run.parent_dag_id,
        "error": attempt.error if attempt else None,
        "outputs": attempt.outputs.get("outputs") if attempt and attempt.outputs else None,
        "steps": [],
        "children": [],
        "run_dir": str(dag_run.run_dir) if dag_run.run_dir else None,
        "outputs_file": str(dag_run.outputs_file) if dag_run.outputs_file else None,
    }

    if attempt:
        # Add duration
        if attempt.started_at and attempt.finished_at:
            duration_seconds = (attempt.finished_at - attempt.started_at).total_seconds()
            result["duration_seconds"] = duration_seconds
            result["duration_human"] = dagu_runs._format_duration(attempt.started_at, attempt.finished_at)

        # Add steps with V1 fields
        for step in attempt.steps:
            step_data = {
                "name": step.name,
                "status": step.status.to_name(),
                "status_code": step.status.value,
                "started_at": step.started_at.isoformat() if step.started_at else None,
                "finished_at": step.finished_at.isoformat() if step.finished_at else None,
                "exit_code": step.exit_code,
                "error": step.error,
                "output": step.output,
                "child_dag_name": step.child_dag_name,
                "child_run_ids": step.child_run_ids,
            }

            # Add step duration
            if step.started_at and step.finished_at:
                step_duration = (step.finished_at - step.started_at).total_seconds()
                step_data["duration_seconds"] = step_duration
                step_data["duration_human"] = dagu_runs._format_duration(step.started_at, step.finished_at)

            result["steps"].append(step_data)

        # RECURSIVE: Add children (this was the bug - old code didn't recurse)
        for child in dag_run.children:
            result["children"].append(_dag_run_to_json(child))  # Recursive call

    return result
```

Then update `dag_run_show` to use this helper instead of inline JSON construction.

### Phase 3: Fix Recursive ASCII Tree

#### 3.1 Rewrite Tree Display for Full Recursion

Current `_print_dag_tree()` only goes 2 levels. Replace with fully recursive version:

```python
def _print_dag_tree(
    dag_run: dagu_runs.DagRun,
    console: Console,
    prefix: str = "",
    show_outputs: bool = False,
) -> None:
    """Print a DAG run and its children as a fully recursive tree."""
    attempt = dag_run.latest_attempt
    if not attempt:
        return

    status_symbols = {
        dagu_runs.DaguStatus.SUCCESS: ("✓", "green"),
        dagu_runs.DaguStatus.FAILED: ("✗", "red"),
        dagu_runs.DaguStatus.RUNNING: ("◐", "yellow"),
        dagu_runs.DaguStatus.PENDING: ("○", "dim"),
        dagu_runs.DaguStatus.SKIPPED: ("⊘", "dim"),
    }

    # Print steps
    for i, step in enumerate(attempt.steps):
        is_last_step = i == len(attempt.steps) - 1
        has_matching_children = step.child_dag_name and any(
            c.dag_name == step.child_dag_name for c in dag_run.children
        )

        # Determine tree characters
        if is_last_step and not has_matching_children:
            step_prefix = prefix + "└── "
            child_prefix = prefix + "    "
        else:
            step_prefix = prefix + "├── "
            child_prefix = prefix + "│   "

        # Format step line
        status_sym, status_color = status_symbols.get(step.status, ("?", "white"))
        duration_str = dagu_runs._format_duration(step.started_at, step.finished_at)
        step_line = f"{step_prefix}[{status_color}]{status_sym} {step.name}[/{status_color}] ({duration_str})"
        console.print(step_line)

        # Print error if step failed
        if step.status == dagu_runs.DaguStatus.FAILED:
            if step.exit_code is not None:
                console.print(f"{child_prefix}[dim]Exit code: {step.exit_code}[/dim]")
            if step.error:
                console.print(f"{child_prefix}[red]Error: {step.error}[/red]")

        # Print step output if available
        if show_outputs and step.output:
            for key, value in step.output.items():
                truncated = str(value)[:80] + ("..." if len(str(value)) > 80 else "")
                console.print(f"{child_prefix}[cyan]{key}:[/cyan] {truncated}")

        # RECURSIVE: Print matching child DAGs
        if step.child_dag_name:
            matching_children = [c for c in dag_run.children if c.dag_name == step.child_dag_name]

            for child_idx, child in enumerate(matching_children):
                is_last_child = child_idx == len(matching_children) - 1 and is_last_step

                # Print child DAG header
                child_attempt = child.latest_attempt
                child_status = child_attempt.status if child_attempt else dagu_runs.DaguStatus.PENDING
                child_sym, child_color = status_symbols.get(child_status, ("?", "white"))
                child_duration = dagu_runs._format_duration(
                    child_attempt.started_at, child_attempt.finished_at
                ) if child_attempt else "N/A"

                child_header = f"{child_prefix}[{child_color}]{child_sym} {child.dag_name}[/{child_color}] ({child_duration})"
                console.print(child_header)

                # RECURSIVE CALL for child's steps
                if child_attempt:
                    nested_prefix = child_prefix + ("    " if is_last_child else "│   ")
                    _print_dag_tree(child, console, nested_prefix, show_outputs)
```

**Key fix**: The recursive call `_print_dag_tree(child, ...)` now properly descends into grandchildren.

### Phase 4: CLI Enhancements

#### 4.1 Update dag_run_show Options

```python
@dag.command("run-show")
@click.argument("dag_name", required=False)
@click.option("--run-id", "-r", help="Specific run ID (default: most recent)")
@click.option("--step", "-s", help="Show details for a specific step")
@click.option("--expand-subdags", "-e", is_flag=True, help="Expand sub-DAG tree hierarchy")
@click.option("--outputs", is_flag=True, help="Include step and dag outputs")  # V1 addition
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def dag_run_show(...):
    """Show details of a DAG run.

    Examples:
        arborist dag run-show                    # Show latest run
        arborist dag run-show --json             # Output as JSON
        arborist dag run-show -e                 # Expand sub-DAG hierarchy
        arborist dag run-show -e --outputs       # Include captured outputs
        arborist dag run-show -s "run"           # Filter to specific step
    """
```

#### 4.2 Update Command Implementation

```python
def dag_run_show(ctx, dag_name, run_id, step, expand_subdags, outputs, as_json):
    # ... existing setup ...

    # Load with V1 options
    dag_run = dagu_runs.load_dag_run(
        Path(dagu_home),
        resolved_dag_name,
        run_id,
        expand_subdags=expand_subdags,
        include_outputs=outputs,  # V1: pass through
    )

    if as_json:
        # Use recursive JSON helper
        json_data = _dag_run_to_json(dag_run)
        console.print(json.dumps(json_data, indent=2))
    else:
        # Print header
        console.print(f"[bold cyan]{dag_run.dag_name}[/bold cyan]")
        console.print(f"[dim]Run ID:[/dim] {dag_run.run_id}")
        # ... status display ...

        # Use recursive tree helper
        _print_dag_tree(dag_run, console, prefix="", show_outputs=outputs)
```

#### 4.3 Remove Existing --logs Flag (V2)

The existing `--logs` flag doesn't work well with the data layer. Remove it for now and re-add in V2 with proper log file discovery.

### Phase 5: Tests (Using E2E Fixtures)

Use existing e2e test patterns with tmp_path setup/teardown.

#### 5.1 Unit Tests for Data Layer (`tests/test_dagu_runs.py`)

```python
class TestOutputsParsing:
    """Tests for outputs.json parsing."""

    def test_parse_outputs_json_valid(self, tmp_path):
        """Test parsing valid outputs.json."""
        outputs_content = {
            "metadata": {"dagName": "test", "dagRunId": "abc123"},
            "outputs": {"result": "success", "count": 42}
        }
        outputs_file = tmp_path / "outputs.json"
        outputs_file.write_text(json.dumps(outputs_content))

        result = dagu_runs.parse_outputs_json(outputs_file)
        assert result == outputs_content

    def test_parse_outputs_json_missing(self, tmp_path):
        """Test parsing missing outputs.json returns empty dict."""
        result = dagu_runs.parse_outputs_json(tmp_path / "missing.json")
        assert result == {}

    def test_parse_outputs_json_invalid(self, tmp_path):
        """Test parsing invalid JSON handles errors gracefully."""
        outputs_file = tmp_path / "invalid.json"
        outputs_file.write_text("{ invalid json")
        result = dagu_runs.parse_outputs_json(outputs_file)
        assert result == {}

    def test_load_step_output(self):
        """Test extracting step output from outputs dict."""
        outputs = {"outputs": {"step1": {"result": "ok"}, "step2": {"value": 42}}}
        assert dagu_runs.load_step_output(outputs, "step1") == {"result": "ok"}
        assert dagu_runs.load_step_output(outputs, "step2") == {"value": 42}
        assert dagu_runs.load_step_output(outputs, "missing") is None


class TestErrorParsing:
    """Tests for error/exit code extraction from status.jsonl."""

    def test_parse_status_with_error_and_exit_code(self, tmp_path):
        """Test parsing status.jsonl with error and exit code."""
        status_data = {
            "dagRunId": "test123",
            "attemptId": "att1",
            "status": 2,  # FAILED
            "startedAt": "2026-01-25T00:00:00Z",
            "finishedAt": "2026-01-25T00:00:10Z",
            "error": "DAG failed",
            "nodes": [
                {"step": {"name": "step1"}, "status": 4, "exitCode": 0},
                {"step": {"name": "step2"}, "status": 2, "exitCode": 1, "error": "Command failed"}
            ]
        }
        status_file = tmp_path / "status.jsonl"
        status_file.write_text(json.dumps(status_data))

        attempt = dagu_runs.parse_status_jsonl(status_file)

        assert attempt.status == dagu_runs.DaguStatus.FAILED
        assert attempt.error == "DAG failed"

        failed_step = next(s for s in attempt.steps if s.name == "step2")
        assert failed_step.exit_code == 1
        assert failed_step.error == "Command failed"


class TestRecursiveLoading:
    """Tests for recursive child loading."""

    def test_load_dag_run_with_outputs(self, tmp_path):
        """Test loading DAG run with outputs enabled."""
        # Create test structure
        dagu_home = tmp_path / "dagu"
        _create_test_dag_run(dagu_home, "test_dag", "run123", with_outputs=True)

        dag_run = dagu_runs.load_dag_run(
            dagu_home, "test_dag", "run123",
            expand_subdags=False, include_outputs=True
        )

        assert dag_run is not None
        assert dag_run.latest_attempt.outputs is not None
        assert dag_run.outputs_file is not None

    def test_load_dag_run_recursive_children(self, tmp_path):
        """Test recursive loading of grandchildren."""
        dagu_home = tmp_path / "dagu"
        _create_test_dag_run_with_children(dagu_home, "root_dag", "run123", depth=3)

        dag_run = dagu_runs.load_dag_run(
            dagu_home, "root_dag", "run123",
            expand_subdags=True, include_outputs=True
        )

        assert dag_run is not None
        assert len(dag_run.children) > 0

        # Verify grandchildren loaded
        child = dag_run.children[0]
        assert len(child.children) > 0  # Has grandchildren


# Test helpers
def _create_test_dag_run(dagu_home, dag_name, run_id, with_outputs=False):
    """Create test DAG run directory structure."""
    run_dir = dagu_home / "data" / "dag-runs" / dag_name / "dag-runs" / "2026" / "01" / "31" / f"dag-run_20260131_000000Z_{run_id}"
    attempt_dir = run_dir / "attempt_1"
    attempt_dir.mkdir(parents=True)

    status_data = {
        "dagRunId": run_id, "name": dag_name, "attemptId": "att1",
        "status": 4, "startedAt": "2026-01-31T00:00:00Z", "finishedAt": "2026-01-31T00:01:00Z",
        "root": {"name": dag_name, "id": run_id}, "parent": {},
        "nodes": [{"step": {"name": "step1"}, "status": 4}]
    }
    (attempt_dir / "status.jsonl").write_text(json.dumps(status_data))

    if with_outputs:
        outputs_data = {"outputs": {"step1": {"result": "success"}}}
        (attempt_dir / "outputs.json").write_text(json.dumps(outputs_data))

    # Create DAG file
    dags_dir = dagu_home / "dags"
    dags_dir.mkdir(parents=True, exist_ok=True)
    (dags_dir / f"{dag_name}.yaml").write_text(f"name: {dag_name}")
```

#### 5.2 CLI Tests (`tests/test_dag_commands.py`)

```python
class TestDagRunShowV1:
    """Tests for V1 dag run-show enhancements."""

    def test_json_output_recursive_children(self, runner, tmp_path):
        """Test JSON output includes recursively nested children."""
        dagu_home = tmp_path / "dagu"
        _create_test_dag_run_with_children(dagu_home, "root_dag", "run123", depth=3)

        result = runner.invoke(
            main, ["dag", "run-show", "root_dag", "-e", "--json"],
            env={"DAGU_HOME": str(dagu_home)}
        )

        assert result.exit_code == 0
        data = json.loads(result.output)

        # Verify recursive structure
        assert "children" in data
        assert len(data["children"]) > 0
        child = data["children"][0]
        assert "children" in child  # Grandchildren present

    def test_json_output_includes_v1_fields(self, runner, tmp_path):
        """Test JSON output includes V1 fields: error, exit_code, outputs."""
        dagu_home = tmp_path / "dagu"
        _create_test_dag_run(dagu_home, "test_dag", "run123", with_outputs=True)

        result = runner.invoke(
            main, ["dag", "run-show", "test_dag", "--json", "--outputs"],
            env={"DAGU_HOME": str(dagu_home)}
        )

        assert result.exit_code == 0
        data = json.loads(result.output)

        assert "error" in data
        assert "outputs" in data
        assert "run_dir" in data
        assert "outputs_file" in data

        step = data["steps"][0]
        assert "exit_code" in step
        assert "error" in step
        assert "output" in step

    def test_tree_output_shows_outputs(self, runner, tmp_path):
        """Test tree output displays step outputs when --outputs flag used."""
        dagu_home = tmp_path / "dagu"
        _create_test_dag_run(dagu_home, "test_dag", "run123", with_outputs=True)

        result = runner.invoke(
            main, ["dag", "run-show", "test_dag", "-e", "--outputs"],
            env={"DAGU_HOME": str(dagu_home)}
        )

        assert result.exit_code == 0
        assert "result:" in result.output or "success" in result.output

    def test_tree_output_shows_errors(self, runner, tmp_path):
        """Test tree output displays errors for failed steps."""
        dagu_home = tmp_path / "dagu"
        _create_failed_dag_run(dagu_home, "test_dag", "run123")

        result = runner.invoke(
            main, ["dag", "run-show", "test_dag", "-e"],
            env={"DAGU_HOME": str(dagu_home)}
        )

        assert result.exit_code == 0
        assert "Exit code:" in result.output or "Error:" in result.output

    def test_echo_outputs_flag(self, runner):
        """Echo test for --outputs flag."""
        result = runner.invoke(main, ["--echo-for-testing", "dag", "run-show", "test", "--outputs"])
        assert "outputs=True" in result.output
```

## Sample Output (V1)

### ASCII Tree with Outputs
```
$ arborist dag run-show -e --outputs

001_hello_world
Run ID: 019bf33d-a303-7af0-91c8-0fa5f28ae023
Status: success
Duration: 4m 44s

├── ✓ branches-setup (2s)
├── ✓ call-T001 (1m 6s)
│   ✓ T001 (1m 6s)
│   ├── ✓ pre-sync (5s)
│   │   branch_created: true
│   │   branch_name: task/T001
│   ├── ✓ run (45s)
│   ├── ✓ commit (3s)
│   └── ✓ post-merge (2s)
├── ✓ call-T002 (2m 30s)
│   ✓ T002 (2m 30s)
│   ├── ✓ pre-sync (4s)
│   ├── ✗ run (2m)
│   │   Exit code: 1
│   │   Error: AI task failed after 3 retries
│   ...
└── ✓ final-merge (5s)
```

### JSON Output (Recursive)
```json
{
  "dag_name": "001_hello_world",
  "run_id": "019bf33d-a303-7af0-91c8-0fa5f28ae023",
  "status": "success",
  "status_code": 4,
  "duration_seconds": 284,
  "duration_human": "4m 44s",
  "error": null,
  "outputs": {"final_branch": "main"},
  "run_dir": "/path/to/run/dir",
  "outputs_file": "/path/to/outputs.json",
  "steps": [
    {"name": "call-T001", "status": "success", "exit_code": null, "error": null, "output": null, ...}
  ],
  "children": [
    {
      "dag_name": "T001",
      "run_id": "child-run-id",
      "steps": [...],
      "children": []  // Recursive - grandchildren would appear here
    }
  ]
}
```

## Implementation Checklist (V1)

### Data Layer (dagu_runs.py)
- [ ] Add V1 fields to `StepNode`: `output`, `exit_code`, `error`
- [ ] Add V1 fields to `DagRunAttempt`: `outputs`, `error`
- [ ] Add V1 fields to `DagRun`: `run_dir`, `outputs_file`
- [ ] Implement `parse_outputs_json()`
- [ ] Implement `load_step_output()`
- [ ] Enhance `parse_status_jsonl()` for errors/exit codes
- [ ] Enhance `load_dag_run()` with `include_outputs` parameter
- [ ] Fix `_load_children()` to pass `include_outputs` through recursively

### CLI (cli.py)
- [ ] Add `--outputs` flag to `dag run-show`
- [ ] Remove broken `--logs` flag (defer to V2)
- [ ] Implement `_dag_run_to_json()` helper (fully recursive)
- [ ] Fix `_print_dag_tree()` for full recursion (currently 2 levels only)
- [ ] Update help text and examples

### Tests
- [ ] Unit tests for outputs parsing
- [ ] Unit tests for error/exit code extraction
- [ ] Unit tests for recursive child loading
- [ ] CLI tests for `--outputs` flag
- [ ] CLI tests for recursive JSON output
- [ ] CLI tests for recursive tree output
- [ ] Use e2e fixtures with tmp_path setup/teardown

## Deferred to V2
- [ ] `--log-content` flag
- [ ] Log file path discovery
- [ ] `--logs` flag with proper data layer support
- [ ] Raw log file parsing

## Estimated Effort: 8-12 hours (~1-2 days)