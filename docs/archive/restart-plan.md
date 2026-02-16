# DAG Restart with Idempotent Task Checking - Implementation Plan

## Problem Statement

When a DAG execution is interrupted or fails, restarting with `dagu restart` re-runs ALL steps from the beginning, even if some steps already completed successfully. This causes:

- Wasted computational resources (re-running AI agents is expensive)
- Unnecessary test execution
- Redundant git operations
- Increased time to completion

**Goal**: Provide a restart mechanism that skips steps that already completed successfully, while ensuring data integrity and correctness.

---

## Solution Architecture

### Core Principle: Restart Always Skips Completed Steps

The `arborist dag restart` command ALWAYS skips steps that completed successfully. There is no option to force re-run - if you need a clean run, use `arborist dag start` to create a new DAG run.

### Dagu Command Selection

The `arborist dag restart` command intelligently selects the appropriate Dagu command based on the DAG's current status:

| DAG Status | Dagu Command | Behavior |
|------------|--------------|----------|
| RUNNING | `dagu restart` then `dagu retry` | Stop running DAG, then retry |
| COMPLETED/FAILED | `dagu retry` | Retry with same run ID |

**Note**: `dagu restart` requires the DAG to be in RUNNING status. For completed/failed DAGs, we use `dagu retry` which works on COMPLETED/FAILED status.

### System Flow

```
┌─────────────────────────────────────────────────────────────┐
│ User Command:                                               │
│ arborist dag restart <spec_name> [--run-id <id>] [--yes]   │
├─────────────────────────────────────────────────────────────┤
│ 1. Identify the source run (current, latest, or specified)  │
│ 2. Load Dagu run history with full subDAG tree              │
│ 3. Load Arborist task state for the spec                    │
│ 4. Build restart context mapping each task's completion     │
│ 5. Save context to ARBORIST_HOME/restart-contexts/          │
│ 6. Set ARBORIST_RESTART_CONTEXT environment variable       │
│ 7. Check DAG status:                                        │
│    - If RUNNING: dagu restart (stop) then dagu retry       │
│    - If COMPLETED/FAILED: dagu retry                       │
│    (Dagu re-initiates the DAG, but steps skip if complete)  │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ In each task step (invoked by Dagu)                         │
├─────────────────────────────────────────────────────────────┤
│ def step_handler(task_id, step_name):                       │
│   if ARBORIST_RESTART_CONTEXT is set:                       │
│     context = load_restart_context()                        │
│     if context.should_skip(task_id, step_name):             │
│       verify_step_integrity(task_id, step_name)             │
│       output {"success": true, "skipped": true,...}        │
│       exit(0)  # No-op success                              │
│     endif                                                    │
│   endif                                                      │
│                                                             │
│   # Execute normally if not complete or verification fails  │
│   execute_step_logic()                                      │
│   output step_result                                        │
└─────────────────────────────────────────────────────────────┘
```

---

## Data Structures

### Restart Context

**Step Name Format**: Full qualified step names are used (e.g., `T001.pre-sync`, `T001.run`) for precise tracking across the task hierarchy.

```python
@dataclass
class StepCompletionState:
    """Completion state for a step in a task."""
    full_step_name: str  # Full qualified: "T001.pre-sync", "T001.run", etc.
    step_type: str  # Step type: "pre-sync", "run", "commit", etc.
    completed: bool
    completed_at: datetime | None
    dag_run_id: str
    status: str  # "success", "failed", "running", "skipped"
    exit_code: int | None  # Exit code from Dagu (V1 feature)
    error: str | None  # Error message if failed (V1 feature)
    output: dict | None  # Captured output from outputs.json (V1 feature)

@dataclass
class TaskRestartContext:
    """Restart context for a single task."""
    spec_id: str
    task_id: str
    run_id: str  # Previous Dagu run ID
    overall_status: str  # "complete", "failed", "running", "partial"
    steps: dict[str, StepCompletionState]  # full_step_name -> state
    children_complete: bool  # For parent tasks: did all children complete?
    branch_name: str | None  # For git verification
    head_commit_sha: str | None  # For git state verification

@dataclass
class RestartContext:
    """Complete restart context for all tasks in a spec."""
    spec_name: str
    spec_id: str
    arborist_home: Path
    dagu_home: Path
    source_run_id: str  # The run being analyzed
    created_at: datetime
    tasks: dict[str, TaskRestartContext]  # task_id -> context
    root_dag_status: DaguStatus
```

### Storage

Restart contexts stored at: `~/.arborist/restart-contexts/<spec_name>_<run_id>.json`

Example filename: `feature-auth_T004_abc123de.json`

---

## Phase 1: Core Infrastructure

### 1.1 Create Restart Context Module

**New File**: `src/agent_arborist/restart_context.py`

Implement data structures with JSON serialization:

```python
def to_dict(self) -> dict:
    """Convert to JSON-serializable dict."""
    return {
        "spec_name": self.spec_name,
        "spec_id": self.spec_id,
        "arborist_home": str(self.arborist_home),
        "dagu_home": str(self.dagu_home),
        "source_run_id": self.source_run_id,
        "created_at": self.created_at.isoformat(),
        "tasks": {
            tid: ctx.to_dict()
            for tid, ctx in self.tasks.items()
        },
        "root_dag_status": self.root_dag_status.value,
    }

@classmethod
def from_dict(cls, data: dict) -> "RestartContext":
    """Load from JSON dict."""
    return cls(
        spec_name=data["spec_name"],
        spec_id=data["spec_id"],
        arborist_home=Path(data["arborist_home"]),
        dagu_home=Path(data["dagu_home"]),
        source_run_id=data["source_run_id"],
        created_at=datetime.fromisoformat(data["created_at"]),
        tasks={
            tid: TaskRestartContext.from_dict(ctx_data)
            for tid, ctx_data in data["tasks"].items()
        },
        root_dag_status=DaguStatus(data["root_dag_status"]),
    )

def save(self, path: Path) -> None:
    """Save context to file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(self.to_dict(), f, indent=2)

@classmethod
def load(cls, path: Path) -> "RestartContext":
    """Load context from file."""
    data = json.loads(path.read_text())
    return cls.from_dict(data)
```

