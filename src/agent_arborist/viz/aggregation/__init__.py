"""Aggregation engine for rolling up metrics in the tree."""

from agent_arborist.viz.aggregation.aggregator import (
    AggregationStrategy,
    aggregate_tree,
    TotalsAggregator,
    AveragesAggregator,
)

__all__ = [
    "AggregationStrategy",
    "aggregate_tree",
    "TotalsAggregator",
    "AveragesAggregator",
]
