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
   - env: ARBORIST_MANIFEST pointing to manifest JSON (see below)
   - steps: List of workflow steps

2. Add env section:
   env:
     - ARBORIST_MANIFEST: ${{DAG_DIR}}/{dag_name}.json

3. Analyze the task hierarchy:
   - Identify all tasks (T001, T002, etc.)
   - Determine parent-child relationships from dependencies
   - A task's "parent" is typically its first dependency
   - Tasks with no dependencies that others depend on are "parent" tasks
   - Tasks at the end of dependency chains are "leaf" tasks

4. First step MUST be branches-setup:
   - name: branches-setup
   - command: arborist branches create-all
   - depends: []

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

CRITICAL: Output ONLY the YAML content. No markdown fences. No explanation. Start directly with "name:" on the first line.
'''


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
            {"ARBORIST_MANIFEST": f"${{DAG_DIR}}/{spec_id}.json"},
        ],
        "steps": [],
    }

    # Add branches setup step (creates all branches from manifest)
    dag["steps"].append({
        "name": "branches-setup",
        "command": "arborist branches create-all",
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
