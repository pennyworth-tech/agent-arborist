"""Base renderer and output format definitions."""

from enum import Enum
from typing import Protocol, Union

from agent_arborist.viz.models.tree import MetricsTree


class OutputFormat(str, Enum):
    """Output format for rendering."""

    ASCII = "ascii"
    JSON = "json"
    SVG = "svg"
    PNG = "png"
    MARKDOWN = "markdown"
    HTML = "html"


class ColorScheme:
    """Color scheme definitions for renderers."""

    STATUS = {
        "success": "#22c55e",  # green-500
        "failed": "#ef4444",  # red-500
        "running": "#3b82f6",  # blue-500
        "pending": "#9ca3af",  # gray-400
        "skipped": "#eab308",  # yellow-500
    }

    QUALITY_GRADIENT = [
        (1, "#ef4444"),  # 1-2: red
        (3, "#f97316"),  # 3-4: orange
        (5, "#eab308"),  # 5-6: yellow
        (7, "#84cc16"),  # 7-8: lime
        (9, "#22c55e"),  # 9-10: green
    ]

    PASS_RATE_GRADIENT = [
        (0.0, "#ef4444"),  # 0%: red
        (0.5, "#eab308"),  # 50%: yellow
        (0.8, "#84cc16"),  # 80%: lime
        (1.0, "#22c55e"),  # 100%: green
    ]

    @classmethod
    def get_status_color(cls, status: str) -> str:
        """Get color for a status."""
        return cls.STATUS.get(status, cls.STATUS["pending"])

    @classmethod
    def get_quality_color(cls, score: float) -> str:
        """Get color for a quality score (1-10)."""
        for threshold, color in cls.QUALITY_GRADIENT:
            if score <= threshold:
                return color
        return cls.QUALITY_GRADIENT[-1][1]

    @classmethod
    def get_pass_rate_color(cls, rate: float) -> str:
        """Get color for a pass rate (0-1)."""
        for threshold, color in cls.PASS_RATE_GRADIENT:
            if rate <= threshold:
                return color
        return cls.PASS_RATE_GRADIENT[-1][1]


class TreeRenderer(Protocol):
    """Protocol for tree renderers."""

    format: OutputFormat

    def render(
        self,
        tree: MetricsTree,
        *,
        color_by: str = "status",
        show_metrics: bool = False,
        depth: int | None = None,
        **options,
    ) -> Union[str, bytes]:
        """Render the tree to the target format.

        Args:
            tree: The metrics tree to render
            color_by: Color scheme to use ("status", "quality", "pass-rate")
            show_metrics: Whether to show inline metrics
            depth: Maximum depth to render (None for unlimited)
            **options: Additional format-specific options

        Returns:
            Rendered output (string for text formats, bytes for binary)
        """
        ...
