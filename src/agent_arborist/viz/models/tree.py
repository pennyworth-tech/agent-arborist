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
            "nodeType": self.node_type,
            "status": self.status,
            "startedAt": self.started_at.isoformat() if self.started_at else None,
            "finishedAt": self.finished_at.isoformat() if self.finished_at else None,
        }

        if self.metrics:
            result["metrics"] = {
                "testsRun": self.metrics.tests_run,
                "testsPassed": self.metrics.tests_passed,
                "testsFailed": self.metrics.tests_failed,
                "testsSkipped": self.metrics.tests_skipped,
                "codeQualityScore": self.metrics.code_quality_score,
                "taskCompletionScore": self.metrics.task_completion_score,
                "testCoverageDelta": self.metrics.test_coverage_delta,
                "durationSeconds": self.metrics.duration_seconds,
            }

        if self.aggregated:
            result["aggregated"] = {
                "totalTestsRun": self.aggregated.total_tests_run,
                "totalTestsPassed": self.aggregated.total_tests_passed,
                "totalTestsFailed": self.aggregated.total_tests_failed,
                "totalTestsSkipped": self.aggregated.total_tests_skipped,
                "avgCodeQuality": self.aggregated.avg_code_quality,
                "avgTaskCompletion": self.aggregated.avg_task_completion,
                "avgTestCoverageDelta": self.aggregated.avg_test_coverage_delta,
                "totalDurationSeconds": self.aggregated.total_duration_seconds,
                "childCount": self.aggregated.child_count,
                "descendantCount": self.aggregated.descendant_count,
                "childrenSucceeded": self.aggregated.children_succeeded,
                "childrenFailed": self.aggregated.children_failed,
                "childrenPending": self.aggregated.children_pending,
            }

        if self.child_dag_name:
            result["childDagName"] = self.child_dag_name

        if self.error:
            result["error"] = self.error

        if self.exit_code is not None:
            result["exitCode"] = self.exit_code

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
            "dagName": self.dag_name,
            "runId": self.run_id,
            "status": self.status,
            "startedAt": self.started_at.isoformat() if self.started_at else None,
            "finishedAt": self.finished_at.isoformat() if self.finished_at else None,
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
                "totalTestsRun": agg.total_tests_run,
                "totalTestsPassed": agg.total_tests_passed,
                "totalTestsFailed": agg.total_tests_failed,
                "totalTestsSkipped": agg.total_tests_skipped,
                "passRate": pass_rate,
                "avgCodeQuality": agg.avg_code_quality,
                "avgTaskCompletion": agg.avg_task_completion,
                "totalDurationSeconds": agg.total_duration_seconds,
                "totalDuration": self._format_duration(agg.total_duration_seconds),
                "nodeCount": agg.descendant_count + 1,
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
