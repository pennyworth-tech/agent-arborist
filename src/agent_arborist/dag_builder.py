"""DAG builder for DAGU task execution using Jujutsu (jj).

This module generates DAGU YAML for parallel task execution:

Key features:
- Uses jj workspaces for parallel execution
- Atomic jj operations (no filesystem locks needed)
- Deterministic squash operations
- Simple DAG structure

The generated DAG has this structure:
- Root DAG: setup-changes -> sequential root task calls
- Parent subdags: pre-sync -> parallel children -> sync steps -> complete
- Leaf subdags: pre-sync -> container-up -> run -> run-test -> complete
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from agent_arborist.container_runner import (
    ContainerMode,
    should_use_container,
)
from agent_arborist.home import get_arborist_home
from agent_arborist.task_spec import TaskSpec
from agent_arborist.task_state import TaskTree


@dataclass
class SubDagStep:
    """A step in a DAGU subdag."""

    name: str
    command: str | None = None  # Command to execute (None if calling subdag)
    call: str | None = None  # Subdag name to call (None if command step)
    depends: list[str] = field(default_factory=list)
    output: str | dict | None = None  # Dagu output: string or {name, key} dict
    retry: dict | None = None  # DAGU retryPolicy: {limit: int, intervalSec: int}


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
class SimpleTask:
    """A simple task representation for AI-generated DAGs.

    Used by the DagGenerator when building DAGs from AI output.
    """
    id: str
    description: str = ""
    depends_on: list[str] = field(default_factory=list)
    parallel_with: list[str] = field(default_factory=list)


@dataclass
class DagConfig:
    """Configuration for DAG generation."""

    name: str
    description: str = ""
    spec_id: str = ""
    # Note: source_rev is set dynamically at dag run time via ARBORIST_SOURCE_REV
    container_mode: ContainerMode = ContainerMode.AUTO
    repo_path: Path | None = None  # For devcontainer detection
    runner: str | None = None  # AI runner to use
    model: str | None = None  # Model to use
    arborist_config: Any = None  # For step-specific settings
    arborist_home: Path | None = None  # For hooks

    def get_step_runner_model(self, step: str) -> tuple[str | None, str | None]:
        """Get runner/model for a specific step.

        If arborist_config is set, uses step-specific config resolution.
        The runner/model fields on DagConfig act as CLI overrides.
        Otherwise falls back to the runner/model fields directly.

        Args:
            step: Step name (e.g., "run", "post-merge")

        Returns:
            Tuple of (runner, model) - may be None if not configured
        """
        if self.arborist_config is not None:
            from agent_arborist.config import get_step_runner_model
            # Pass runner/model as CLI overrides (highest precedence)
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
        subcommand: Task subcommand (e.g., "run", "complete", "sync-parent")

    Returns:
        Command string

    Example:
        >>> build_arborist_command("T001", "run")
        "arborist task run T001"
    """
    return f"arborist task {subcommand} {task_id}"


