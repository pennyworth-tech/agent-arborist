"""SVG tree renderer for dendrogram visualization.

Generates horizontal tree layouts with colored nodes and metrics badges.
Uses pure SVG without external dependencies.
"""

from dataclasses import dataclass
from typing import Any

from agent_arborist.viz.models.tree import MetricsNode, MetricsTree
from agent_arborist.viz.renderers.base import ColorScheme, OutputFormat


@dataclass
class NodeLayout:
    """Layout information for a node."""

    x: float
    y: float
    width: float
    height: float
    node: MetricsNode


class SVGRenderer:
    """Renders a MetricsTree as SVG dendrogram."""

    format = OutputFormat.SVG

    # Layout configuration
    NODE_HEIGHT = 32
    NODE_PADDING = 8
    VERTICAL_SPACING = 12
    HORIZONTAL_SPACING = 200
    TEXT_SIZE = 12
    BADGE_SIZE = 16
    MARGIN = 40

    # Status symbols (using unicode)
    STATUS_SYMBOLS = {
        "success": "✓",
        "failed": "✗",
        "running": "●",
        "pending": "○",
        "skipped": "⊘",
    }

    def render(
        self,
        tree: MetricsTree,
        *,
        color_by: str = "status",
        show_metrics: bool = False,
        depth: int | None = None,
        width: int | None = None,
        height: int | None = None,
        **options,
    ) -> str:
        """Render the tree as SVG.

        Args:
            tree: The metrics tree to render
            color_by: Color scheme ("status", "quality", "pass-rate")
            show_metrics: Whether to show inline metrics
            depth: Maximum depth to render
            width: Override SVG width
            height: Override SVG height
            **options: Additional options

        Returns:
            SVG string
        """
        # Calculate layout
        layouts = self._calculate_layout(tree.root, depth)

        # Calculate bounds
        max_x = max(l.x + l.width for l in layouts) + self.MARGIN
        max_y = max(l.y + l.height for l in layouts) + self.MARGIN

        svg_width = width or int(max_x)
        svg_height = height or int(max_y)

        # Generate SVG
        svg_parts = [
            self._svg_header(svg_width, svg_height),
            self._svg_styles(color_by),
            self._svg_defs(),
        ]

        # Draw edges first (so they appear behind nodes)
        for layout in layouts:
            if layout.node.parent:
                parent_layout = self._find_layout(layouts, layout.node.parent)
                if parent_layout:
                    svg_parts.append(
                        self._draw_edge(parent_layout, layout)
                    )

        # Draw nodes
        for layout in layouts:
            svg_parts.append(
                self._draw_node(layout, color_by, show_metrics)
            )

        svg_parts.append("</svg>")

        return "\n".join(svg_parts)

    def _calculate_layout(
        self,
        root: MetricsNode,
        max_depth: int | None,
    ) -> list[NodeLayout]:
        """Calculate layout positions for all nodes."""
        layouts: list[NodeLayout] = []
        y_offset = [self.MARGIN]  # Use list for mutable closure

        def _layout_node(node: MetricsNode, depth: int) -> NodeLayout:
            """Recursively layout a node and its children."""
            if max_depth is not None and depth > max_depth:
                return None

            x = self.MARGIN + depth * self.HORIZONTAL_SPACING
            y = y_offset[0]

            # Calculate node width based on text
            text_width = len(node.name) * 7 + self.BADGE_SIZE + self.NODE_PADDING * 2
            width = max(text_width, 120)

            layout = NodeLayout(
                x=x,
                y=y,
                width=width,
                height=self.NODE_HEIGHT,
                node=node,
            )
            layouts.append(layout)

            # Layout children
            if node.children and (max_depth is None or depth < max_depth):
                for child in node.children:
                    y_offset[0] += self.NODE_HEIGHT + self.VERTICAL_SPACING
                    _layout_node(child, depth + 1)
            else:
                y_offset[0] += self.NODE_HEIGHT + self.VERTICAL_SPACING

            return layout

        _layout_node(root, 0)

        # Adjust parent Y positions to center them among children
        self._center_parents(root, layouts)

        return layouts

    def _center_parents(
        self,
        node: MetricsNode,
        layouts: list[NodeLayout],
    ) -> tuple[float, float]:
        """Center parent nodes vertically among their children."""
        layout = self._find_layout(layouts, node)
        if not layout:
            return (0, 0)

        if not node.children:
            return (layout.y, layout.y + layout.height)

        # Get bounds of all children
        child_bounds = [
            self._center_parents(child, layouts) for child in node.children
        ]

        min_y = min(b[0] for b in child_bounds)
        max_y = max(b[1] for b in child_bounds)

        # Center this node
        center_y = (min_y + max_y) / 2 - layout.height / 2
        layout.y = center_y

        return (min_y, max_y)

    def _find_layout(
        self,
        layouts: list[NodeLayout],
        node: MetricsNode,
    ) -> NodeLayout | None:
        """Find layout for a given node."""
        for layout in layouts:
            if layout.node is node:
                return layout
        return None

    def _svg_header(self, width: int, height: int) -> str:
        """Generate SVG header."""
        return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">'''

    def _svg_styles(self, color_by: str) -> str:
        """Generate SVG styles."""
        return """<style>
    .node-rect {
        rx: 4;
        ry: 4;
        stroke-width: 2;
    }
    .node-text {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        font-size: 12px;
        dominant-baseline: middle;
    }
    .node-symbol {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        font-size: 14px;
        dominant-baseline: middle;
        text-anchor: middle;
    }
    .edge {
        fill: none;
        stroke: #94a3b8;
        stroke-width: 1.5;
    }
    .duration-text {
        font-size: 10px;
        fill: #64748b;
    }
    .metrics-badge {
        font-size: 10px;
        fill: white;
    }
</style>"""

    def _svg_defs(self) -> str:
        """Generate SVG definitions (markers, gradients)."""
        return """<defs>
    <marker id="arrow" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
        <polygon points="0 0, 10 3.5, 0 7" fill="#94a3b8"/>
    </marker>
</defs>"""

    def _draw_edge(
        self,
        parent: NodeLayout,
        child: NodeLayout,
    ) -> str:
        """Draw an edge between parent and child nodes."""
        # Start from right side of parent, end at left side of child
        x1 = parent.x + parent.width
        y1 = parent.y + parent.height / 2
        x2 = child.x
        y2 = child.y + child.height / 2

        # Use a curved path
        mid_x = (x1 + x2) / 2

        return f'''<path class="edge" d="M {x1} {y1} C {mid_x} {y1}, {mid_x} {y2}, {x2} {y2}"/>'''

    def _draw_node(
        self,
        layout: NodeLayout,
        color_by: str,
        show_metrics: bool,
    ) -> str:
        """Draw a node with its label and status indicator."""
        node = layout.node
        parts = []

        # Determine colors
        fill_color, stroke_color, text_color = self._get_node_colors(
            node, color_by
        )

        # Background rect
        parts.append(
            f'''<rect class="node-rect" x="{layout.x}" y="{layout.y}" '''
            f'''width="{layout.width}" height="{layout.height}" '''
            f'''fill="{fill_color}" stroke="{stroke_color}"/>'''
        )

        # Status symbol
        symbol = self.STATUS_SYMBOLS.get(node.status, "○")
        symbol_x = layout.x + 12
        symbol_y = layout.y + layout.height / 2
        symbol_color = ColorScheme.get_status_color(node.status)
        parts.append(
            f'''<text class="node-symbol" x="{symbol_x}" y="{symbol_y}" fill="{symbol_color}">{symbol}</text>'''
        )

        # Node name
        text_x = layout.x + 24
        text_y = layout.y + layout.height / 2

        # Truncate long names
        name = node.name
        if len(name) > 20:
            name = name[:18] + "..."

        parts.append(
            f'''<text class="node-text" x="{text_x}" y="{text_y}" fill="{text_color}">{self._escape_xml(name)}</text>'''
        )

        # Duration badge (if available)
        duration = node.duration_seconds
        if duration and duration > 0:
            duration_text = self._format_duration(duration)
            dur_x = layout.x + layout.width - 10
            dur_y = layout.y + layout.height / 2
            parts.append(
                f'''<text class="duration-text" x="{dur_x}" y="{dur_y}" text-anchor="end">{duration_text}</text>'''
            )

        # Metrics badge (if requested and available)
        if show_metrics and node.aggregated and node.aggregated.has_test_metrics():
            agg = node.aggregated
            badge_text = f"{agg.total_tests_passed}/{agg.total_tests_run}"
            badge_x = layout.x + layout.width - 50
            badge_y = layout.y + 4
            badge_color = self._get_pass_rate_badge_color(agg.total_pass_rate)
            parts.append(
                f'''<rect x="{badge_x}" y="{badge_y}" width="40" height="14" rx="7" fill="{badge_color}"/>'''
            )
            parts.append(
                f'''<text class="metrics-badge" x="{badge_x + 20}" y="{badge_y + 10}" text-anchor="middle">{badge_text}</text>'''
            )

        return f'''<g class="node" data-id="{node.id}">\n{''.join(parts)}\n</g>'''

    def _get_node_colors(
        self,
        node: MetricsNode,
        color_by: str,
    ) -> tuple[str, str, str]:
        """Get fill, stroke, and text colors for a node."""
        if color_by == "status":
            status_color = ColorScheme.get_status_color(node.status)
            # Light background with colored border
            if node.status == "success":
                return ("#f0fdf4", status_color, "#166534")  # green tones
            elif node.status == "failed":
                return ("#fef2f2", status_color, "#991b1b")  # red tones
            elif node.status == "running":
                return ("#eff6ff", status_color, "#1e40af")  # blue tones
            elif node.status == "skipped":
                return ("#fefce8", status_color, "#854d0e")  # yellow tones
            else:
                return ("#f8fafc", "#cbd5e1", "#475569")  # gray tones

        elif color_by == "quality":
            score = None
            if node.metrics:
                score = node.metrics.code_quality_score
            if score:
                quality_color = ColorScheme.get_quality_color(score)
                return ("#ffffff", quality_color, "#1f2937")
            return ("#f8fafc", "#cbd5e1", "#475569")

        elif color_by == "pass-rate":
            rate = None
            if node.aggregated:
                rate = node.aggregated.total_pass_rate
            if rate is not None:
                rate_color = ColorScheme.get_pass_rate_color(rate)
                return ("#ffffff", rate_color, "#1f2937")
            return ("#f8fafc", "#cbd5e1", "#475569")

        # Default
        return ("#ffffff", "#e2e8f0", "#1f2937")

    def _get_pass_rate_badge_color(self, rate: float | None) -> str:
        """Get badge color for pass rate."""
        if rate is None:
            return "#94a3b8"
        if rate >= 0.95:
            return "#22c55e"
        elif rate >= 0.8:
            return "#84cc16"
        elif rate >= 0.5:
            return "#eab308"
        else:
            return "#ef4444"

    def _format_duration(self, seconds: float) -> str:
        """Format duration as human-readable string."""
        if seconds < 1:
            return "<1s"
        elif seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            secs = int(seconds % 60)
            if secs:
                return f"{minutes}m{secs}s"
            return f"{minutes}m"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}h{minutes}m"

    def _escape_xml(self, text: str) -> str:
        """Escape XML special characters."""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )
