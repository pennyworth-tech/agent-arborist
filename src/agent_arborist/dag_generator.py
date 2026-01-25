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


# Step 1: AI analyzes spec and outputs simple task structure
TASK_ANALYSIS_PROMPT = '''Analyze the task specification and output a simple JSON structure describing the tasks.

TASK SPECIFICATION DIRECTORY: {spec_dir}

Review all files in this directory to understand the tasks, their dependencies, and any groupings.

OUTPUT FORMAT - JSON only:
```json
{{
  "description": "Brief project description",
  "tasks": [
    {{
      "id": "T001",
      "description": "What this task does",
      "depends_on": [],
      "parallel_with": []
    }},
    {{
      "id": "T002",
      "description": "What this task does",
      "depends_on": ["T001"],
      "parallel_with": []
    }},
    {{
      "id": "T003",
      "description": "Can run parallel with T004",
      "depends_on": ["T002"],
      "parallel_with": ["T004"]
    }},
    {{
      "id": "T004",
      "description": "Can run parallel with T003",
      "depends_on": ["T002"],
      "parallel_with": ["T003"]
    }}
  ]
}}
```

RULES:
1. Each task needs an ID (T001, T002, etc.) and description
2. "depends_on" lists tasks that MUST complete before this task starts
3. "parallel_with" lists tasks that can run at the same time (same dependencies)
4. Tasks are executed in order: first those with no dependencies, then those whose dependencies are met
5. If tasks share the same dependencies and can run together, mark them parallel_with each other

CRITICAL: Output ONLY valid JSON. No markdown fences. No explanation. Start with {{ on line 1.
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


@dataclass
class TaskInfo:
    """Simple task info from AI analysis."""
    id: str
    description: str
    depends_on: list[str]
    parallel_with: list[str]


def build_dag_from_tasks(
    dag_name: str,
    description: str,
    tasks: list[TaskInfo],
    manifest_path: str,
) -> str:
    """Build full DAGU DAG YAML from simple task list.

    Step 2 & 3: Add the standard task pattern and boilerplate.
    """
    dag_name_safe = dag_name.replace("-", "_")

    # Build root DAG steps
    root_steps = [
        {"name": "branches-setup", "command": "arborist spec branch-create-all"}
    ]

    # Group tasks by their dependencies to find parallel groups
    # Tasks with same depends_on can potentially run in parallel
    dep_groups: dict[tuple, list[TaskInfo]] = {}
    for task in tasks:
        key = tuple(sorted(task.depends_on))
        if key not in dep_groups:
            dep_groups[key] = []
        dep_groups[key].append(task)

    # Build execution order - topological sort
    completed: set[str] = set()
    task_by_id = {t.id: t for t in tasks}
    ordered_groups: list[list[TaskInfo]] = []

    while len(completed) < len(tasks):
        # Find tasks whose dependencies are all completed
        ready = []
        for task in tasks:
            if task.id in completed:
                continue
            if all(dep in completed for dep in task.depends_on):
                ready.append(task)

        if not ready:
            # Circular dependency - just add remaining
            ready = [t for t in tasks if t.id not in completed]

        # Group ready tasks that are parallel_with each other
        parallel_groups: list[list[TaskInfo]] = []
        used = set()
        for task in ready:
            if task.id in used:
                continue
            group = [task]
            used.add(task.id)
            for other in ready:
                if other.id in used:
                    continue
                if task.id in other.parallel_with or other.id in task.parallel_with:
                    group.append(other)
                    used.add(other.id)
            parallel_groups.append(group)

        ordered_groups.extend(parallel_groups)
        for task in ready:
            completed.add(task.id)

    # Build root DAG call steps
    prev_deps = ["branches-setup"]
    for group in ordered_groups:
        group_step_names = []
        for task in sorted(group, key=lambda t: t.id):
            step = {
                "name": f"c-{task.id}",
                "call": task.id,
                "depends": prev_deps.copy(),
            }
            root_steps.append(step)
            group_step_names.append(f"c-{task.id}")
        prev_deps = group_step_names

    # Build root DAG document
    root_dag = {
        "name": dag_name_safe,
        "description": description,
        "env": [f"ARBORIST_MANIFEST={manifest_path}"],
        "steps": root_steps,
    }

    # Build subdag for each task with standard pattern
    subdags = []
    for task in sorted(tasks, key=lambda t: t.id):
        subdag = {
            "name": task.id,
            "steps": [
                {"name": "pre-sync", "command": f"arborist task pre-sync {task.id}"},
                {"name": "run", "command": f"arborist task run {task.id}", "depends": ["pre-sync"]},
                {"name": "commit", "command": f"arborist task commit {task.id}", "depends": ["run"]},
                {"name": "run-test", "command": f"arborist task run-test {task.id}", "depends": ["commit"]},
                {"name": "post-merge", "command": f"arborist task post-merge {task.id}", "depends": ["run-test"]},
                {"name": "post-cleanup", "command": f"arborist task post-cleanup {task.id}", "depends": ["post-merge"]},
            ],
            "env": [f"ARBORIST_MANIFEST={manifest_path}"],
        }
        subdags.append(subdag)

    # Serialize to multi-document YAML
    documents = [root_dag] + subdags
    yaml_parts = []
    for doc in documents:
        yaml_parts.append(yaml.dump(doc, default_flow_style=False, sort_keys=False))

    return "---\n".join(yaml_parts)


class DagGenerator:
    """Generates DAGU DAGs using AI inference."""

    def __init__(self, runner: Runner | None = None, runner_type: RunnerType = DEFAULT_RUNNER):
        self.runner = runner or get_runner(runner_type)

    def generate(
        self,
        spec_dir: Path,
        dag_name: str,
        timeout: int = 120,
        manifest_path: str | None = None,
    ) -> GenerationResult:
        """Generate a DAGU DAG from task spec directory using AI.

        Two-step process:
        1. AI analyzes spec and outputs simple task JSON
        2. Code builds full DAG YAML with standard patterns

        Args:
            spec_dir: Directory containing task specification files
            dag_name: Name for the DAG
            timeout: Timeout for AI inference
            manifest_path: Path to manifest JSON (for env var)
        """
        # Step 1: AI analyzes and outputs simple task structure
        prompt = TASK_ANALYSIS_PROMPT.format(spec_dir=spec_dir.resolve())
        result = self.runner.run(prompt, timeout=timeout, cwd=spec_dir)

        if not result.success:
            return GenerationResult(
                success=False,
                error=result.error or "Runner failed",
                raw_output=result.output,
            )

        # Extract JSON from output
        task_json = self._extract_json(result.output)
        if not task_json:
            return GenerationResult(
                success=False,
                error="Could not extract valid JSON from AI output",
                raw_output=result.output,
            )

        # Parse JSON
        import json
        try:
            data = json.loads(task_json)
        except json.JSONDecodeError as e:
            return GenerationResult(
                success=False,
                error=f"Invalid JSON: {e}",
                raw_output=result.output,
            )

        # Validate structure
        if "tasks" not in data or not isinstance(data["tasks"], list):
            return GenerationResult(
                success=False,
                error="JSON missing 'tasks' array",
                raw_output=result.output,
            )

        # Convert to TaskInfo objects
        tasks = []
        for t in data["tasks"]:
            if "id" not in t:
                continue
            tasks.append(TaskInfo(
                id=t["id"],
                description=t.get("description", t["id"]),
                depends_on=t.get("depends_on", []),
                parallel_with=t.get("parallel_with", []),
            ))

        if not tasks:
            return GenerationResult(
                success=False,
                error="No valid tasks found in JSON",
                raw_output=result.output,
            )

        # Step 2 & 3: Build full DAG YAML
        manifest = manifest_path or f"{dag_name}.json"
        description = data.get("description", f"DAG for {dag_name}")

        yaml_content = build_dag_from_tasks(dag_name, description, tasks, manifest)

        return GenerationResult(
            success=True,
            yaml_content=yaml_content,
            raw_output=result.output,
        )

    def _extract_json(self, output: str) -> str | None:
        """Extract JSON content from AI output."""
        import json

        # Try to find JSON in code blocks first
        code_block_pattern = r"```(?:json)?\s*\n(.*?)```"
        matches = re.findall(code_block_pattern, output, re.DOTALL)
        if matches:
            return matches[0].strip()

        # Try to find content starting with {
        lines = output.strip().split("\n")
        json_start = None
        for i, line in enumerate(lines):
            if line.strip().startswith("{"):
                json_start = i
                break

        if json_start is not None:
            # Find the matching closing brace
            content = "\n".join(lines[json_start:])
            # Try to parse incrementally to find valid JSON
            brace_count = 0
            end_idx = 0
            for i, char in enumerate(content):
                if char == "{":
                    brace_count += 1
                elif char == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        end_idx = i + 1
                        break
            if end_idx > 0:
                return content[:end_idx]

        return None

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
            name=f"c-{task_id}",
            call=task_id,
            depends=[prev_step],
        ))
        prev_step = f"c-{task_id}"

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
