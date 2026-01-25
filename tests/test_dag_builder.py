"""Tests for dag_builder module with subdag architecture."""

import pytest
import yaml
from pathlib import Path

from agent_arborist.task_spec import Task, Phase, TaskSpec, parse_task_spec
from agent_arborist.task_state import TaskTree, TaskNode
from agent_arborist.dag_builder import (
    SubDagStep, SubDag, DagBundle, DagConfig,
    SubDagBuilder, DagBuilder, DagStep, build_dag,
    _build_tree_from_spec,
)


class TestSubDagStep:
    """Tests for SubDagStep dataclass."""

    def test_command_step(self):
        step = SubDagStep(name="test-step", command="echo test")
        assert step.name == "test-step"
        assert step.command == "echo test"
        assert step.call is None
        assert step.depends == []

    def test_call_step(self):
        step = SubDagStep(name="c-T001", call="T001", depends=["pre-sync"])
        assert step.call == "T001"
        assert step.command is None
        assert step.depends == ["pre-sync"]


class TestSubDag:
    """Tests for SubDag dataclass."""

    def test_basic_subdag(self):
        subdag = SubDag(name="T001", steps=[])
        assert subdag.name == "T001"
        assert subdag.steps == []
        assert subdag.is_root is False

    def test_root_dag(self):
        subdag = SubDag(
            name="my-dag",
            env=["ARBORIST_MANIFEST=spec.json"],
            is_root=True,
        )
        assert subdag.is_root is True
        assert len(subdag.env) == 1


class TestDagConfig:
    """Tests for DagConfig dataclass."""

    def test_config_defaults(self):
        config = DagConfig(name="test-dag")
        assert config.name == "test-dag"
        assert config.description == ""
        assert config.spec_id == ""


class TestBuildTreeFromSpec:
    """Tests for _build_tree_from_spec helper."""

    def test_linear_chain(self):
        """T001 -> T002 -> T003 (linear dependency chain)."""
        spec = TaskSpec(
            project="Test",
            total_tasks=3,
            phases=[Phase(
                name="P1",
                tasks=[
                    Task(id="T001", description="First"),
                    Task(id="T002", description="Second"),
                    Task(id="T003", description="Third"),
                ],
            )],
            dependencies={"T001": [], "T002": ["T001"], "T003": ["T002"]},
        )

        tree = _build_tree_from_spec(spec, "test-spec")

        # T001 is root
        assert "T001" in tree.root_tasks
        assert tree.tasks["T001"].parent_id is None
        assert "T002" in tree.tasks["T001"].children

        # T002 has parent T001 and child T003
        assert tree.tasks["T002"].parent_id == "T001"
        assert "T003" in tree.tasks["T002"].children

        # T003 is leaf
        assert tree.tasks["T003"].parent_id == "T002"
        assert tree.tasks["T003"].children == []

    def test_parallel_children(self):
        """T001 -> (T002, T003, T004) parallel children."""
        spec = TaskSpec(
            project="Test",
            total_tasks=4,
            phases=[Phase(
                name="P1",
                tasks=[
                    Task(id="T001", description="Parent"),
                    Task(id="T002", description="Child A"),
                    Task(id="T003", description="Child B"),
                    Task(id="T004", description="Child C"),
                ],
            )],
            dependencies={
                "T001": [],
                "T002": ["T001"],
                "T003": ["T001"],
                "T004": ["T001"],
            },
        )

        tree = _build_tree_from_spec(spec, "test-spec")

        # T001 is root with 3 children
        assert tree.tasks["T001"].parent_id is None
        assert set(tree.tasks["T001"].children) == {"T002", "T003", "T004"}

        # All children have T001 as parent
        for tid in ["T002", "T003", "T004"]:
            assert tree.tasks[tid].parent_id == "T001"
            assert tree.tasks[tid].children == []