### 1.2 Build Restart Context from Dagu History

**Function**: `build_restart_context(spec_name: str, run_id: str, dagu_home: Path, arborist_home: Path) -> RestartContext`

**Implementation Steps**:

1. **Load Dagu run hierarchy** (with V1 output capture):
   ```python
   dag_run = load_dag_run(
       dagu_home, spec_name, run_id,
       expand_subdags=True,
       include_outputs=True  # V1 feature: capture step outputs
   )
   ```

2. **Load Arborist task tree**:
   ```python
   task_tree = load_task_tree(spec_name)
   ```

3. **Parse step names from DAG structure**:
   Steps in sub-DAGs use full qualified names (e.g., `T001.pre-sync`). The step type is extracted from the suffix:
   ```python
   STEP_TYPES = {
       "pre-sync", "container-up", "run", "commit",
       "run-test", "post-merge", "container-stop", "post-cleanup"
   }

   def extract_step_type(full_step_name: str) -> str | None:
       """Extract step type from full name like 'T001.pre-sync' -> 'pre-sync'"""
       for step_type in STEP_TYPES:
           if full_step_name.endswith(f".{step_type}"):
               return step_type
       return None
   ```

4. **Parse each task's completion state**:
   - Iterate through `dag_run.children` (each child is a task subDAG)
   - For each task subDAG, check each step's status in `latest_attempt.steps`
   - Mark step as `completed=True` if `status == DaguStatus.SUCCESS`
   - Capture `finished_at` timestamp, `exit_code`, `error`, and `output` (V1 features)
   - For parent tasks, check if all child runs completed

5. **Extract git state verification data**:
   - For "commit" step: store HEAD commit SHA (from step output if available)
   - For "post-merge" step: store parent branch HEAD SHA
   - Store branch name for worktree verification

6. **Build and return context**

### 1.3 Update StepResult for Skipped State

**File**: `src/agent_arborist/step_results.py`

Add `skipped` field to all result types:

```python
@dataclass
class StepResult:
    """Base result for any step execution."""
    success: bool
    skipped: bool = False
    skip_reason: str | None = None
    timestamp: str | None = None
    metadata: dict = field(default_factory=dict)

    def to_json(self) -> str:
        """Serialize to JSON for Dagu capture."""
        return json.dumps({
            "success": self.success,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        })
```

Update all subclasses (`PreSyncResult`, `RunResult`, `CommitResult`, etc.) to inherit properly.

---

## Phase 2: CLI Command Implementation

### 2.1 Add dag restart Command

**File**: `src/agent_arborist/cli.py`

