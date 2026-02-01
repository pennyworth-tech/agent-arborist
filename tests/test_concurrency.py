"""Tests for concurrency limiting feature."""

import json
import os
from pathlib import Path

import pytest
import yaml

from agent_arborist.config import (
    ArboristConfig,
    ConcurrencyConfig,
    ConfigValidationError,
    apply_env_overrides,
    get_config,
    merge_configs,
)
from agent_arborist.dag_builder import (
    AI_TASK_QUEUE,
    DagConfig,
    SubDagBuilder,
    SubDagStep,
)
from agent_arborist.task_spec import TaskSpec, Task, Phase
from agent_arborist.task_state import TaskTree, TaskNode


def make_spec(tasks: list[Task], dependencies: dict[str, list[str]] | None = None) -> TaskSpec:
    """Helper to create a TaskSpec from a list of tasks."""
    return TaskSpec(
        project="Test project",
        total_tasks=len(tasks),
        phases=[Phase(name="Phase 1", tasks=tasks)],
        dependencies=dependencies or {},
    )


class TestConcurrencyConfig:
    """Tests for ConcurrencyConfig dataclass."""

    def test_default_values(self):
        """Test default concurrency values."""
        config = ConcurrencyConfig()
        assert config.max_ai_tasks == 2

    def test_custom_values(self):
        """Test custom concurrency values."""
        config = ConcurrencyConfig(max_ai_tasks=10)
        assert config.max_ai_tasks == 10

    def test_validate_positive(self):
        """Test validation passes for positive values."""
        config = ConcurrencyConfig(max_ai_tasks=1)
        config.validate()  # Should not raise

    def test_validate_zero_raises(self):
        """Test validation fails for zero."""
        config = ConcurrencyConfig(max_ai_tasks=0)
        with pytest.raises(ConfigValidationError, match="must be positive"):
            config.validate()

    def test_validate_negative_raises(self):
        """Test validation fails for negative values."""
        config = ConcurrencyConfig(max_ai_tasks=-1)
        with pytest.raises(ConfigValidationError, match="must be positive"):
            config.validate()

    def test_to_dict(self):
        """Test conversion to dictionary."""
        config = ConcurrencyConfig(max_ai_tasks=3)
        d = config.to_dict()
        assert d == {"max_ai_tasks": 3}

    def test_from_dict(self):
        """Test creation from dictionary."""
        config = ConcurrencyConfig.from_dict({"max_ai_tasks": 7})
        assert config.max_ai_tasks == 7

    def test_from_dict_default(self):
        """Test creation from empty dictionary uses defaults."""
        config = ConcurrencyConfig.from_dict({})
        assert config.max_ai_tasks == 2

    def test_from_dict_strict_unknown_field(self):
        """Test strict mode rejects unknown fields."""
        with pytest.raises(ConfigValidationError, match="Unknown fields"):
            ConcurrencyConfig.from_dict({"unknown_field": 1}, strict=True)


class TestArboristConfigConcurrency:
    """Tests for concurrency in ArboristConfig."""

    def test_default_concurrency(self):
        """Test ArboristConfig has default concurrency."""
        config = ArboristConfig()
        assert config.concurrency.max_ai_tasks == 2

    def test_to_dict_includes_concurrency(self):
        """Test to_dict includes concurrency section."""
        config = ArboristConfig()
        config.concurrency.max_ai_tasks = 3
        d = config.to_dict()
        assert "concurrency" in d
        assert d["concurrency"]["max_ai_tasks"] == 3

    def test_from_dict_with_concurrency(self):
        """Test from_dict parses concurrency section."""
        data = {
            "concurrency": {"max_ai_tasks": 10}
        }
        config = ArboristConfig.from_dict(data)
        assert config.concurrency.max_ai_tasks == 10

    def test_from_dict_without_concurrency(self):
        """Test from_dict uses default when concurrency not specified."""
        config = ArboristConfig.from_dict({})
        assert config.concurrency.max_ai_tasks == 2

    def test_validate_includes_concurrency(self):
        """Test validate checks concurrency."""
        config = ArboristConfig()
        config.concurrency.max_ai_tasks = 0
        with pytest.raises(ConfigValidationError, match="must be positive"):
            config.validate()


