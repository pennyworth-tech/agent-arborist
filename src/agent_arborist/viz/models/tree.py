"""Tree data models for the visualization system."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from agent_arborist.viz.models.metrics import AggregatedMetrics, NodeMetrics


@dataclass
class MetricsNode:
    """A node in the metrics tree.

    Represents a task or step in the DAG execution, with its own
    metrics and optionally aggregated metrics from children.
    """

    # Identity
    id: str  # Task ID or step name
    name: str  # Display name
    node_type: str = "step"  # "dag", "step", "call"

    # Execution info
    status: str = "pending"  # pending, running, success, failed, skipped
    started_at: datetime | None = None
    finished_at: datetime | None = None

    # Own metrics for this node
    metrics: NodeMetrics | None = None

    # Aggregated metrics (populated after aggregation pass)
    aggregated: AggregatedMetrics | None = None

    # Tree structure
    children: list["MetricsNode"] = field(default_factory=list)

    # Parent reference (for traversal)
    parent: "MetricsNode | None" = field(default=None, repr=False)

    # Additional metadata
    child_dag_name: str | None = None  # If this is a call step
    error: str | None = None
    exit_code: int | None = None

    @property
    def is_leaf(self) -> bool:
        """Check if this is a leaf node (no children)."""
        return len(self.children) == 0

    @property
    def depth(self) -> int:
        """Calculate depth from root."""
        if self.parent is None:
            return 0
        return self.parent.depth + 1

    @property
    def duration_seconds(self) -> float | None:
        """Calculate duration from timestamps."""
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None

    def add_child(self, child: "MetricsNode") -> None:
        """Add a child node and set parent reference."""
        child.parent = self
        self.children.append(child)

    def to_dict(self, include_children: bool = True) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "id": self.id,
            "name": self.name,
            "node_type": self.node_type,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }

        if self.metrics:
            result["metrics"] = {
                "tests_run": self.metrics.tests_run,
                "tests_passed": self.metrics.tests_passed,
                "tests_failed": self.metrics.tests_failed,
                "tests_skipped": self.metrics.tests_skipped,
                "code_quality_score": self.metrics.code_quality_score,
                "task_completion_score": self.metrics.task_completion_score,
                "test_coverage_delta": self.metrics.test_coverage_delta,
                "duration_seconds": self.metrics.duration_seconds,
            }

        if self.aggregated:
            result["aggregated"] = {
                "total_tests_run": self.aggregated.total_tests_run,
                "total_tests_passed": self.aggregated.total_tests_passed,
                "total_tests_failed": self.aggregated.total_tests_failed,
                "total_tests_skipped": self.aggregated.total_tests_skipped,
                "avg_code_quality": self.aggregated.avg_code_quality,
                "avg_task_completion": self.aggregated.avg_task_completion,
                "avg_test_coverage_delta": self.aggregated.avg_test_coverage_delta,
                "total_duration_seconds": self.aggregated.total_duration_seconds,
                "child_count": self.aggregated.child_count,
                "descendant_count": self.aggregated.descendant_count,
                "children_succeeded": self.aggregated.children_succeeded,
                "children_failed": self.aggregated.children_failed,
                "children_pending": self.aggregated.children_pending,
            }

        if self.child_dag_name:
            result["child_dag_name"] = self.child_dag_name

        if self.error:
            result["error"] = self.error

        if self.exit_code is not None:
            result["exit_code"] = self.exit_code

        if include_children and self.children:
            result["children"] = [child.to_dict(include_children=True) for child in self.children]

        return result


@dataclass
class MetricsTree:
    """The complete metrics tree for a DAG run.

    Contains the root node and metadata about the DAG run.
    """

    # DAG run info
    dag_name: str
    run_id: str

    # Root of the tree
    root: MetricsNode

    # Run metadata
    started_at: datetime | None = None
    finished_at: datetime | None = None
    status: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "dag_name": self.dag_name,
            "run_id": self.run_id,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "root": self.root.to_dict(),
        }

    def iter_nodes(self) -> list[MetricsNode]:
        """Iterate over all nodes in the tree (depth-first)."""
        nodes = []

        def _collect(node: MetricsNode) -> None:
            nodes.append(node)
            for child in node.children:
                _collect(child)

        _collect(self.root)
        return nodes

    def get_summary(self) -> dict[str, Any]:
        """Get summary metrics for the entire tree."""
        if self.root.aggregated:
            agg = self.root.aggregated
            pass_rate = agg.total_pass_rate

            return {
                "total_tests_run": agg.total_tests_run,
                "total_tests_passed": agg.total_tests_passed,
                "total_tests_failed": agg.total_tests_failed,
                "total_tests_skipped": agg.total_tests_skipped,
                "pass_rate": pass_rate,
                "avg_code_quality": agg.avg_code_quality,
                "avg_task_completion": agg.avg_task_completion,
                "total_duration_seconds": agg.total_duration_seconds,
                "total_duration": self._format_duration(agg.total_duration_seconds),
                "node_count": agg.descendant_count + 1,
            }
        return {}

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Format duration in human-readable form."""
        if seconds < 1:
            return "<1s"
        elif seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{minutes}m {secs}s"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}h {minutes}m"