```python
@dag.command("restart")
@click.argument("spec_name", required=False)
@click.option("--run-id", "-r", help="Dagu run ID to restart (default: latest)")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt (for automated testing)")
@click.pass_context
def dag_restart(ctx: click.Context, spec_name: str | None, run_id: str | None, yes: bool) -> None:
    """Restart a DAG execution, skipping steps that already completed successfully.

    This command analyzes the previous run to determine which steps completed
    successfully. When the DAG runs again, completed steps will be skipped as
    no-ops to save time and resources.

    Automatically selects the appropriate Dagu command based on DAG status:
    - If RUNNING: stops the DAG first, then retries
    - If COMPLETED/FAILED: retries directly

    To start a fresh run without skipping, use: arborist dag run <spec_name>
    """
    from agent_arborist.restart_context import build_restart_context, RestartContext
    from agent_arborist.dagu_runs import list_dag_runs, load_dag_run, DaguStatus
    import subprocess

    # Resolve spec name
    spec_name = spec_name or ctx.obj.get("spec_id")
    if not spec_name:
        console.print("[red]Error:[/red] No spec specified and none detected from git")
        raise SystemExit(1)

    spec_id = spec_name

    dagu_home = Path(ctx.obj.get("dagu_home") or os.environ.get("DAGU_HOME", "~/.config/dagu"))
    dagu_home = dagu_home.expanduser()
    arborist_home = Path(ctx.obj.get("arborist_home"))

    if not arborist_home.exists():
        console.print(f"[red]Error:[/red] Arborist home not found: {arborist_home}")
        raise SystemExit(1)

    # Find source run ID and get its status
    source_run_id, dag_status = _find_source_run_id_and_status(dagu_home, spec_name, run_id)

    console.print(f"[cyan]Analyzing run:[/cyan] {source_run_id} (status: {dag_status.to_name()})")

    # Build restart context
    try:
        context = build_restart_context(spec_name, source_run_id, dagu_home, arborist_home)
    except Exception as e:
        console.print(f"[red]Error building restart context:[/red] {e}")
        raise SystemExit(1)

    # Save context
    context_dir = arborist_home / "restart-contexts"
    context_dir.mkdir(parents=True, exist_ok=True)

    context_file = context_dir / f"{spec_name}_{source_run_id}.json"
    context.save(context_file)

    console.print(f"[green]✓[/green] Restart context saved")

    # Display summary
    _print_restart_summary(context)

    # Confirm unless --yes flag
    if not yes and not click.confirm("\nProceed with restart?"):
        console.print("Cancelled")
        return

    # Select appropriate Dagu command based on status
    env = os.environ.copy()
    env["ARBORIST_RESTART_CONTEXT"] = str(context_file)

    if dag_status == DaguStatus.RUNNING:
        # Stop running DAG first
        console.print(f"\n[cyan]Stopping running DAG...[/cyan]")
        stop_cmd = ["dagu", "stop", spec_name]
        subprocess.run(stop_cmd, env=env)

    # Use dagu retry for the actual restart
    dagu_cmd = ["dagu", "retry", "--run-id", source_run_id, spec_name]

    console.print(f"\n[cyan]Executing:[/cyan] {' '.join(dagu_cmd)}\n")

    result = subprocess.run(dagu_cmd, env=env)

    raise SystemExit(result.returncode)


def _find_source_run_id_and_status(
    dagu_home: Path, spec_name: str, provided_run_id: str | None
) -> tuple[str, DaguStatus]:
    """Find the run ID to restart from and its current status."""
    from agent_arborist.dagu_runs import list_dag_runs, load_dag_run, DaguStatus

    if provided_run_id:
        # Load the specific run to get its status
        dag_run = load_dag_run(dagu_home, spec_name, provided_run_id)
        if not dag_run or not dag_run.latest_attempt:
            console.print(f"[red]Error:[/red] Run {provided_run_id} not found")
            raise SystemExit(1)
        return provided_run_id, dag_run.latest_attempt.status

    # Try current running run first
    running_runs = list_dag_runs(dagu_home, spec_name, status=DaguStatus.RUNNING, limit=1)
    if running_runs:
        run = running_runs[0]
        console.print(f"[dim]Using current running run:[/dim] {run.run_id}")
        return run.run_id, DaguStatus.RUNNING

    # Use latest run (any status)
    latest_runs = list_dag_runs(dagu_home, spec_name, limit=1)
    if latest_runs:
        run = latest_runs[0]
        status = run.latest_attempt.status if run.latest_attempt else DaguStatus.PENDING
        console.print(f"[dim]Using latest run:[/dim] {run.run_id}")
        return run.run_id, status

    console.print("[red]Error:[/red] No previous run found")
    console.print("[dim]Hint: Use 'arborist dag run <spec>' to start a new run[/dim]")
    raise SystemExit(1)


def _print_restart_summary(context: RestartContext) -> None:
    """Print summary of what will be skipped vs run."""
    from rich.table import Table

    table = Table(title="Restart Summary")
    table.add_column("Task", style="cyan")
    table.add_column("Status", style="magenta")
    table.add_column("Steps Completed", justify="right")
    table.add_column("Steps to Run", justify="right")

    total_completed = 0
    total_to_run = 0

    for task_id, task_ctx in sorted(context.tasks.items()):
        completed = sum(1 for s in task_ctx.steps.values() if s.completed)
        to_run = len(task_ctx.steps) - completed

        total_completed += completed
        total_to_run += to_run

        total = len(task_ctx.steps)
        status = "✓ Complete" if to_run == 0 else "○ Partial"

        table.add_row(
            task_id,
            status,
            f"{completed}/{total}",
            f"{to_run}" if to_run > 0 else "—",
        )

    console.print(table)

    console.print(f"\n[bold]Total:[/bold] {total_completed} steps already complete, {total_to_run} to run")

    if total_to_run == 0:
        console.print("[yellow]Warning:[/yellow] All steps already complete. Consider running a fresh DAG instead.")
```

---

## Phase 3: Step-Level Skip Logic

### 3.1 Integrity Verification Functions

**File**: `src/agent_arborist/restart_context.py`

```python
def verify_step_integrity(task_id: str, step_name: str, context: RestartContext) -> tuple[bool, str | None]:
    """Verify that a step's claimed completion is still valid.

    Args:
        task_id: Task to verify
        step_name: Step to verify
        context: Restart context with completion data

    Returns:
        (valid, error) - True if valid, False with error message if invalid
    """
    task_ctx = context.tasks.get(task_id)
    if not task_ctx:
        return False, f"Task {task_id} not found in context"

    step_state = task_ctx.steps.get(step_name)
    if not step_state:
        return False, f"Step {step_name} not found in context"

    # Different verification strategies per step type
    if step_name == "commit":
        # Verify git commit exists and matches expected SHA
        return _verify_commit_integrity(task_ctx)

    elif step_name == "pre-sync":
        # Verify worktree exists and has correct branch
        return _verify_worktree_integrity(task_ctx)

    elif step_name == "run":
        # Verify commit exists (run creates a commit)
        return _verify_commit_integrity(task_ctx, require_commit=True)

    elif step_name in ("run-test", "post-merge"):
        # Verify task is marked complete in state
        return _verify_task_state_integrity(task_id, context)

    elif step_name == "post-cleanup":
        # Worktree should NOT exist (cleanup removes it)
        return _verify_cleanup_integrity(task_id, context)

    # Default: assume valid
    return True, None


def _verify_commit_integrity(task_ctx: TaskRestartContext, require_commit: bool = True) -> tuple[bool, str | None]:
    """Verify git state matches commit expectations."""
    if not task_ctx.head_commit_sha:
        return False, "No commit SHA recorded"

    worktree_path = _get_worktree_path(task_ctx.spec_id, task_ctx.task_id)

    if not worktree_path.exists():
        return False, f"Worktree not found at {worktree_path}"

    # Check HEAD commit
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return False, "Cannot get HEAD commit"

    current_sha = result.stdout.strip()

    if current_sha != task_ctx.head_commit_sha:
        return False, f"HEAD commit mismatch: expected {task_ctx.head_commit_sha[:8]}, got {current_sha[:8]}"

    return True, None


def _verify_worktree_integrity(task_ctx: TaskRestartContext) -> tuple[bool, str | None]:
    """Verify worktree exists and is on correct branch."""
    worktree_path = _get_worktree_path(task_ctx.spec_id, task_ctx.task_id)

    if not worktree_path.exists():
        return False, f"Worktree not found at {worktree_path}"

    if not task_ctx.branch_name:
        return False, f"No branch name recorded for task {task_ctx.task_id}"

    # Check current branch
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return False, "Cannot get current branch"

    current_branch = result.stdout.strip()

    if current_branch != task_ctx.branch_name:
        return False, f"Branch mismatch: expected {task_ctx.branch_name}, got {current_branch}"

    return True, None


def _verify_cleanup_integrity(task_id: str, context: RestartContext) -> tuple[bool, str | None]:
    """Verify cleanup was performed (worktree removed)."""
    worktree_path = _get_worktree_path(context.spec_id, task_id)

    if worktree_path.exists():
        return False, f"Worktree still exists at {worktree_path}, cleanup not completed"

    return True, None


def _verify_task_state_integrity(task_id: str, context: RestartContext) -> tuple[bool, str | None]:
    """Verify task state file indicates completion."""
    task_tree = load_task_tree(context.spec_id)
    if not task_tree:
        return False, "Cannot load task tree"

    task = task_tree.get_task(task_id)
    if not task:
        return False, f"Task {task_id} not found in tree"

    if task.status not in ("complete", "running"):
        return False, f"Task status is {task.status}, not complete or running"

    return True, None
```

