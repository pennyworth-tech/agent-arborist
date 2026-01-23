"""AI-powered DAG generator using LLM runners.

This module generates multi-document YAML with subdags:
- Root DAG: branches-setup + linear calls to root tasks
- Parent subdags: pre-sync + parallel child calls + complete
- Leaf subdags: 5 sequential command nodes
"""

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


# Prompt for subdag-based task execution with deterministic branch manifest
DAG_GENERATION_PROMPT = '''You are a workflow automation expert. Analyze the task specification and output a DAGU DAG with subdags as multi-document YAML.

TASK SPECIFICATION:
---
{spec_content}
---

OUTPUT FORMAT:
Generate a multi-document YAML (separated by ---) with:
1. Root DAG (first document)
2. One subdag per task (subsequent documents)

ROOT DAG STRUCTURE:
```yaml
name: "{dag_name}"
description: Brief project description
env:
  - ARBORIST_MANIFEST={dag_name}.json
steps:
  - name: branches-setup
    command: arborist spec branch-create-all
  - name: call-T001
    call: T001
    depends: [branches-setup]
  - name: call-T005  # Next root task (if exists)
    call: T005
    depends: [call-T001]  # Linear chain at root level
```

LEAF SUBDAG (tasks with no children):
```yaml
---
name: T002
steps:
  - name: pre-sync
    command: arborist task pre-sync T002
  - name: run
    command: arborist task run T002
    depends: [pre-sync]
  - name: run-test
    command: arborist task run-test T002
    depends: [run]
  - name: post-merge
    command: arborist task post-merge T002
    depends: [run-test]
  - name: post-cleanup
    command: arborist task post-cleanup T002
    depends: [post-merge]
```

PARENT SUBDAG (tasks with children):
```yaml
---
name: T001
steps:
  - name: pre-sync
    command: arborist task pre-sync T001
  - name: call-T002
    call: T002
    depends: [pre-sync]
  - name: call-T003  # Multiple children run in parallel
    call: T003
    depends: [pre-sync]
  - name: complete
    command: |
      arborist task run-test T001 &&
      arborist task post-merge T001 &&
      arborist task post-cleanup T001
    depends: [call-T002, call-T003]
```

RULES:
1. Root DAG calls root-level tasks (no parent) in LINEAR sequence by task ID
2. Parent subdags call children in PARALLEL (all depend on pre-sync)
3. Leaf subdags have exactly 5 steps: pre-sync, run, run-test, post-merge, post-cleanup
4. Task hierarchy is inferred from dependencies (first dependency = parent)
5. Tasks marked [P] are parallel siblings (same parent)
6. Sort subdags by task ID (T001, T002, T003...)

CRITICAL: Output ONLY the YAML content. No markdown fences. No explanation. Start with "name:" on line 1.
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
        dag_data: Parsed YAML dict (single document)

    Returns:
        (fixed_dag_data, list of fixes applied)
    """
    all_fixes = []

    # Fix env format and duplicates (only root DAG has env)
    all_fixes.extend(_fix_env_format(dag_data))

    # Remove empty depends arrays
    all_fixes.extend(_remove_empty_depends(dag_data))

    # Topologically sort steps
    if "steps" in dag_data:
        sorted_steps, sort_fixes = _topological_sort_steps(dag_data["steps"])
        dag_data["steps"] = sorted_steps
        all_fixes.extend(sort_fixes)

    return dag_data, all_fixes


def validate_and_fix_multi_doc(documents: list[dict]) -> tuple[list[dict], list[str]]:
    """Validate and fix all documents in a multi-doc YAML.

    Args:
        documents: List of parsed YAML dicts

    Returns:
        (fixed_documents, list of all fixes applied)
    """
    all_fixes = []
    fixed_docs = []

    for i, doc in enumerate(documents):
        fixed_doc, fixes = validate_and_fix_dag(doc)
        fixed_docs.append(fixed_doc)
        # Prefix fixes with document identifier
        doc_name = doc.get("name", f"doc-{i}")
        all_fixes.extend([f"[{doc_name}] {fix}" for fix in fixes])

    return fixed_docs, all_fixes


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
        """Generate a DAGU DAG with subdags from task spec content using AI.

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

        # Parse multi-document YAML
        try:
            documents = list(yaml.safe_load_all(yaml_content))
            if not documents:
                return GenerationResult(
                    success=False,
                    error="No YAML documents found",
                    raw_output=result.output,
                )

            # First document should be root DAG
            root = documents[0]
            if not isinstance(root, dict) or "steps" not in root:
                return GenerationResult(
                    success=False,
                    error="Root DAG missing required 'steps' field",
                    raw_output=result.output,
                )

        except yaml.YAMLError as e:
            return GenerationResult(
                success=False,
                error=f"Invalid YAML: {e}",
                raw_output=result.output,
            )

        # Validate and fix all documents
        fixed_docs, fixes = validate_and_fix_multi_doc(documents)

        # Check for unfixable issues (like cycles)
        for fix in fixes:
            if "Cycle detected" in fix:
                return GenerationResult(
                    success=False,
                    error=fix,
                    raw_output=result.output,
                )

        # Re-serialize as multi-document YAML
        yaml_parts = []
        for doc in fixed_docs:
            yaml_parts.append(yaml.dump(doc, default_flow_style=False, sort_keys=False))

        yaml_content = "---\n".join(yaml_parts)

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

        # Try to find content starting with "name:" or "---"
        lines = output.strip().split("\n")
        yaml_start = None
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("name:") or stripped == "---":
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
    """Build a subdag-based DAG YAML from a list of tasks.

    This is a deterministic alternative to AI generation.

    Args:
        spec_id: The spec identifier
        tasks: List of task dicts with 'id', 'description', 'parent_id', 'children'
        description: DAG description

    Returns:
        Multi-document YAML string with root DAG and subdags
    """
    from agent_arborist.dag_builder import (
        SubDagBuilder, DagConfig, SubDag, SubDagStep
    )
    from agent_arborist.task_state import TaskTree, TaskNode

    dag_name = spec_id.replace("-", "_")

    # Build a TaskTree from the task list
    tree = TaskTree(spec_id=spec_id)

    for task in tasks:
        tree.tasks[task["id"]] = TaskNode(
            task_id=task["id"],
            description=task.get("description", task["id"]),
            parent_id=task.get("parent_id"),
            children=task.get("children", []),
        )

    # Find root tasks
    tree.root_tasks = [
        tid for tid, t in tree.tasks.items()
        if t.parent_id is None
    ]

    # Build using SubDagBuilder
    config = DagConfig(name=dag_name, description=description, spec_id=spec_id)
    builder = SubDagBuilder(config)

    # We need a TaskSpec but we don't have one, so we build manually
    # Build root DAG
    root_steps: list[SubDagStep] = [
        SubDagStep(name="branches-setup", command="arborist spec branch-create-all")
    ]

    # Linear calls to root tasks
    prev_step = "branches-setup"
    for task_id in sorted(tree.root_tasks):
        root_steps.append(SubDagStep(
            name=f"call-{task_id}",
            call=task_id,
            depends=[prev_step],
        ))
        prev_step = f"call-{task_id}"

    root = SubDag(
        name=dag_name,
        description=description or f"DAG for {spec_id}",
        env=[f"ARBORIST_MANIFEST={spec_id}.json"],
        steps=root_steps,
        is_root=True,
    )

    # Build subdags for each task
    subdags: list[SubDag] = []
    for task_id in sorted(tree.tasks.keys()):
        task = tree.get_task(task_id)
        if not task:
            continue

        if tree.is_leaf(task_id):
            subdag = builder._build_leaf_subdag(task_id)
        else:
            subdag = builder._build_parent_subdag(task_id, tree)

        subdags.append(subdag)

    # Render to multi-document YAML
    import yaml

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
            return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
        return dumper.represent_scalar("tag:yaml.org,2002:str", data)

    CustomDumper.add_representer(list, represent_list)
    CustomDumper.add_representer(str, represent_str)

    documents = []

    # Root DAG
    root_dict = builder._subdag_to_dict(root)
    documents.append(yaml.dump(
        root_dict, Dumper=CustomDumper, default_flow_style=False, sort_keys=False
    ))

    # Subdags
    for subdag in subdags:
        subdag_dict = builder._subdag_to_dict(subdag)
        documents.append(yaml.dump(
            subdag_dict, Dumper=CustomDumper, default_flow_style=False, sort_keys=False
        ))

    return "---\n".join(documents)
