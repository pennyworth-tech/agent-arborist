"""AI-powered DAG generator using LLM runners."""

import re
import yaml
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_arborist.runner import Runner, get_runner, RunnerType, DEFAULT_RUNNER


@dataclass
class GenerationResult:
    """Result from AI DAG generation."""

    success: bool
    yaml_content: str | None = None
    error: str | None = None
    raw_output: str | None = None


# Prompt for git-worktree-based task execution with deterministic branch manifest
DAG_GENERATION_PROMPT = '''You are a workflow automation expert. Analyze the task specification and output a DAGU DAG as YAML.

TASK SPECIFICATION:
---
{spec_content}
---

REQUIREMENTS:
1. Output valid DAGU YAML with:
   - name: "{dag_name}" (underscores, no dashes)
   - description: Brief project description
   - env: Single ARBORIST_MANIFEST entry (see below)
   - steps: List of workflow steps IN TOPOLOGICAL ORDER

2. Add env section with EXACTLY ONE entry (DAGU requires KEY=value format):
   env:
     - ARBORIST_MANIFEST=${{DAG_DIR}}/{dag_name}.json

3. Analyze the task hierarchy:
   - Identify all tasks (T001, T002, etc.)
   - Determine parent-child relationships from dependencies
   - A task's "parent" is typically its first dependency
   - Tasks with no dependencies that others depend on are "parent" tasks
   - Tasks at the end of dependency chains are "leaf" tasks

4. First step MUST be branches-setup (no depends key needed):
   - name: branches-setup
     command: arborist spec branch-create-all

5. For LEAF tasks (no children depend on them), create a step:
   - name: "TXXX-slug" (max 40 chars, slug from description)
   - command: |
       arborist task pre-sync TXXX &&
       arborist task run TXXX &&
       arborist task run-test TXXX &&
       arborist task post-merge TXXX &&
       arborist task post-cleanup TXXX
   - depends: [parent-task-step-name or branches-setup if root]

6. For PARENT tasks (other tasks depend on them), create TWO steps:
   a) Setup step:
      - name: "TXXX-setup"
      - command: arborist task pre-sync TXXX
      - depends: [its-parent-step-name or branches-setup if root]

   b) Complete step (runs after all children complete):
      - name: "TXXX-complete"
      - command: |
          arborist task run-test TXXX &&
          arborist task post-merge TXXX &&
          arborist task post-cleanup TXXX
      - depends: [all-child-step-names]

7. INFER DEPENDENCIES from:
   - Explicit "Dependencies" section (arrows like "T001 → T002")
   - Task ordering within phases/sections
   - "Parallel Opportunities" sections

8. Tasks marked [P] can run in parallel (share same parent dependency)

9. Do NOT add phase-complete or all-complete steps - just the task steps.

10. CRITICAL - TOPOLOGICAL ORDERING: Steps MUST be listed so that every step's
    dependencies appear BEFORE that step in the YAML. Order should be:
    - branches-setup (first, no deps)
    - All setup steps in dependency order (T001-setup, T002-setup, etc.)
    - All leaf task steps (after their parent setup steps)
    - All complete steps in REVERSE order (T003-complete before T002-complete before T001-complete)
    - Final tasks that depend on complete steps

CRITICAL: Output ONLY the YAML content. No markdown fences. No explanation. Start directly with "name:" on the first line.
'''


def _fix_env_format(dag_data: dict) -> list[str]:
    """Fix env entries to use KEY=value format and remove duplicates.

    Returns list of issues that were fixed.
    """
    fixes = []
    if "env" not in dag_data:
        return fixes

    seen_keys = set()
    fixed_env = []

    for entry in dag_data["env"]:
        # Handle dict format like {KEY: value}
        if isinstance(entry, dict):
            for key, value in entry.items():
                if key not in seen_keys:
                    fixed_env.append(f"{key}={value}")
                    seen_keys.add(key)
                    fixes.append(f"Converted env dict {key}: {value} to {key}={value}")
                else:
                    fixes.append(f"Removed duplicate env key: {key}")
        # Handle string format
        elif isinstance(entry, str):
            # Check if it's already KEY=value format
            if "=" in entry and ": " not in entry.split("=")[0]:
                key = entry.split("=")[0].strip()
                if key not in seen_keys:
                    fixed_env.append(entry)
                    seen_keys.add(key)
                else:
                    fixes.append(f"Removed duplicate env key: {key}")
            # Check if it's KEY: value format (wrong)
            elif ": " in entry:
                parts = entry.split(": ", 1)
                if len(parts) == 2:
                    key, value = parts
                    if key not in seen_keys:
                        fixed_env.append(f"{key}={value}")
                        seen_keys.add(key)
                        fixes.append(f"Converted env '{entry}' to '{key}={value}'")
                    else:
                        fixes.append(f"Removed duplicate env key: {key}")
            else:
                fixed_env.append(entry)

    dag_data["env"] = fixed_env
    return fixes