class TestSubDagBuilder:
    """Tests for SubDagBuilder."""

    @pytest.fixture
    def linear_tree(self):
        """T001 -> T002 -> T003 linear chain."""
        tree = TaskTree(spec_id="test")
        tree.tasks = {
            "T001": TaskNode(task_id="T001", description="First", children=["T002"]),
            "T002": TaskNode(task_id="T002", description="Second", parent_id="T001", children=["T003"]),
            "T003": TaskNode(task_id="T003", description="Third", parent_id="T002"),
        }
        tree.root_tasks = ["T001"]
        return tree

    @pytest.fixture
    def parallel_tree(self):
        """T001 with parallel children T002, T003."""
        tree = TaskTree(spec_id="test")
        tree.tasks = {
            "T001": TaskNode(task_id="T001", description="Parent", children=["T002", "T003"]),
            "T002": TaskNode(task_id="T002", description="Child A", parent_id="T001"),
            "T003": TaskNode(task_id="T003", description="Child B", parent_id="T001"),
        }
        tree.root_tasks = ["T001"]
        return tree

    def test_build_leaf_subdag(self, linear_tree):
        config = DagConfig(name="test", spec_id="test")
        builder = SubDagBuilder(config)

        subdag = builder._build_leaf_subdag("T003")

        assert subdag.name == "T003"
        assert len(subdag.steps) == 5

        # Verify step names and order
        step_names = [s.name for s in subdag.steps]
        assert step_names == ["pre-sync", "run", "run-test", "post-merge", "post-cleanup"]

        # Verify dependencies
        assert subdag.steps[0].depends == []  # pre-sync
        assert subdag.steps[1].depends == ["pre-sync"]  # run
        assert subdag.steps[2].depends == ["run"]  # run-test
        assert subdag.steps[3].depends == ["run-test"]  # post-merge
        assert subdag.steps[4].depends == ["post-merge"]  # post-cleanup

        # Verify commands
        assert "arborist task pre-sync T003" in subdag.steps[0].command
        assert "arborist task run T003" in subdag.steps[1].command

    def test_build_parent_subdag(self, parallel_tree):
        config = DagConfig(name="test", spec_id="test")
        builder = SubDagBuilder(config)

        subdag = builder._build_parent_subdag("T001", parallel_tree)

        assert subdag.name == "T001"

        # Should have: pre-sync, c-T002, c-T003, complete
        assert len(subdag.steps) == 4

        step_names = [s.name for s in subdag.steps]
        assert "pre-sync" in step_names
        assert "c-T002" in step_names
        assert "c-T003" in step_names
        assert "complete" in step_names

        # Verify pre-sync has no deps
        pre_sync = next(s for s in subdag.steps if s.name == "pre-sync")
        assert pre_sync.depends == []

        # Verify calls depend on pre-sync (parallel)
        call_t002 = next(s for s in subdag.steps if s.name == "c-T002")
        assert call_t002.call == "T002"
        assert call_t002.depends == ["pre-sync"]

        call_t003 = next(s for s in subdag.steps if s.name == "c-T003")
        assert call_t003.depends == ["pre-sync"]

        # Verify complete depends on all calls
        complete = next(s for s in subdag.steps if s.name == "complete")
        assert set(complete.depends) == {"c-T002", "c-T003"}

    def test_build_root_dag(self, linear_tree):
        config = DagConfig(name="test_dag", spec_id="test-spec")
        builder = SubDagBuilder(config)

        root = builder._build_root_dag(linear_tree)

        assert root.name == "test_dag"
        assert root.is_root is True
        assert "ARBORIST_MANIFEST=test-spec.json" in root.env

        # Should have: branches-setup, c-T001
        assert len(root.steps) == 2

        # Verify branches-setup
        assert root.steps[0].name == "branches-setup"
        assert root.steps[0].command == "arborist spec branch-create-all"
        assert root.steps[0].depends == []

        # Verify c-T001
        assert root.steps[1].name == "c-T001"
        assert root.steps[1].call == "T001"
        assert root.steps[1].depends == ["branches-setup"]

    def test_build_root_dag_multiple_roots(self):
        """Test root DAG with multiple root tasks."""
        tree = TaskTree(spec_id="test")
        tree.tasks = {
            "T001": TaskNode(task_id="T001", description="First"),
            "T005": TaskNode(task_id="T005", description="Fifth"),
        }
        tree.root_tasks = ["T001", "T005"]

        config = DagConfig(name="test", spec_id="test")
        builder = SubDagBuilder(config)

        root = builder._build_root_dag(tree)

        # Should have: branches-setup, c-T001, c-T005 (in linear sequence)
        assert len(root.steps) == 3

        # Linear chain: branches-setup -> c-T001 -> c-T005
        assert root.steps[1].name == "c-T001"
        assert root.steps[1].depends == ["branches-setup"]

        assert root.steps[2].name == "c-T005"
        assert root.steps[2].depends == ["c-T001"]

    def test_build_all_subdags(self, linear_tree):
        config = DagConfig(name="test", spec_id="test")
        builder = SubDagBuilder(config)

        subdags = builder._build_all_subdags(linear_tree)

        # Should have 3 subdags (T001, T002, T003)
        assert len(subdags) == 3

        subdag_names = [s.name for s in subdags]
        assert "T001" in subdag_names
        assert "T002" in subdag_names
        assert "T003" in subdag_names

        # T001 and T002 are parents (have children)
        t001 = next(s for s in subdags if s.name == "T001")
        assert any(step.call is not None for step in t001.steps)

        # T003 is leaf (no calls)
        t003 = next(s for s in subdags if s.name == "T003")
        assert all(step.call is None for step in t003.steps)
        assert len(t003.steps) == 5

    def test_build_complete_bundle(self, parallel_tree):
        spec = TaskSpec(
            project="Test",
            total_tasks=3,
            phases=[Phase(name="P1", tasks=[
                Task(id="T001", description="Parent"),
                Task(id="T002", description="Child A"),
                Task(id="T003", description="Child B"),
            ])],
            dependencies={"T001": [], "T002": ["T001"], "T003": ["T001"]},
        )

        config = DagConfig(name="test", spec_id="test")
        builder = SubDagBuilder(config)

        bundle = builder.build(spec, parallel_tree)

        assert bundle.root.name == "test"
        assert bundle.root.is_root is True
        assert len(bundle.subdags) == 3

    def test_build_yaml_multi_document(self, linear_tree):
        spec = TaskSpec(
            project="Test",
            total_tasks=3,
            phases=[Phase(name="P1", tasks=[
                Task(id="T001", description="First"),
                Task(id="T002", description="Second"),
                Task(id="T003", description="Third"),
            ])],
            dependencies={"T001": [], "T002": ["T001"], "T003": ["T002"]},
        )

        config = DagConfig(name="test", spec_id="test")
        builder = SubDagBuilder(config)

        yaml_content = builder.build_yaml(spec, linear_tree)

        # Should be multi-document YAML
        assert "---" in yaml_content

        # Parse all documents
        documents = list(yaml.safe_load_all(yaml_content))

        # Should have 4 documents: root + 3 subdags
        assert len(documents) == 4

        # First is root
        assert documents[0]["name"] == "test"
        assert "env" in documents[0]

        # Others are subdags
        subdag_names = [d["name"] for d in documents[1:]]
        assert "T001" in subdag_names
        assert "T002" in subdag_names
        assert "T003" in subdag_names


