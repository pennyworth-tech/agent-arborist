"""Tests for dag_builder module (sequential execution)."""

from unittest.mock import patch
import pytest
import yaml

from agent_arborist.container_runner import ContainerMode
from agent_arborist.dag_builder import (
    SubDagStep,
    SubDag,
    DagBundle,
    DagConfig,
    build_arborist_command,
    SequentialDagBuilder,
    build_dag_yaml,
    parse_yaml_to_bundle,
    is_task_dag,
)
from agent_arborist.task_state import TaskTree, TaskNode


class TestSubDagStep:
    """Tests for SubDagStep dataclass."""

    def test_create_command_step(self):
        """Creates a command step."""
        step = SubDagStep(
            name="run",
            command="arborist task run T001",
            depends=["setup"],
        )
        assert step.name == "run"
        assert step.command == "arborist task run T001"
        assert step.call is None
        assert step.depends == ["setup"]
        assert step.output is None

    def test_create_call_step(self):
        """Creates a call (subdag) step."""
        step = SubDagStep(
            name="c-T001",
            call="T001",
            depends=["setup"],
        )
        assert step.name == "c-T001"
        assert step.command is None
        assert step.call == "T001"
        assert step.depends == ["setup"]

    def test_create_step_with_output(self):
        """Creates a step with output configuration."""
        step = SubDagStep(
            name="run",
            command="arborist task run T001",
            output={"name": "T001_RUN_RESULT", "key": "T001_RUN_RESULT"},
        )
        assert step.output == {"name": "T001_RUN_RESULT", "key": "T001_RUN_RESULT"}

    def test_default_values(self):
        """Verifies default values."""
        step = SubDagStep(name="test")
        assert step.command is None
        assert step.call is None
        assert step.depends == []
        assert step.output is None


class TestSubDag:
    """Tests for SubDag dataclass."""

    def test_create_subdag(self):
        """Creates a subdag with steps."""
        step1 = SubDagStep(name="T002", command="arborist task run T002")
        step2 = SubDagStep(name="T003", command="arborist task run T003", depends=["T002"])

        subdag = SubDag(
            name="T001",
            steps=[step1, step2],
            description="Phase T001",
            env=["ARBORIST_TASK_ID=T001"],
        )

        assert subdag.name == "T001"
        assert len(subdag.steps) == 2
        assert subdag.description == "Phase T001"
        assert subdag.env == ["ARBORIST_TASK_ID=T001"]
        assert subdag.is_root is False

    def test_create_root_subdag(self):
        """Creates a root DAG."""
        subdag = SubDag(
            name="002-feature",
            is_root=True,
            env=["ARBORIST_SPEC_ID=002-feature"],
        )
        assert subdag.is_root is True

    def test_default_values(self):
        """Verifies default values."""
        subdag = SubDag(name="test")
        assert subdag.steps == []
        assert subdag.description == ""
        assert subdag.env == []
        assert subdag.is_root is False


class TestDagBundle:
    """Tests for DagBundle dataclass."""

    def test_create_bundle(self):
        """Creates a bundle with root and subdags."""
        root = SubDag(name="002-feature", is_root=True)
        subdags = [
            SubDag(name="T001"),
            SubDag(name="T002"),
        ]

        bundle = DagBundle(root=root, subdags=subdags)

        assert bundle.root.name == "002-feature"
        assert len(bundle.subdags) == 2
        assert bundle.subdags[0].name == "T001"


class TestDagConfig:
    """Tests for DagConfig dataclass."""

    def test_create_config(self):
        """Creates config with all fields."""
        config = DagConfig(
            name="002_feature",
            description="Feature implementation",
            spec_id="002-feature",
            container_mode=ContainerMode.ENABLED,
        )

        assert config.name == "002_feature"
        assert config.description == "Feature implementation"
        assert config.spec_id == "002-feature"
        assert config.container_mode == ContainerMode.ENABLED

    def test_default_values(self):
        """Verifies default values."""
        config = DagConfig(name="test")
        assert config.description == ""
        assert config.spec_id == ""
        assert config.container_mode == ContainerMode.AUTO
        assert config.repo_path is None
        assert config.runner is None
        assert config.model is None


class TestBuildArboristCommand:
    """Tests for build_arborist_command function."""

    def test_build_run_command(self):
        """Builds run command."""
        cmd = build_arborist_command("T001", "run")
        assert cmd == "arborist task run T001"

    def test_build_run_test_command(self):
        """Builds run-test command."""
        cmd = build_arborist_command("T002", "run-test")
        assert cmd == "arborist task run-test T002"