### 3.2 Check and Skip Logic

```python
def should_skip_step(task_id: str, step_name: str) -> tuple[bool, str | None]:
    """Determine if a step should be skipped based on restart context.

    Returns:
        (should_skip, error_message)
    """
    context_path = os.environ.get("ARBORIST_RESTART_CONTEXT")
    if not context_path:
        return False, None  # No restart context, run normally

    try:
        context = RestartContext.load(Path(context_path))
    except Exception as e:
        console.print(f"[yellow]Warning:[/yellow] Failed to load restart context: {e}")
        return False, None

    task_ctx = context.tasks.get(task_id)
    if not task_ctx:
        return False, f"Task {task_id} not found in restart context"

    step_state = task_ctx.steps.get(step_name)
    if not step_state or not step_state.completed:
        return False, f"Step {step_name} not marked as completed"

    # Verify integrity
    valid, error = verify_step_integrity(task_id, step_name, context)
    if not valid:
        console.print(f"[yellow]Warning:[/yellow] Integrity check failed: {error}")
        console.print(f"[dim]Re-running {step_name} to ensure correctness[/dim]")
        return False, None

    return True, f"Step completed at {step_state.completed_at}"
```

### 3.3 Integrate Skip Logic into Task Commands

**File**: `src/agent_arborist/cli.py`

Add helper function:

```python
def _check_skip_and_output(task_id: str, step_name: str, result_type: type) -> bool:
    """Check if step should be skipped. Returns True if skipped."""
    should_skip, reason = should_skip_step(task_id, step_name)

    if should_skip:
        # Output skipped result
        result = result_type(
            success=True,
            skipped=True,
            skip_reason=reason,
            timestamp=datetime.now().isoformat(),
        )
        output_result(result, click.get_current_context())
        console.print(f"[dim]✓ Skipped {step_name}:[/dim] {reason}")
        return True

    if reason:
        console.print(f"[dim]→ Running {step_name}:[/dim] {reason}")

    return False
```

Modify each task command (example for `task_pre_sync`):

```python
@task.command("pre-sync")
@click.argument("task_id")
@click.pass_context
def task_pre_sync(ctx: click.Context, task_id: str) -> None:
    """Create worktree and sync from parent for a task."""

    # Skip check
    if _check_skip_and_output(task_id, "pre-sync", PreSyncResult):
        return

    # ... existing implementation ...
```

Apply pattern to:
- `task_run` (step_name="run")
- `task_commit` (step_name="commit")
- `task_run_test` (step_name="run-test")
- `task_post_merge` (step_name="post-merge")
- `task_post_cleanup` (step_name="post-cleanup")
- `task_container_up` (step_name="container-up")
- `task_container_stop` (step_name="container-stop")

---

## Phase 4: DAG Generation Updates

### 4.1 Auto-Detect Restart Context

**File**: `src/agent_arborist/dag_builder.py`

```python
def find_latest_restart_context(spec_id: str, arborist_home: Path) -> Path | None:
    """Find the most recent restart context for a spec."""
    context_dir = arborist_home / "restart-contexts"
    if not context_dir.exists():
        return None

    contexts = sorted(context_dir.glob(f"{spec_id}_*.json"), reverse=True)
    return contexts[0] if contexts else None


class SubDagBuilder:
    def _build_root_dag(self, task_tree: TaskTree) -> SubDag:
        """Build root DAG with optional restart context."""
        spec_id = self.config.spec_id or self.config.name
        arborist_home = get_arborist_home()

        env = [
            f"ARBORIST_MANIFEST={spec_id}.json",
            f"ARBORIST_CONTAINER_MODE={self.config.container_mode.value}",
        ]

        # Auto-detect and add restart context if exists
        restart_context = find_latest_restart_context(spec_id, arborist_home)
        if restart_context:
            env.append(f"ARBORIST_RESTART_CONTEXT={restart_context}")
            console.print(f"[dim]Using restart context:[/dim] {restart_context}")

        # ... rest of implementation ...
```

---

## Testing Scenarios

### Testing Strategy

**Approach**: Use arborist-generated DAGs with `--echo-only` mode (Option B)
- Generate real multi-level DAGs via `spec dag-build --echo-only`
- The `--echo-for-testing` flag makes arborist commands return immediately
- Tests the full step structure (pre-sync → run → commit → etc.)
- Inject failures by having specific echo steps return non-zero exit codes
- Git operations are REAL (worktrees, branches, commits)
- AI runner is MOCKED via echo mode