def _topological_sort_steps(steps: list[dict]) -> tuple[list[dict], list[str]]:
    """Sort steps in topological order (dependencies before dependents).

    Returns (sorted_steps, issues_fixed).
    """
    issues = []

    # Build dependency graph
    step_names = {s["name"] for s in steps}
    step_by_name = {s["name"]: s for s in steps}

    # Build adjacency list (step -> steps that depend on it)
    dependents: dict[str, list[str]] = {name: [] for name in step_names}
    in_degree: dict[str, int] = {name: 0 for name in step_names}

    for step in steps:
        deps = step.get("depends", [])
        if isinstance(deps, str):
            deps = [deps]
        for dep in deps:
            if dep in step_names:
                dependents[dep].append(step["name"])
                in_degree[step["name"]] += 1
            # Ignore missing deps - they might be external

    # Kahn's algorithm for topological sort
    queue = [name for name, degree in in_degree.items() if degree == 0]
    sorted_names = []

    while queue:
        # Sort queue to ensure deterministic ordering
        queue.sort()
        node = queue.pop(0)
        sorted_names.append(node)

        for dependent in dependents[node]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    # Check for cycles
    if len(sorted_names) != len(steps):
        remaining = set(step_names) - set(sorted_names)
        issues.append(f"Cycle detected involving steps: {remaining}")
        # Return original order if cycle detected
        return steps, issues

    # Check if reordering was needed
    original_order = [s["name"] for s in steps]
    if original_order != sorted_names:
        issues.append(f"Reordered {len(steps)} steps to topological order")

    sorted_steps = [step_by_name[name] for name in sorted_names]
    return sorted_steps, issues


def _remove_empty_depends(dag_data: dict) -> list[str]:
    """Remove empty depends arrays (DAGU prefers no key over empty array)."""
    fixes = []
    for step in dag_data.get("steps", []):
        if "depends" in step and step["depends"] == []:
            del step["depends"]
            fixes.append(f"Removed empty depends from step '{step['name']}'")
    return fixes


def validate_and_fix_dag(dag_data: dict) -> tuple[dict, list[str]]:
    """Validate and fix common issues in generated DAG data.

    Args:
        dag_data: Parsed YAML dict

    Returns:
        (fixed_dag_data, list of fixes applied)
    """
    all_fixes = []

    # Fix env format and duplicates
    all_fixes.extend(_fix_env_format(dag_data))

    # Remove empty depends arrays
    all_fixes.extend(_remove_empty_depends(dag_data))

    # Topologically sort steps
    if "steps" in dag_data:
        sorted_steps, sort_fixes = _topological_sort_steps(dag_data["steps"])
        dag_data["steps"] = sorted_steps
        all_fixes.extend(sort_fixes)

    return dag_data, all_fixes


class DagGenerator:
    """Generates DAGU DAGs using AI inference."""

    def __init__(self, runner: Runner | None = None, runner_type: RunnerType = DEFAULT_RUNNER):
        self.runner = runner or get_runner(runner_type)

    def generate(
        self,
        spec_content: str,
        dag_name: str,
        timeout: int = 120,
        spec_dir: Path | None = None,
    ) -> GenerationResult:
        """Generate a DAGU DAG from task spec content using AI.

        Args:
            spec_content: The task specification content
            dag_name: Name for the DAG
            timeout: Timeout for AI inference
            spec_dir: Optional directory for AI to explore (for richer context)
        """
        # Build the prompt
        prompt = DAG_GENERATION_PROMPT.format(
            spec_content=spec_content,
            dag_name=dag_name.replace("-", "_"),
        )

        # Run the AI (optionally in the spec directory for context)
        result = self.runner.run(prompt, timeout=timeout, cwd=spec_dir)

        if not result.success:
            return GenerationResult(
                success=False,
                error=result.error or "Runner failed",
                raw_output=result.output,
            )

        # Extract YAML from output
        yaml_content = self._extract_yaml(result.output)

        if not yaml_content:
            return GenerationResult(
                success=False,
                error="Could not extract valid YAML from AI output",
                raw_output=result.output,
            )

        # Validate the YAML
        try:
            parsed = yaml.safe_load(yaml_content)
            if not isinstance(parsed, dict) or "steps" not in parsed:
                return GenerationResult(
                    success=False,
                    error="YAML missing required 'steps' field",
                    raw_output=result.output,
                )
        except yaml.YAMLError as e:
            return GenerationResult(
                success=False,
                error=f"Invalid YAML: {e}",
                raw_output=result.output,
            )

        # Validate and fix common issues
        fixed_dag, fixes = validate_and_fix_dag(parsed)

        # Check for unfixable issues (like cycles)
        for fix in fixes:
            if "Cycle detected" in fix:
                return GenerationResult(
                    success=False,
                    error=fix,
                    raw_output=result.output,
                )

        # Re-serialize the fixed YAML
        yaml_content = yaml.dump(fixed_dag, default_flow_style=False, sort_keys=False)

        return GenerationResult(
            success=True,
            yaml_content=yaml_content,
            raw_output=result.output,
        )

    def _extract_yaml(self, output: str) -> str | None:
        """Extract YAML content from AI output."""
        # Try to find YAML in code blocks first
        code_block_pattern = r"```(?:yaml|yml)?\s*\n(.*?)```"
        matches = re.findall(code_block_pattern, output, re.DOTALL)
        if matches:
            return matches[0].strip()

        # Try to find content starting with "name:"
        lines = output.strip().split("\n")
        yaml_start = None
        for i, line in enumerate(lines):
            if line.strip().startswith("name:"):
                yaml_start = i
                break

        if yaml_start is not None:
            yaml_content = "\n".join(lines[yaml_start:])
            return yaml_content.strip()

        # Return the whole output if it looks like YAML
        if output.strip().startswith("name:") or output.strip().startswith("---"):
            return output.strip()

        return None

    def generate_from_file(
        self,
        spec_path: Path,
        dag_name: str | None = None,
        timeout: int = 120,
    ) -> GenerationResult:
        """Generate a DAGU DAG from a task spec file."""
        spec_content = spec_path.read_text()

        if dag_name is None:
            dag_name = spec_path.stem.replace("tasks-", "").replace("tasks", "spec")

        # Pass the spec directory for context
        return self.generate(spec_content, dag_name, timeout, spec_dir=spec_path.parent)

    def generate_from_directory(
        self,
        spec_dir: Path,
        dag_name: str | None = None,
        timeout: int = 120,
    ) -> GenerationResult:
        """Generate a DAGU DAG from a spec directory."""
        # Find task spec files
        task_files = list(spec_dir.glob("tasks*.md")) + list(spec_dir.glob("*.md"))

        if not task_files:
            return GenerationResult(
                success=False,
                error=f"No task spec files found in {spec_dir}",
            )

        # Use the first task file
        task_file = task_files[0]

        if dag_name is None:
            dag_name = spec_dir.name

        return self.generate_from_file(task_file, dag_name, timeout)