class TestDagBuilderLegacy:
    """Tests for legacy DagBuilder compatibility."""

    def test_legacy_builder_produces_yaml(self):
        spec = TaskSpec(
            project="Test",
            total_tasks=2,
            phases=[Phase(name="P1", tasks=[
                Task(id="T001", description="First"),
                Task(id="T002", description="Second"),
            ])],
            dependencies={"T001": [], "T002": ["T001"]},
        )

        config = DagConfig(name="test", spec_id="test")
        builder = DagBuilder(config)

        yaml_content = builder.build_yaml(spec)

        # Should be valid multi-document YAML
        documents = list(yaml.safe_load_all(yaml_content))
        assert len(documents) >= 1
        assert documents[0]["name"] == "test"


class TestBuildDag:
    """Tests for build_dag convenience function."""

    def test_build_dag_simple(self):
        spec = TaskSpec(
            project="Test",
            total_tasks=2,
            phases=[Phase(name="P1", tasks=[
                Task(id="T001", description="First"),
                Task(id="T002", description="Second"),
            ])],
            dependencies={"T001": [], "T002": ["T001"]},
        )

        yaml_content = build_dag(spec, "test-dag")

        # Should be valid multi-document YAML
        documents = list(yaml.safe_load_all(yaml_content))
        assert documents[0]["name"] == "test-dag"


class TestBuildDagFromFixtures:
    """Integration tests with fixture files."""

    @pytest.fixture
    def fixtures_dir(self):
        return Path(__file__).parent / "fixtures"

    def test_build_hello_world_dag(self, fixtures_dir):
        spec = parse_task_spec(fixtures_dir / "tasks-hello-world.md")
        yaml_content = build_dag(spec, "hello-world")

        documents = list(yaml.safe_load_all(yaml_content))

        # First document is root DAG
        root = documents[0]
        assert root["name"] == "hello-world"

        # Should have subdags for each task
        # tasks-hello-world.md has 6 tasks
        assert len(documents) == 7  # 1 root + 6 subdags

    def test_build_calculator_dag(self, fixtures_dir):
        spec = parse_task_spec(fixtures_dir / "tasks-calculator.md")
        yaml_content = build_dag(spec, "calculator")

        documents = list(yaml.safe_load_all(yaml_content))

        # First document is root DAG
        root = documents[0]
        assert root["name"] == "calculator"

        # tasks-calculator.md has 12 tasks
        assert len(documents) == 13  # 1 root + 12 subdags

    def test_build_todo_app_dag(self, fixtures_dir):
        spec = parse_task_spec(fixtures_dir / "tasks-todo-app.md")
        yaml_content = build_dag(spec, "todo-app")

        documents = list(yaml.safe_load_all(yaml_content))

        # tasks-todo-app.md has 18 tasks
        assert len(documents) == 19  # 1 root + 18 subdags

    def test_leaf_subdag_has_five_steps(self, fixtures_dir):
        """Verify leaf subdags have exactly 5 steps."""
        spec = parse_task_spec(fixtures_dir / "tasks-hello-world.md")
        yaml_content = build_dag(spec, "hello-world")

        documents = list(yaml.safe_load_all(yaml_content))

        # Find a leaf task (one that has no 'call' steps)
        for doc in documents[1:]:  # Skip root
            steps = doc.get("steps", [])
            has_call = any("call" in step for step in steps)
            if not has_call:
                # This is a leaf - should have 5 steps
                assert len(steps) == 5
                step_names = [s["name"] for s in steps]
                assert step_names == ["pre-sync", "run", "run-test", "post-merge", "post-cleanup"]
                break

    def test_root_dag_has_branches_setup(self, fixtures_dir):
        """Verify root DAG starts with branches-setup."""
        spec = parse_task_spec(fixtures_dir / "tasks-hello-world.md")
        yaml_content = build_dag(spec, "hello-world")

        documents = list(yaml.safe_load_all(yaml_content))
        root = documents[0]

        first_step = root["steps"][0]
        assert first_step["name"] == "branches-setup"
        assert first_step["command"] == "arborist spec branch-create-all"
