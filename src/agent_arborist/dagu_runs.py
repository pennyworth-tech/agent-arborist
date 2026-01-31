"""Data layer for parsing Dagu status.jsonl files and DAG run history."""

import json
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from pathlib import Path


def normalize_dag_name(dag_name: str) -> str:
    """Normalize DAG name to match Dagu's directory naming convention.

    Note: Older versions of dagu converted hyphens to underscores, but current
    versions preserve the original name. This function now returns the original.
    """
    return dag_name


def _get_dag_name_variants(dag_name: str) -> list[str]:
    """Get possible directory name variants for a DAG.

    Dagu behavior has varied - some versions convert hyphens to underscores,
    others preserve the original name. Return both variants to search.
    """
    variants = [dag_name]
    # Also try with hyphens converted to underscores (legacy behavior)
    underscore_name = dag_name.replace("-", "_")
    if underscore_name != dag_name:
        variants.append(underscore_name)
    # And vice versa
    hyphen_name = dag_name.replace("_", "-")
    if hyphen_name != dag_name:
        variants.append(hyphen_name)
    return variants


class DaguStatus(IntEnum):
    """Dagu step/run status codes."""

    PENDING = 0
    RUNNING = 1
    FAILED = 2
    SKIPPED = 3
    SUCCESS = 4

    @classmethod
    def from_name(cls, name: str) -> "DaguStatus | None":
        """Convert status name to enum value."""
        status_map = {
            "pending": cls.PENDING,
            "running": cls.RUNNING,
            "failed": cls.FAILED,
            "skipped": cls.SKIPPED,
            "success": cls.SUCCESS,
        }
        return status_map.get(name.lower())

    def to_name(self) -> str:
        """Convert enum to status name."""
        return self.name.lower()


@dataclass
class StepNode:
    """A step in a DAG run."""

    name: str
    status: DaguStatus
    started_at: datetime | None
    finished_at: datetime | None
    child_dag_name: str | None
    child_run_ids: list[str]
    # V1 additions for observability
    output: dict | None = None  # Captured output from outputs.json
    exit_code: int | None = None  # Exit code for failed steps
    error: str | None = None  # Error message for failed steps


@dataclass
class DagRunAttempt:
    """An attempt to run a DAG."""

    attempt_id: str
    status: DaguStatus
    steps: list[StepNode]
    started_at: datetime | None
    finished_at: datetime | None
    # V1 additions for observability
    outputs: dict | None = None  # Full outputs.json content
    error: str | None = None  # DAG-level error message


@dataclass
class DagRun:
    """A DAG run with optional children."""

    dag_name: str
    run_id: str
    root_dag_name: str | None
    root_dag_id: str | None
    parent_dag_name: str | None
    parent_dag_id: str | None
    latest_attempt: DagRunAttempt | None
    children: list["DagRun"]  # For expanded sub-DAGs
    # V1 additions for observability
    run_dir: Path | None = None  # Path to run directory
    outputs_file: Path | None = None  # Path to outputs.json if exists