**Test Infrastructure Requirements**:
- Each test creates its own temporary git repository
- Arborist is initialized in each temp repo
- Some tests include `.devcontainer` configurations
- All tests use real Dagu execution (not mocked)

### Required: 8 Real Dagu Run Scenarios

**File**: `tests/test_restart_e2e.py`

These tests MUST execute real Dagu runs. The AI runner is mocked via echo mode, but Dagu execution is real.

#### Scenario 1: Full Success → Restart All Skipped
```python
def test_restart_full_success_all_skipped(git_repo, dagu_home):
    """All steps complete → restart skips everything."""
    # Setup: Create 3-task spec, build DAG with echo-only
    # Run: Execute DAG to full completion
    # Action: arborist dag restart --yes
    # Assert: All steps output skipped=True
    # Assert: Restart completes in <5 seconds
    # Assert: Git state unchanged (same commit SHAs)
```

#### Scenario 2: Fail at Run Step → Restart Resumes
```python
def test_restart_fail_at_run_step(git_repo, dagu_home):
    """Failure at T002.run → restart skips T001, re-runs T002."""
    # Setup: Create spec where T002.run exits with code 1
    # Run: Execute DAG (T001 succeeds, T002.run fails)
    # Action: Fix T002.run to succeed, then restart
    # Assert: T001.* steps all skipped
    # Assert: T002.pre-sync skipped, T002.run re-executed
    # Assert: T002 completes successfully
```

#### Scenario 3: Fail at Commit Step → Preserves Pre-Work
```python
def test_restart_fail_at_commit_step(git_repo, dagu_home):
    """Failure at T001.commit → restart skips pre-sync and run."""
    # Setup: Create spec where T001.commit exits with code 1
    # Run: Execute DAG (pre-sync and run succeed, commit fails)
    # Action: Fix commit, restart
    # Assert: T001.pre-sync skipped
    # Assert: T001.run skipped (work preserved)
    # Assert: T001.commit re-executed
```

#### Scenario 4: Fail at Test Step → Re-run Tests Only
```python
def test_restart_fail_at_test_step(git_repo, dagu_home):
    """Failure at T001.run-test → restart skips run/commit, re-runs test."""
    # Setup: Create spec where T001.run-test exits with code 1
    # Run: Execute DAG (run and commit succeed, test fails)
    # Action: Restart
    # Assert: T001.run skipped (commit exists)
    # Assert: T001.commit skipped
    # Assert: T001.run-test re-executed
```

#### Scenario 5: Parent Task with Child Failure
```python
def test_restart_parent_with_child_failure(git_repo, dagu_home):
    """Parent P001 with children C001, C002 - C002 fails."""
    # Setup: Create parent-child spec, C002.run fails
    # Run: Execute DAG (C001 completes, C002 fails, P001 waiting)
    # Action: Fix C002, restart
    # Assert: C001.* all skipped
    # Assert: C002.pre-sync skipped, C002.run re-executed
    # Assert: P001 proceeds after C002 completes
```

#### Scenario 6: Integrity Check Fails (Worktree Deleted)
```python
def test_restart_integrity_fail_worktree_deleted(git_repo, dagu_home):
    """Worktree manually deleted → integrity fails → re-runs pre-sync."""
    # Setup: Run DAG to completion
    # Corrupt: Manually delete T001's worktree directory
    # Action: Restart
    # Assert: Warning logged about integrity failure
    # Assert: T001.pre-sync re-executed (worktree recreated)
    # Assert: Subsequent steps succeed
```

#### Scenario 7: Multiple Sequential Restarts
```python
def test_restart_multiple_sequential(git_repo, dagu_home):
    """Multiple restarts accumulate skipped steps correctly."""
    # Setup: 5-task spec, T003.run fails
    # Run 1: T001, T002 complete, T003 fails
    # Restart 1: Fix T003, run → T001/T002 skipped, T003 re-runs
    # Corrupt: Make T005.run fail
    # Run continues: T003, T004 complete, T005 fails
    # Restart 2: Fix T005, run → T001-T004 skipped, T005 re-runs
    # Assert: No duplicate work across restarts
    # Assert: Final git state correct
```

#### Scenario 8: Container Mode with Devcontainer
```python
def test_restart_with_devcontainer(git_repo_with_devcontainer, dagu_home):
    """Container mode restart handles container-up/stop correctly."""
    # Setup: Spec with devcontainer enabled, container-up fails
    # Run: Execute DAG (container-up fails)
    # Action: Fix container, restart
    # Assert: container-up re-executed
    # Assert: Subsequent container steps work
    # Assert: No port conflicts
```

### Unit Tests

**File**: `tests/test_restart_context.py`

#### Test Cases

1. **`test_build_restart_context_from_successful_run`**
   - Create a fully successful DAG run
   - Build restart context
   - Assert all tasks marked complete
   - Assert all steps completed=True

2. **`test_build_restart_context_from_failed_run`**
   - Create a DAG run with one task failing at "run" step
   - Build restart context
   - Assert failed step has completed=False
   - Assert earlier steps (pre-sync, container-up if any) have completed=True

3. **`test_build_restart_context_parent_task_children_complete`**
   - Create parent task with 3 child tasks all complete
   - Build restart context
   - Assert parent's children_complete=True

4. **`test_build_restart_context_parent_task_child_incomplete`**
   - Create parent task with one child incomplete
   - Build restart context
   - Assert parent's children_complete=False

5. **`test_restart_context_serialization`**
   - Create complex restart context
   - Serialize to JSON
   - Deserialize
   - Assert all fields preserved
   - Test datetime roundtrip

