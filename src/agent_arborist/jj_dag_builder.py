"""DAG builder for Jujutsu-based task execution.

This module generates DAGU YAML that uses Jujutsu (jj) operations instead of
Git worktrees. The key differences from dag_builder.py:

1. No worktrees - uses jj workspaces for parallel execution
2. No filesystem locks - jj operations are atomic
3. No retry loops - squash operations are deterministic
4. Simpler DAG structure - fewer setup/cleanup steps

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
class JJSubDagStep:
    """A step in a DAGU subdag for jj workflow."""

    name: str
    command: str | None = None  # Command to execute (None if calling subdag)
    call: str | None = None  # Subdag name to call (None if command step)
    depends: list[str] = field(default_factory=list)
    output: str | dict | None = None  # Dagu output: string or {name, key} dict
    # Note: No retry field - jj operations are atomic, no lock contention


@dataclass
class JJSubDag:
    """A DAGU subdag for jj workflow."""

    name: str
    steps: list[JJSubDagStep] = field(default_factory=list)
    description: str = ""
    env: list[str] = field(default_factory=list)
    is_root: bool = False


@dataclass
class JJDagBundle:
    """Complete DAG bundle with root and all subdags for jj workflow."""

    root: JJSubDag
    subdags: list[JJSubDag]


@dataclass
class JJDagConfig:
    """Configuration for jj DAG generation."""

    name: str
    description: str = ""
    spec_id: str = ""
    container_mode: ContainerMode = ContainerMode.AUTO
    repo_path: Path | None = None  # For devcontainer detection
    runner: str | None = None  # AI runner to use
    model: str | None = None  # Model to use
    arborist_config: Any = None  # For step-specific settings
    arborist_home: Path | None = None  # For hooks


def build_jj_command(task_id: str, subcommand: str) -> str:
    """Build arborist jj command.

    Args:
        task_id: Task identifier (e.g., "T001")
        subcommand: Task subcommand (e.g., "run", "complete", "sync-parent")

    Returns:
        Command string

    Example:
        >>> build_jj_command("T001", "run")
        "arborist jj run T001"
    """
    return f"arborist jj {subcommand} {task_id}"


class JJSubDagBuilder:
    """Builds DAGU DAG with subdags for jj-based task execution."""

    def __init__(self, config: JJDagConfig):
        self.config = config
        self._task_tree: TaskTree | None = None
        self._use_containers = False

    def build(self, spec: TaskSpec, task_tree: TaskTree) -> JJDagBundle:
        """Build a complete DAG bundle from a TaskSpec and TaskTree.

        Args:
            spec: Parsed task specification (unused, kept for compatibility)
            task_tree: Task hierarchy with parent/child relationships

        Returns:
            JJDagBundle with root DAG and all subdags
        """
        return self.build_from_tree(task_tree)

    def build_from_tree(self, task_tree: TaskTree) -> JJDagBundle:
        """Build a complete DAG bundle from a TaskTree.

        Args:
            task_tree: Task hierarchy with parent/child relationships

        Returns:
            JJDagBundle with root DAG and all subdags
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

        return JJDagBundle(root=root, subdags=subdags)

    def _build_root_dag(self, task_tree: TaskTree) -> JJSubDag:
        """Build the root DAG with setup and sequential task calls."""
        steps: list[JJSubDagStep] = []

        # First step: setup-changes (creates all jj changes)
        steps.append(JJSubDagStep(
            name="setup-changes",
            command="arborist jj setup-spec",
        ))

        # If using containers, start the merge container
        if self._use_containers:
            steps.append(JJSubDagStep(
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
            steps.append(JJSubDagStep(
                name=f"c-{task_id}",
                call=task_id,
                depends=[prev_step],
            ))
            prev_step = f"c-{task_id}"

        # Environment variables
        spec_id = self.config.spec_id or self.config.name
        env = [
            f"ARBORIST_SPEC_ID={spec_id}",
            f"ARBORIST_CONTAINER_MODE={self.config.container_mode.value}",
            "ARBORIST_VCS=jj",  # Mark as jj workflow
        ]

        return JJSubDag(
            name=self.config.name,
            description=self.config.description,
            env=env,
            steps=steps,
            is_root=True,
        )

    def _build_all_subdags(self, task_tree: TaskTree) -> list[JJSubDag]:
        """Build subdags for all tasks."""
        subdags: list[JJSubDag] = []

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

    def _build_leaf_subdag(self, task_id: str) -> JJSubDag:
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

        steps: list[JJSubDagStep] = []

        # Pre-sync (creates workspace if needed, rebases onto parent)
        steps.append(JJSubDagStep(
            name="pre-sync",
            command=build_jj_command(task_id, "pre-sync"),
            output=output_var("pre-sync"),
        ))

        # Container lifecycle
        if self._use_containers:
            steps.append(JJSubDagStep(
                name="container-up",
                command=build_jj_command(task_id, "container-up"),
                depends=["pre-sync"],
            ))

        # Run
        steps.append(JJSubDagStep(
            name="run",
            command=build_jj_command(task_id, "run"),
            depends=["container-up"] if self._use_containers else ["pre-sync"],
            output=output_var("run"),
        ))

        # Run-test
        steps.append(JJSubDagStep(
            name="run-test",
            command=build_jj_command(task_id, "run-test"),
            depends=["run"],
            output=output_var("run-test"),
        ))

        # Complete (squash into parent - no retry needed)
        steps.append(JJSubDagStep(
            name="complete",
            command=build_jj_command(task_id, "complete"),
            depends=["run-test"],
            output=output_var("complete"),
        ))

        # Container down
        if self._use_containers:
            steps.append(JJSubDagStep(
                name="container-down",
                command=build_jj_command(task_id, "container-stop"),
                depends=["complete"],
            ))

        # Environment
        spec_id = self.config.spec_id or self.config.name
        env_vars = [
            f"ARBORIST_SPEC_ID={spec_id}",
            f"ARBORIST_TASK_ID={task_id}",
            f"ARBORIST_CONTAINER_MODE={self.config.container_mode.value}",
            "ARBORIST_VCS=jj",
        ]

        return JJSubDag(name=task_id, steps=steps, env=env_vars)

    def _build_parent_subdag(self, task_id: str, task_tree: TaskTree) -> JJSubDag:
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

        steps: list[JJSubDagStep] = []

        # Pre-sync
        steps.append(JJSubDagStep(
            name="pre-sync",
            command=build_jj_command(task_id, "pre-sync"),
            output=output_var("pre-sync"),
        ))

        # Get children sorted
        task = task_tree.get_task(task_id)
        if not task:
            return JJSubDag(name=task_id, steps=steps)

        child_ids = sorted(task.children)

        # For jj workflow, we run children sequentially with sync between each
        # This ensures each child gets the previous child's work
        prev_dep = "pre-sync"

        for i, child_id in enumerate(child_ids):
            # Call child
            call_name = f"c-{child_id}"
            steps.append(JJSubDagStep(
                name=call_name,
                call=child_id,
                depends=[prev_dep],
            ))

            # Sync after child (rebases remaining children onto updated parent)
            sync_name = f"sync-after-{child_id}"
            steps.append(JJSubDagStep(
                name=sync_name,
                command=build_jj_command(task_id, "sync-parent"),
                depends=[call_name],
                output=output_var(f"sync-{child_id}"),
            ))

            prev_dep = sync_name

        # Run integration tests after all children
        steps.append(JJSubDagStep(
            name="run-test",
            command=build_jj_command(task_id, "run-test"),
            depends=[prev_dep],
            output=output_var("run-test"),
        ))

        # Complete (squash into parent)
        steps.append(JJSubDagStep(
            name="complete",
            command=build_jj_command(task_id, "complete"),
            depends=["run-test"],
            output=output_var("complete"),
        ))

        # Cleanup
        steps.append(JJSubDagStep(
            name="cleanup",
            command=build_jj_command(task_id, "cleanup"),
            depends=["complete"],
            output=output_var("cleanup"),
        ))

        # Environment
        spec_id = self.config.spec_id or self.config.name
        env_vars = [
            f"ARBORIST_SPEC_ID={spec_id}",
            f"ARBORIST_TASK_ID={task_id}",
            "ARBORIST_VCS=jj",
        ]

        return JJSubDag(name=task_id, steps=steps, env=env_vars)

    def _step_to_dict(self, step: JJSubDagStep) -> dict[str, Any]:
        """Convert a JJSubDagStep to a dictionary for YAML serialization."""
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

    def _subdag_to_dict(self, subdag: JJSubDag) -> dict[str, Any]:
        """Convert a JJSubDag to a dictionary for YAML serialization."""
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

    def _serialize_bundle(self, bundle: JJDagBundle) -> str:
        """Serialize a JJDagBundle to multi-document YAML."""

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


def build_jj_dag_yaml(
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
    """
    config = JJDagConfig(
        name=dag_name.replace("-", "_"),
        description=description,
        spec_id=dag_name,
        container_mode=container_mode,
        repo_path=repo_path,
    )

    builder = JJSubDagBuilder(config)
    bundle = builder.build_from_tree(task_tree)
    return builder._serialize_bundle(bundle)


def parse_jj_yaml_to_bundle(yaml_content: str) -> JJDagBundle:
    """Parse a multi-document DAGU YAML string into a JJDagBundle.

    Args:
        yaml_content: Multi-document YAML string

    Returns:
        JJDagBundle with root and subdags populated
    """
    documents = list(yaml.safe_load_all(yaml_content))

    if not documents:
        raise ValueError("No YAML documents found")

    # First document is root DAG
    root_dict = documents[0]
    root = JJSubDag(
        name=root_dict.get("name", "root"),
        description=root_dict.get("description", ""),
        env=root_dict.get("env", []),
        is_root=True,
        steps=[
            JJSubDagStep(
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
        subdag = JJSubDag(
            name=doc.get("name", ""),
            description=doc.get("description", ""),
            env=doc.get("env", []),
            is_root=False,
            steps=[
                JJSubDagStep(
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

    return JJDagBundle(root=root, subdags=subdags)


def is_jj_dag(yaml_content: str) -> bool:
    """Check if a DAG YAML is a jj DAG.

    Looks for ARBORIST_VCS=jj in the environment.

    Args:
        yaml_content: Multi-document YAML string

    Returns:
        True if this is a jj DAG
    """
    try:
        documents = list(yaml.safe_load_all(yaml_content))
        if not documents:
            return False

        root = documents[0]
        env = root.get("env", [])
        return any("ARBORIST_VCS=jj" in e for e in env)
    except Exception:
        return False
