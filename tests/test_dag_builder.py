"""Tests for dag_builder module."""

import pytest
import yaml
from pathlib import Path

from agent_arborist.task_spec import Task, Phase, TaskSpec, parse_task_spec
from agent_arborist.dag_builder import DagStep, DagConfig, DagBuilder, build_dag


class TestDagStep:
    """Tests for DagStep dataclass."""

    def test_basic_step(self):
        step = DagStep(name="test-step", command="echo test")
        assert step.name == "test-step"
        assert step.command == "echo test"
        assert step.depends == []

    def test_step_with_deps(self):
        step = DagStep(name="step2", command="echo 2", depends=["step1"])
        assert step.depends == ["step1"]


class TestDagConfig:
    """Tests for DagConfig dataclass."""

    def test_config_defaults(self):
        config = DagConfig(name="test-dag")
        assert config.name == "test-dag"
        assert config.description == ""
        assert config.echo_delay_ms == 100


class TestDagBuilder:
    """Tests for DagBuilder."""

    @pytest.fixture
    def simple_spec(self):
        return TaskSpec(
            project="Test Project",
            total_tasks=2,
            phases=[
                Phase(
                    name="Setup",
                    tasks=[
                        Task(id="T001", description="Create project"),
                        Task(id="T002", description="Add files"),
                    ],
                    checkpoint="Ready",
                )
            ],
            dependencies={"T001": [], "T002": ["T001"]},
        )

    @pytest.fixture
    def multi_phase_spec(self):
        return TaskSpec(
            project="Multi Phase Project",
            total_tasks=4,
            phases=[
                Phase(
                    name="Setup",
                    tasks=[
                        Task(id="T001", description="Setup task"),
                    ],
                    checkpoint="Setup done",
                ),
                Phase(
                    name="Build",
                    tasks=[
                        Task(id="T002", description="Build module A"),
                        Task(id="T003", description="Build module B", parallel=True),
                    ],
                    checkpoint="Build done",
                ),
                Phase(
                    name="Test",
                    tasks=[
                        Task(id="T004", description="Run tests"),
                    ],
                    checkpoint="Tests pass",
                ),
            ],
            dependencies={
                "T001": [],
                "T002": ["T001"],
                "T003": ["T001"],
                "T004": ["T002", "T003"],
            },
        )

    def test_build_simple_dag(self, simple_spec):
        config = DagConfig(name="simple-dag")
        builder = DagBuilder(config)
        dag = builder.build(simple_spec)

        assert dag["name"] == "simple-dag"
        assert dag["description"] == "Test Project"
        assert len(dag["steps"]) == 4  # 2 tasks + 1 phase complete + 1 all complete

    def test_step_names_use_full_name(self, simple_spec):
        config = DagConfig(name="test")
        builder = DagBuilder(config)
        dag = builder.build(simple_spec)

        step_names = [s["name"] for s in dag["steps"]]
        assert "T001-create-project" in step_names
        assert "T002-add-files" in step_names

    def test_dependencies_are_correct(self, simple_spec):
        config = DagConfig(name="test")
        builder = DagBuilder(config)
        dag = builder.build(simple_spec)

        # Find T002 step
        t002_step = next(s for s in dag["steps"] if s["name"] == "T002-add-files")
        assert t002_step["depends"] == ["T001-create-project"]

    def test_phase_complete_step(self, simple_spec):
        config = DagConfig(name="test")
        builder = DagBuilder(config)
        dag = builder.build(simple_spec)

        # Find phase complete step
        phase_step = next(s for s in dag["steps"] if "phase-complete" in s["name"])
        assert "setup" in phase_step["name"].lower()
        # Should depend on all tasks in the phase
        assert "T001-create-project" in phase_step["depends"]
        assert "T002-add-files" in phase_step["depends"]

    def test_all_complete_step(self, simple_spec):
        config = DagConfig(name="test")
        builder = DagBuilder(config)
        dag = builder.build(simple_spec)

        all_complete = next(s for s in dag["steps"] if s["name"] == "all-complete")
        # Should depend on all phase complete steps
        assert any("phase-complete" in dep for dep in all_complete["depends"])

    def test_multi_phase_dag_structure(self, multi_phase_spec):
        config = DagConfig(name="multi")
        builder = DagBuilder(config)
        dag = builder.build(multi_phase_spec)

        # Should have: 4 tasks + 3 phase completes + 1 all complete = 8 steps
        assert len(dag["steps"]) == 8

        # Verify T004 depends on both T002 and T003
        t004_step = next(s for s in dag["steps"] if s["name"].startswith("T004"))
        assert len(t004_step["depends"]) == 2

    def test_build_yaml_output(self, simple_spec):
        config = DagConfig(name="test")
        builder = DagBuilder(config)
        yaml_content = builder.build_yaml(simple_spec)

        # Should be valid YAML
        parsed = yaml.safe_load(yaml_content)
        assert parsed["name"] == "test"
        assert "steps" in parsed

    def test_echo_delay(self, simple_spec):
        config = DagConfig(name="test", echo_delay_ms=200)
        builder = DagBuilder(config)
        dag = builder.build(simple_spec)

        task_step = next(s for s in dag["steps"] if s["name"].startswith("T001"))
        assert "sleep 0.2" in task_step["command"]


class TestBuildDag:
    """Tests for build_dag convenience function."""

    def test_build_dag_simple(self):
        spec = TaskSpec(
            project="Test",
            total_tasks=1,
            phases=[Phase(name="P1", tasks=[Task(id="T001", description="Test")])],
        )
        yaml_content = build_dag(spec, "test-dag")

        parsed = yaml.safe_load(yaml_content)
        assert parsed["name"] == "test-dag"


class TestBuildDagFromFixtures:
    """Integration tests with fixture files."""

    @pytest.fixture
    def fixtures_dir(self):
        return Path(__file__).parent / "fixtures"

    def test_build_hello_world_dag(self, fixtures_dir):
        spec = parse_task_spec(fixtures_dir / "tasks-hello-world.md")
        yaml_content = build_dag(spec, "hello-world")

        dag = yaml.safe_load(yaml_content)
        assert dag["name"] == "hello-world"

        # 6 tasks + 3 phases + 1 all complete = 10 steps
        assert len(dag["steps"]) == 10

        # Verify dependency chain
        step_map = {s["name"]: s for s in dag["steps"]}

        # T002 depends on T001
        t002 = next(s for name, s in step_map.items() if name.startswith("T002"))
        assert any("T001" in dep for dep in t002.get("depends", []))

    def test_build_calculator_dag(self, fixtures_dir):
        spec = parse_task_spec(fixtures_dir / "tasks-calculator.md")
        yaml_content = build_dag(spec, "calculator")

        dag = yaml.safe_load(yaml_content)

        # 12 tasks + 4 phases + 1 all complete = 17 steps
        assert len(dag["steps"]) == 17

    def test_build_todo_app_dag(self, fixtures_dir):
        spec = parse_task_spec(fixtures_dir / "tasks-todo-app.md")
        yaml_content = build_dag(spec, "todo-app")

        dag = yaml.safe_load(yaml_content)

        # 18 tasks + 4 phases + 1 all complete = 23 steps
        assert len(dag["steps"]) == 23