class TestMergeConfigsConcurrency:
    """Tests for merging concurrency config."""

    def test_merge_overrides_non_default(self):
        """Test merging overrides non-default concurrency values."""
        base = ArboristConfig()
        override = ArboristConfig()
        override.concurrency.max_ai_tasks = 10

        merged = merge_configs(base, override)
        assert merged.concurrency.max_ai_tasks == 10

    def test_merge_keeps_base_if_override_is_default(self):
        """Test merging keeps base value if override is default."""
        base = ArboristConfig()
        base.concurrency.max_ai_tasks = 10
        override = ArboristConfig()  # Default is 5

        merged = merge_configs(base, override)
        # Default (5) doesn't override non-default (10)
        assert merged.concurrency.max_ai_tasks == 10


class TestEnvOverridesConcurrency:
    """Tests for environment variable overrides."""

    def test_env_override_max_ai_tasks(self, monkeypatch):
        """Test ARBORIST_MAX_AI_TASKS environment variable."""
        monkeypatch.setenv("ARBORIST_MAX_AI_TASKS", "15")

        config = ArboristConfig()
        result = apply_env_overrides(config)

        assert result.concurrency.max_ai_tasks == 15

    def test_env_override_invalid_value(self, monkeypatch):
        """Test invalid environment variable value raises error."""
        monkeypatch.setenv("ARBORIST_MAX_AI_TASKS", "not-a-number")

        config = ArboristConfig()
        with pytest.raises(ConfigValidationError, match="must be an integer"):
            apply_env_overrides(config)


class TestSubDagStepQueue:
    """Tests for SubDagStep queue field."""

    def test_queue_field_default_none(self):
        """Test queue field defaults to None."""
        step = SubDagStep(name="test")
        assert step.queue is None

    def test_queue_field_custom_value(self):
        """Test queue field can be set."""
        step = SubDagStep(name="test", queue="my-queue")
        assert step.queue == "my-queue"