class TestSequentialDagBuilder:
    """Tests for SequentialDagBuilder class."""

    @pytest.fixture
    def simple_tree(self):
        """Creates a simple task tree with one leaf task."""
        tree = TaskTree(spec_id="002-feature")
        tree.tasks["T001"] = TaskNode(
            task_id="T001",
            description="First task",
            parent_id=None,
            children=[],
        )
        tree.root_tasks = ["T001"]
        return tree

    @pytest.fixture
    def tree_with_children(self):
        """Creates a task tree with parent and children."""
        tree = TaskTree(spec_id="002-feature")
        tree.tasks["T001"] = TaskNode(
            task_id="T001",
            description="Parent task",
            parent_id=None,
            children=["T002", "T003"],
        )
        tree.tasks["T002"] = TaskNode(
            task_id="T002",
            description="First child",
            parent_id="T001",
            children=[],
        )
        tree.tasks["T003"] = TaskNode(
            task_id="T003",
            description="Second child",
            parent_id="T001",
            children=[],
        )
        tree.root_tasks = ["T001"]
        return tree

    @pytest.fixture
    def builder(self):
        """Creates a builder with default config."""
        config = DagConfig(
            name="002_feature",
            spec_id="002-feature",
            container_mode=ContainerMode.DISABLED,
        )
        return SequentialDagBuilder(config)

    def test_build_from_simple_tree(self, builder, simple_tree):
        """Builds DAG from simple tree with leaf task."""
        with patch("agent_arborist.dag_builder.should_use_container", return_value=False):
            bundle = builder.build(simple_tree)

        assert bundle.root.name == "002_feature"
        assert bundle.root.is_root is True
        # Leaf task has no subdag - it's called directly from root
        assert len(bundle.subdags) == 0

    def test_build_root_dag_with_leaf_task(self, builder, simple_tree):
        """Verifies root DAG has correct steps for leaf task."""
        with patch("agent_arborist.dag_builder.should_use_container", return_value=False):
            bundle = builder.build(simple_tree)

        root = bundle.root
        step_names = [s.name for s in root.steps]

        # Sequential: setup -> T001 -> finalize
        assert "setup" in step_names
        assert "T001" in step_names
        assert "finalize" in step_names

        # Verify sequential dependencies
        t001_step = next(s for s in root.steps if s.name == "T001")
        assert "setup" in t001_step.depends

        finalize_step = next(s for s in root.steps if s.name == "finalize")
        assert "T001" in finalize_step.depends

    def test_build_root_dag_with_parent_task(self, builder, tree_with_children):
        """Verifies root DAG calls subdag for parent task."""
        with patch("agent_arborist.dag_builder.should_use_container", return_value=False):
            bundle = builder.build(tree_with_children)

        root = bundle.root
        step_names = [s.name for s in root.steps]

        # Should call T001 subdag (c- prefix)
        assert "setup" in step_names
        assert "c-T001" in step_names
        assert "finalize" in step_names

        # T001 is a parent, so it should have a subdag
        assert len(bundle.subdags) == 1
        assert bundle.subdags[0].name == "T001"

    def test_build_root_dag_env(self, builder, simple_tree):
        """Verifies root DAG has correct environment."""
        with patch("agent_arborist.dag_builder.should_use_container", return_value=False):
            bundle = builder.build(simple_tree)

        env = bundle.root.env
        assert "ARBORIST_SPEC_ID=002-feature" in env
        assert "ARBORIST_CONTAINER_MODE=${ARBORIST_CONTAINER_MODE}" in env

    def test_build_parent_subdag_sequential(self, builder, tree_with_children):
        """Verifies parent subdag executes children sequentially."""
        with patch("agent_arborist.dag_builder.should_use_container", return_value=False):
            bundle = builder.build(tree_with_children)

        # Find T001 subdag
        parent = next(s for s in bundle.subdags if s.name == "T001")
        step_names = [s.name for s in parent.steps]

        # Children run SEQUENTIALLY
        assert "T002" in step_names
        assert "T003" in step_names

        # T003 depends on T002 (sequential)
        t003_step = next(s for s in parent.steps if s.name == "T003")
        assert "T002" in t003_step.depends

    def test_build_parent_subdag_with_phase_tests(self, builder, tree_with_children):
        """Verifies parent subdag includes phase-tests step."""
        with patch("agent_arborist.dag_builder.should_use_container", return_value=False):
            bundle = builder.build(tree_with_children)

        parent = next(s for s in bundle.subdags if s.name == "T001")
        step_names = [s.name for s in parent.steps]

        # Phase tests after all children
        assert "phase-tests" in step_names

        phase_tests = next(s for s in parent.steps if s.name == "phase-tests")
        assert "T003" in phase_tests.depends  # Depends on last child

    def test_build_multiple_root_tasks_sequential(self):
        """Verifies multiple root tasks run sequentially."""
        tree = TaskTree(spec_id="002-feature")
        tree.tasks["T001"] = TaskNode(task_id="T001", description="First root", parent_id=None, children=[])
        tree.tasks["T002"] = TaskNode(task_id="T002", description="Second root", parent_id=None, children=[])
        tree.root_tasks = ["T001", "T002"]

        config = DagConfig(name="002_feature", spec_id="002-feature", container_mode=ContainerMode.DISABLED)
        builder = SequentialDagBuilder(config)

        with patch("agent_arborist.dag_builder.should_use_container", return_value=False):
            bundle = builder.build(tree)

        root = bundle.root

        # Both leaf tasks, so no subdags
        assert len(bundle.subdags) == 0

        # T001 and T002 run sequentially
        t001_step = next(s for s in root.steps if s.name == "T001")
        t002_step = next(s for s in root.steps if s.name == "T002")

        assert "setup" in t001_step.depends
        assert "T001" in t002_step.depends  # T002 depends on T001

    def test_build_yaml(self, builder, simple_tree):
        """Builds YAML from task tree."""
        with patch("agent_arborist.dag_builder.should_use_container", return_value=False):
            bundle = builder.build(simple_tree)
            yaml_content = builder._serialize_bundle(bundle)

        # Parse and verify
        docs = list(yaml.safe_load_all(yaml_content))
        assert len(docs) == 1  # Just root (leaf task has no subdag)

        # Root doc
        assert docs[0]["name"] == "002_feature"
        assert "ARBORIST_SPEC_ID=002-feature" in docs[0]["env"]

    def test_build_yaml_with_subdags(self, builder, tree_with_children):
        """Builds YAML with subdags for parent tasks."""
        with patch("agent_arborist.dag_builder.should_use_container", return_value=False):
            bundle = builder.build(tree_with_children)
            yaml_content = builder._serialize_bundle(bundle)

        # Should be multi-document YAML
        assert "---" in yaml_content

        docs = list(yaml.safe_load_all(yaml_content))
        assert len(docs) == 2  # root + T001 subdag

        assert docs[0]["name"] == "002_feature"
        assert docs[1]["name"] == "T001"


