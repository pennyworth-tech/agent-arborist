"""Step result schemas for JSON output.

Each step type has a specific schema for its JSON output.
Results are emitted to stdout for Dagu's output: field to capture.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any
import json


@dataclass
class StepResultBase:
    """Base class for step results."""

    success: bool
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    error: str | None = None
    # Restart support: indicates step was skipped because already completed
    skipped: bool = False
    skip_reason: str | None = None

    def to_json(self) -> str:
        """Serialize to JSON string for stdout."""
        return json.dumps(asdict(self), default=str)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class PreSyncResult(StepResultBase):
    """Result from task pre-sync step.

    Captures worktree creation and branch sync information.
    """

    worktree_path: str = ""
    branch: str = ""
    parent_branch: str = ""
    created_worktree: bool = False
    synced_from_parent: bool = False


@dataclass
class RunResult(StepResultBase):
    """Result from task run step (AI execution).

    Captures AI execution metrics and output.
    """

    files_changed: int = 0
    commit_message: str | None = None
    summary: str = ""
    runner: str = ""
    model: str | None = None
    duration_seconds: float = 0.0


@dataclass
class CommitResult(StepResultBase):
    """Result from task commit step.

    Captures commit creation information.
    """

    commit_sha: str | None = None
    message: str = ""
    files_staged: int = 0
    was_fallback: bool = False


@dataclass
class RunTestResult(StepResultBase):
    """Result from task run-test step.

    Captures test execution results.
    """

    test_command: str | None = None
    test_count: int | None = None
    passed: int | None = None
    failed: int | None = None
    skipped: int | None = None
    output_summary: str = ""


@dataclass
class PostMergeResult(StepResultBase):
    """Result from task post-merge step.

    Captures merge operation results.
    """

    merged_into: str = ""
    source_branch: str = ""
    commit_sha: str | None = None
    conflicts: list[str] = field(default_factory=list)
    conflict_resolved: bool = False


@dataclass
class PostCleanupResult(StepResultBase):
    """Result from task post-cleanup step.

    Captures cleanup operation results.
    """

    worktree_removed: bool = False
    branch_deleted: bool = False
    cleaned_up: bool = False


@dataclass
class ContainerUpResult(StepResultBase):
    """Result from task container-up step.

    Captures devcontainer startup information.
    """

    worktree_path: str = ""
    container_id: str | None = None


@dataclass
class ContainerStopResult(StepResultBase):
    """Result from task container-stop step.

    Captures devcontainer stop information.
    """

    worktree_path: str = ""
    container_stopped: bool = False


# Type alias for any step result
StepResult = (
    PreSyncResult
    | RunResult
    | CommitResult
    | RunTestResult
    | PostMergeResult
    | PostCleanupResult
    | ContainerUpResult
    | ContainerStopResult
)
