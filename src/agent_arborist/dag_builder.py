"""DAG builder for generating DAGU YAML with subdags from task specs.

This module generates a multi-document YAML file where:
- Root DAG: Contains branches-setup and linear calls to root-level subdags
- Parent subdags: For tasks with children - pre-sync, child calls, complete
- Leaf subdags: For tasks without children - individual command nodes
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from agent_arborist.container_runner import (
    ContainerMode,
    should_use_container,
    devcontainer_up_command,
    devcontainer_down_command,
    devcontainer_exec_command,
)
from agent_arborist.home import get_arborist_home
from agent_arborist.task_spec import TaskSpec, Task
from agent_arborist.task_state import TaskTree, build_task_tree_from_spec


@dataclass
class SubDagStep:
    """A step in a DAGU subdag."""

    name: str
    command: str | None = None  # Command to execute (None if calling subdag)
    call: str | None = None  # Subdag name to call (None if command step)
    depends: list[str] = field(default_factory=list)
    output: str | None = None  # Dagu output variable name for stdout capture


@dataclass
class SubDag:
    """A DAGU subdag (or root DAG)."""

    name: str  # Task ID like "T001" or spec name for root
    steps: list[SubDagStep] = field(default_factory=list)
    description: str = ""
    env: list[str] = field(default_factory=list)
    is_root: bool = False


@dataclass
class DagBundle:
    """Complete DAG bundle with root and all subdags."""

    root: SubDag
    subdags: list[SubDag]  # All subdags in topological order


@dataclass
class DagConfig:
    """Configuration for DAG generation."""

    name: str
    description: str = ""
    spec_id: str = ""  # For manifest path
    container_mode: ContainerMode = ContainerMode.AUTO  # Container execution mode
    repo_path: Path | None = None  # Path to target repo for devcontainer detection
    runner: str | None = None  # Runner to use (claude, opencode, gemini)
    model: str | None = None  # Model to use (format depends on runner)


class SubDagBuilder:
    """Builds DAGU DAG with subdags from a TaskSpec."""

    def __init__(self, config: DagConfig):
        self.config = config
        self._task_tree: TaskTree | None = None
        self._use_containers = False  # Set during build()

    def build(self, spec: TaskSpec, task_tree: TaskTree) -> DagBundle:
        """Build a complete DAG bundle from a TaskSpec and TaskTree.

        Args:
            spec: Parsed task specification
            task_tree: Task hierarchy with parent/child relationships

        Returns:
            DagBundle with root DAG and all subdags
        """
        self._task_tree = task_tree

        # Check if we should use containers
        self._use_containers = should_use_container(
            self.config.container_mode,
            self.config.repo_path
        )

        # Build all subdags (leaves first, then parents)
        subdags = self._build_all_subdags(task_tree)

        # Build root DAG
        root = self._build_root_dag(task_tree)

        return DagBundle(root=root, subdags=subdags)

    def _build_root_dag(self, task_tree: TaskTree) -> SubDag:
        """Build the root DAG with branches-setup and linear task calls."""
        steps: list[SubDagStep] = []

        # First step: branches-setup
        steps.append(SubDagStep(
            name="branches-setup",
            command="arborist spec branch-create-all",
        ))

        # Get root tasks (no parent) sorted by ID
        root_task_ids = sorted(task_tree.root_tasks)

        # Add calls to root tasks in linear sequence
        prev_step = "branches-setup"
        for task_id in root_task_ids:
            steps.append(SubDagStep(
                name=f"c-{task_id}",
                call=task_id,
                depends=[prev_step],
            ))
            prev_step = f"c-{task_id}"

        # Create root DAG
        spec_id = self.config.spec_id or self.config.name
        return SubDag(
            name=self.config.name,
            description=self.config.description,
            env=[f"ARBORIST_MANIFEST={spec_id}.json"],
            steps=steps,
            is_root=True,
        )

    def _build_all_subdags(self, task_tree: TaskTree) -> list[SubDag]:
        """Build subdags for all tasks in topological order."""
        subdags: list[SubDag] = []

        # Process tasks in topological order (parents before children doesn't matter
        # for subdag definition, but we want consistent ordering)
        # We'll process leaves first, then parents
        task_ids = sorted(task_tree.tasks.keys())

        for task_id in task_ids:
            task = task_tree.get_task(task_id)
            if not task:
                continue

            if task_tree.is_leaf(task_id):
                subdag = self._build_leaf_subdag(task_id)
            else:
                subdag = self._build_parent_subdag(task_id, task_tree)

            subdags.append(subdag)

        return subdags

    def _build_leaf_subdag(self, task_id: str) -> SubDag:
        """Build a leaf subdag with individual command nodes.

        Leaf subdags have steps in sequence:
        - With containers: container-up -> pre-sync -> run -> commit -> run-test -> post-merge -> container-down -> post-cleanup
        - Without containers: pre-sync -> run -> commit -> run-test -> post-merge -> post-cleanup

        Each step captures its JSON output via Dagu's output: field.
        """

        def output_var(step: str) -> str:
            """Generate output variable name for a step."""
            return f"{task_id}_{step.upper().replace('-', '_')}_RESULT"

        steps: list[SubDagStep] = []

        # Pre-sync (runs on host to create worktree)
        steps.append(SubDagStep(
            name="pre-sync",
            command=f"arborist task pre-sync {task_id}",
            output=output_var("pre-sync"),
        ))

        # Container lifecycle: Start container (AFTER worktree exists)
        if self._use_containers:
            steps.append(SubDagStep(
                name="container-up",
                command=f"{devcontainer_up_command()} {task_id}",
                depends=["pre-sync"],
            ))

        # Run (arborist on host, but will invoke runner inside container)
        run_cmd = f"arborist task run {task_id}"
        if self.config.runner:
            run_cmd += f" --runner {self.config.runner}"
        if self.config.model:
            run_cmd += f" --model '{self.config.model}'"
        steps.append(SubDagStep(
            name="run",
            command=run_cmd,
            depends=["container-up"] if self._use_containers else ["pre-sync"],
            output=output_var("run"),
        ))

        # Commit (arborist on host)
        steps.append(SubDagStep(
            name="commit",
            command=f"arborist task commit {task_id}",
            depends=["run"],
            output=output_var("commit"),
        ))

        # Run-test (arborist on host, executes tests inside worktree/container)
        steps.append(SubDagStep(
            name="run-test",
            command=f"arborist task run-test {task_id}",
            depends=["commit"],
            output=output_var("run-test"),
        ))

        # Post-merge (arborist on host, will invoke runner inside container)
        steps.append(SubDagStep(
            name="post-merge",
            command=f"arborist task post-merge {task_id}",
            depends=["run-test"],
            output=output_var("post-merge"),
        ))

        # Container lifecycle: Stop container for this worktree
        if self._use_containers:
            steps.append(SubDagStep(
                name="container-down",
                command=f"{devcontainer_down_command()} {task_id}",
                depends=["post-merge"],
            ))

        # Post-cleanup (runs on host to remove worktree)
        steps.append(SubDagStep(
            name="post-cleanup",
            command=f"arborist task post-cleanup {task_id}",
            depends=["container-down"] if self._use_containers else ["post-merge"],
            output=output_var("post-cleanup"),
        ))

        # Add environment variable for worktree path
        # Compute absolute path to worktree
        spec_id = self.config.spec_id or self.config.name
        try:
            arborist_home = get_arborist_home()
            worktree_path = arborist_home / "worktrees" / spec_id / task_id
            env_vars = [
                f"ARBORIST_MANIFEST={spec_id}.json",
                f"ARBORIST_WORKTREE={worktree_path}",
            ]
        except Exception:
            # Fallback if we can't determine arborist home
            env_vars = [f"ARBORIST_MANIFEST={spec_id}.json"]

        return SubDag(name=task_id, steps=steps, env=env_vars)

    def _build_parent_subdag(self, task_id: str, task_tree: TaskTree) -> SubDag:
        """Build a parent subdag that calls child subdags.

        Parent subdags have:
        - pre-sync step
        - calls to all children (parallel - all depend on pre-sync)
        - complete step (depends on all children)
        """

        def output_var(step: str) -> str:
            """Generate output variable name for a step."""
            return f"{task_id}_{step.upper().replace('-', '_')}_RESULT"

        steps: list[SubDagStep] = []

        # Pre-sync step
        steps.append(SubDagStep(
            name="pre-sync",
            command=f"arborist task pre-sync {task_id}",
            output=output_var("pre-sync"),
        ))

        # Get children sorted by ID
        task = task_tree.get_task(task_id)
        if not task:
            return SubDag(name=task_id, steps=steps)

        child_ids = sorted(task.children)
        child_call_names = []

        # Add parallel calls to all children (all depend on pre-sync)
        for child_id in child_ids:
            call_name = f"c-{child_id}"
            child_call_names.append(call_name)
            steps.append(SubDagStep(
                name=call_name,
                call=child_id,
                depends=["pre-sync"],
            ))

        # Complete step (depends on all children)
        complete_command = f"""arborist task run-test {task_id} &&