class TestBuildDagYaml:
    """Tests for build_dag_yaml function."""

    def test_build_dag_yaml(self):
        """Builds YAML via convenience function."""
        tree = TaskTree(spec_id="002-feature")
        tree.tasks["T001"] = TaskNode(task_id="T001", description="Task", parent_id=None, children=[])
        tree.root_tasks = ["T001"]

        with patch("agent_arborist.dag_builder.should_use_container", return_value=False):
            yaml_content = build_dag_yaml(
                task_tree=tree,
                dag_name="002-feature",
                description="Feature description",
            )

        docs = list(yaml.safe_load_all(yaml_content))
        assert docs[0]["name"] == "002_feature"
        assert docs[0]["description"] == "Feature description"


class TestParseYamlToBundle:
    """Tests for parse_yaml_to_bundle function."""

    def test_parse_simple_yaml(self):
        """Parses simple multi-document YAML."""
        yaml_content = """name: 002_feature
description: Test DAG
env: [ARBORIST_SPEC_ID=002-feature]
steps:
  - name: setup
    command: arborist spec setup
  - name: T001
    command: arborist task run T001
    depends: [setup]
  - name: finalize
    command: arborist spec finalize
    depends: [T001]
---
name: T001
env: [ARBORIST_TASK_ID=T001]
steps:
  - name: T002
    command: arborist task run T002
  - name: T003
    command: arborist task run T003
    depends: [T002]
"""
        bundle = parse_yaml_to_bundle(yaml_content)

        assert bundle.root.name == "002_feature"
        assert bundle.root.is_root is True
        assert len(bundle.root.steps) == 3

        assert len(bundle.subdags) == 1
        assert bundle.subdags[0].name == "T001"
        assert bundle.subdags[0].is_root is False
        assert len(bundle.subdags[0].steps) == 2

    def test_parse_step_details(self):
        """Verifies step details are parsed correctly."""
        yaml_content = """name: root
steps:
  - name: run
    command: arborist task run T001
    depends: [setup]
    output:
      name: T001_RUN_RESULT
      key: T001_RUN_RESULT
"""
        bundle = parse_yaml_to_bundle(yaml_content)

        step = bundle.root.steps[0]
        assert step.name == "run"
        assert step.command == "arborist task run T001"
        assert step.depends == ["setup"]
        assert step.output == {"name": "T001_RUN_RESULT", "key": "T001_RUN_RESULT"}

    def test_parse_empty_yaml(self):
        """Raises error for empty YAML."""
        with pytest.raises(ValueError, match="No YAML documents"):
            parse_yaml_to_bundle("")


