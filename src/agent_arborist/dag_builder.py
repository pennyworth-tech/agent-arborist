"""Sequential DAG builder for DAGU task execution.

This module generates DAGU YAML for sequential task execution.
All tasks execute one at a time, with hierarchy expressed via subdags.

Key features:
- Sequential execution only (no parallelism)
- Subdags for logical grouping (phases, task groups)
- Hooks and tests at any level in the hierarchy
- Plain git commits (no jj, no workspaces)
- Container mode: auto, enabled, or disabled
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from agent_arborist.container_runner import (
    ContainerMode,
    should_use_container,
)
from agent_arborist.task_state import TaskTree


@dataclass
class SubDagStep:
    """A step in a DAGU subdag."""

    name: str
    command: str | None = None  # Command to execute (None if calling subdag)
    call: str | None = None  # Subdag name to call (None if command step)
    depends: list[str] = field(default_factory=list)
    output: str | dict | None = None  # Dagu output: string or {name, key} dict


@dataclass
class SubDag:
    """A DAGU subdag."""

    name: str
    steps: list[SubDagStep] = field(default_factory=list)
    description: str = ""
    env: list[str] = field(default_factory=list)
    is_root: bool = False


@dataclass
class DagBundle:
    """Complete DAG bundle with root and all subdags."""

    root: SubDag
    subdags: list[SubDag]


@dataclass
class DagConfig:
    """Configuration for DAG generation."""

    name: str
    description: str = ""
    spec_id: str = ""
    container_mode: ContainerMode = ContainerMode.AUTO
    repo_path: Path | None = None  # For devcontainer detection
    runner: str | None = None  # AI runner to use
    model: str | None = None  # Model to use
    arborist_config: Any = None  # For step-specific settings
    arborist_home: Path | None = None  # For hooks

    def get_step_runner_model(self, step: str) -> tuple[str | None, str | None]:
        """Get runner/model for a specific step."""
        if self.arborist_config is not None:
            from agent_arborist.config import get_step_runner_model
            return get_step_runner_model(
                self.arborist_config,
                step,
                cli_runner=self.runner,
                cli_model=self.model,
            )
        return self.runner, self.model


def build_arborist_command(task_id: str, subcommand: str) -> str:
    """Build arborist task command.

    Args:
        task_id: Task identifier (e.g., "T001")
        subcommand: Task subcommand (e.g., "run", "run-test")

    Returns:
        Command string
    """
    return f"arborist task {subcommand} {task_id}"


class SequentialDagBuilder:
    """Builds sequential DAGU DAG with subdags for task execution."""

    def __init__(self, config: DagConfig):
        self.config = config
        self._task_tree: TaskTree | None = None
        self._use_containers = False

    def build(self, task_tree: TaskTree) -> DagBundle:
        """Build a complete DAG bundle from a TaskTree.

        Args:
            task_tree: Task hierarchy with parent/child relationships

        Returns:
            DagBundle with root DAG and all subdags
        """
        self._task_tree = task_tree

        # Check if we should use containers
        self._use_containers = should_use_container(
            self.config.container_mode,
            self.config.repo_path,
        )

        # Build all subdags (for tasks with children)
        subdags = self._build_all_subdags(task_tree)

        # Build root DAG
        root = self._build_root_dag(task_tree)

        return DagBundle(root=root, subdags=subdags)

    def _build_root_dag(self, task_tree: TaskTree) -> SubDag:
        """Build the root DAG that calls root tasks sequentially.

        Structure:
        1. setup: Create feature branch if needed
        2. Sequential calls to root tasks (each depends on previous)
        3. finalize: Push to remote
        """
        steps: list[SubDagStep] = []
        prev_step: str | None = None

        # Root tasks: execute sequentially
        root_task_ids = task_tree.root_tasks
        for task_id in root_task_ids:
            task = task_tree.get_task(task_id)
            if not task:
                continue

            # If task has children, call its subdag
            # Otherwise, run the task directly
            if task.children:
                step = SubDagStep(
                    name=f"c-{task_id}",
                    call=task_id,
                    depends=[prev_step] if prev_step else [],
                )
            else:
                step = SubDagStep(
                    name=task_id,
                    command=build_arborist_command(task_id, "run"),
                    depends=[prev_step] if prev_step else [],
                )
            steps.append(step)
            prev_step = step.name

        # Finalize: push to remote
        steps.append(SubDagStep(
            name="finalize",
            command="arborist spec finalize",
            depends=[prev_step] if prev_step else [],
        ))

        # Environment variables
        spec_id = self.config.spec_id or self.config.name
        env = [
            f"ARBORIST_SPEC_ID={spec_id}",
            "ARBORIST_CONTAINER_MODE=${ARBORIST_CONTAINER_MODE}",
            "ARBORIST_SOURCE_REV=${ARBORIST_SOURCE_REV}",
            "ARBORIST_RUNNER=${ARBORIST_RUNNER}",
            "ARBORIST_MODEL=${ARBORIST_MODEL}",
        ]

        return SubDag(
            name=self.config.name,
            description=self.config.description,
            env=env,
            steps=steps,
            is_root=True,
        )

    def _build_all_subdags(self, task_tree: TaskTree) -> list[SubDag]:
        """Build subdags for all tasks that have children."""
        subdags: list[SubDag] = []

        for task_id in task_tree.tasks.keys():
            task = task_tree.get_task(task_id)
            if not task or not task.children:
                # Skip leaf tasks - they're called directly
                continue

            subdag = self._build_parent_subdag(task_id, task_tree)
            subdags.append(subdag)

        return subdags

    def _build_parent_subdag(self, task_id: str, task_tree: TaskTree) -> SubDag:
        """Build a subdag for a parent task (task with children).

        The subdag executes children sequentially, then runs tests/hooks.

        Structure:
        1. Sequential child execution (each depends on previous)
        2. Phase-level tests (if any)
        3. Phase-level hooks (if any)
        """
        steps: list[SubDagStep] = []
        task = task_tree.get_task(task_id)

        if not task:
            return SubDag(name=task_id, steps=steps)

        child_ids = task.children
        prev_step: str | None = None

        for child_id in child_ids:
            child = task_tree.get_task(child_id)
            if not child:
                continue

            # If child has children, call its subdag
            # Otherwise, run the task directly
            if child.children:
                step = SubDagStep(
                    name=f"c-{child_id}",
                    call=child_id,
                    depends=[prev_step] if prev_step else [],
                )
            else:
                step = SubDagStep(
                    name=child_id,
                    command=build_arborist_command(child_id, "run"),
                    depends=[prev_step] if prev_step else [],
                )
            steps.append(step)
            prev_step = step.name

        # Add phase-level test step if this is a phase (has description)
        if prev_step and task.description:
            steps.append(SubDagStep(
                name="phase-tests",
                command=f"arborist task run-test {task_id}",
                depends=[prev_step],
            ))

        # Environment
        spec_id = self.config.spec_id or self.config.name
        env = [
            f"ARBORIST_SPEC_ID={spec_id}",
            f"ARBORIST_TASK_ID={task_id}",
            "ARBORIST_CONTAINER_MODE=${ARBORIST_CONTAINER_MODE}",
            "ARBORIST_SOURCE_REV=${ARBORIST_SOURCE_REV}",
            "ARBORIST_RUNNER=${ARBORIST_RUNNER}",
            "ARBORIST_MODEL=${ARBORIST_MODEL}",
        ]

        return SubDag(
            name=task_id,
            description=task.description,
            env=env,
            steps=steps,
        )

    def _step_to_dict(self, step: SubDagStep) -> dict[str, Any]:
        """Convert a SubDagStep to a dictionary for YAML serialization."""
        d: dict[str, Any] = {"name": step.name}

        if step.command is not None:
            d["command"] = step.command
        if step.call is not None:
            d["call"] = step.call
        if step.depends:
            d["depends"] = step.depends
        if step.output is not None:
            d["output"] = step.output

        return d

    def _subdag_to_dict(self, subdag: SubDag) -> dict[str, Any]:
        """Convert a SubDag to a dictionary for YAML serialization."""
        d: dict[str, Any] = {"name": subdag.name}

        if subdag.description:
            d["description"] = subdag.description
        if subdag.env:
            d["env"] = subdag.env

        d["steps"] = [self._step_to_dict(step) for step in subdag.steps]

        return d

    def build_yaml(self, task_tree: TaskTree) -> str:
        """Build multi-document DAGU YAML string from a TaskTree."""
        bundle = self.build(task_tree)
        return self._serialize_bundle(bundle)

    def _serialize_bundle(self, bundle: DagBundle) -> str:
        """Serialize a DagBundle to multi-document YAML."""

        # Custom YAML dumper for better formatting
        class CustomDumper(yaml.SafeDumper):
            pass

        def represent_list(dumper, data):
            if all(isinstance(item, str) for item in data):
                return dumper.represent_sequence(
                    "tag:yaml.org,2002:seq", data, flow_style=True
                )
            return dumper.represent_sequence("tag:yaml.org,2002:seq", data)

        def represent_str(dumper, data):
            if "\n" in data:
                return dumper.represent_scalar(
                    "tag:yaml.org,2002:str", data, style="|"
                )
            return dumper.represent_scalar("tag:yaml.org,2002:str", data)

        CustomDumper.add_representer(list, represent_list)
        CustomDumper.add_representer(str, represent_str)

        # Build multi-document YAML
        documents = []

        # Root DAG first
        root_dict = self._subdag_to_dict(bundle.root)
        documents.append(yaml.dump(
            root_dict, Dumper=CustomDumper, default_flow_style=False, sort_keys=False
        ))

        # Then all subdags
        for subdag in bundle.subdags:
            subdag_dict = self._subdag_to_dict(subdag)
            documents.append(yaml.dump(
                subdag_dict, Dumper=CustomDumper, default_flow_style=False, sort_keys=False
            ))

        return "---\n".join(documents)


def build_dag_yaml(
    task_tree: TaskTree,
    dag_name: str = "",
    description: str = "",
    container_mode: ContainerMode = ContainerMode.AUTO,
    repo_path: Path | None = None,
    arborist_config: Any = None,
    arborist_home: Path | None = None,
) -> str:
    """Build sequential DAG YAML from a TaskTree.

    This is the main entry point for generating sequential DAGs.

    Args:
        task_tree: Task hierarchy
        dag_name: Name for the DAG
        description: DAG description
        container_mode: Container execution mode
        repo_path: Path to repo for devcontainer detection
        arborist_config: Arborist configuration
        arborist_home: Arborist home directory

    Returns:
        Multi-document YAML string
    """
    config = DagConfig(
        name=dag_name.replace("-", "_"),
        description=description,
        spec_id=dag_name,
        container_mode=container_mode,
        repo_path=repo_path,
        arborist_config=arborist_config,
        arborist_home=arborist_home,
    )

    builder = SequentialDagBuilder(config)
    return builder.build_yaml(task_tree)


def parse_yaml_to_bundle(yaml_content: str) -> DagBundle:
    """Parse a multi-document DAGU YAML string into a DagBundle.

    Args:
        yaml_content: Multi-document YAML string

    Returns:
        DagBundle with root and subdags populated
    """
    documents = list(yaml.safe_load_all(yaml_content))

    if not documents:
        raise ValueError("No YAML documents found")

    # First document is root DAG
    root_dict = documents[0]
    root = SubDag(
        name=root_dict.get("name", "root"),
        description=root_dict.get("description", ""),
        env=root_dict.get("env", []),
        is_root=True,
        steps=[
            SubDagStep(
                name=s.get("name", ""),
                command=s.get("command"),
                call=s.get("call"),
                depends=s.get("depends", []),
                output=s.get("output"),
            )
            for s in root_dict.get("steps", [])
        ],
    )

    # Remaining documents are subdags
    subdags = []
    for doc in documents[1:]:
        subdag = SubDag(
            name=doc.get("name", ""),
            description=doc.get("description", ""),
            env=doc.get("env", []),
            is_root=False,
            steps=[
                SubDagStep(
                    name=s.get("name", ""),
                    command=s.get("command"),
                    call=s.get("call"),
                    depends=s.get("depends", []),
                    output=s.get("output"),
                )
                for s in doc.get("steps", [])
            ],
        )
        subdags.append(subdag)

    return DagBundle(root=root, subdags=subdags)


def is_task_dag(yaml_content: str) -> bool:
    """Check if a DAG YAML is an arborist-generated task DAG.

    Looks for ARBORIST_SPEC_ID in the environment.

    Args:
        yaml_content: Multi-document YAML string

    Returns:
        True if this is an arborist task DAG
    """
    try:
        documents = list(yaml.safe_load_all(yaml_content))
        if not documents:
            return False

        root = documents[0]
        env = root.get("env", [])
        return any(e.startswith("ARBORIST_SPEC_ID=") for e in env)
    except Exception:
        return False
