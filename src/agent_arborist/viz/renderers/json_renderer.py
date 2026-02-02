"""JSON renderer for metrics trees."""

import json
from typing import Any, Union

from agent_arborist.viz.models.tree import MetricsTree
from agent_arborist.viz.renderers.base import OutputFormat


class JSONRenderer:
    """Renders a MetricsTree as JSON."""

    format = OutputFormat.JSON

    def render(
        self,
        tree: MetricsTree,
        *,
        color_by: str = "status",
        show_metrics: bool = True,
        depth: int | None = None,
        **options,
    ) -> str:
        """Render the tree as JSON.

        Args:
            tree: The metrics tree to render
            color_by: Ignored for JSON (included for interface compatibility)
            show_metrics: Ignored for JSON (always includes metrics)
            depth: Maximum depth to render
            **options: Additional options (indent, etc.)

        Returns:
            JSON string representation of the tree
        """
        # Convert to dict
        data = tree.to_dict()

        # Apply depth limit if specified
        if depth is not None:
            data["root"] = self._limit_depth(data["root"], depth, current_depth=0)

        # Format with indentation
        indent = options.get("indent", 2)
        return json.dumps(data, indent=indent, default=str)

    def _limit_depth(
        self,
        node_dict: dict[str, Any],
        max_depth: int,
        current_depth: int,
    ) -> dict[str, Any]:
        """Limit tree depth in the dictionary representation."""
        if current_depth >= max_depth:
            # Remove children beyond max depth
            result = {k: v for k, v in node_dict.items() if k != "children"}
            if "children" in node_dict and node_dict["children"]:
                result["childrenCount"] = len(node_dict["children"])
                result["childrenTruncated"] = True
            return result

        # Recurse into children
        result = dict(node_dict)
        if "children" in result and result["children"]:
            result["children"] = [
                self._limit_depth(child, max_depth, current_depth + 1)
                for child in result["children"]
            ]

        return result


class MetricsJSONRenderer:
    """Renders just the metrics summary as JSON."""

    format = OutputFormat.JSON

    def render(
        self,
        tree: MetricsTree,
        *,
        include_by_task: bool = True,
        **options,
    ) -> str:
        """Render metrics summary as JSON.

        Args:
            tree: The metrics tree
            include_by_task: Include per-task metrics breakdown
            **options: Additional options

        Returns:
            JSON string with metrics summary
        """
        data = {
            "runId": tree.run_id,
            "dagName": tree.dag_name,
            "status": tree.status,
            "summary": tree.get_summary(),
        }

        if include_by_task:
            data["byTask"] = self._collect_task_metrics(tree)

        indent = options.get("indent", 2)
        return json.dumps(data, indent=indent, default=str)

    def _collect_task_metrics(self, tree: MetricsTree) -> dict[str, Any]:
        """Collect metrics for each task in the tree."""
        by_task = {}

        for node in tree.iter_nodes():
            if node.metrics and node.metrics.has_test_metrics():
                by_task[node.id] = {
                    "name": node.name,
                    "status": node.status,
                    "testsRun": node.metrics.tests_run,
                    "testsPassed": node.metrics.tests_passed,
                    "testsFailed": node.metrics.tests_failed,
                    "testsSkipped": node.metrics.tests_skipped,
                    "durationSeconds": node.metrics.duration_seconds,
                }

        return by_task