6. **`test_should_skip_step_completed`**
   - Mock restart context with step marked complete
   - Mock successful integrity verification
   - Assert should_skip=True

7. **`test_should_skip_step_not_completed`**
   - Mock restart context with step not completed
   - Assert should_skip=False

8. **`test_should_skip_step_integrity_failed`**
   - Mock restart context with step marked complete
   - Mock failed integrity verification
   - Assert should_skip=False

9. **`test_should_skip_no_context`**
   - No ARBORIST_RESTART_CONTEXT set
   - Assert should_skip=False

10. **`test_verify_commit_integrity_success`**
    - Mock worktree with expected commit SHA
    - Assert verification passes

11. **`test_verify_commit_integrity_wrong_sha`**
    - Mock worktree with different HEAD commit
    - Assert verification fails with error

12. **`test_verify_worktree_integrity_success`**
    - Mock worktree with correct branch
    - Assert verification passes

13. **`test_verify_worktree_integrity_wrong_branch`**
    - Mock worktree on wrong branch
    - Assert verification fails

14. **`test_verify_cleanup_integrity_worktree_removed`**
    - Mock worktree path not existing
    - Assert verification passes

15. **`test_verify_cleanup_integrity_worktree_exists`**
    - Mock worktree path still existing
    - Assert verification fails

16. **`test_find_source_run_id_provided`**
    - Test function with provided run_id
    - Assert returns provided run_id

17. **`test_find_source_run_id_current_running`**
    - Mock running run exists
    - Assert finds and returns running run_id

18. **`test_find_source_run_id_latest`**
    - Mock no running runs, with latest run
    - Assert returns latest run_id

19. **`test_find_source_run_id_none_found`**
    - Mock no runs at all
    - Assert raises SystemExit

---

### Integration Tests

**File**: `tests/test_restart_integration.py`

#### Test Cases

1. **`test_restart_full_run_all_skipped`**
   - Setup: Create spec, run DAG to completion successfully
   - Action: Run `arborist dag restart <spec>`
   - Assert: All steps are skipped (no actual work done)
   - Assert: Restart completes quickly (under 5s)
   - Assert: All steps output `skipped=True`

2. **`test_restart_partial_completion_skips_only_completed`**
   - Setup: Create spec, interrupt during task T002 "run" step
   - Action: Run `arborist dag restart <spec>`
   - Assert: T001 steps are all skipped
   - Assert: T002's pre-sync is skipped, run is re-executed
   - Assert: T002 completes successfully
   - Assert: Subsequent tasks process normally

3. **`test_restart_after_failure_at_run_step`**
   - Setup: Cause failure at task T003 "run" step (AI error)
   - Action: Run `arborist dag restart <spec>`
   - Assert: All prior tasks' steps skipped
   - Assert: T003's pre-sync skipped, run executes again
   - Assert: No duplicate commits created

4. **`test_restart_after_failure_at_test_step`**
   - Setup: Run DAG, cause test failure at T004 "run-test"
   - Action: Run `arborist dag restart <spec>`
   - Assert: T004's run step is skipped (already committed)
   - Assert: T004's run-test re-executes

5. **`test_restart_parent_task_with_all_children_complete`**
   - Setup: Parent task P002 with children T005, T006, T007 all complete
   - Action: Interrupt at P002's "post-merge" step
   - Action: Restart
   - Assert: All children' steps skipped
   - Assert: P002's run-test skipped (children complete)
   - Assert: P002's post-merge re-executes

6. **`test_restart_parent_task_with_incomplete_child`**
   - Setup: Parent with 3 children, T008 failed mid-run
   - Action: Restart
   - Assert: T008's pre-sync skipped, run re-executes
   - Assert: Parent's steps run normally (not skipped)

7. **`test_restart_with_git_state_corruption`**
   - Setup: Complete run, but manually modify HEAD commit in worktree
   - Action: Restart
   - Assert: Step that depends on git (commit, run) is re-executed
   - Assert: Integrity check failure logged

8. **`test_restart_with_worktree_deleted`**
   - Setup: Complete run, then manually delete worktree directory
   - Action: Restart
   - Assert: pre-sync step is re-executed (worktree recreated)

9. **`test_restart_with_branch_switched`**
   - Setup: Complete run, switch worktree to different branch
   - Action: Restart
   - Assert: pre-sync re-executes (branch mismatch detected)

10. **`test_restart_creates_new_run_id`**
    - Setup: Run DAG, get run ID
    - Action: Restart
    - Assert: New run ID generated (different from original)
    - Assert: Original run history unchanged

11. **`test_restart_multiple_times`**
    - Setup: Run DAG
    - Action: Restart (partial completion)
    - Action: Restart again
    - Assert: Each restart skips appropriate steps
    - Assert: No duplicate work across restarts

12. **`test_restart_specifies_run_id`**
    - Setup: Create 3 runs of same DAG (successful, failed, running)
    - Action: Restart with `--run-id` pointing to failed run
    - Assert: Correct run's completion state used

13. **`test_restart_output_format_json`**
    - Setup: Partially completed DAG
    - Action: Restart with `--format json`
    - Assert: Skipped steps output proper JSON with skipped=True

14. **`test_restart_output_format_text`**
    - Setup: Partially completed DAG
    - Action: Restart with `--format text`
    - Assert: Human-readable output shows skipped steps

15. **`test_restart_without_prior_run`**
    - Setup: Spec exists but no DAG runs
    - Action: Try restart
    - Assert: Error message displayed
    - Assert: Exit code 1

---

### Edge Case Tests

1. **`test_restart_with_container_mode_enabled`**
   - Setup: Spec with devcontainer, run to completion
   - Action: Restart
   - Assert: container-up/stop steps properly detected and skipped
   - Assert: Containers not restarted unnecessarily