class TestDagBuilderQueues:
    """Tests for queue assignment in DAG builder."""

    def _create_simple_tree(self) -> TaskTree:
        """Create a simple task tree with one leaf task."""
        tree = TaskTree(spec_id="test")
        tree.tasks["T001"] = TaskNode(
            task_id="T001",
            description="Test task"
        )
        tree.root_tasks = ["T001"]
        return tree

    def _create_parent_child_tree(self) -> TaskTree:
        """Create a task tree with parent and child."""
        tree = TaskTree(spec_id="test")
        tree.tasks["T001"] = TaskNode(
            task_id="T001",
            description="Parent task",
            children=["T002"]
        )
        tree.tasks["T002"] = TaskNode(
            task_id="T002",
            description="Child task",
            parent_id="T001"
        )
        tree.root_tasks = ["T001"]
        return tree

    def test_ai_task_queue_constant(self):
        """Test AI_TASK_QUEUE constant value."""
        assert AI_TASK_QUEUE == "arborist:ai"

    def test_leaf_run_step_has_queue(self):
        """Test run step in leaf subdag has AI queue."""
        dag_config = DagConfig(name="test")
        builder = SubDagBuilder(dag_config)
        tree = self._create_simple_tree()

        spec = make_spec([Task(id="T001", description="Test")])
        bundle = builder.build(spec, tree)

        # Find T001 subdag
        t001_subdag = next(s for s in bundle.subdags if s.name == "T001")

        # Find run step
        run_step = next(s for s in t001_subdag.steps if s.name == "run")
        assert run_step.queue == AI_TASK_QUEUE

    def test_leaf_post_merge_step_has_queue(self):
        """Test post-merge step in leaf subdag has AI queue."""
        dag_config = DagConfig(name="test")
        builder = SubDagBuilder(dag_config)
        tree = self._create_simple_tree()

        spec = make_spec([Task(id="T001", description="Test")])
        bundle = builder.build(spec, tree)

        # Find T001 subdag
        t001_subdag = next(s for s in bundle.subdags if s.name == "T001")

        # Find post-merge step
        post_merge_step = next(s for s in t001_subdag.steps if s.name == "post-merge")
        assert post_merge_step.queue == AI_TASK_QUEUE

    def test_leaf_non_ai_steps_no_queue(self):
        """Test non-AI steps don't have queue."""
        dag_config = DagConfig(name="test")
        builder = SubDagBuilder(dag_config)
        tree = self._create_simple_tree()

        spec = make_spec([Task(id="T001", description="Test")])
        bundle = builder.build(spec, tree)

        # Find T001 subdag
        t001_subdag = next(s for s in bundle.subdags if s.name == "T001")

        # Check non-AI steps
        for step_name in ["pre-sync", "commit", "run-test"]:
            step = next((s for s in t001_subdag.steps if s.name == step_name), None)
            if step:
                assert step.queue is None, f"{step_name} should not have a queue"

    def test_parent_complete_step_has_queue(self):
        """Test complete step in parent subdag has AI queue."""
        dag_config = DagConfig(name="test")
        builder = SubDagBuilder(dag_config)
        tree = self._create_parent_child_tree()

        spec = make_spec(
            [
                Task(id="T001", description="Parent"),
                Task(id="T002", description="Child")
            ],
            dependencies={"T002": ["T001"]}
        )
        bundle = builder.build(spec, tree)

        # Find T001 subdag (parent)
        t001_subdag = next(s for s in bundle.subdags if s.name == "T001")

        # Find complete step
        complete_step = next(s for s in t001_subdag.steps if s.name == "complete")
        assert complete_step.queue == AI_TASK_QUEUE

    def test_generated_yaml_includes_queue(self):
        """Test generated YAML includes queue field."""
        dag_config = DagConfig(name="test", spec_id="test")
        builder = SubDagBuilder(dag_config)
        tree = self._create_simple_tree()

        spec = make_spec([Task(id="T001", description="Test")])
        yaml_content = builder.build_yaml(spec, tree)

        # Parse YAML
        documents = list(yaml.safe_load_all(yaml_content))

        # Find T001 subdag
        t001_doc = next(d for d in documents if d.get("name") == "T001")

        # Find run step
        run_step = next(s for s in t001_doc["steps"] if s["name"] == "run")
        assert run_step["queue"] == AI_TASK_QUEUE

        # Find post-merge step
        post_merge_step = next(s for s in t001_doc["steps"] if s["name"] == "post-merge")
        assert post_merge_step["queue"] == AI_TASK_QUEUE

    def test_generated_yaml_non_ai_steps_no_queue(self):
        """Test non-AI steps don't have queue in YAML."""
        dag_config = DagConfig(name="test", spec_id="test")
        builder = SubDagBuilder(dag_config)
        tree = self._create_simple_tree()

        spec = make_spec([Task(id="T001", description="Test")])
        yaml_content = builder.build_yaml(spec, tree)

        # Parse YAML
        documents = list(yaml.safe_load_all(yaml_content))

        # Find T001 subdag
        t001_doc = next(d for d in documents if d.get("name") == "T001")

        # Check pre-sync step doesn't have queue
        pre_sync_step = next(s for s in t001_doc["steps"] if s["name"] == "pre-sync")
        assert "queue" not in pre_sync_step


