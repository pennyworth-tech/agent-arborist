"""Task specification parser for task markdown files."""

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Task:
    """A single task in the spec."""

    id: str  # e.g., "T001"
    description: str  # e.g., "Create project directory structure"
    parallel: bool = False  # [P] flag
    phase: str | None = None  # Phase name

    # Dagu has a 40 char limit on step names
    MAX_STEP_NAME_LENGTH = 40

    @property
    def slug(self) -> str:
        """Generate a slug from the description."""
        # Take first few words and slugify
        words = self.description.split()[:4]
        slug = "-".join(words).lower()
        # Remove non-alphanumeric except hyphens
        slug = re.sub(r"[^a-z0-9-]", "", slug)
        # Remove consecutive hyphens
        slug = re.sub(r"-+", "-", slug)
        return slug.strip("-")

    @property
    def full_name(self) -> str:
        """Full step name: TASK_ID-slug (max 40 chars for dagu)."""
        name = f"{self.id}-{self.slug}"
        if len(name) > self.MAX_STEP_NAME_LENGTH:
            # Truncate slug to fit, preserving task ID
            max_slug_len = self.MAX_STEP_NAME_LENGTH - len(self.id) - 1
            truncated_slug = self.slug[:max_slug_len].rstrip("-")
            name = f"{self.id}-{truncated_slug}"
        return name


@dataclass
class Phase:
    """A phase containing multiple tasks."""

    name: str  # e.g., "Phase 1: Setup"
    tasks: list[Task] = field(default_factory=list)
    checkpoint: str | None = None  # e.g., "Project structure exists"


@dataclass
class TaskSpec:
    """Parsed task specification."""

    project: str  # Project description
    total_tasks: int  # Expected task count
    phases: list[Phase] = field(default_factory=list)
    dependencies: dict[str, list[str]] = field(default_factory=dict)  # task_id -> [depends_on_ids]

    @property
    def tasks(self) -> list[Task]:
        """All tasks across all phases."""
        return [task for phase in self.phases for task in phase.tasks]

    def get_task(self, task_id: str) -> Task | None:
        """Get a task by ID."""
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None

    def get_dependents(self, task_id: str) -> list[str]:
        """Get tasks that depend on the given task."""
        dependents = []
        for tid, deps in self.dependencies.items():
            if task_id in deps:
                dependents.append(tid)
        return dependents


class TaskSpecParser:
    """Parser for task specification markdown files."""

    # Pattern: - [ ] T001 Description or - [ ] T001 [P] Description
    TASK_PATTERN = re.compile(
        r"^-\s*\[\s*\]\s*(T\d+)\s*(\[P\])?\s*(.+)$"
    )

    # Pattern: ## Phase N: Name
    PHASE_PATTERN = re.compile(r"^##\s*Phase\s*\d+:\s*(.+)$")

    # Pattern: **Checkpoint**: Description
    CHECKPOINT_PATTERN = re.compile(r"^\*\*Checkpoint\*\*:\s*(.+)$")

    # Pattern: **Project**: Description
    PROJECT_PATTERN = re.compile(r"^\*\*Project\*\*:\s*(.+)$")

    # Pattern: **Total Tasks**: N
    TOTAL_TASKS_PATTERN = re.compile(r"^\*\*Total Tasks\*\*:\s*(\d+)$")

    # Dependency patterns
    # T001 → T002 or T001 → T002, T003
    DEP_ARROW_PATTERN = re.compile(r"(T\d+)\s*→\s*([^→\n]+)")

    def parse(self, content: str) -> TaskSpec:
        """Parse task spec from markdown content."""
        lines = content.strip().split("\n")

        project = ""
        total_tasks = 0
        phases: list[Phase] = []
        current_phase: Phase | None = None
        in_dependencies = False
        dep_lines: list[str] = []

        for line in lines:
            line = line.strip()

            # Check for dependencies section
            if line == "## Dependencies":
                in_dependencies = True
                continue

            if in_dependencies:
                if line.startswith("```"):
                    continue
                if line:
                    dep_lines.append(line)
                continue

            # Project description
            if match := self.PROJECT_PATTERN.match(line):
                project = match.group(1)
                continue

            # Total tasks
            if match := self.TOTAL_TASKS_PATTERN.match(line):
                total_tasks = int(match.group(1))
                continue

            # Phase header
            if match := self.PHASE_PATTERN.match(line):
                if current_phase:
                    phases.append(current_phase)
                current_phase = Phase(name=match.group(1))
                continue

            # Checkpoint
            if match := self.CHECKPOINT_PATTERN.match(line):
                if current_phase:
                    current_phase.checkpoint = match.group(1)
                continue

            # Task
            if match := self.TASK_PATTERN.match(line):
                task_id = match.group(1)
                parallel = match.group(2) is not None  # [P] present
                description = match.group(3).strip()

                task = Task(
                    id=task_id,
                    description=description,
                    parallel=parallel,
                    phase=current_phase.name if current_phase else None,
                )

                if current_phase:
                    current_phase.tasks.append(task)
                continue

        # Add last phase
        if current_phase:
            phases.append(current_phase)

        # Parse dependencies
        dependencies = self._parse_dependencies(dep_lines, phases)

        return TaskSpec(
            project=project,
            total_tasks=total_tasks,
            phases=phases,
            dependencies=dependencies,
        )

    def _parse_dependencies(
        self, dep_lines: list[str], phases: list[Phase]
    ) -> dict[str, list[str]]:
        """Parse dependency lines into a dependency map."""
        dependencies: dict[str, list[str]] = {}

        # Initialize all tasks with empty deps
        for phase in phases:
            for task in phase.tasks:
                dependencies[task.id] = []

        for line in dep_lines:
            # Skip phase-level comments
            if "Phase" in line or "Within" in line:
                continue

            # Find all arrows in the line
            # Handle chains like T001 → T002 → T003, T004
            # Split by →
            parts = re.split(r"\s*→\s*", line)

            for i in range(1, len(parts)):
                # Previous part is the dependency
                prev_part = parts[i - 1].strip()
                curr_part = parts[i].strip()

                # Get the last task from prev_part (handles "T003, T004" → "T005")
                prev_tasks = [t.strip() for t in prev_part.split(",")]
                prev_tasks = [t for t in prev_tasks if re.match(r"T\d+", t)]

                # Get all tasks in curr_part
                curr_tasks = [t.strip() for t in curr_part.split(",")]
                curr_tasks = [t for t in curr_tasks if re.match(r"T\d+", t)]

                # Each curr task depends on all prev tasks
                for curr_task in curr_tasks:
                    if curr_task in dependencies:
                        for prev_task in prev_tasks:
                            if prev_task not in dependencies[curr_task]:
                                dependencies[curr_task].append(prev_task)

        return dependencies

    def parse_file(self, path: Path) -> TaskSpec:
        """Parse task spec from a file."""
        content = path.read_text()
        return self.parse(content)


def parse_task_spec(path: Path) -> TaskSpec:
    """Convenience function to parse a task spec file."""
    parser = TaskSpecParser()
    return parser.parse_file(path)
