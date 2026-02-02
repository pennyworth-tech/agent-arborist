"""Arborist Visualization Module.

Provides metrics extraction, aggregation, and visualization for DAG runs.

Public API:
    - build_metrics_tree: DagRun → MetricsTree
    - aggregate_tree: MetricsTree → MetricsTree (with aggregated values)
    - render_tree: MetricsTree → str/bytes
    - visualize_run: run_id → rendered output (all-in-one)

Example:
    from agent_arborist.viz import visualize_run, OutputFormat

    # Quick visualization
    svg = visualize_run("abc123", format=OutputFormat.SVG)

    # Step by step
    from agent_arborist.viz import build_metrics_tree, aggregate_tree, render_tree
    from agent_arborist.dagu_runs import load_dag_run

    dag_run = load_dag_run(dagu_home, "my-dag", "run-id", expand_subdags=True, include_outputs=True)
    tree = build_metrics_tree(dag_run)
    tree = aggregate_tree(tree)
    output = render_tree(tree, format=OutputFormat.ASCII)
"""

from pathlib import Path
from typing import Union

from agent_arborist.viz.models import (
    NodeMetrics,
    AggregatedMetrics,
    MetricsNode,
    MetricsTree,
)
from agent_arborist.viz.extraction import extract_metrics_from_dag_run
from agent_arborist.viz.aggregation import (
    AggregationStrategy,
    aggregate_tree,
)
from agent_arborist.viz.tree import build_metrics_tree
from agent_arborist.viz.renderers import (
    OutputFormat,
    ASCIIRenderer,
    JSONRenderer,
    SVGRenderer,
)


def render_tree(
    tree: MetricsTree,
    *,
    format: OutputFormat = OutputFormat.ASCII,
    color_by: str = "status",
    show_metrics: bool = False,
    depth: int | None = None,
    **options,
) -> Union[str, bytes]:
    """Render a MetricsTree to the specified format.

    Args:
        tree: The metrics tree to render
        format: Output format (ASCII, JSON, SVG, etc.)
        color_by: Color scheme ("status", "quality", "pass-rate")
        show_metrics: Whether to show inline metrics
        depth: Maximum tree depth to render
        **options: Format-specific options

    Returns:
        Rendered output (string or bytes depending on format)
    """
    if format == OutputFormat.ASCII:
        renderer = ASCIIRenderer()
    elif format == OutputFormat.JSON:
        renderer = JSONRenderer()
    elif format == OutputFormat.SVG:
        renderer = SVGRenderer()
    else:
        # For now, fall back to ASCII for unsupported formats
        renderer = ASCIIRenderer()

    return renderer.render(
        tree,
        color_by=color_by,
        show_metrics=show_metrics,
        depth=depth,
        **options,
    )


def render_metrics(
    tree: MetricsTree,
    *,
    format: OutputFormat = OutputFormat.JSON,
    include_by_task: bool = True,
    **options,
) -> str:
    """Render metrics summary for a tree.

    Args:
        tree: The metrics tree
        format: Output format (JSON or table)
        include_by_task: Include per-task breakdown
        **options: Format-specific options

    Returns:
        Rendered metrics summary
    """
    from agent_arborist.viz.renderers.json_renderer import MetricsJSONRenderer

    if format == OutputFormat.JSON:
        renderer = MetricsJSONRenderer()
        return renderer.render(tree, include_by_task=include_by_task, **options)
    else:
        # For now, return JSON for unsupported formats
        renderer = MetricsJSONRenderer()
        return renderer.render(tree, include_by_task=include_by_task, **options)


def visualize_run(
    run_id: str,
    dagu_home: Path | None = None,
    dag_name: str | None = None,
    *,
    format: OutputFormat = OutputFormat.ASCII,
    aggregation: AggregationStrategy = AggregationStrategy.TOTALS,
    color_by: str = "status",
    show_metrics: bool = False,
    expand_subdags: bool = True,
    **options,
) -> Union[str, bytes]:
    """All-in-one function to visualize a DAG run.

    Args:
        run_id: The run ID to visualize
        dagu_home: Path to dagu home (auto-detected if None)
        dag_name: DAG name (auto-detected if None)
        format: Output format
        aggregation: Aggregation strategy
        color_by: Color scheme
        show_metrics: Show inline metrics
        expand_subdags: Expand nested sub-DAGs
        **options: Additional options

    Returns:
        Rendered visualization
    """
    from agent_arborist.home import get_dagu_home
    from agent_arborist.dagu_runs import load_dag_run, list_dag_runs

    # Get dagu home
    if dagu_home is None:
        dagu_home = get_dagu_home()

    # Find the DAG run
    dag_run = None

    if dag_name:
        dag_run = load_dag_run(
            dagu_home,
            dag_name,
            run_id,
            expand_subdags=expand_subdags,
            include_outputs=True,
        )
    else:
        # Search all DAGs for this run ID
        runs = list_dag_runs(dagu_home, limit=100)
        for run in runs:
            if run.run_id == run_id or run_id in run.run_id:
                dag_run = load_dag_run(
                    dagu_home,
                    run.dag_name,
                    run.run_id,
                    expand_subdags=expand_subdags,
                    include_outputs=True,
                )
                break

    if dag_run is None:
        raise ValueError(f"Run not found: {run_id}")

    # Build tree
    tree = build_metrics_tree(dag_run)

    # Aggregate
    tree = aggregate_tree(tree, strategy=aggregation)

    # Render
    return render_tree(
        tree,
        format=format,
        color_by=color_by,
        show_metrics=show_metrics,
        **options,
    )


__all__ = [
    # Models
    "NodeMetrics",
    "AggregatedMetrics",
    "MetricsNode",
    "MetricsTree",
    # Configuration
    "AggregationStrategy",
    "OutputFormat",
    # Core functions
    "build_metrics_tree",
    "aggregate_tree",
    "render_tree",
    "render_metrics",
    "visualize_run",
    "extract_metrics_from_dag_run",
]