class TestIsTaskDag:
    """Tests for is_task_dag function."""

    def test_is_task_dag_true(self):
        """Returns True for arborist DAG with ARBORIST_SPEC_ID."""
        yaml_content = """name: test
env: [ARBORIST_SPEC_ID=002-feature]
steps: []
"""
        assert is_task_dag(yaml_content) is True

    def test_is_task_dag_false(self):
        """Returns False for non-arborist DAG."""
        yaml_content = """name: test
env: [SOME_OTHER_VAR=value]
steps: []
"""
        assert is_task_dag(yaml_content) is False

    def test_is_task_dag_no_env(self):
        """Returns False when no env."""
        yaml_content = """name: test
steps: []
"""
        assert is_task_dag(yaml_content) is False

    def test_is_task_dag_invalid_yaml(self):
        """Returns False for invalid YAML."""
        assert is_task_dag("not: valid: yaml:") is False

    def test_is_task_dag_empty(self):
        """Returns False for empty content."""
        assert is_task_dag("") is False


class TestStepSerialization:
    """Tests for step/subdag serialization."""

    def test_step_to_dict_command(self):
        """Serializes command step."""
        config = DagConfig(name="test", container_mode=ContainerMode.DISABLED)
        builder = SequentialDagBuilder(config)

        step = SubDagStep(
            name="run",
            command="arborist task run T001",
            depends=["setup"],
            output={"name": "VAR", "key": "VAR"},
        )

        d = builder._step_to_dict(step)

        assert d["name"] == "run"
        assert d["command"] == "arborist task run T001"
        assert d["depends"] == ["setup"]
        assert d["output"] == {"name": "VAR", "key": "VAR"}
        assert "call" not in d

    def test_step_to_dict_call(self):
        """Serializes call step."""
        config = DagConfig(name="test", container_mode=ContainerMode.DISABLED)
        builder = SequentialDagBuilder(config)

        step = SubDagStep(
            name="c-T001",
            call="T001",
            depends=["setup"],
        )

        d = builder._step_to_dict(step)

        assert d["name"] == "c-T001"
        assert d["call"] == "T001"
        assert d["depends"] == ["setup"]
        assert "command" not in d

    def test_subdag_to_dict(self):
        """Serializes subdag."""
        config = DagConfig(name="test", container_mode=ContainerMode.DISABLED)
        builder = SequentialDagBuilder(config)

        subdag = SubDag(
            name="T001",
            description="Task T001",
            env=["VAR=value"],
            steps=[SubDagStep(name="run", command="cmd")],
        )

        d = builder._subdag_to_dict(subdag)

        assert d["name"] == "T001"
        assert d["description"] == "Task T001"
        assert d["env"] == ["VAR=value"]
        assert len(d["steps"]) == 1


class TestRoundTrip:
    """Tests for YAML round-trip (build -> parse)."""

    def test_round_trip(self):
        """Verifies YAML survives round-trip."""
        tree = TaskTree(spec_id="002-feature")
        tree.tasks["T001"] = TaskNode(task_id="T001", description="Parent", parent_id=None, children=["T002"])
        tree.tasks["T002"] = TaskNode(task_id="T002", description="Child", parent_id="T001", children=[])
        tree.root_tasks = ["T001"]

        config = DagConfig(name="002_feature", spec_id="002-feature", container_mode=ContainerMode.DISABLED)
        builder = SequentialDagBuilder(config)

        with patch("agent_arborist.dag_builder.should_use_container", return_value=False):
            bundle = builder.build(tree)
            yaml_content = builder._serialize_bundle(bundle)

        # Parse it back
        parsed = parse_yaml_to_bundle(yaml_content)

        # Verify structure matches
        assert parsed.root.name == bundle.root.name
        assert len(parsed.subdags) == len(bundle.subdags)

        for orig, parsed_subdag in zip(bundle.subdags, parsed.subdags):
            assert parsed_subdag.name == orig.name
            assert len(parsed_subdag.steps) == len(orig.steps)
