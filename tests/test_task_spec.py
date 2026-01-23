"""Tests for task_spec module."""

import pytest
from pathlib import Path

from agent_arborist.task_spec import Task, Phase, TaskSpec, TaskSpecParser, parse_task_spec


class TestTask:
    """Tests for Task dataclass."""

    def test_slug_simple(self):
        task = Task(id="T001", description="Create project directory")
        assert task.slug == "create-project-directory"

    def test_slug_truncates_to_four_words(self):
        task = Task(id="T001", description="Create project directory with src and tests folders")
        assert task.slug == "create-project-directory-with"

    def test_slug_removes_special_chars(self):
        task = Task(id="T001", description="Create `src/__init__.py` file")
        assert task.slug == "create-srcinitpy-file"

    def test_full_name(self):
        task = Task(id="T001", description="Create project")
        assert task.full_name == "T001-create-project"

    def test_full_name_truncated_for_dagu(self):
        # Dagu has 40 char limit on step names
        task = Task(id="T001", description="Create a very long task description that exceeds the limit")
        assert len(task.full_name) <= 40
        assert task.full_name.startswith("T001-")

    def test_parallel_default_false(self):
        task = Task(id="T001", description="Test")
        assert task.parallel is False


class TestPhase:
    """Tests for Phase dataclass."""

    def test_phase_with_tasks(self):
        phase = Phase(
            name="Setup",
            tasks=[
                Task(id="T001", description="Task 1"),
                Task(id="T002", description="Task 2"),
            ],
            checkpoint="Ready",
        )
        assert len(phase.tasks) == 2
        assert phase.checkpoint == "Ready"


class TestTaskSpec:
    """Tests for TaskSpec dataclass."""

    def test_tasks_property(self):
        spec = TaskSpec(
            project="Test",
            total_tasks=2,
            phases=[
                Phase(name="P1", tasks=[Task(id="T001", description="Task 1")]),
                Phase(name="P2", tasks=[Task(id="T002", description="Task 2")]),
            ],
        )
        assert len(spec.tasks) == 2
        assert spec.tasks[0].id == "T001"
        assert spec.tasks[1].id == "T002"

    def test_get_task(self):
        spec = TaskSpec(
            project="Test",
            total_tasks=1,
            phases=[Phase(name="P1", tasks=[Task(id="T001", description="Task 1")])],
        )
        task = spec.get_task("T001")
        assert task is not None
        assert task.id == "T001"

        assert spec.get_task("T999") is None

    def test_get_dependents(self):
        spec = TaskSpec(
            project="Test",
            total_tasks=2,
            phases=[],
            dependencies={"T002": ["T001"], "T003": ["T001"]},
        )
        dependents = spec.get_dependents("T001")
        assert set(dependents) == {"T002", "T003"}


class TestTaskSpecParser:
    """Tests for TaskSpecParser."""

    def test_parse_simple_spec(self):
        content = """# Tasks: Test Project

**Project**: Simple test
**Total Tasks**: 2

## Phase 1: Setup

- [ ] T001 Create project
- [ ] T002 Add file

**Checkpoint**: Ready

---

## Dependencies

```
T001 → T002
```
"""
        parser = TaskSpecParser()
        spec = parser.parse(content)

        assert spec.project == "Simple test"
        assert spec.total_tasks == 2
        assert len(spec.phases) == 1
        assert spec.phases[0].name == "Setup"
        assert len(spec.tasks) == 2
        assert spec.dependencies == {"T001": [], "T002": ["T001"]}

    def test_parse_parallel_tasks(self):
        content = """# Tasks: Test

**Project**: Parallel test
**Total Tasks**: 3

## Phase 1: Setup

- [ ] T001 Setup base
- [ ] T002 [P] Create module A
- [ ] T003 [P] Create module B

---
"""
        parser = TaskSpecParser()
        spec = parser.parse(content)

        assert spec.tasks[0].parallel is False
        assert spec.tasks[1].parallel is True
        assert spec.tasks[2].parallel is True

    def test_parse_complex_dependencies(self):
        content = """# Tasks: Test

**Project**: Complex deps
**Total Tasks**: 4

## Phase 1: Setup

- [ ] T001 First
- [ ] T002 Second
- [ ] T003 Third
- [ ] T004 Fourth

---

## Dependencies

```
T001 → T002 → T003, T004
```
"""
        parser = TaskSpecParser()
        spec = parser.parse(content)

        assert spec.dependencies["T001"] == []
        assert spec.dependencies["T002"] == ["T001"]
        assert "T002" in spec.dependencies["T003"]
        assert "T002" in spec.dependencies["T004"]

    def test_parse_multiple_phases(self):
        content = """# Tasks: Multi Phase

**Project**: Multiple phases
**Total Tasks**: 4

## Phase 1: Setup

- [ ] T001 Setup 1
- [ ] T002 Setup 2

**Checkpoint**: Setup done

---

## Phase 2: Build

- [ ] T003 Build 1
- [ ] T004 Build 2

**Checkpoint**: Build done

---
"""
        parser = TaskSpecParser()
        spec = parser.parse(content)

        assert len(spec.phases) == 2
        assert spec.phases[0].name == "Setup"
        assert spec.phases[0].checkpoint == "Setup done"
        assert len(spec.phases[0].tasks) == 2
        assert spec.phases[1].name == "Build"
        assert spec.phases[1].checkpoint == "Build done"
        assert len(spec.phases[1].tasks) == 2


class TestParseTaskSpecFile:
    """Tests for parse_task_spec function with fixture files."""

    @pytest.fixture
    def fixtures_dir(self):
        return Path(__file__).parent / "fixtures"

    def test_parse_hello_world(self, fixtures_dir):
        spec = parse_task_spec(fixtures_dir / "tasks-hello-world.md")

        assert spec.project == "Minimal HTTP hello world"
        assert spec.total_tasks == 6
        assert len(spec.phases) == 3
        assert len(spec.tasks) == 6

        # Check first task
        t001 = spec.get_task("T001")
        assert t001 is not None
        assert t001.description == "Create project directory with `src/`"

        # Check dependencies
        assert spec.dependencies["T001"] == []
        assert spec.dependencies["T002"] == ["T001"]

    def test_parse_calculator(self, fixtures_dir):
        spec = parse_task_spec(fixtures_dir / "tasks-calculator.md")

        assert spec.project == "Simple command-line calculator"
        assert spec.total_tasks == 12
        assert len(spec.phases) == 4

        # Check parallel tasks
        t003 = spec.get_task("T003")
        assert t003 is not None
        assert t003.parallel is True

        t007 = spec.get_task("T007")
        assert t007 is not None
        assert t007.parallel is True

    def test_parse_todo_app(self, fixtures_dir):
        spec = parse_task_spec(fixtures_dir / "tasks-todo-app.md")

        assert spec.project == "Simple todo list with SQLite storage"
        assert spec.total_tasks == 18
        assert len(spec.phases) == 4

        # Verify phase structure
        assert spec.phases[0].name == "Setup"
        assert spec.phases[1].name == "Data Layer"
        assert spec.phases[2].name == "CLI Interface"
        assert spec.phases[3].name == "Polish"
