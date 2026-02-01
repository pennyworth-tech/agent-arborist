"""Restart context for DAG execution with idempotent step checking.

This module provides:
- Data structures for tracking step completion state
- Building restart context from Dagu run history
- Integrity verification for completed steps
- Skip logic for step execution
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console

from agent_arborist.dagu_runs import (
    DagRun,
    DaguStatus,
    load_dag_run,
)

console = Console(stderr=True)

# Step types that can be tracked for restart
STEP_TYPES = {
    "pre-sync",
    "container-up",
    "run",
    "commit",
    "run-test",
    "post-merge",
    "container-stop",
    "post-cleanup",
}


def extract_step_type(full_step_name: str) -> str | None:
    """Extract step type from full name like 'T001.pre-sync' -> 'pre-sync'.

    Also handles step names without task prefix (e.g., 'pre-sync' -> 'pre-sync').
    """
    for step_type in STEP_TYPES:
        if full_step_name.endswith(f".{step_type}") or full_step_name == step_type:
            return step_type
    return None


def extract_task_id(full_step_name: str) -> str | None:
    """Extract task ID from full name like 'T001.pre-sync' -> 'T001'.

    Returns None if no task prefix found.
    """
    if "." in full_step_name:
        return full_step_name.rsplit(".", 1)[0]
    return None


@dataclass
class StepCompletionState:
    """Completion state for a step in a task."""

    full_step_name: str  # Full qualified: "T001.pre-sync", "T001.run", etc.
    step_type: str  # Step type: "pre-sync", "run", "commit", etc.
    completed: bool
    completed_at: datetime | None
    dag_run_id: str
    status: str  # "success", "failed", "running", "skipped", "pending"
    exit_code: int | None = None  # Exit code from Dagu (V1 feature)
    error: str | None = None  # Error message if failed (V1 feature)
    output: dict | None = None  # Captured output from outputs.json (V1 feature)

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "full_step_name": self.full_step_name,
            "step_type": self.step_type,
            "completed": self.completed,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "dag_run_id": self.dag_run_id,
            "status": self.status,
            "exit_code": self.exit_code,
            "error": self.error,
            "output": self.output,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StepCompletionState:
        """Create from JSON dict."""
        completed_at = None
        if data.get("completed_at"):
            completed_at = datetime.fromisoformat(data["completed_at"])

        return cls(
            full_step_name=data["full_step_name"],
            step_type=data["step_type"],
            completed=data["completed"],
            completed_at=completed_at,
            dag_run_id=data["dag_run_id"],
            status=data["status"],
            exit_code=data.get("exit_code"),
            error=data.get("error"),
            output=data.get("output"),
        )


@dataclass
class TaskRestartContext:
    """Restart context for a single task."""

    spec_id: str
    task_id: str
    run_id: str  # Previous Dagu run ID
    overall_status: str  # "complete", "failed", "running", "partial"
    steps: dict[str, StepCompletionState]  # full_step_name -> state
    children_complete: bool  # For parent tasks: did all children complete?
    branch_name: str | None = None  # For git verification
    head_commit_sha: str | None = None  # For git state verification

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "spec_id": self.spec_id,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "overall_status": self.overall_status,
            "steps": {k: v.to_dict() for k, v in self.steps.items()},
            "children_complete": self.children_complete,
            "branch_name": self.branch_name,
            "head_commit_sha": self.head_commit_sha,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskRestartContext:
        """Create from JSON dict."""
        return cls(
            spec_id=data["spec_id"],
            task_id=data["task_id"],
            run_id=data["run_id"],
            overall_status=data["overall_status"],
            steps={k: StepCompletionState.from_dict(v) for k, v in data["steps"].items()},
            children_complete=data["children_complete"],
            branch_name=data.get("branch_name"),
            head_commit_sha=data.get("head_commit_sha"),
        )


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

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "spec_name": self.spec_name,
            "spec_id": self.spec_id,
            "arborist_home": str(self.arborist_home),
            "dagu_home": str(self.dagu_home),
            "source_run_id": self.source_run_id,
            "created_at": self.created_at.isoformat(),
            "tasks": {tid: ctx.to_dict() for tid, ctx in self.tasks.items()},
            "root_dag_status": self.root_dag_status.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RestartContext:
        """Create from JSON dict."""
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
    def load(cls, path: Path) -> RestartContext:
        """Load context from file."""
        data = json.loads(path.read_text())
        return cls.from_dict(data)


def _extract_task_contexts_from_dag_run(
    dag_run: DagRun,
    spec_id: str,
    tasks: dict[str, TaskRestartContext],
) -> None:
    """Recursively extract task contexts from a DAG run and its children.

    Args:
        dag_run: The DAG run to process
        spec_id: The spec ID
        tasks: Dict to populate with task contexts (mutated)
    """
    if not dag_run.latest_attempt:
        return

    # Process steps in this DAG run
    for step in dag_run.latest_attempt.steps:
        step_type = extract_step_type(step.name)
        if not step_type:
            continue

        # Extract task ID from step name or DAG name
        task_id = extract_task_id(step.name)
        if not task_id:
            # Try to get task ID from DAG name (for sub-DAGs)
            # Sub-DAGs are named like "T001" or "c-T001"
            dag_name = dag_run.dag_name
            if dag_name.startswith("c-"):
                task_id = dag_name[2:]  # Remove "c-" prefix
            else:
                task_id = dag_name

        if not task_id:
            continue

        # Create or get task context
        if task_id not in tasks:
            tasks[task_id] = TaskRestartContext(
                spec_id=spec_id,
                task_id=task_id,
                run_id=dag_run.run_id,
                overall_status="pending",
                steps={},
                children_complete=True,  # Will be updated below
            )

        task_ctx = tasks[task_id]

        # Create step completion state
        completed = step.status == DaguStatus.SUCCESS
        step_state = StepCompletionState(
            full_step_name=step.name,
            step_type=step_type,
            completed=completed,
            completed_at=step.finished_at,
            dag_run_id=dag_run.run_id,
            status=step.status.to_name(),
            exit_code=step.exit_code,
            error=step.error,
            output=step.output,
        )

        task_ctx.steps[step.name] = step_state

        # Update overall status
        if step.status == DaguStatus.SUCCESS:
            if task_ctx.overall_status == "pending":
                task_ctx.overall_status = "partial"
        elif step.status == DaguStatus.FAILED:
            task_ctx.overall_status = "failed"
        elif step.status == DaguStatus.RUNNING:
            task_ctx.overall_status = "running"

        # Extract git info from commit step output if available
        if step_type == "commit" and step.output:
            task_ctx.head_commit_sha = step.output.get("commit_sha")

        # Extract branch info from pre-sync step output if available
        if step_type == "pre-sync" and step.output:
            task_ctx.branch_name = step.output.get("branch")

    # Update overall status if all steps completed
    for task_ctx in tasks.values():
        if task_ctx.overall_status == "partial":
            all_complete = all(s.completed for s in task_ctx.steps.values())
            if all_complete:
                task_ctx.overall_status = "complete"

    # Process children recursively
    for child in dag_run.children:
        _extract_task_contexts_from_dag_run(child, spec_id, tasks)

        # Check if child completed (affects parent's children_complete)
        if child.latest_attempt and child.latest_attempt.status != DaguStatus.SUCCESS:
            # Find parent task and mark children_complete = False
            child_task_id = extract_task_id(child.dag_name) or child.dag_name
            if child_task_id.startswith("c-"):
                child_task_id = child_task_id[2:]

            # Find the parent task context
            for task_ctx in tasks.values():
                if task_ctx.task_id != child_task_id:
                    # This task might be a parent
                    task_ctx.children_complete = False


def build_restart_context(
    spec_name: str,
    run_id: str,
    dagu_home: Path,
    arborist_home: Path,
) -> RestartContext:
    """Build restart context from a Dagu run.

    Args:
        spec_name: Name of the spec
        run_id: Run ID to analyze
        dagu_home: Path to Dagu home directory
        arborist_home: Path to Arborist home directory

    Returns:
        RestartContext with completion state for all tasks

    Raises:
        ValueError: If run not found or invalid
    """
    # Load DAG run with full hierarchy and outputs
    dag_run = load_dag_run(
        dagu_home,
        spec_name,
        run_id,
        expand_subdags=True,
        include_outputs=True,
    )

    if not dag_run:
        raise ValueError(f"Run {run_id} not found for spec {spec_name}")

    if not dag_run.latest_attempt:
        raise ValueError(f"Run {run_id} has no attempt data")

    # Extract task contexts from the DAG run hierarchy
    tasks: dict[str, TaskRestartContext] = {}
    _extract_task_contexts_from_dag_run(dag_run, spec_name, tasks)

    return RestartContext(
        spec_name=spec_name,
        spec_id=spec_name,
        arborist_home=arborist_home,
        dagu_home=dagu_home,
        source_run_id=run_id,
        created_at=datetime.now(),
        tasks=tasks,
        root_dag_status=dag_run.latest_attempt.status,
    )


# =============================================================================
# Integrity Verification Functions
# =============================================================================


def _get_worktree_path(spec_id: str, task_id: str, arborist_home: Path | None = None) -> Path:
    """Get the worktree path for a task.

    Args:
        spec_id: The spec ID
        task_id: The task ID
        arborist_home: Optional arborist home path (uses ARBORIST_HOME env var if not provided)

    Returns:
        Path to the worktree directory
    """
    if arborist_home is None:
        arborist_home = Path(os.environ.get("ARBORIST_HOME", ".arborist"))

    return arborist_home / "worktrees" / spec_id / task_id


def verify_step_integrity(
    task_id: str,
    step_type: str,
    context: RestartContext,
) -> tuple[bool, str | None]:
    """Verify that a step's claimed completion is still valid.

    Args:
        task_id: Task to verify
        step_type: Step type to verify (e.g., "pre-sync", "run", "commit")
        context: Restart context with completion data

    Returns:
        (valid, error) - True if valid, False with error message if invalid
    """
    task_ctx = context.tasks.get(task_id)
    if not task_ctx:
        return False, f"Task {task_id} not found in context"

    # Find the step state by type
    step_state = None
    for step_name, state in task_ctx.steps.items():
        if state.step_type == step_type:
            step_state = state
            break

    if not step_state:
        return False, f"Step type {step_type} not found in context for task {task_id}"

    # Different verification strategies per step type
    if step_type == "commit":
        return _verify_commit_integrity(task_ctx, context.arborist_home)

    elif step_type == "pre-sync":
        return _verify_worktree_integrity(task_ctx, context.arborist_home)

    elif step_type == "run":
        # Verify commit exists (run creates a commit)
        return _verify_commit_integrity(task_ctx, context.arborist_home, require_commit=True)

    elif step_type in ("run-test", "post-merge"):
        # These don't have easy integrity checks, assume valid
        return True, None

    elif step_type == "post-cleanup":
        # Worktree should NOT exist (cleanup removes it)
        return _verify_cleanup_integrity(task_ctx, context.arborist_home)

    elif step_type in ("container-up", "container-stop"):
        # Container checks would require docker inspection
        # For now, assume valid
        return True, None

    # Default: assume valid
    return True, None


def _verify_commit_integrity(
    task_ctx: TaskRestartContext,
    arborist_home: Path,
    require_commit: bool = False,
) -> tuple[bool, str | None]:
    """Verify git state matches commit expectations."""
    worktree_path = _get_worktree_path(task_ctx.spec_id, task_ctx.task_id, arborist_home)

    if not worktree_path.exists():
        return False, f"Worktree not found at {worktree_path}"

    if not task_ctx.head_commit_sha:
        if require_commit:
            return False, "No commit SHA recorded"
        # If commit SHA not recorded but not required, skip this check
        return True, None

    # Check HEAD commit
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return False, f"Cannot get HEAD commit: {result.stderr}"

    current_sha = result.stdout.strip()

    if current_sha != task_ctx.head_commit_sha:
        return False, (
            f"HEAD commit mismatch: expected {task_ctx.head_commit_sha[:8]}, "
            f"got {current_sha[:8]}"
        )

    return True, None


def _verify_worktree_integrity(
    task_ctx: TaskRestartContext,
    arborist_home: Path,
) -> tuple[bool, str | None]:
    """Verify worktree exists and is on correct branch."""
    worktree_path = _get_worktree_path(task_ctx.spec_id, task_ctx.task_id, arborist_home)

    if not worktree_path.exists():
        return False, f"Worktree not found at {worktree_path}"

    if not task_ctx.branch_name:
        # Branch name not recorded, can't verify
        return True, None

    # Check current branch
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return False, f"Cannot get current branch: {result.stderr}"

    current_branch = result.stdout.strip()

    if current_branch != task_ctx.branch_name:
        return False, (
            f"Branch mismatch: expected {task_ctx.branch_name}, got {current_branch}"
        )

    return True, None


def _verify_cleanup_integrity(
    task_ctx: TaskRestartContext,
    arborist_home: Path,
) -> tuple[bool, str | None]:
    """Verify cleanup was performed (worktree removed)."""
    worktree_path = _get_worktree_path(task_ctx.spec_id, task_ctx.task_id, arborist_home)

    if worktree_path.exists():
        return False, f"Worktree still exists at {worktree_path}, cleanup not completed"

    return True, None


# =============================================================================
# Skip Logic
# =============================================================================


def should_skip_step(
    task_id: str,
    step_type: str,
) -> tuple[bool, str | None]:
    """Determine if a step should be skipped based on restart context.

    Checks the ARBORIST_RESTART_CONTEXT environment variable for a restart
    context file. If found, loads it and checks if the step was already
    completed successfully.

    Args:
        task_id: The task ID
        step_type: The step type (e.g., "pre-sync", "run", "commit")

    Returns:
        (should_skip, reason) - True if step should be skipped with reason,
        False with optional error message if not
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

    # Find the step state by type
    step_state = None
    for step_name, state in task_ctx.steps.items():
        if state.step_type == step_type:
            step_state = state
            break

    if not step_state:
        return False, f"Step type {step_type} not found in context for task {task_id}"

    if not step_state.completed:
        return False, f"Step {step_type} not marked as completed"

    # Verify integrity
    valid, error = verify_step_integrity(task_id, step_type, context)
    if not valid:
        console.print(f"[yellow]Warning:[/yellow] Integrity check failed: {error}")
        console.print(f"[dim]Re-running {step_type} to ensure correctness[/dim]")
        return False, None

    # Format completion time for reason
    completed_at_str = ""
    if step_state.completed_at:
        completed_at_str = f" at {step_state.completed_at.isoformat()}"

    return True, f"Step completed{completed_at_str}"


def find_latest_restart_context(spec_id: str, arborist_home: Path) -> Path | None:
    """Find the most recent restart context for a spec.

    Args:
        spec_id: The spec ID to find context for
        arborist_home: Path to arborist home directory

    Returns:
        Path to the latest restart context file, or None if not found
    """
    context_dir = arborist_home / "restart-contexts"
    if not context_dir.exists():
        return None

    # Find all contexts for this spec, sorted by modification time (newest first)
    contexts = sorted(
        context_dir.glob(f"{spec_id}_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return contexts[0] if contexts else None
