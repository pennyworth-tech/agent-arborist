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
    output: str | dict | None = None  # Dagu output: string or {name, key} dict


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
    runner: str | None = None  # AI runner to use (claude, opencode, gemini)
    model: str | None = None  # Model to use (uses runner default if not specified)
    arborist_config: Any = None  # ArboristConfig for step-specific settings
    arborist_home: Path | None = None  # Path to .arborist directory for hooks

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


def build_arborist_command(
    task_id: str,
    subcommand: str,
) -> str:
    """Build arborist task command.

    Runner/model are NOT included in the command - they are resolved
    at runtime by the task command based on config/env vars.

    Args:
        task_id: Task identifier (e.g., "T001")
        subcommand: Task subcommand (e.g., "run", "post-merge", "run-test")

    Returns:
        Command string

    Example:
        >>> build_arborist_command("T001", "run")
        "arborist task run T001"
    """
    return f"arborist task {subcommand} {task_id}"


class SubDagBuilder:
    """Builds DAGU DAG with subdags from a TaskSpec."""

    def __init__(self, config: DagConfig):
        self.config = config
        self._task_tree: TaskTree | None = None
        self._use_containers = False  # Set during build()

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

        This is the unified entry point for DAG building - both AI and
        deterministic paths should use this method.

        Args:
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
        """Build the root DAG with branches-setup and linear task calls.

        Optionally auto-detects and includes restart context if one exists
        for this spec.
        """
        from rich.console import Console
        from agent_arborist.restart_context import find_latest_restart_context

        console = Console(stderr=True)
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
        arborist_home = get_arborist_home()

        env = [
            f"ARBORIST_MANIFEST={spec_id}.json",
            f"ARBORIST_CONTAINER_MODE={self.config.container_mode.value}",
        ]

        # Auto-detect and add restart context if exists
        restart_context = find_latest_restart_context(spec_id, arborist_home)
        if restart_context:
            env.append(f"ARBORIST_RESTART_CONTEXT={restart_context}")
            console.print(f"[dim]Using restart context:[/dim] {restart_context}")

        return SubDag(
            name=self.config.name,
            description=self.config.description,
            env=env,
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
        - With containers: pre-sync -> container-up -> run -> commit -> run-test -> post-merge -> container-down
        - Without containers: pre-sync -> run -> commit -> run-test -> post-merge

        Commands are self-aware: they detect container needs and wrap their subprocesses
        (AI runners, test commands) with 'devcontainer exec' when needed.

        Each step captures its JSON output via Dagu's output: field.

        Note: Containers are stopped but not removed. Worktrees are kept for inspection.
        Use 'arborist cleanup' commands to clean up afterward.
        """

        def output_var(step: str) -> dict:
            """Generate output config for a step.

            Uses object form to preserve snake_case key in outputs.json.
            Dagu converts string outputs to camelCase, but respects explicit keys.
            """
            var_name = f"{task_id}_{step.upper().replace('-', '_')}_RESULT"
            return {"name": var_name, "key": var_name}

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
                command=f"arborist task container-up {task_id}",
                depends=["pre-sync"],
            ))

        # Run (wraps AI runner subprocess with devcontainer exec if needed)
        # Runner/model resolved at runtime via config
        steps.append(SubDagStep(
            name="run",
            command=build_arborist_command(task_id, "run"),
            depends=["container-up"] if self._use_containers else ["pre-sync"],
            output=output_var("run"),
        ))

        # Commit (runs git on host)
        steps.append(SubDagStep(
            name="commit",
            command=f"arborist task commit {task_id}",
            depends=["run"],
            output=output_var("commit"),
        ))

        # Run-test (wraps test command subprocess with devcontainer exec if needed)
        steps.append(SubDagStep(
            name="run-test",
            command=f"arborist task run-test {task_id}",
            depends=["commit"],
            output=output_var("run-test"),
        ))

        # Post-merge (self-aware - wraps AI runner subprocess if needed)
        # Runner/model resolved at runtime via config
        steps.append(SubDagStep(
            name="post-merge",
            command=build_arborist_command(task_id, "post-merge"),
            depends=["run-test"],
            output=output_var("post-merge"),
        ))

        # Container lifecycle: Stop container for this worktree (but don't remove it)
        if self._use_containers:
            steps.append(SubDagStep(
                name="container-down",
                command=f"arborist task container-stop {task_id}",
                depends=["post-merge"],
            ))

        # Add environment variables for worktree path and container mode
        # Compute absolute path to worktree
        spec_id = self.config.spec_id or self.config.name
        try:
            arborist_home = get_arborist_home()
            worktree_path = arborist_home / "worktrees" / spec_id / task_id
            env_vars = [
                f"ARBORIST_MANIFEST={spec_id}.json",
                f"ARBORIST_WORKTREE={worktree_path}",
                f"ARBORIST_CONTAINER_MODE={self.config.container_mode.value}",
            ]
        except Exception:
            # Fallback if we can't determine arborist home
            env_vars = [
                f"ARBORIST_MANIFEST={spec_id}.json",
                f"ARBORIST_CONTAINER_MODE={self.config.container_mode.value}",
            ]

        return SubDag(name=task_id, steps=steps, env=env_vars)

    def _build_parent_subdag(self, task_id: str, task_tree: TaskTree) -> SubDag:
        """Build a parent subdag that calls child subdags.

        Parent subdags have:
        - pre-sync step
        - calls to all children (parallel - all depend on pre-sync)
        - complete step (depends on all children)
        """

        def output_var(step: str) -> dict:
            """Generate output config for a step.

            Uses object form to preserve snake_case key in outputs.json.
            Dagu converts string outputs to camelCase, but respects explicit keys.
            """
            var_name = f"{task_id}_{step.upper().replace('-', '_')}_RESULT"
            return {"name": var_name, "key": var_name}

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
        # Runner/model resolved at runtime via config
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

    def _apply_hooks(self, bundle: DagBundle) -> DagBundle:
        """Apply hooks to the DAG bundle.

        This is the post-AI hook application phase. Hooks are applied
        deterministically based on configuration.

        Args:
            bundle: DAG bundle to augment

        Returns:
            Augmented DAG bundle
        """
        # Check if hooks are configured
        arborist_config = self.config.arborist_config
        if arborist_config is None:
            return bundle

        hooks_config = getattr(arborist_config, "hooks", None)
        if hooks_config is None or not hooks_config.enabled:
            return bundle

        # Get arborist_home from config
        arborist_home = self.config.arborist_home
        if arborist_home is None:
            arborist_home = get_arborist_home()

        spec_id = self.config.spec_id or self.config.name

        # Import and apply hooks
        from agent_arborist.hooks import inject_hooks

        return inject_hooks(
            bundle=bundle,
            hooks_config=hooks_config,
            spec_id=spec_id,
            arborist_home=arborist_home,
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

    def build_yaml(self, spec: TaskSpec, task_tree: TaskTree) -> str:
        """Build multi-document DAGU YAML string from a TaskSpec.

        If hooks are configured and enabled in arborist_config, they will
        be applied to the DAG bundle after the base DAG is built.
        """
        bundle = self.build(spec, task_tree)

        # Apply hooks if configured (post-AI phase)
        bundle = self._apply_hooks(bundle)

        return self._serialize_bundle(bundle)

    def _serialize_bundle(self, bundle: DagBundle) -> str:
        """Serialize a DagBundle to multi-document YAML.

        Args:
            bundle: DagBundle to serialize

        Returns:
            Multi-document YAML string
        """
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


@dataclass
class SimpleTask:
    """Simple task representation for unified DAG building.

    This is the common format that both AI and deterministic paths produce.
    """

    id: str
    description: str
    depends_on: list[str] = field(default_factory=list)
    parallel_with: list[str] = field(default_factory=list)


def build_tree_from_simple_tasks(
    tasks: list[SimpleTask],
    spec_id: str,
    flat: bool = True,
) -> TaskTree:
    """Build a TaskTree from a list of SimpleTask objects.

    This is used by DagGenerator to convert AI-extracted tasks into the
    common TaskTree format used by SubDagBuilder.

    Args:
        tasks: List of simple task objects with id, description, depends_on
        spec_id: Spec identifier
        flat: If True, all tasks are root-level (AI mode). If False, build
              hierarchy from dependencies (deterministic mode).

    Returns:
        TaskTree ready for SubDagBuilder
    """
    from agent_arborist.task_state import TaskNode

    tree = TaskTree(spec_id=spec_id)

    # Create all task nodes
    for task in tasks:
        tree.tasks[task.id] = TaskNode(
            task_id=task.id,
            description=task.description,
        )

    if not flat:
        # Build hierarchy from dependencies (first dep = parent)
        for task in tasks:
            if task.depends_on and task.id in tree.tasks:
                parent_id = task.depends_on[0]
                if parent_id in tree.tasks:
                    tree.tasks[task.id].parent_id = parent_id
                    if task.id not in tree.tasks[parent_id].children:
                        tree.tasks[parent_id].children.append(task.id)

    # Find root tasks (no parent, or all tasks if flat)
    tree.root_tasks = [
        tid for tid, t in tree.tasks.items()
        if t.parent_id is None
    ]

    return tree


def build_dag_yaml(
    tasks: list[SimpleTask],
    dag_name: str,
    description: str = "",
    arborist_config: Any = None,
    arborist_home: Path | None = None,
    container_mode: ContainerMode = ContainerMode.AUTO,
    repo_path: Path | None = None,
) -> str:
    """Unified DAG builder - single entry point for both AI and deterministic paths.

    This function:
    1. Converts tasks to TaskTree
    2. Builds DagBundle via SubDagBuilder
    3. Applies hooks if configured
    4. Serializes to YAML

    Args:
        tasks: List of SimpleTask objects
        dag_name: Name for the DAG
        description: DAG description
        arborist_config: ArboristConfig for hooks (optional)
        arborist_home: Path to .arborist directory (optional)
        container_mode: Container execution mode
        repo_path: Path to repo for devcontainer detection

    Returns:
        Multi-document YAML string with hooks applied
    """
    dag_name_safe = dag_name.replace("-", "_")

    # Build TaskTree from tasks
    tree = build_tree_from_simple_tasks(tasks, dag_name)

    # Create config for SubDagBuilder
    config = DagConfig(
        name=dag_name_safe,
        description=description,
        spec_id=dag_name,
        container_mode=container_mode,
        repo_path=repo_path,
        arborist_config=arborist_config,
        arborist_home=arborist_home,
    )

    # Build the bundle using SubDagBuilder
    builder = SubDagBuilder(config)
    bundle = builder.build_from_tree(tree)

    # Apply hooks if configured
    bundle = builder._apply_hooks(bundle)

    # Serialize to YAML
    return builder._serialize_bundle(bundle)


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


def parse_yaml_to_bundle(yaml_content: str) -> DagBundle:
    """Parse a multi-document DAGU YAML string into a DagBundle.

    This is the inverse of DagBuilder.build_yaml() - it reconstructs
    the DagBundle from YAML so hooks can be injected.

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


def bundle_to_yaml(bundle: DagBundle) -> str:
    """Serialize a DagBundle back to multi-document YAML.

    Args:
        bundle: DagBundle to serialize

    Returns:
        Multi-document YAML string
    """
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

    def step_to_dict(step: SubDagStep) -> dict[str, Any]:
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

    def subdag_to_dict(subdag: SubDag) -> dict[str, Any]:
        d: dict[str, Any] = {"name": subdag.name}
        if subdag.description:
            d["description"] = subdag.description
        if subdag.env:
            d["env"] = subdag.env
        d["steps"] = [step_to_dict(step) for step in subdag.steps]
        return d

    # Build multi-document YAML
    documents = []

    # Root DAG first
    root_dict = subdag_to_dict(bundle.root)
    documents.append(yaml.dump(
        root_dict, Dumper=CustomDumper, default_flow_style=False, sort_keys=False
    ))

    # Then all subdags
    for subdag in bundle.subdags:
        subdag_dict = subdag_to_dict(subdag)
        documents.append(yaml.dump(
            subdag_dict, Dumper=CustomDumper, default_flow_style=False, sort_keys=False
        ))

    return "---\n".join(documents)