class TestConfigSyncQueues:
    """Tests for config sync-queues CLI command."""

    def test_sync_queues_creates_config(self, tmp_path, monkeypatch):
        """Test sync-queues creates DAGU config file."""
        from click.testing import CliRunner

        from agent_arborist.cli import main

        # Set DAGU_HOME to temp directory
        dagu_home = tmp_path / "dagu"
        monkeypatch.setenv("DAGU_HOME", str(dagu_home))

        # Run CLI command
        runner = CliRunner()
        result = runner.invoke(main, ["config", "sync-queues"])

        assert result.exit_code == 0, result.output
        assert "Queue config synced" in result.output

        # Check config file was created
        config_path = dagu_home / "config.yaml"
        assert config_path.exists()

        # Check content
        config = yaml.safe_load(config_path.read_text())
        assert config["queues"]["enabled"] is True
        assert len(config["queues"]["config"]) == 1
        assert config["queues"]["config"][0]["name"] == AI_TASK_QUEUE
        assert config["queues"]["config"][0]["maxConcurrency"] == 2  # Default

    def test_sync_queues_uses_config_value(self, tmp_path, monkeypatch):
        """Test sync-queues uses configured max_ai_tasks."""
        from click.testing import CliRunner

        from agent_arborist.cli import main

        # Set DAGU_HOME to temp directory
        dagu_home = tmp_path / "dagu"
        monkeypatch.setenv("DAGU_HOME", str(dagu_home))

        # Set custom max_ai_tasks via env var
        monkeypatch.setenv("ARBORIST_MAX_AI_TASKS", "10")

        # Run CLI command
        runner = CliRunner()
        result = runner.invoke(main, ["config", "sync-queues"])

        assert result.exit_code == 0, result.output
        assert "max 10 concurrent" in result.output

        # Check content
        config_path = dagu_home / "config.yaml"
        config = yaml.safe_load(config_path.read_text())
        assert config["queues"]["config"][0]["maxConcurrency"] == 10

    def test_sync_queues_preserves_existing_config(self, tmp_path, monkeypatch):
        """Test sync-queues preserves other DAGU config sections."""
        from click.testing import CliRunner

        from agent_arborist.cli import main

        # Set DAGU_HOME to temp directory
        dagu_home = tmp_path / "dagu"
        dagu_home.mkdir(parents=True)
        monkeypatch.setenv("DAGU_HOME", str(dagu_home))

        # Create existing config with other settings
        existing_config = {
            "dagsDir": "/custom/dags",
            "logDir": "/custom/logs",
        }
        config_path = dagu_home / "config.yaml"
        config_path.write_text(yaml.dump(existing_config))

        # Run CLI command
        runner = CliRunner()
        result = runner.invoke(main, ["config", "sync-queues"])

        assert result.exit_code == 0, result.output

        # Check existing settings preserved
        config = yaml.safe_load(config_path.read_text())
        assert config["dagsDir"] == "/custom/dags"
        assert config["logDir"] == "/custom/logs"
        assert config["queues"]["enabled"] is True


class TestConfigFileIntegration:
    """Integration tests for config file with concurrency."""

    def test_project_config_with_concurrency(self, tmp_path):
        """Test loading project config with concurrency section."""
        # Create project config
        arborist_home = tmp_path / ".arborist"
        arborist_home.mkdir()

        config_data = {
            "concurrency": {
                "max_ai_tasks": 3
            }
        }
        config_path = arborist_home / "config.json"
        config_path.write_text(json.dumps(config_data))

        # Load config
        config = get_config(arborist_home)

        assert config.concurrency.max_ai_tasks == 3

    def test_global_config_with_concurrency(self, tmp_path, monkeypatch):
        """Test loading global config with concurrency section."""
        # Create global config
        global_config_path = tmp_path / ".arborist_config.json"
        config_data = {
            "concurrency": {
                "max_ai_tasks": 8
            }
        }
        global_config_path.write_text(json.dumps(config_data))

        # Patch home directory
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        # Load config (no arborist_home)
        config = get_config()

        assert config.concurrency.max_ai_tasks == 8