arborist task post-merge {task_id} &&
arborist task post-cleanup {task_id}"""

        steps.append(SubDagStep(
            name="complete",
            command=complete_command,
            depends=child_call_names,
            output=output_var("complete"),
        ))

        # Add environment variable for worktree path
        spec_id = self.config.spec_id or self.config.name
        try:
            arborist_home = get_arborist_home()
            worktree_path = arborist_home / "worktrees" / spec_id / task_id
            env_vars = [
                f"ARBORIST_MANIFEST={spec_id}.json",
                f"ARBORIST_WORKTREE={worktree_path}",
            ]
        except Exception:
            # Fallback if we can't determine arborist home
            env_vars = [f"ARBORIST_MANIFEST={spec_id}.json"]

        return SubDag(name=task_id, steps=steps, env=env_vars)

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

    def build_yaml(self, spec: TaskSpec, task_tree: TaskTree) -> str:
        """Build multi-document DAGU YAML string from a TaskSpec."""
        bundle = self.build(spec, task_tree)

        # Custom YAML dumper for better formatting
        class CustomDumper(yaml.SafeDumper):
            pass

        # Make lists flow-style for depends
        def represent_list(dumper, data):
            if all(isinstance(item, str) for item in data):
                return dumper.represent_sequence(
                    "tag:yaml.org,2002:seq", data, flow_style=True
                )
            return dumper.represent_sequence("tag:yaml.org,2002:seq", data)

        # Preserve multiline strings
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


# Legacy compatibility - keep old classes for now
@dataclass
class DagStep:
    """A step in the DAGU DAG (legacy)."""

    name: str
    command: str
    depends: list[str] = field(default_factory=list)
    description: str | None = None


class DagBuilder:
    """Builds DAGU DAG YAML from a TaskSpec (legacy wrapper)."""

    def __init__(self, config: DagConfig):
        self.config = config
        self._subdag_builder = SubDagBuilder(config)

    def build(self, spec: TaskSpec, task_tree: TaskTree | None = None) -> dict[str, Any]:
        """Build a DAGU DAG dictionary from a TaskSpec.

        Note: This now returns only the root DAG dict for compatibility.
        Use SubDagBuilder.build() for full subdag support.
        """
        if task_tree is None:
            # Build task tree from spec (need spec_id)
            task_tree = _build_tree_from_spec(spec, self.config.spec_id or self.config.name)

        bundle = self._subdag_builder.build(spec, task_tree)
        return self._subdag_builder._subdag_to_dict(bundle.root)

    def build_yaml(self, spec: TaskSpec, task_tree: TaskTree | None = None) -> str:
        """Build DAGU DAG YAML string from a TaskSpec."""
        if task_tree is None:
            task_tree = _build_tree_from_spec(spec, self.config.spec_id or self.config.name)

        return self._subdag_builder.build_yaml(spec, task_tree)


def _build_tree_from_spec(spec: TaskSpec, spec_id: str) -> TaskTree:
    """Build a TaskTree from a TaskSpec without needing a file."""
    tree = TaskTree(spec_id=spec_id)

    # First pass: create all task nodes
    for task in spec.tasks:
        from agent_arborist.task_state import TaskNode
        tree.tasks[task.id] = TaskNode(
            task_id=task.id,
            description=task.description,
        )

    # Second pass: build hierarchy from dependencies
    for task_id, deps in spec.dependencies.items():
        if deps and task_id in tree.tasks:
            parent_id = deps[0]  # First dependency is the parent
            if parent_id in tree.tasks:
                tree.tasks[task_id].parent_id = parent_id
                if task_id not in tree.tasks[parent_id].children:
                    tree.tasks[parent_id].children.append(task_id)

    # Find root tasks (no parent)
    tree.root_tasks = [
        tid for tid, task in tree.tasks.items()
        if task.parent_id is None
    ]

    return tree


def build_dag(spec: TaskSpec, name: str, description: str = "", spec_id: str = "") -> str:
    """Convenience function to build a DAG YAML from a TaskSpec."""
    config = DagConfig(name=name, description=description, spec_id=spec_id or name)
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
