"""Aggregation engine for rolling up metrics in the tree."""

from enum import Enum
from typing import Protocol

from agent_arborist.viz.models.metrics import AggregatedMetrics, NodeMetrics
from agent_arborist.viz.models.tree import MetricsNode, MetricsTree


class AggregationStrategy(str, Enum):
    """Aggregation strategy for rolling up metrics."""

    TOTALS = "totals"  # Sum with deduplication
    AVERAGES = "averages"  # Average scores only
    BOTH = "both"  # Include both totals and averages


class Aggregator(Protocol):
    """Protocol for aggregation strategies."""

    def aggregate(self, node: MetricsNode) -> AggregatedMetrics:
        """Aggregate metrics for a node and its descendants."""
        ...


class TotalsAggregator:
    """Aggregator that sums metrics from all descendants."""

    def aggregate(self, node: MetricsNode) -> AggregatedMetrics:
        """Aggregate by summing metrics from all descendants.

        Args:
            node: The node to aggregate (recursively processes children)

        Returns:
            AggregatedMetrics with totals from entire subtree
        """
        # Start with own metrics
        own_metrics = node.metrics or NodeMetrics(task_id=node.id)

        # Initialize with own values
        total_run = own_metrics.tests_run
        total_passed = own_metrics.tests_passed
        total_failed = own_metrics.tests_failed
        total_skipped = own_metrics.tests_skipped
        total_duration = own_metrics.duration_seconds

        # Status counts
        succeeded = 0
        failed = 0
        pending = 0
        skipped = 0
        descendant_count = 0

        # Aggregate from children (recursive)
        for child in node.children:
            # First aggregate the child
            if child.aggregated is None:
                child.aggregated = self.aggregate(child)

            child_agg = child.aggregated

            # Add child's totals
            total_run += child_agg.total_tests_run
            total_passed += child_agg.total_tests_passed
            total_failed += child_agg.total_tests_failed
            total_skipped += child_agg.total_tests_skipped
            total_duration += child_agg.total_duration_seconds

            # Count child status
            if child.status == "success":
                succeeded += 1
            elif child.status == "failed":
                failed += 1
            elif child.status == "skipped":
                skipped += 1
            else:
                pending += 1

            # Count all descendants
            descendant_count += 1 + child_agg.descendant_count

        return AggregatedMetrics(
            own=own_metrics,
            total_tests_run=total_run,
            total_tests_passed=total_passed,
            total_tests_failed=total_failed,
            total_tests_skipped=total_skipped,
            total_duration_seconds=total_duration,
            child_count=len(node.children),
            descendant_count=descendant_count,
            children_succeeded=succeeded,
            children_failed=failed,
            children_pending=pending,
            children_skipped=skipped,
        )


class AveragesAggregator:
    """Aggregator that computes weighted averages for quality scores."""

    def aggregate(self, node: MetricsNode) -> AggregatedMetrics:
        """Aggregate by computing weighted averages for quality scores.

        Args:
            node: The node to aggregate

        Returns:
            AggregatedMetrics with averaged quality scores
        """
        # First compute totals
        totals_aggregator = TotalsAggregator()
        agg = totals_aggregator.aggregate(node)

        # Compute averages for quality scores
        quality_scores: list[float] = []
        completion_scores: list[float] = []
        coverage_deltas: list[float] = []

        def collect_scores(n: MetricsNode) -> None:
            if n.metrics:
                if n.metrics.code_quality_score is not None:
                    quality_scores.append(n.metrics.code_quality_score)
                if n.metrics.task_completion_score is not None:
                    completion_scores.append(n.metrics.task_completion_score)
                if n.metrics.test_coverage_delta is not None:
                    coverage_deltas.append(n.metrics.test_coverage_delta)
            for child in n.children:
                collect_scores(child)

        collect_scores(node)

        # Compute averages
        if quality_scores:
            agg.avg_code_quality = sum(quality_scores) / len(quality_scores)
        if completion_scores:
            agg.avg_task_completion = sum(completion_scores) / len(completion_scores)
        if coverage_deltas:
            agg.avg_test_coverage_delta = sum(coverage_deltas) / len(coverage_deltas)

        return agg


def aggregate_tree(
    tree: MetricsTree,
    strategy: AggregationStrategy = AggregationStrategy.TOTALS,
) -> MetricsTree:
    """Aggregate metrics throughout the entire tree.

    Args:
        tree: The metrics tree to aggregate
        strategy: The aggregation strategy to use

    Returns:
        The same tree with aggregated metrics populated
    """
    # Choose aggregator based on strategy
    if strategy == AggregationStrategy.AVERAGES:
        aggregator = AveragesAggregator()
    else:
        # TOTALS and BOTH use the averages aggregator (which includes totals)
        aggregator = AveragesAggregator()

    # Aggregate from root (which recursively aggregates all children)
    tree.root.aggregated = aggregator.aggregate(tree.root)

    return tree
