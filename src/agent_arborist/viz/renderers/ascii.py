"""ASCII tree renderer using Rich for terminal output."""

from typing import Union

from rich.console import Console
from rich.tree import Tree
from rich.text import Text
from rich.style import Style

from agent_arborist.viz.models.tree import MetricsNode, MetricsTree
from agent_arborist.viz.renderers.base import OutputFormat


class ASCIIRenderer:
    """Renders a MetricsTree as ASCII art using Rich."""

    format = OutputFormat.ASCII

    # Status symbols and colors
    STATUS_STYLES = {
        "success": ("✓", "green"),
        "failed": ("✗", "red"),
        "running": ("●", "blue"),
        "pending": ("○", "dim"),
        "skipped": ("⊘", "yellow"),
    }

    def render(
        self,
        tree: MetricsTree,
        *,
        color_by: str = "status",
        show_metrics: bool = False,
        depth: int | None = None,
        **options,
    ) -> str:
        """Render the tree as ASCII.

        Args:
            tree: The metrics tree to render
            color_by: Color scheme ("status", "quality", "pass-rate")
            show_metrics: Whether to show inline metrics
            depth: Maximum depth to render
            **options: Additional options (width, etc.)

        Returns:
            ASCII string representation of the tree
        """
        # Create a Rich Tree
        rich_tree = self._create_rich_tree(
            tree.root,
            color_by=color_by,
            show_metrics=show_metrics,
            max_depth=depth,
            current_depth=0,
        )

        # Render to string
        console = Console(
            force_terminal=True,
            width=options.get("width", 120),
            record=True,
        )
        console.print(rich_tree)

        return console.export_text()

    def _create_rich_tree(
        self,
        node: MetricsNode,
        *,
        color_by: str,
        show_metrics: bool,
        max_depth: int | None,
        current_depth: int,
    ) -> Tree:
        """Create a Rich Tree from a MetricsNode."""
        # Build label
        label = self._build_label(node, color_by=color_by, show_metrics=show_metrics)

        # Create tree node
        rich_tree = Tree(label)

        # Add children if within depth limit
        if max_depth is None or current_depth < max_depth:
            for child in node.children:
                child_tree = self._create_rich_tree(
                    child,
                    color_by=color_by,
                    show_metrics=show_metrics,
                    max_depth=max_depth,
                    current_depth=current_depth + 1,
                )
                rich_tree.add(child_tree)

        return rich_tree

    def _build_label(
        self,
        node: MetricsNode,
        *,
        color_by: str,
        show_metrics: bool,
    ) -> Text:
        """Build the label text for a node."""
        # Get status symbol and color
        symbol, color = self.STATUS_STYLES.get(
            node.status, self.STATUS_STYLES["pending"]
        )

        # Override color based on color_by option
        if color_by == "quality" and node.metrics and node.metrics.code_quality_score:
            color = self._get_quality_color(node.metrics.code_quality_score)
        elif color_by == "pass-rate" and node.aggregated:
            rate = node.aggregated.total_pass_rate
            if rate is not None:
                color = self._get_pass_rate_color(rate)

        # Build the text
        parts = []

        # Status symbol
        parts.append((f"{symbol} ", color))

        # Node name
        name_style = "bold" if node.node_type == "dag" else ""
        parts.append((node.name, name_style))

        # Duration if available
        duration = node.duration_seconds
        if duration is not None and duration > 0:
            parts.append((f" ({self._format_duration(duration)})", "dim"))

        # Node type indicator for call steps
        if node.node_type == "call" and node.child_dag_name:
            parts.append((f" → {node.child_dag_name}", "dim cyan"))

        # Inline metrics
        if show_metrics and node.aggregated and node.aggregated.has_test_metrics():
            agg = node.aggregated
            parts.append((" [", "dim"))
            parts.append((f"{agg.total_tests_passed}", "green"))
            parts.append(("/", "dim"))
            if agg.total_tests_failed > 0:
                parts.append((f"{agg.total_tests_failed}", "red"))
            else:
                parts.append((f"{agg.total_tests_failed}", "dim"))
            if agg.total_tests_skipped > 0:
                parts.append(("/", "dim"))
                parts.append((f"{agg.total_tests_skipped}", "yellow"))
            parts.append((f" tests]", "dim"))

            # Pass rate
            rate = agg.total_pass_rate
            if rate is not None:
                rate_color = self._get_pass_rate_color(rate)
                parts.append((f" {rate*100:.0f}%", rate_color))

        # Error message if present
        if node.error:
            parts.append((f" ERROR: {node.error[:50]}", "red"))
        elif node.exit_code is not None and node.exit_code != 0:
            parts.append((f" (exit: {node.exit_code})", "red"))

        # Compose Text object
        text = Text()
        for content, style in parts:
            text.append(content, style=style if style else None)

        return text

    def _get_quality_color(self, score: float) -> str:
        """Get color for a quality score (1-10)."""
        if score >= 9:
            return "green"
        elif score >= 7:
            return "bright_green"
        elif score >= 5:
            return "yellow"
        elif score >= 3:
            return "orange3"
        else:
            return "red"

    def _get_pass_rate_color(self, rate: float) -> str:
        """Get color for a pass rate (0-1)."""
        if rate >= 0.95:
            return "green"
        elif rate >= 0.8:
            return "bright_green"
        elif rate >= 0.6:
            return "yellow"
        elif rate >= 0.4:
            return "orange3"
        else:
            return "red"

    def _format_duration(self, seconds: float) -> str:
        """Format duration as human-readable string."""
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
