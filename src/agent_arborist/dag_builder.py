"""DAG builder for generating DAGU YAML from task specs."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from agent_arborist.task_spec import TaskSpec, Task


@dataclass
class DagStep:
    """A step in the DAGU DAG."""

    name: str
    command: str
    depends: list[str] = field(default_factory=list)
    description: str | None = None


@dataclass
class DagConfig:
    """Configuration for DAG generation."""

    name: str
    description: str = ""
    echo_delay_ms: int = 100  # Delay for echo commands


class DagBuilder:
    """Builds DAGU DAG YAML from a TaskSpec."""

    def __init__(self, config: DagConfig):
        self.config = config

    def build(self, spec: TaskSpec) -> dict[str, Any]:
        """Build a DAGU DAG dictionary from a TaskSpec."""
        steps: list[DagStep] = []

        # Build task steps
        for task in spec.tasks:
            step = self._build_task_step(task, spec)
            steps.append(step)

        # Build phase completion steps
        for phase in spec.phases:
            if phase.tasks:
                phase_step = self._build_phase_complete_step(phase, spec)
                steps.append(phase_step)

        # Build final completion step
        final_step = self._build_final_step(spec)
        steps.append(final_step)

        # Convert to DAGU format
        dag = {
            "name": self.config.name,
            "description": self.config.description or spec.project,
            "steps": [self._step_to_dict(step) for step in steps],
        }

        return dag

    def _build_task_step(self, task: Task, spec: TaskSpec) -> DagStep:
        """Build a DAG step for a task."""
        # Get dependencies for this task
        deps = spec.dependencies.get(task.id, [])

        # Convert dependency task IDs to step names
        dep_step_names = []
        for dep_id in deps:
            dep_task = spec.get_task(dep_id)
            if dep_task:
                dep_step_names.append(dep_task.full_name)

        # Create echo command with delay
        # Escape backticks to prevent shell command substitution
        safe_description = task.description.replace("`", "'")
        delay_sec = self.config.echo_delay_ms / 1000
        command = f'sleep {delay_sec} && echo "[{task.id}] {safe_description}"'

        return DagStep(
            name=task.full_name,
            command=command,
            depends=dep_step_names,
            description=task.description,
        )

    def _build_phase_complete_step(self, phase, spec: TaskSpec) -> DagStep:
        """Build a completion step for a phase."""
        # Depends on all tasks in the phase
        phase_task_names = [task.full_name for task in phase.tasks]

        # Slugify phase name
        phase_slug = phase.name.lower()
        phase_slug = phase_slug.replace(" ", "-").replace(":", "")
        phase_slug = "".join(c for c in phase_slug if c.isalnum() or c == "-")

        step_name = f"phase-complete-{phase_slug}"

        checkpoint_msg = phase.checkpoint or phase.name
        delay_sec = self.config.echo_delay_ms / 1000
        command = f'sleep {delay_sec} && echo "✓ Phase complete: {checkpoint_msg}"'

        return DagStep(
            name=step_name,
            command=command,
            depends=phase_task_names,
            description=f"Phase complete: {phase.name}",
        )

    def _build_final_step(self, spec: TaskSpec) -> DagStep:
        """Build a final completion step."""
        # Depends on all phase completion steps
        phase_step_names = []
        for phase in spec.phases:
            if phase.tasks:
                phase_slug = phase.name.lower()
                phase_slug = phase_slug.replace(" ", "-").replace(":", "")
                phase_slug = "".join(c for c in phase_slug if c.isalnum() or c == "-")
                phase_step_names.append(f"phase-complete-{phase_slug}")

        delay_sec = self.config.echo_delay_ms / 1000
        command = f'sleep {delay_sec} && echo "✓ All tasks complete: {spec.project}"'

        return DagStep(
            name="all-complete",
            command=command,
            depends=phase_step_names,
            description="All tasks complete",
        )

    def _step_to_dict(self, step: DagStep) -> dict[str, Any]:
        """Convert a DagStep to a dictionary for YAML serialization."""
        d: dict[str, Any] = {
            "name": step.name,
            "command": step.command,
        }

        if step.depends:
            d["depends"] = step.depends

        return d

    def build_yaml(self, spec: TaskSpec) -> str:
        """Build DAGU DAG YAML string from a TaskSpec."""
        dag = self.build(spec)

        # Custom YAML dumper for better formatting
        class CustomDumper(yaml.SafeDumper):
            pass

        # Make lists flow-style for depends
        def represent_list(dumper, data):
            if all(isinstance(item, str) for item in data):
                return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=True)
            return dumper.represent_sequence("tag:yaml.org,2002:seq", data)

        CustomDumper.add_representer(list, represent_list)

        return yaml.dump(dag, Dumper=CustomDumper, default_flow_style=False, sort_keys=False)


def build_dag(spec: TaskSpec, name: str, description: str = "") -> str:
    """Convenience function to build a DAG YAML from a TaskSpec."""
    config = DagConfig(name=name, description=description)
    builder = DagBuilder(config)
    return builder.build_yaml(spec)


def build_dag_from_file(
    spec_path: Path,
    output_path: Path | None = None,
    name: str | None = None,
    description: str = "",
) -> str:
    """Build a DAG from a task spec file."""
    from agent_arborist.task_spec import parse_task_spec

    spec = parse_task_spec(spec_path)

    # Use filename as name if not provided
    if name is None:
        name = spec_path.stem.replace("tasks-", "").replace("-", "_")

    yaml_content = build_dag(spec, name, description)

    if output_path:
        output_path.write_text(yaml_content)

    return yaml_content
