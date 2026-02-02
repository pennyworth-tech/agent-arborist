"""Hook injector for DAG augmentation.

The HookInjector takes a generated DAG and applies hooks to it based on
the configuration. This is run as a post-AI phase after the initial DAG
is generated.

Hook Points:
- pre_root: After branches-setup, before any task calls
- post_roots: After all root task calls, before final steps
- pre_task: At the start of each task subdag
- post_task: At the end of each task subdag
- final: At the very end of the root DAG
"""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from agent_arborist.config import HookInjection, HooksConfig, StepDefinition
from agent_arborist.hooks.base import HookApplication, HookDiagnostics

if TYPE_CHECKING:
    from agent_arborist.dag_builder import DagBundle, SubDag, SubDagStep

logger = logging.getLogger(__name__)


@dataclass
class InjectorConfig:
    """Configuration for hook injection."""

    hooks_config: HooksConfig
    spec_id: str
    arborist_home: Path


class HookInjector:
    """Injects hook steps into a DAG bundle.

    Hook injection happens AFTER the AI generates the base DAG.
    This ensures hooks are applied deterministically based on config.
    """

    def __init__(self, config: InjectorConfig):
        """Initialize the hook injector.

        Args:
            config: Configuration including hooks config and paths
        """
        self.config = config
        self.hooks_config = config.hooks_config
        self.diagnostics = HookDiagnostics()

    def inject(self, bundle: "DagBundle") -> "DagBundle":
        """Inject hooks into a DAG bundle.

        This modifies the bundle in place and returns it.

        Args:
            bundle: DAG bundle to augment with hooks

        Returns:
            The augmented DAG bundle
        """
        if not self.hooks_config.enabled:
            logger.debug("Hooks disabled, skipping injection")
            return bundle

        # Process DAG-level hooks
        self._inject_dag_level_hooks(bundle)

        # Process task-level hooks
        self._inject_task_level_hooks(bundle)

        logger.info(self.diagnostics.summary())
        return bundle

    def _inject_dag_level_hooks(self, bundle: "DagBundle") -> None:
        """Inject DAG-level hooks (pre_root, post_roots, final).

        Args:
            bundle: DAG bundle to modify
        """
        root = bundle.root

        # pre_root: After branches-setup, before task calls
        pre_root_injections = self.hooks_config.injections.get("pre_root", [])
        for injection in pre_root_injections:
            step = self._build_hook_step(injection, "pre_root", None)
            if step:
                self._insert_after_step(root, "branches-setup", step)
                self.diagnostics.record(
                    step_name=step.name,
                    hook_point="pre_root",
                    task_id=None,
                    step_type=self._get_step_type(injection),
                )

        # post_roots: After all root task calls
        post_roots_injections = self.hooks_config.injections.get("post_roots", [])
        for injection in post_roots_injections:
            step = self._build_hook_step(injection, "post_roots", None)
            if step:
                # Find last task call in root and insert after
                last_task_idx = self._find_last_task_call_index(root)
                if last_task_idx >= 0:
                    self._insert_after_index(root, last_task_idx, step)
                else:
                    # No task calls, append to end
                    root.steps.append(step)
                self.diagnostics.record(
                    step_name=step.name,
                    hook_point="post_roots",
                    task_id=None,
                    step_type=self._get_step_type(injection),
                )

        # final: At the very end of root DAG
        final_injections = self.hooks_config.injections.get("final", [])
        for injection in final_injections:
            step = self._build_hook_step(injection, "final", None)
            if step:
                # Make it depend on the last step
                if root.steps:
                    step.depends = [root.steps[-1].name]
                root.steps.append(step)
                self.diagnostics.record(
                    step_name=step.name,
                    hook_point="final",
                    task_id=None,
                    step_type=self._get_step_type(injection),
                )

    def _inject_task_level_hooks(self, bundle: "DagBundle") -> None:
        """Inject task-level hooks (pre_task, post_task).

        Args:
            bundle: DAG bundle to modify
        """
        pre_task_injections = self.hooks_config.injections.get("pre_task", [])
        post_task_injections = self.hooks_config.injections.get("post_task", [])

        for subdag in bundle.subdags:
            task_id = subdag.name

            # Check each pre_task injection
            for injection in pre_task_injections:
                if self._task_matches(task_id, injection):
                    step = self._build_hook_step(injection, "pre_task", task_id)
                    if step:
                        # Insert at start of subdag
                        self._insert_at_start(subdag, step)
                        self.diagnostics.record(
                            step_name=step.name,
                            hook_point="pre_task",
                            task_id=task_id,
                            step_type=self._get_step_type(injection),
                        )

            # Check each post_task injection
            for injection in post_task_injections:
                if self._task_matches(task_id, injection):
                    step = self._build_hook_step(injection, "post_task", task_id)
                    if step:
                        # Append to end of subdag, depending on last step
                        if subdag.steps:
                            step.depends = [subdag.steps[-1].name]
                        subdag.steps.append(step)
                        self.diagnostics.record(
                            step_name=step.name,
                            hook_point="post_task",
                            task_id=task_id,
                            step_type=self._get_step_type(injection),
                        )

    def _task_matches(self, task_id: str, injection: HookInjection) -> bool:
        """Check if a task matches the injection's task filter.

        Args:
            task_id: Task identifier (e.g., "T001")
            injection: Injection configuration

        Returns:
            True if the task should have this hook applied
        """
        # Check exclude list first
        for pattern in injection.tasks_exclude:
            if self._matches_pattern(task_id, pattern):
                return False

        # Check include list
        for pattern in injection.tasks:
            if self._matches_pattern(task_id, pattern):
                return True

        return False

    def _matches_pattern(self, task_id: str, pattern: str) -> bool:
        """Check if task_id matches a pattern.

        Args:
            task_id: Task identifier
            pattern: Pattern (exact match, "*" for all, or glob)

        Returns:
            True if matches
        """
        if pattern == "*":
            return True
        if "*" in pattern or "?" in pattern:
            return fnmatch.fnmatch(task_id, pattern)
        return task_id == pattern

    def _build_hook_step(
        self,
        injection: HookInjection,
        hook_point: str,
        task_id: str | None,
    ) -> "SubDagStep | None":
        """Build a SubDagStep from an injection config.

        Args:
            injection: Hook injection configuration
            hook_point: Hook point name
            task_id: Task ID (None for DAG-level hooks)

        Returns:
            SubDagStep to inject, or None if invalid
        """
        from agent_arborist.dag_builder import SubDagStep

        # Get step definition (from reference or inline)
        step_def = self._resolve_step_definition(injection)
        if step_def is None:
            logger.warning(
                f"Could not resolve step definition for injection at {hook_point}"
            )
            return None

        # Generate unique step name
        step_name = self._generate_step_name(injection, hook_point, task_id)

        # Build the command to execute the hook
        command = self._build_hook_command(step_def, task_id)

        # Determine dependencies
        depends = []
        if injection.after:
            depends.append(injection.after)

        # Use object form for output to preserve snake_case key in outputs.json
        # Dagu converts string outputs to camelCase, but respects explicit keys
        output_var = f"{step_name}_result"
        return SubDagStep(
            name=step_name,
            command=command,
            depends=depends,
            output={"name": output_var, "key": output_var},
        )

    def _resolve_step_definition(
        self, injection: HookInjection
    ) -> StepDefinition | None:
        """Resolve step definition from injection.

        Args:
            injection: Hook injection config

        Returns:
            StepDefinition or None
        """
        if injection.step:
            # Reference to named step
            return self.hooks_config.step_definitions.get(injection.step)
        else:
            # Inline step definition
            return injection.get_step_definition()

    def _generate_step_name(
        self,
        injection: HookInjection,
        hook_point: str,
        task_id: str | None,
    ) -> str:
        """Generate a unique step name for the hook.

        Args:
            injection: Hook injection config
            hook_point: Hook point name
            task_id: Task ID or None

        Returns:
            Unique step name
        """
        base_name = injection.step or injection.type or "hook"
        if task_id:
            return f"hook_{hook_point}_{base_name}_{task_id}"
        return f"hook_{hook_point}_{base_name}"

    def _build_hook_command(
        self, step_def: StepDefinition, task_id: str | None
    ) -> str:
        """Build the command to execute a hook step.

        This creates an arborist command that will run the hook
        with the appropriate configuration.

        Args:
            step_def: Step definition
            task_id: Task ID or None

        Returns:
            Command string
        """
        # The hook execution command calls arborist hooks run
        # which will load the config and execute the step
        cmd_parts = ["arborist", "hooks", "run"]

        # Add step type
        cmd_parts.extend(["--type", step_def.type])

        # Add task ID if applicable
        if task_id:
            cmd_parts.extend(["--task", task_id])

        # For shell commands, include the command
        if step_def.type == "shell" and step_def.command:
            cmd_parts.extend(["--command", f'"{step_def.command}"'])

        # For LLM eval, include prompt reference
        if step_def.type == "llm_eval":
            if step_def.prompt_file:
                cmd_parts.extend(["--prompt-file", step_def.prompt_file])
            elif step_def.prompt:
                # For inline prompts, we'll reference the config
                # The hooks run command will load it
                cmd_parts.append("--prompt-from-config")

        # For quality check, include command
        if step_def.type == "quality_check" and step_def.command:
            cmd_parts.extend(["--command", f'"{step_def.command}"'])
            if step_def.min_score is not None:
                cmd_parts.extend(["--min-score", str(step_def.min_score)])

        # For python steps, include class path
        if step_def.type == "python" and step_def.class_path:
            cmd_parts.extend(["--class", step_def.class_path])

        return " ".join(cmd_parts)

    def _get_step_type(self, injection: HookInjection) -> str:
        """Get the step type from an injection.

        Args:
            injection: Hook injection config

        Returns:
            Step type string
        """
        if injection.step:
            step_def = self.hooks_config.step_definitions.get(injection.step)
            return step_def.type if step_def else "unknown"
        return injection.type or "unknown"

    def _insert_after_step(
        self, subdag: "SubDag", after_name: str, step: "SubDagStep"
    ) -> None:
        """Insert a step after a named step in a subdag.

        Args:
            subdag: SubDag to modify
            after_name: Name of step to insert after
            step: Step to insert
        """
        for i, existing in enumerate(subdag.steps):
            if existing.name == after_name:
                step.depends = [after_name]
                subdag.steps.insert(i + 1, step)
                # Update dependencies of subsequent steps
                for j in range(i + 2, len(subdag.steps)):
                    if after_name in subdag.steps[j].depends:
                        # Replace dependency on after_name with the new step
                        subdag.steps[j].depends = [
                            step.name if d == after_name else d
                            for d in subdag.steps[j].depends
                        ]
                return
        # If step not found, append
        subdag.steps.append(step)

    def _insert_after_index(
        self, subdag: "SubDag", index: int, step: "SubDagStep"
    ) -> None:
        """Insert a step after a given index.

        Args:
            subdag: SubDag to modify
            index: Index to insert after
            step: Step to insert
        """
        if index < len(subdag.steps):
            step.depends = [subdag.steps[index].name]
        subdag.steps.insert(index + 1, step)

    def _insert_at_start(self, subdag: "SubDag", step: "SubDagStep") -> None:
        """Insert a step at the start of a subdag.

        Args:
            subdag: SubDag to modify
            step: Step to insert
        """
        subdag.steps.insert(0, step)
        # Update first original step to depend on new step
        if len(subdag.steps) > 1:
            if not subdag.steps[1].depends:
                subdag.steps[1].depends = [step.name]
            else:
                subdag.steps[1].depends.insert(0, step.name)

    def _find_last_task_call_index(self, root: "SubDag") -> int:
        """Find the index of the last task call step in root DAG.

        Args:
            root: Root SubDag

        Returns:
            Index of last task call, or -1 if none found
        """
        last_idx = -1
        for i, step in enumerate(root.steps):
            if step.call is not None:
                last_idx = i
        return last_idx


def inject_hooks(
    bundle: "DagBundle",
    hooks_config: HooksConfig,
    spec_id: str,
    arborist_home: Path,
) -> "DagBundle":
    """Convenience function to inject hooks into a DAG bundle.

    Args:
        bundle: DAG bundle to augment
        hooks_config: Hooks configuration
        spec_id: Specification identifier
        arborist_home: Path to .arborist directory

    Returns:
        Augmented DAG bundle
    """
    config = InjectorConfig(
        hooks_config=hooks_config,
        spec_id=spec_id,
        arborist_home=arborist_home,
    )
    injector = HookInjector(config)
    return injector.inject(bundle)
