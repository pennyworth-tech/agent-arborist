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


DAG_GENERATION_PROMPT = '''You are a workflow automation expert. Read the following task specification and generate a DAGU DAG YAML file.

TASK SPECIFICATION:
---
{spec_content}
---

REQUIREMENTS:
1. Generate valid DAGU YAML with these fields:
   - name: Use "{dag_name}" (underscores, no dashes)
   - description: Brief project description
   - steps: List of workflow steps

2. For each task (T001, T002, etc.), create a step with:
   - name: "{task_id}-{slug}" where slug is 2-4 words from description (max 40 chars total)
   - command: 'sleep 0.1 && echo "[{task_id}] {description}"'
   - depends: List of step names this task depends on (based on the Dependencies section)

3. Escape any backticks in descriptions with single quotes

4. Add phase completion steps:
   - name: "phase-complete-{phase-slug}"
   - command: 'sleep 0.1 && echo "Phase complete: {checkpoint}"'
   - depends: All task steps in that phase

5. Add final step:
   - name: "all-complete"
   - depends: All phase-complete steps

6. Parse the Dependencies section carefully:
   - "T001 → T002" means T002 depends on T001
   - "T001 → T002, T003" means both T002 and T003 depend on T001
   - "T001 → T002 → T003" is a chain

7. Tasks marked [P] can run in parallel with siblings (they share the same dependencies)

OUTPUT FORMAT:
Return ONLY valid YAML, no markdown code fences, no explanation. Start directly with "name:".
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
    ) -> GenerationResult:
        """Generate a DAGU DAG from task spec content using AI."""
        # Build the prompt
        prompt = DAG_GENERATION_PROMPT.format(
            spec_content=spec_content,
            dag_name=dag_name.replace("-", "_"),
            task_id="{task_id}",  # Keep as template markers in instructions
            slug="{slug}",
            description="{description}",
            checkpoint="{checkpoint}",
        )

        # Run the AI
        result = self.runner.run(prompt, timeout=timeout)

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

        return self.generate(spec_content, dag_name, timeout)

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