def _parse_datetime(ts: str | None) -> datetime | None:
    """Parse ISO timestamp string to datetime."""
    if not ts:
        return None
    try:
        # Handle ISO format with timezone
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def _format_duration(started_at: datetime | None, finished_at: datetime | None) -> str:
    """Format duration between two datetimes as human-readable string."""
    if not started_at or not finished_at:
        return "N/A"

    duration_seconds = (finished_at - started_at).total_seconds()

    if duration_seconds < 1:
        return "<1s"
    elif duration_seconds < 60:
        return f"{int(duration_seconds)}s"
    elif duration_seconds < 3600:
        minutes = int(duration_seconds // 60)
        seconds = int(duration_seconds % 60)
        return f"{minutes}m {seconds}s"
    else:
        hours = int(duration_seconds // 3600)
        minutes = int((duration_seconds % 3600) // 60)
        return f"{hours}h {minutes}m"


def parse_outputs_json(path: Path) -> dict:
    """Parse outputs.json file and return output data.

    Args:
        path: Path to the outputs.json file

    Returns:
        Parsed outputs dict, or empty dict if file doesn't exist or is invalid
    """
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, IOError):
        return {}


def load_step_output(outputs: dict, step_name: str) -> dict | None:
    """Extract step output from parsed outputs.json.

    Args:
        outputs: Parsed outputs.json content
        step_name: Name of the step to extract output for

    Returns:
        Step output dict, or None if not found
    """
    return outputs.get("outputs", {}).get(step_name)


def parse_status_jsonl(path: Path) -> DagRunAttempt:
    """Parse a status.jsonl file and return a DagRunAttempt.

    Args:
        path: Path to the status.jsonl file

    Returns:
        DagRunAttempt with parsed data

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If file content is invalid
    """
    if not path.exists():
        raise FileNotFoundError(f"Status file not found: {path}")

    content = path.read_text().strip()
    if not content:
        raise ValueError(f"Empty status file: {path}")

    # Parse JSON (it's JSONL but should be a single line)
    data = json.loads(content)

    # Extract attempt info
    attempt_id = data.get("attemptId", "unknown")
    status_code = data.get("status", 0)
    status = DaguStatus(status_code)

    # Parse timestamps
    started_at = _parse_datetime(data.get("startedAt"))
    finished_at = _parse_datetime(data.get("finishedAt"))

    # V1: Extract DAG-level error
    dag_error = data.get("error")

    # Parse nodes (steps)
    steps = []
    for node in data.get("nodes", []):
        step_info = node.get("step", {})
        step_name = step_info.get("name", "unknown")
        step_status = DaguStatus(node.get("status", 0))

        step_started = _parse_datetime(node.get("startedAt"))
        step_finished = _parse_datetime(node.get("finishedAt"))

        # Check if this is a call step (has childDag)
        child_dag = step_info.get("childDag")
        child_dag_name = child_dag.get("name") if child_dag else None

        # Get child run IDs
        child_run_ids = []
        for child in node.get("children", []):
            child_run_id = child.get("dagRunId")
            if child_run_id:
                child_run_ids.append(child_run_id)

        # V1: Extract exit code and error for step
        exit_code = node.get("exitCode")
        step_error = node.get("error")

        step = StepNode(
            name=step_name,
            status=step_status,
            started_at=step_started,
            finished_at=step_finished,
            child_dag_name=child_dag_name,
            child_run_ids=child_run_ids,
            output=None,  # Populated later if include_outputs=True
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


def _find_run_dir(dagu_home: Path, dag_name: str, run_id: str) -> Path | None:
    """Find the run directory for a specific DAG run.

    Args:
        dagu_home: Path to Dagu home directory
        dag_name: Name of the DAG
        run_id: Run ID (full or partial)

    Returns:
        Path to run directory or None if not found
    """
    # Try all possible name variants (handles both hyphen and underscore conventions)
    for name_variant in _get_dag_name_variants(dag_name):
        runs_dir = dagu_home / "data" / "dag-runs" / name_variant / "dag-runs"

        if not runs_dir.exists():
            continue

        # Search for matching run directory
        # Run directories are at: YYYY/MM/DD/dag-run_<timestamp>_<run-id>
        # Use glob to find all matching directories
        for run_dir in sorted(runs_dir.glob("*/*/*/dag-run_*"), reverse=True):
            if not run_dir.is_dir():
                continue

            # Check if run_id matches directory name
            if run_id in run_dir.name:
                return run_dir

    return None


def _load_all_children_flat(
    children_dir: Path,
    include_outputs: bool = False,
) -> dict[str, tuple[DagRun, str | None]]:
    """Load ALL child DAGs from a children directory into a flat dict.

    Dagu stores all descendants (children, grandchildren, etc.) flat under
    the root DAG's children/ directory. This function loads them all and
    returns a mapping of run_id -> (DagRun, parent_id).

    Args:
        children_dir: Path to the children directory
        include_outputs: Whether to load outputs.json data

    Returns:
        Dict mapping run_id to (DagRun, parent_run_id)
    """
    if not children_dir.exists():
        return {}

    runs_by_id: dict[str, tuple[DagRun, str | None]] = {}

    for child_dir in children_dir.iterdir():
        if not child_dir.is_dir() or not child_dir.name.startswith("child_"):
            continue

        # Find the status.jsonl file in the attempt directory
        attempt_dirs = list(child_dir.glob("attempt_*/status.jsonl"))
        if not attempt_dirs:
            continue

        status_file = attempt_dirs[0]

        try:
            attempt = parse_status_jsonl(status_file)

            # Get child info from status
            with status_file.open("r") as f:
                child_data = json.loads(f.read().strip())

            # Extract parent info
            parent_info = child_data.get("parent", {})
            root_info = child_data.get("root", {})
            parent_run_id = parent_info.get("id")

            # V1: Load outputs.json if requested
            outputs_file = None
            outputs_files = list(child_dir.glob("attempt_*/outputs.json"))
            if outputs_files:
                outputs_file = outputs_files[0]

            if include_outputs and outputs_file:
                outputs_data = parse_outputs_json(outputs_file)
                attempt.outputs = outputs_data
                # Populate per-step outputs
                for step in attempt.steps:
                    step.output = load_step_output(outputs_data, step.name)

            run_id = child_data.get("dagRunId", "unknown")
            child_run = DagRun(
                dag_name=child_data.get("name", "unknown"),
                run_id=run_id,
                root_dag_name=root_info.get("name"),
                root_dag_id=root_info.get("id"),
                parent_dag_name=parent_info.get("name"),
                parent_dag_id=parent_run_id,
                latest_attempt=attempt,
                children=[],  # Will be populated during tree building
                run_dir=child_dir,
                outputs_file=outputs_file,
            )
            runs_by_id[run_id] = (child_run, parent_run_id)
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            # Skip malformed child data
            continue

    return runs_by_id


def _build_children_tree(
    runs_by_id: dict[str, tuple[DagRun, str | None]],
    parent_run_id: str,
) -> list[DagRun]:
    """Build a tree of children for a given parent run ID.

    Args:
        runs_by_id: Dict mapping run_id to (DagRun, parent_run_id)
        parent_run_id: The run ID of the parent to find children for

    Returns:
        List of child DagRun objects with their children recursively populated
    """
    children = []
    for run_id, (dag_run, actual_parent_id) in runs_by_id.items():
        if actual_parent_id == parent_run_id:
            # This run is a direct child of the parent
            # Recursively build its children
            dag_run.children = _build_children_tree(runs_by_id, run_id)
            children.append(dag_run)
    return children


def _load_children(
    dagu_home: Path,
    parent_run_dir: Path,
    parent_status: dict,
    expand_subdags: bool = False,
    include_outputs: bool = False,
) -> list[DagRun]:
    """Load child DAGs from a run directory, building proper hierarchy.

    Dagu stores all descendants flat under the root's children/ directory.
    This function builds the proper tree structure based on parent references.

    Args:
        dagu_home: Path to Dagu home directory
        parent_run_dir: Path to parent run directory
        parent_status: Parsed parent status JSON data
        expand_subdags: Whether to recursively load grandchildren
        include_outputs: Whether to load outputs.json data

    Returns:
        List of child DagRun objects with proper nesting
    """
    children_dir = parent_run_dir / "children"
    if not children_dir.exists():
        return []

    if not expand_subdags:
        # Simple case: just load direct children without expansion
        runs_by_id = _load_all_children_flat(children_dir, include_outputs)
        parent_run_id = parent_status.get("dagRunId")
        return [dag_run for dag_run, actual_parent_id in runs_by_id.values()
                if actual_parent_id == parent_run_id]

    # Full expansion: load all and build tree
    runs_by_id = _load_all_children_flat(children_dir, include_outputs)
    parent_run_id = parent_status.get("dagRunId")
    return _build_children_tree(runs_by_id, parent_run_id)


def load_dag_run(
    dagu_home: Path,
    dag_name: str,
    run_id: str,
    expand_subdags: bool = False,
    include_outputs: bool = False,
) -> DagRun | None:
    """Load a specific DAG run.

    Args:
        dagu_home: Path to Dagu home directory
        dag_name: Name of the DAG
        run_id: Run ID (full or partial)
        expand_subdags: Whether to load child DAGs recursively
        include_outputs: Whether to load outputs.json data

    Returns:
        DagRun object or None if not found
    """
    run_dir = _find_run_dir(dagu_home, dag_name, run_id)
    if not run_dir:
        return None

    # Find the latest attempt directory
    attempt_dirs = sorted(run_dir.glob("attempt_*/status.jsonl"), reverse=True)
    if not attempt_dirs:
        return None

    status_file = attempt_dirs[0]

    try:
        attempt = parse_status_jsonl(status_file)

        # Read status to get root info
        with status_file.open("r") as f:
            status_data = json.loads(f.read().strip())

        root_info = status_data.get("root", {})
        parent_info = status_data.get("parent", {})

        # V1: Load outputs.json if requested
        outputs_file = None
        outputs_files = list(run_dir.glob("attempt_*/outputs.json"))
        if outputs_files:
            outputs_file = outputs_files[0]

        if include_outputs and outputs_file:
            outputs_data = parse_outputs_json(outputs_file)
            attempt.outputs = outputs_data
            # Populate per-step outputs
            for step in attempt.steps:
                step.output = load_step_output(outputs_data, step.name)

        # Load children if requested (V1: pass include_outputs through)
        children = []
        if expand_subdags:
            children = _load_children(
                dagu_home, run_dir, status_data,
                expand_subdags=True, include_outputs=include_outputs
            )

        return DagRun(
            dag_name=dag_name,
            run_id=status_data.get("dagRunId", run_id),
            root_dag_name=root_info.get("name"),
            root_dag_id=root_info.get("id"),
            parent_dag_name=parent_info.get("name"),
            parent_dag_id=parent_info.get("id"),
            latest_attempt=attempt,
            children=children,
            run_dir=run_dir,
            outputs_file=outputs_file,
        )
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        return None


def list_dag_runs(
    dagu_home: Path,
    dag_name: str | None = None,
    status: DaguStatus | None = None,
    limit: int = 20,
) -> list[DagRun]:
    """List DAG runs with optional filtering.

    Args:
        dagu_home: Path to Dagu home directory
        dag_name: Optional filter by DAG name
        status: Optional filter by status
        limit: Maximum number of runs to return

    Returns:
        List of DagRun objects (without children expanded)
    """
    runs_dir = dagu_home / "data" / "dag-runs"

    if not runs_dir.exists():
        return []

    all_runs = []

    # Determine which DAG directories to scan
    if dag_name:
        # Try all possible name variants (handles both hyphen and underscore conventions)
        dag_dirs = [runs_dir / variant for variant in _get_dag_name_variants(dag_name)]
    else:
        dag_dirs = [d for d in runs_dir.iterdir() if d.is_dir()]

    for dag_dir in dag_dirs:
        if not dag_dir.is_dir():
            continue

        current_dag_name = dag_dir.name
        dag_runs_path = dag_dir / "dag-runs"

        if not dag_runs_path.exists():
            continue

        # Scan date directories (YYYY/MM/DD/dag-run_*)
        for run_dir in sorted(dag_runs_path.glob("*/*/*/dag-run_*"), reverse=True):
            if not run_dir.is_dir():
                continue

            # Find latest attempt
            attempt_files = list(run_dir.glob("attempt_*/status.jsonl"))
            if not attempt_files:
                continue

            status_file = sorted(attempt_files, reverse=True)[0]

            try:
                attempt = parse_status_jsonl(status_file)

                # Filter by status if specified
                if status is not None and attempt.status != status:
                    continue

                # Read status to get IDs
                with status_file.open("r") as f:
                    status_data = json.loads(f.read().strip())

                root_info = status_data.get("root", {})
                parent_info = status_data.get("parent", {})

                run = DagRun(
                    dag_name=current_dag_name,
                    run_id=status_data.get("dagRunId", run_dir.name),
                    root_dag_name=root_info.get("name"),
                    root_dag_id=root_info.get("id"),
                    parent_dag_name=parent_info.get("name"),
                    parent_dag_id=parent_info.get("id"),
                    latest_attempt=attempt,
                    children=[],  # Don't expand children for list
                )
                all_runs.append(run)
            except (FileNotFoundError, ValueError, json.JSONDecodeError):
                continue

    # Sort by started_at descending
    all_runs.sort(
        key=lambda r: r.latest_attempt.started_at or datetime.min, reverse=True
    )

    # Apply limit
    return all_runs[:limit]
