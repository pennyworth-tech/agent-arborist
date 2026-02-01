"""Base classes and types for the hook system."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_arborist.step_results import StepResultBase


@dataclass
class StepContext:
    """Context available to steps during execution.

    This provides all the information a step might need about the
    current task and environment.
    """

    task_id: str | None
    spec_id: str
    worktree_path: Path | None
    branch_name: str
    parent_branch: str
    arborist_home: Path

    def to_variables(self) -> dict[str, str]:
        """Convert context to variable dictionary for substitution."""
        return {
            "task_id": self.task_id or "",
            "spec_id": self.spec_id,
            "worktree_path": str(self.worktree_path) if self.worktree_path else "",
            "branch_name": self.branch_name,
            "parent_branch": self.parent_branch,
            "arborist_home": str(self.arborist_home),
            "timestamp": datetime.now().isoformat(),
        }


class CustomStep(ABC):
    """Base class for custom Python steps.

    Users can implement this interface to create custom hook steps
    that are loaded dynamically from configuration.

    Example:
        class MyValidator(CustomStep):
            def __init__(self, config: dict):
                self.strict = config.get("strict", False)

            def execute(self, ctx: StepContext) -> StepResultBase:
                # Custom validation logic
                return CustomStepResult(success=True, data={"validated": True})
    """

    @abstractmethod
    def __init__(self, config: dict[str, Any]):
        """Initialize with configuration from JSON.

        Args:
            config: Configuration dictionary from the step definition's
                   "config" field.
        """
        pass

    @abstractmethod
    def execute(self, ctx: StepContext) -> "StepResultBase":
        """Execute the step and return a result.

        Args:
            ctx: Step context with task and environment information.

        Returns:
            A StepResultBase subclass with the execution results.
        """
        pass


@dataclass
class HookApplication:
    """Record of a single hook application."""

    step_name: str
    hook_point: str
    task_id: str | None
    step_type: str = ""


class HookDiagnostics:
    """Diagnostic utility for tracking hook application.

    Collects information about which hooks were applied during
    DAG generation for debugging and visibility.
    """

    def __init__(self):
        self.applications: list[HookApplication] = []

    def record(
        self,
        step_name: str,
        hook_point: str,
        task_id: str | None,
        step_type: str = "",
    ) -> None:
        """Record a hook application.

        Args:
            step_name: Name of the injected step
            hook_point: Hook point where injection occurred
            task_id: Task ID (None for DAG-level hooks)
            step_type: Type of step (llm_eval, shell, etc.)
        """
        self.applications.append(
            HookApplication(
                step_name=step_name,
                hook_point=hook_point,
                task_id=task_id,
                step_type=step_type,
            )
        )

    def summary(self) -> str:
        """Generate diagnostic summary.

        Returns:
            Human-readable summary of hook applications.
        """
        if not self.applications:
            return "No hooks applied"

        # Count by hook point
        by_point: dict[str, int] = {}
        for app in self.applications:
            by_point[app.hook_point] = by_point.get(app.hook_point, 0) + 1

        # Count by step type
        by_type: dict[str, int] = {}
        for app in self.applications:
            if app.step_type:
                by_type[app.step_type] = by_type.get(app.step_type, 0) + 1

        lines = [
            "Hook Application Summary",
            f"  Total injections: {len(self.applications)}",
            "",
            "  By hook point:",
        ]

        for point, count in sorted(by_point.items()):
            lines.append(f"    {point}: {count}")

        if by_type:
            lines.append("")
            lines.append("  By step type:")
            for step_type, count in sorted(by_type.items()):
                lines.append(f"    {step_type}: {count}")

        return "\n".join(lines)

    def get_applications_for_task(self, task_id: str) -> list[HookApplication]:
        """Get all hook applications for a specific task.

        Args:
            task_id: Task identifier

        Returns:
            List of hook applications for that task.
        """
        return [app for app in self.applications if app.task_id == task_id]

    def get_applications_for_point(self, hook_point: str) -> list[HookApplication]:
        """Get all hook applications at a specific hook point.

        Args:
            hook_point: Hook point name

        Returns:
            List of hook applications at that point.
        """
        return [app for app in self.applications if app.hook_point == hook_point]