2. **`test_restart_with_container_stopped_manually`**
   - Setup: Run with containers, complete, manually stop containers
   - Action: Restart
   - Assert: Integrity check detects containers stopped
   - Assert: container-up may need to re-run (if verification fails)

3. **`test_restart_with_orphaned_restart_context`**
   - Setup: Restart context file exists but source run deleted
   - Action: Try restart
   - Assert: Graceful error handling
   - Assert: Suggests using `arborist dag start` instead

4. **`test_restart_context_very_old`**
   - Setup: Create restart context from run 7 days ago
   - Action: Restart
   - Assert: Warning about stale context
   - Assert: Still proceeds if integrity checks pass

5. **`test_restart_with_concurrent_access`**
   - Setup: Have one restart in progress
   - Action: Start second restart simultaneously
   - Assert: No corruption of restart context or run state

6. **`test_restart_with_corrupted_context_file`**
   - Setup: Create invalid JSON in restart context file
   - Action: Restart
   - Assert: Error message about corrupted context
   - Assert: Fallback to normal execution (no skip)

7. **`test_restart_with_multiple_task_trees`**
   - Setup: Multiple specs sharing same arborist home
   - Action: Restart one spec
   - Assert: Only that spec's context used
   - Assert: Other spec's tasks unaffected

8. **`test_restart_task_not_in_manifest`**
   - Setup: Restart context references task T999 not in current manifest
   - Action: Restart
   - Assert: Warning about missing task
   - Assert: Excludes task from further checks

9. **`test_restart_step_name_mismatch`**
   - Setup: Step in context named differently than expected
   - Action: Restart
   - Assert: Graceful handling, step runs normally