class SubDagBuilder:
    """Builds DAGU DAG with subdags for task execution."""

    def __init__(self, config: DagConfig):
        self.config = config
        self._task_tree: TaskTree | None = None
        self._use_containers = False

    def build(self, spec: TaskSpec, task_tree: TaskTree) -> DagBundle:
        """Build a complete DAG bundle from a TaskSpec and TaskTree.

        Args:
            spec: Parsed task specification (unused, kept for compatibility)
            task_tree: Task hierarchy with parent/child relationships

        Returns:
            DagBundle with root DAG and all subdags
        """
        return self.build_from_tree(task_tree)

    def build_from_tree(self, task_tree: TaskTree) -> DagBundle:
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

        # Build all subdags
        subdags = self._build_all_subdags(task_tree)

        # Build root DAG
        root = self._build_root_dag(task_tree)

        return DagBundle(root=root, subdags=subdags)

    def _build_root_dag(self, task_tree: TaskTree) -> SubDag:
        """Build the root DAG with setup and sequential task calls."""
        steps: list[SubDagStep] = []

        # First step: setup-changes (creates all changes)
        steps.append(SubDagStep(
            name="setup-changes",
            command="arborist task setup-spec",
        ))

        # If using containers, start the merge container
        if self._use_containers:
            steps.append(SubDagStep(
                name="merge-container-up",
                command="arborist spec merge-container-up",
                depends=["setup-changes"],
            ))
            prev_step = "merge-container-up"
        else:
            prev_step = "setup-changes"

        # Get root tasks sorted by ID
        root_task_ids = sorted(task_tree.root_tasks)
        for task_id in root_task_ids:
            steps.append(SubDagStep(
                name=f"c-{task_id}",
                call=task_id,
                depends=[prev_step],
            ))
            prev_step = f"c-{task_id}"

        # Add finalize step after all tasks complete
        steps.append(SubDagStep(
            name="finalize",
            command="arborist spec finalize",
            depends=[prev_step],
        ))

        # Environment variables
        # ARBORIST_SOURCE_REV is passed through from parent process
        spec_id = self.config.spec_id or self.config.name
        env = [
            f"ARBORIST_SPEC_ID={spec_id}",
            f"ARBORIST_CONTAINER_MODE={self.config.container_mode.value}",
            "ARBORIST_SOURCE_REV=${ARBORIST_SOURCE_REV}",
        ]

        return SubDag(
            name=self.config.name,
            description=self.config.description,
            env=env,
            steps=steps,
            is_root=True,
        )

    def _compute_task_paths(self, task_tree: TaskTree) -> dict[str, list[str]]:
        """Compute hierarchical paths for all tasks.

        Returns:
            Dict mapping task_id to its full path (e.g., {"T6": ["T1", "T2", "T6"]})
        """
        paths: dict[str, list[str]] = {}

        def compute_path(task_id: str) -> list[str]:
            if task_id in paths:
                return paths[task_id]

            task = task_tree.get_task(task_id)
            if not task or not task.parent_id:
                # Root task
                paths[task_id] = [task_id]
            else:
                # Child task - parent path + this task
                parent_path = compute_path(task.parent_id)
                paths[task_id] = parent_path + [task_id]

            return paths[task_id]

        for task_id in task_tree.tasks:
            compute_path(task_id)

        return paths

    def _build_all_subdags(self, task_tree: TaskTree) -> list[SubDag]:
        """Build subdags for all tasks."""
        subdags: list[SubDag] = []

        # Compute hierarchical paths for all tasks
        task_paths = self._compute_task_paths(task_tree)

        task_ids = sorted(task_tree.tasks.keys())

        for task_id in task_ids:
            task = task_tree.get_task(task_id)
            if not task:
                continue

            task_path = task_paths.get(task_id, [task_id])

            if task_tree.is_leaf(task_id):
                subdag = self._build_leaf_subdag(task_id, task_path)
            else:
                subdag = self._build_parent_subdag(task_id, task_tree, task_path)

            subdags.append(subdag)

        return subdags

    def _build_leaf_subdag(self, task_id: str, task_path: list[str]) -> SubDag:
        """Build a leaf subdag for jj workflow.

        Leaf subdags have:
        - pre-sync: Setup workspace and rebase onto parent
        - container-up: Start container (if enabled)
        - run: Execute AI runner
        - run-test: Run tests
        - complete: Mark done and squash into parent
        - container-down: Stop container (if enabled)

        Note: No retry needed - jj squash is atomic.
        """

        def output_var(step: str) -> dict:
            """Generate output config for a step."""
            var_name = f"{task_id}_{step.upper().replace('-', '_')}_RESULT"
            return {"name": var_name, "key": var_name}

        steps: list[SubDagStep] = []

        # Pre-sync (creates workspace if needed, rebases onto parent)
        steps.append(SubDagStep(
            name="pre-sync",
            command=build_arborist_command(task_id, "pre-sync"),
            output=output_var("pre-sync"),
        ))

        # Container lifecycle
        if self._use_containers:
            steps.append(SubDagStep(
                name="container-up",
                command=build_arborist_command(task_id, "container-up"),
                depends=["pre-sync"],
            ))

        # Run
        steps.append(SubDagStep(
            name="run",
            command=build_arborist_command(task_id, "run"),
            depends=["container-up"] if self._use_containers else ["pre-sync"],
            output=output_var("run"),
        ))

        # Run-test
        steps.append(SubDagStep(
            name="run-test",
            command=build_arborist_command(task_id, "run-test"),
            depends=["run"],
            output=output_var("run-test"),
        ))

        # Complete (squash into parent - no retry needed)
        steps.append(SubDagStep(
            name="complete",
            command=build_arborist_command(task_id, "complete"),
            depends=["run-test"],
            output=output_var("complete"),
        ))

        # Container down
        if self._use_containers:
            steps.append(SubDagStep(
                name="container-down",
                command=build_arborist_command(task_id, "container-stop"),
                depends=["complete"],
            ))

        # Environment
        spec_id = self.config.spec_id or self.config.name
        task_path_str = ":".join(task_path)  # e.g., "T1:T2:T6"
        env_vars = [
            f"ARBORIST_SPEC_ID={spec_id}",
            f"ARBORIST_TASK_ID={task_id}",
            f"ARBORIST_TASK_PATH={task_path_str}",
            f"ARBORIST_CONTAINER_MODE={self.config.container_mode.value}",
        ]

        return SubDag(name=task_id, steps=steps, env=env_vars)

    def _build_parent_subdag(self, task_id: str, task_tree: TaskTree, task_path: list[str]) -> SubDag:
        """Build a parent subdag that calls child subdags.

        Parent subdags have:
        - pre-sync: Setup workspace
        - Parallel child calls (all depend on pre-sync)
        - sync-after-<child> steps to propagate changes
        - run-test: Integration tests after all children
        - complete: Final squash into parent

        The sync steps are the key innovation for jj:
        - After each child completes, sync-parent rebases remaining children
        - This propagates sibling work incrementally
        """

        def output_var(step: str) -> dict:
            """Generate output config for a step."""
            var_name = f"{task_id}_{step.upper().replace('-', '_')}_RESULT"
            return {"name": var_name, "key": var_name}

        steps: list[SubDagStep] = []

        # Pre-sync
        steps.append(SubDagStep(
            name="pre-sync",
            command=build_arborist_command(task_id, "pre-sync"),
            output=output_var("pre-sync"),
        ))

        # Get children sorted
        task = task_tree.get_task(task_id)
        if not task:
            return SubDag(name=task_id, steps=steps)

        child_ids = sorted(task.children)

        # For jj workflow, we run children sequentially with sync between each
        # This ensures each child gets the previous child's work
        prev_dep = "pre-sync"

        for i, child_id in enumerate(child_ids):
            # Call child
            call_name = f"c-{child_id}"
            steps.append(SubDagStep(
                name=call_name,
                call=child_id,
                depends=[prev_dep],
            ))

            # Sync after child (rebases remaining children onto updated parent)
            sync_name = f"sync-after-{child_id}"
            steps.append(SubDagStep(
                name=sync_name,
                command=build_arborist_command(task_id, "sync-parent"),
                depends=[call_name],
                output=output_var(f"sync-{child_id}"),
            ))

            prev_dep = sync_name

        # Run integration tests after all children
        steps.append(SubDagStep(
            name="run-test",
            command=build_arborist_command(task_id, "run-test"),
            depends=[prev_dep],
            output=output_var("run-test"),
        ))

        # Complete (squash into parent)
        steps.append(SubDagStep(
            name="complete",
            command=build_arborist_command(task_id, "complete"),
            depends=["run-test"],
            output=output_var("complete"),
        ))

        # Cleanup
        steps.append(SubDagStep(
            name="cleanup",
            command=build_arborist_command(task_id, "cleanup"),
            depends=["complete"],
            output=output_var("cleanup"),
        ))

        # Environment
        spec_id = self.config.spec_id or self.config.name
        task_path_str = ":".join(task_path)  # e.g., "T1:T2"
        env_vars = [
            f"ARBORIST_SPEC_ID={spec_id}",
            f"ARBORIST_TASK_ID={task_id}",
            f"ARBORIST_TASK_PATH={task_path_str}",
        ]

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
        # Note: No retryPolicy for jj - operations are atomic

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


