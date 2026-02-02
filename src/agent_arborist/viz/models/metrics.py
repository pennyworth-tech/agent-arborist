"""Metrics data models for the visualization system."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class NodeMetrics:
    """Metrics for a single task node.

    These are the "own" metrics for a node - extracted directly from
    the step outputs, not aggregated from children.
    """

    task_id: str

    # Test metrics (from RunTestResult outputs)
    tests_run: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    tests_skipped: int = 0

    # Quality metrics (from hooks - future)
    code_quality_score: float | None = None
    task_completion_score: float | None = None
    test_coverage_delta: float | None = None

    # Execution metrics
    duration_seconds: float = 0.0
    status: str = "pending"  # pending, running, success, failed, skipped

    # Source tracking for deduplication
    test_file_hashes: set[str] = field(default_factory=set)

    # Raw output data (for inspection)
    raw_output: dict[str, Any] | None = None

    @property
    def pass_rate(self) -> float | None:
        """Calculate pass rate as a decimal (0.0 to 1.0)."""
        if self.tests_run == 0:
            return None
        return self.tests_passed / self.tests_run

    def has_test_metrics(self) -> bool:
        """Check if this node has any test metrics."""
        return self.tests_run > 0


@dataclass
class AggregatedMetrics:
    """Rolled-up metrics for a subtree.

    These represent the aggregated values from all descendants
    of a node, including the node's own metrics.
    """

    # Direct metrics from this node
    own: NodeMetrics

    # Aggregated totals from children (with deduplication where applicable)
    total_tests_run: int = 0
    total_tests_passed: int = 0
    total_tests_failed: int = 0
    total_tests_skipped: int = 0
    total_duration_seconds: float = 0.0

    # Averages (for quality scores)
    avg_code_quality: float | None = None
    avg_task_completion: float | None = None
    avg_test_coverage_delta: float | None = None

    # Counts for structure
    child_count: int = 0
    descendant_count: int = 0

    # Status summary
    children_succeeded: int = 0
    children_failed: int = 0
    children_pending: int = 0
    children_skipped: int = 0

    @property
    def total_pass_rate(self) -> float | None:
        """Calculate aggregated pass rate as a decimal (0.0 to 1.0)."""
        if self.total_tests_run == 0:
            return None
        return self.total_tests_passed / self.total_tests_run

    def has_test_metrics(self) -> bool:
        """Check if the aggregation has any test metrics."""
        return self.total_tests_run > 0