def generate_dag(
    spec_content: str,
    dag_name: str,
    runner_type: RunnerType = DEFAULT_RUNNER,
    timeout: int = 120,
) -> GenerationResult:
    """Convenience function to generate a DAG using AI."""
    generator = DagGenerator(runner_type=runner_type)
    return generator.generate(spec_content, dag_name, timeout)


def build_simple_dag(
    spec_id: str,
    tasks: list[dict],
    description: str = "",
) -> str:
    """Build a simple DAG YAML from a list of tasks.

    This is a deterministic alternative to AI generation.

    Args:
        spec_id: The spec identifier
        tasks: List of task dicts with 'id', 'description', 'parent_id', 'children'
        description: DAG description

    Returns:
        YAML string for the DAG
    """
    dag_name = spec_id.replace("-", "_")
    dag = {
        "name": dag_name,
        "description": description or f"DAG for {spec_id}",
        "env": [
            f"ARBORIST_MANIFEST=${{DAG_DIR}}/{spec_id}.json",
        ],
        "steps": [],
    }

    # Add branches setup step (creates all branches from manifest)
    dag["steps"].append({
        "name": "branches-setup",
        "command": "arborist spec branch-create-all",
    })

    # Build steps for each task
    for task in tasks:
        task_id = task["id"]
        has_children = bool(task.get("children"))
        parent_id = task.get("parent_id")

        # Determine slug from description
        desc_words = task.get("description", task_id).split()[:4]
        slug = "-".join(w.lower() for w in desc_words if w.isalnum())[:30]

        if has_children:
            # Parent task: create setup and complete steps
            setup_step = {
                "name": f"{task_id}-setup",
                "command": f"arborist task pre-sync {task_id}",
            }
            if parent_id:
                setup_step["depends"] = [f"{parent_id}-setup"]
            else:
                setup_step["depends"] = ["branches-setup"]
            dag["steps"].append(setup_step)

            # Complete step will be added after we know all children
            # (handled in second pass)
        else:
            # Leaf task: full workflow
            step = {
                "name": f"{task_id}-{slug}"[:40],
                "command": f"""arborist task pre-sync {task_id} &&
arborist task run {task_id} &&
arborist task run-test {task_id} &&
arborist task post-merge {task_id} &&
arborist task post-cleanup {task_id}""",
            }
            if parent_id:
                step["depends"] = [f"{parent_id}-setup"]
            else:
                step["depends"] = ["branches-setup"]
            dag["steps"].append(step)

    # Second pass: add complete steps for parent tasks
    for task in tasks:
        if task.get("children"):
            task_id = task["id"]
            children = task["children"]

            # Find step names for children
            child_deps = []
            for child_id in children:
                child_task = next((t for t in tasks if t["id"] == child_id), None)
                if child_task:
                    if child_task.get("children"):
                        child_deps.append(f"{child_id}-complete")
                    else:
                        # Find the leaf step name
                        desc_words = child_task.get("description", child_id).split()[:4]
                        slug = "-".join(w.lower() for w in desc_words if w.isalnum())[:30]
                        child_deps.append(f"{child_id}-{slug}"[:40])

            complete_step = {
                "name": f"{task_id}-complete",
                "command": f"""arborist task run-test {task_id} &&
arborist task post-merge {task_id} &&
arborist task post-cleanup {task_id}""",
                "depends": child_deps,
            }
            dag["steps"].append(complete_step)

    return yaml.dump(dag, default_flow_style=False, sort_keys=False)