def _build_dag_yaml_from_tree(
    task_tree: TaskTree,
    dag_name: str,
    description: str = "",
    container_mode: ContainerMode = ContainerMode.AUTO,
    repo_path: Path | None = None,
) -> str:
    """Build jj DAG YAML from a TaskTree.

    This is the main entry point for generating jj-based DAGs.

    Args:
        task_tree: Task hierarchy
        dag_name: Name for the DAG
        description: DAG description
        container_mode: Container execution mode
        repo_path: Path to repo for devcontainer detection

    Returns:
        Multi-document YAML string

    Note:
        ARBORIST_SOURCE_REV is set dynamically at dag run time,
        not baked into the DAG YAML.
    """
    config = DagConfig(
        name=dag_name.replace("-", "_"),
        description=description,
        spec_id=dag_name,
        container_mode=container_mode,
        repo_path=repo_path,
    )

    builder = SubDagBuilder(config)
    bundle = builder.build_from_tree(task_tree)
    return builder._serialize_bundle(bundle)


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


def build_dag_yaml(
    task_tree: TaskTree | None = None,
    dag_name: str = "",
    description: str = "",
    container_mode: ContainerMode = ContainerMode.AUTO,
    repo_path: Path | None = None,
    tasks: list[SimpleTask] | None = None,
    arborist_config: Any = None,
    arborist_home: Path | None = None,
) -> str:
    """Build DAG YAML from either a TaskTree or a list of SimpleTask.

    This is a unified entry point that supports both:
    - TaskTree (from task specs)
    - list[SimpleTask] (from AI generator)

    Args:
        task_tree: Task hierarchy (mutually exclusive with tasks)
        dag_name: Name for the DAG
        description: DAG description
        container_mode: Container execution mode
        repo_path: Path to repo for devcontainer detection
        tasks: List of simple tasks (mutually exclusive with task_tree)
        arborist_config: Arborist configuration (for step settings)
        arborist_home: Arborist home directory (for hooks)

    Returns:
        Multi-document YAML string

    Note:
        ARBORIST_SOURCE_REV is set dynamically at dag run time,
        not baked into the DAG YAML.
    """
    # If tasks are provided, convert to TaskTree
    if tasks is not None:
        from agent_arborist.task_state import TaskTree as TT, TaskNode
        tree = TT(spec_id=dag_name)

        # Build task lookup and find dependencies
        for task in tasks:
            # Determine parent from depends_on (first dependency is parent in jj model)
            parent_id = task.depends_on[0] if task.depends_on else None
            tree.tasks[task.id] = TaskNode(
                task_id=task.id,
                description=task.description,
                parent_id=parent_id,
                children=[],
            )

        # Build children relationships
        for task_id, node in tree.tasks.items():
            if node.parent_id and node.parent_id in tree.tasks:
                tree.tasks[node.parent_id].children.append(task_id)

        # Find root tasks
        tree.root_tasks = [
            tid for tid, t in tree.tasks.items() if t.parent_id is None
        ]

        task_tree = tree

    if task_tree is None:
        raise ValueError("Either task_tree or tasks must be provided")

    # Use the jj builder
    return _build_dag_yaml_from_tree(
        task_tree=task_tree,
        dag_name=dag_name,
        description=description,
        container_mode=container_mode,
        repo_path=repo_path,
    )