10. **`test_restart_with_file_permission_issues`**
    - Setup: Make restart context file read-only
    - Action: Restart
    - Assert: Handles gracefully (reads but doesn't try to modify)

---

### Manual Testing Scenarios

#### Scenario 1: Happy Path - Full Completion Skip

**Objective**: Verify normal restart flow with all steps skipped

**Steps**:
1. Create simple spec with 2 tasks: T001 (add feature), T002 (refactor)
2. Run: `arborist dag start my-spec`
3. Wait for completion (both tasks success)
4. Check: `arborist dag status my-spec` - shows complete
5. Run: `arborist dag restart my-spec`
6. Observe output showing all steps skipped
7. Verify restart completes in <5 seconds
8. Check no new commits created

**Success Criteria**: All steps marked skipped, no duplicate work

---

#### Scenario 2: Partial Failure - AI Runner Timeout

**Objective**: Verify restart after AI timeout, skipping completed work

**Steps**:
1. Create spec with 3 tasks: T001, T002, T003
2. Run: `arborist dag start my-spec`
3. Wait for T001 and T002 to complete
4. Cause T003 to fail (e.g., set short timeout, slow task)
5. Cancel or let fail
6. Check status: T001/T002 complete, T003 failed
7. Run: `arborist dag restart my-spec`
8. Observe: T001/T002 steps skipped, T003 re-runs
9. Fix timeout issue (increase), restart again if needed

**Success Criteria**: Completed tasks skipped, only failed task re-runs

---

#### Scenario 3: Test Failure Scenario

**Objective**: Verify restart after test failure preserves code changes

**Steps**:
1. Spec with task requiring tests
2. Initial run completes "run" (AI makes changes) with buggy code
3. "run-test" step fails
4. Restart: `arborist dag restart my-spec`
5. Observe: "run" step skipped (commit exists), "run-test" re-runs
6. Manually fix code in worktree
7. Run tests again manually, they pass
8. Restart: skip "run" now, "run-test" passes
9. DAG continues to post-merge

**Success Criteria**: Code preserved across restart, only test re-runs

---

#### Scenario 4: Parent Task with Child Failures

**Objective**: Verify restart handles parent-child dependencies correctly

**Steps**:
1. Spec with parent task P001 and 3 children: C001, C002, C003
2. Run DAG, let C002 fail mid-execute
3. Parent P001 waiting for children, stuck
4. Restart: `arborist dag restart my-spec`
5. Observe: C001 and C003 steps skipped (already complete)
6. C002 re-runs from pre-sync
7. After C002 completes, P002 proceeds
8. Parent's run-test skipped (all children now complete)

**Success Criteria**: Child restarts properly, parent continues after children complete

---

#### Scenario 5: Integrity Check Failures

**Objective**: Verify restart detects and handles integrity issues

**Steps**:
1. Run spec to completion
2. Manually modify T001's HEAD commit (e.g., `git reset --hard HEAD~1`)
3. Run: `arborist dag restart my-spec`
4. Observe warning about integrity failure
5. T001's "commit" and/or "run" steps re-run
6. Verify correct behavior after integrity issues

**Success Criteria**: Integrity failures trigger re-run, proper warnings displayed

---

#### Scenario 6: Container Mode Restart

**Objective**: Verify containers handled correctly in restart

**Steps**:
1. Spec with devcontainer enabled
2. Run to completion
3. Verify containers stopped after cleanup
4. Restart: `arborist dag restart my-spec`
5. Observe container-up/stop steps skipped
6. Verify no container conflicts (ports already in use)

**Success Criteria**: Container steps properly skipped, no container conflicts

---

#### Scenario 7: Branch-Switched Worktree

**Objective**: Verify restart detects worktree branch changes

**Steps**:
1. Run spec, T001 creates worktree on branch task-T001
2. Complete successfully
3. Manually switch worktree to main: `git checkout main`
4. Restart: `arborist dag restart my-spec`
5. Observe: pre-sync re-runs (branch integrity check fails)
6. Worktree recreated on correct branch
7. DAG continues

**Success Criteria**: Branch changes detected, worktree rebuilt correctly

---

#### Scenario 8: Multiple Sequential Restarts

**Objective**: Verify system handles multiple restarts gracefully

**Steps**:
1. Run spec with 5 tasks
2. Interrupt at task T003
3. Restart #1: Should skip T001/T002, resume at T003
4. Let T003 complete, interrupt at T005
5. Restart #2: Should skip T001/T002/T003/T004, resume at T005
6. Verify restart contexts are all valid
7. Verify no duplicate work across restarts

**Success Criteria**: Each restart correctly skips only completed work

---

#### Scenario 9: Stale Context Warning

**Objective**: Verify warning for old restart contexts

**Steps**:
1. Run DAG to completion 14 days ago
2. Restart: `arborist dag restart my-spec`
3. Observe warning about stale context (>7 days old)
4. Confirm to proceed
5. Verify restart still works if integrity checks pass

**Success Criteria**: Warning displayed for old contexts, still functional

---

#### Scenario 10: No Prior Run Error

**Objective**: Verify error handling for new specs

**Steps**:
1. Create new spec that has never been run
2. Run: `arborist dag restart my-spec`
3. Observe error message: "No previous run found"
4. Suggestion to use `arborist dag start` instead

**Success Criteria**: Clear error message, helpful suggestion

---

## Implementation Checklist

**IMPORTANT**: No deviation from this plan without human approval.

- [ ] Phase 1: Core Infrastructure
  - [ ] Create `restart_context.py` module
  - [ ] Implement data structures with JSON I/O (full step names like `T001.pre-sync`)
  - [ ] Implement `build_restart_context()` function with `include_outputs=True`
  - [ ] Add `skipped` field to `StepResult` base class
  - [ ] Update all StepResult subclasses

- [ ] Phase 2: CLI Command
  - [ ] Add `dag restart` command to `cli.py`
  - [ ] Add `--yes` / `-y` flag for non-interactive mode
  - [ ] Implement `_find_source_run_id_and_status()` helper
  - [ ] Implement status-aware Dagu command selection (restart vs retry)
  - [ ] Implement `_print_restart_summary()` helper

- [ ] Phase 3: Skip Logic
  - [ ] Implement integrity verification functions (real git checks)
  - [ ] Implement `should_skip_step()` function
  - [ ] Add `_check_skip_and_output()` helper to CLI
  - [ ] Integrate skip check into all task commands:
    - [ ] `task_pre_sync`
    - [ ] `task_run`
    - [ ] `task_commit`
    - [ ] `task_run_test`
    - [ ] `task_post_merge`
    - [ ] `task_post_cleanup`
    - [ ] `task_container_up`
    - [ ] `task_container_stop`

- [ ] Phase 4: DAG Generation
  - [ ] Implement `find_latest_restart_context()` helper
  - [ ] Update `_build_root_dag()` to auto-detect context
  - [ ] Add restart context to DAG env variables

- [ ] Phase 5: Testing (8 Real Dagu Runs Required)
  - [ ] Create test fixtures with temp git repos
  - [ ] Create devcontainer fixture for Scenario 8
  - [ ] Implement all 8 e2e test scenarios:
    - [ ] Scenario 1: Full success → all skipped
    - [ ] Scenario 2: Fail at run step
    - [ ] Scenario 3: Fail at commit step
    - [ ] Scenario 4: Fail at test step
    - [ ] Scenario 5: Parent with child failure
    - [ ] Scenario 6: Integrity check fails (worktree deleted)
    - [ ] Scenario 7: Multiple sequential restarts
    - [ ] Scenario 8: Container mode with devcontainer
  - [ ] Write unit tests for restart_context.py
  - [ ] Write unit tests for integrity verification

- [ ] Phase 6: Documentation
  - [ ] Add `arborist dag restart` to README
  - [ ] Document `--yes` flag
  - [ ] Document restart vs retry behavior

---

## Future Enhancements

### Retry Specific Step

```bash
arborist dag retry --step T003:commit my-spec
```

Re-run only a specific step for a task, useful for targeted fixes.

### Interactive Restart

```bash
arborist dag restart --interactive my-spec
```

Show table of steps with completion status, let user select which to skip vs re-run.

### Restart Point-in-Time

```bash
arborist dag restart --at "2024-01-15T10:30:00" my-spec
```

Restart from a specific historical snapshot, not just latest run.

### Dry-Run Restart

```bash
arborist dag restart --dry-run my-spec
```

Show what would be skipped vs re-run without actually executing.

### Restart Cleanup

```bash
arborist dag restart-contexts cleanup --older-than 7d
```

Clean up stale restart context files to save disk space.

### Progress Resumption

Track checkpoints mid-task (e.g., after every file operation in AI runner) to allow resuming from mid-point, not just step boundaries.

### Metrics Collection

Track restart statistics:
- Average restart time saved
- Most commonly failed steps
- Cost savings from rerunning AI agents

---

## Notes and Considerations

1. **Performance**: Restart context building should be fast (<1s for typical specs)
2. **Disk Usage**: Restart contexts are small (~10-100KB), but implement cleanup for old ones
3. **Concurrency**: Restart context files are read-only during execution, no locking needed
4. **Error Handling**: Graceful degradation if restart context missing or corrupted
5. **Backward Compatibility**: Existing DAGs continue to work without restart support
6. **Testing Priority**: Integration tests most critical to verify end-to-end behavior

---

## References

- Dagu restart command: `docs/restart-research.md`
- Dagu status.jsonl format: analyzed in `dagu_runs.py`
- Task tree structure: `task_state.py`
- DAG generation: `dag_builder.py`
- Step result types: `step_results.py`