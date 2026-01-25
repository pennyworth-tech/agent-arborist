"""Mocked tests for DAG generator that don't require actual AI inference.

These tests use mock runners to simulate AI responses, ensuring deterministic
and fast test execution while still testing the generator's parsing and
validation logic.
"""

import pytest
import yaml
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent_arborist.dag_generator import (
    DagGenerator,
    GenerationResult,
    validate_and_fix_dag,
    validate_and_fix_multi_doc,
)
from agent_arborist.runner import Runner, RunResult


class MockRunner(Runner):
    """Mock runner that returns pre-configured responses."""

    def __init__(self, response: str, success: bool = True, error: str | None = None):
        self._response = response
        self._success = success
        self._error = error

    def run(self, prompt: str, timeout: int = 60, cwd: Path | None = None) -> RunResult:
        return RunResult(
            success=self._success,
            output=self._response,
            error=self._error,
        )

    def is_available(self) -> bool:
        return True


# Sample valid multi-document YAML response
VALID_MULTI_DOC_RESPONSE = """name: test_dag
description: Test DAG
env:
  - ARBORIST_MANIFEST=test_dag.json
steps:
  - name: branches-setup
    command: arborist spec branch-create-all
  - name: c-T001
    call: T001
    depends: [branches-setup]
---
name: T001
steps:
  - name: pre-sync
    command: arborist task pre-sync T001
  - name: c-T002
    call: T002
    depends: [pre-sync]
  - name: complete
    command: |
      arborist task run-test T001 &&
      arborist task post-merge T001 &&
      arborist task post-cleanup T001
    depends: [c-T002]
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
"""

# Response with env in wrong format (dict instead of KEY=value)
RESPONSE_WITH_DICT_ENV = """name: test_dag
env:
  - ARBORIST_MANIFEST: test.json
steps:
  - name: branches-setup
    command: echo setup
---
name: T001
steps:
  - name: pre-sync
    command: echo pre-sync
"""

# Response with steps in wrong order
RESPONSE_WITH_WRONG_ORDER = """name: test_dag
env:
  - ARBORIST_MANIFEST=test.json
steps:
  - name: step3
    command: echo 3
    depends: [step2]
  - name: step1
    command: echo 1
  - name: step2
    command: echo 2
    depends: [step1]
"""

# Response with cycle (unfixable)
RESPONSE_WITH_CYCLE = """name: test_dag
steps:
  - name: step1
    command: echo 1
    depends: [step2]
  - name: step2
    command: echo 2
    depends: [step1]
"""

# Response wrapped in markdown code block
RESPONSE_IN_CODE_BLOCK = """Here's the generated DAG:

```yaml
name: test_dag
env:
  - ARBORIST_MANIFEST=test.json
steps:
  - name: branches-setup
    command: echo setup
```

This DAG includes the basic structure.
"""

# Response with empty depends arrays
RESPONSE_WITH_EMPTY_DEPENDS = """name: test_dag
steps:
  - name: step1
    command: echo 1
    depends: []
  - name: step2
    command: echo 2
    depends: [step1]
"""


class TestDagGeneratorWithMockRunner:
    """Tests for DagGenerator using mocked runners."""

    def test_generates_valid_multi_doc_yaml(self, tmp_path):
        """Test successful generation of multi-document YAML."""
        runner = MockRunner(VALID_MULTI_DOC_RESPONSE)
        generator = DagGenerator(runner=runner)

        result = generator.generate(tmp_path, "test_dag")

        assert result.success
        assert result.yaml_content is not None

        # Parse multi-document YAML
        documents = list(yaml.safe_load_all(result.yaml_content))
        assert len(documents) == 3  # root + 2 subdags

        # Check root DAG
        root = documents[0]
        assert root["name"] == "test_dag"
        assert "env" in root
        assert len(root["steps"]) == 2

        # Check subdags
        assert documents[1]["name"] == "T001"
        assert documents[2]["name"] == "T002"

    def test_fixes_dict_env_format(self, tmp_path):
        """Test that dict env format is fixed to KEY=value."""
        runner = MockRunner(RESPONSE_WITH_DICT_ENV)
        generator = DagGenerator(runner=runner)

        result = generator.generate(tmp_path, "test")

        assert result.success
        documents = list(yaml.safe_load_all(result.yaml_content))
        root = documents[0]

        # Env should be fixed to KEY=value format
        assert len(root["env"]) == 1
        assert "=" in root["env"][0]
        assert "ARBORIST_MANIFEST=" in root["env"][0]

    def test_fixes_step_order(self, tmp_path):
        """Test that steps are reordered topologically."""
        runner = MockRunner(RESPONSE_WITH_WRONG_ORDER)
        generator = DagGenerator(runner=runner)

        result = generator.generate(tmp_path, "test")

        assert result.success
        documents = list(yaml.safe_load_all(result.yaml_content))
        root = documents[0]

        step_names = [s["name"] for s in root["steps"]]
        # step1 should come before step2, step2 before step3
        assert step_names.index("step1") < step_names.index("step2")
        assert step_names.index("step2") < step_names.index("step3")

    def test_detects_cycle_error(self, tmp_path):
        """Test that cycles are detected and reported."""
        runner = MockRunner(RESPONSE_WITH_CYCLE)
        generator = DagGenerator(runner=runner)

        result = generator.generate(tmp_path, "test")

        assert not result.success
        assert "Cycle detected" in result.error

    def test_extracts_yaml_from_code_block(self, tmp_path):
        """Test that YAML is extracted from markdown code blocks."""
        runner = MockRunner(RESPONSE_IN_CODE_BLOCK)
        generator = DagGenerator(runner=runner)

        result = generator.generate(tmp_path, "test")

        assert result.success
        documents = list(yaml.safe_load_all(result.yaml_content))
        assert documents[0]["name"] == "test_dag"

    def test_removes_empty_depends(self, tmp_path):
        """Test that empty depends arrays are removed."""
        runner = MockRunner(RESPONSE_WITH_EMPTY_DEPENDS)
        generator = DagGenerator(runner=runner)

        result = generator.generate(tmp_path, "test")

        assert result.success
        documents = list(yaml.safe_load_all(result.yaml_content))
        root = documents[0]

        # step1 should not have depends key
        step1 = next(s for s in root["steps"] if s["name"] == "step1")
        assert "depends" not in step1

    def test_runner_failure_returns_error(self, tmp_path):
        """Test that runner failure is properly reported."""
        runner = MockRunner("", success=False, error="Runner timeout")
        generator = DagGenerator(runner=runner)

        result = generator.generate(tmp_path, "test")

        assert not result.success
        assert "Runner timeout" in result.error

    def test_invalid_yaml_returns_error(self, tmp_path):
        """Test that invalid YAML is reported."""
        runner = MockRunner("not: valid: yaml: [[[")
        generator = DagGenerator(runner=runner)

        result = generator.generate(tmp_path, "test")

        assert not result.success
        assert "Invalid YAML" in result.error or "YAML" in result.error

    def test_missing_steps_returns_error(self, tmp_path):
        """Test that missing steps field is reported."""
        runner = MockRunner("name: test\ndescription: no steps")
        generator = DagGenerator(runner=runner)

        result = generator.generate(tmp_path, "test")

        assert not result.success
        assert "steps" in result.error.lower()


class TestYamlExtraction:
    """Tests for YAML extraction from various AI response formats."""

    def test_extract_from_code_block(self):
        """Test extraction from ```yaml code block."""
        generator = DagGenerator(runner=MockRunner(""))

        response = """Some text
```yaml
name: test
steps: []
```
More text"""

        result = generator._extract_yaml(response)
        assert "name: test" in result

    def test_extract_from_plain_yaml(self):
        """Test extraction when response starts with name:."""
        generator = DagGenerator(runner=MockRunner(""))

        response = """name: test
steps:
  - name: step1
"""

        result = generator._extract_yaml(response)
        assert "name: test" in result

    def test_extract_from_yaml_with_preamble(self):
        """Test extraction when there's text before YAML."""
        generator = DagGenerator(runner=MockRunner(""))

        response = """Here's your DAG:

name: test
steps:
  - name: step1
"""

        result = generator._extract_yaml(response)
        assert "name: test" in result

    def test_extract_from_multi_doc_yaml(self):
        """Test extraction of multi-document YAML."""
        generator = DagGenerator(runner=MockRunner(""))

        response = """name: root
steps: []
---
name: subdag
steps: []
"""

        result = generator._extract_yaml(response)
        assert "---" in result
        assert "name: root" in result
        assert "name: subdag" in result


class TestValidationFunctions:
    """Tests for validation helper functions."""

    def test_validate_and_fix_multi_doc_all_documents(self):
        """Test that validation is applied to all documents."""
        documents = [
            {
                "name": "root",
                "env": [{"KEY": "value"}],  # Wrong format
                "steps": [
                    {"name": "step1", "depends": []},  # Empty depends
                ],
            },
            {
                "name": "subdag",
                "steps": [
                    {"name": "b", "depends": ["a"]},  # Wrong order
                    {"name": "a"},
                ],
            },
        ]

        fixed_docs, fixes = validate_and_fix_multi_doc(documents)

        # Root env should be fixed
        assert "=" in fixed_docs[0]["env"][0]

        # Root empty depends should be removed
        assert "depends" not in fixed_docs[0]["steps"][0]

        # Subdag steps should be reordered
        subdag_steps = [s["name"] for s in fixed_docs[1]["steps"]]
        assert subdag_steps.index("a") < subdag_steps.index("b")

        # Should have fixes from both documents
        assert any("[root]" in f for f in fixes)
        assert any("[subdag]" in f for f in fixes)


class TestGeneratorFromFile:
    """Tests for generate_from_file method."""

    def test_generate_from_file(self, tmp_path):
        """Test generating from a spec file."""
        spec_file = tmp_path / "tasks.md"
        spec_file.write_text("# Tasks\n- T001: Do something")

        runner = MockRunner(VALID_MULTI_DOC_RESPONSE)
        generator = DagGenerator(runner=runner)

        result = generator.generate_from_file(spec_file, dag_name="test")

        assert result.success
        documents = list(yaml.safe_load_all(result.yaml_content))
        assert len(documents) >= 1

    def test_generate_from_file_default_name(self, tmp_path):
        """Test that dag name is derived from filename."""
        spec_file = tmp_path / "tasks-my-feature.md"
        spec_file.write_text("# Tasks\n- T001: Do something")

        runner = MockRunner(VALID_MULTI_DOC_RESPONSE)
        generator = DagGenerator(runner=runner)

        # Should use "my-feature" as dag name
        result = generator.generate_from_file(spec_file)

        assert result.success


class TestGeneratorFromDirectory:
    """Tests for generate_from_directory method."""

    def test_generate_from_directory(self, tmp_path):
        """Test generating from a spec directory."""
        spec_dir = tmp_path / "spec"
        spec_dir.mkdir()
        (spec_dir / "tasks.md").write_text("# Tasks\n- T001: Do something")

        runner = MockRunner(VALID_MULTI_DOC_RESPONSE)
        generator = DagGenerator(runner=runner)

        result = generator.generate_from_directory(spec_dir)

        assert result.success

    def test_generate_from_directory_no_files(self, tmp_path):
        """Test error when no spec files found."""
        spec_dir = tmp_path / "empty"
        spec_dir.mkdir()

        runner = MockRunner(VALID_MULTI_DOC_RESPONSE)
        generator = DagGenerator(runner=runner)

        result = generator.generate_from_directory(spec_dir)

        assert not result.success
        assert "No task spec files found" in result.error


class TestBuildSimpleDag:
    """Tests for build_simple_dag function."""

    def test_build_simple_dag_linear_chain(self):
        """Test building a simple linear DAG."""
        from agent_arborist.dag_generator import build_simple_dag

        tasks = [
            {"id": "T001", "description": "First task", "parent_id": None, "children": ["T002"]},
            {"id": "T002", "description": "Second task", "parent_id": "T001", "children": []},
        ]

        yaml_content = build_simple_dag("test-spec", tasks)

        documents = list(yaml.safe_load_all(yaml_content))

        # Should have root + 2 subdags
        assert len(documents) == 3

        # Root should call T001
        root = documents[0]
        assert any(s.get("call") == "T001" for s in root["steps"])

        # T001 should be parent (call T002)
        t001 = next(d for d in documents if d["name"] == "T001")
        assert any(s.get("call") == "T002" for s in t001["steps"])

        # T002 should be leaf (6 steps, no calls)
        t002 = next(d for d in documents if d["name"] == "T002")
        assert len(t002["steps"]) == 6
        assert all(s.get("call") is None for s in t002["steps"])

    def test_build_simple_dag_parallel_children(self):
        """Test building DAG with parallel children."""
        from agent_arborist.dag_generator import build_simple_dag

        tasks = [
            {"id": "T001", "description": "Parent", "parent_id": None, "children": ["T002", "T003"]},
            {"id": "T002", "description": "Child A", "parent_id": "T001", "children": []},
            {"id": "T003", "description": "Child B", "parent_id": "T001", "children": []},
        ]

        yaml_content = build_simple_dag("test-spec", tasks)

        documents = list(yaml.safe_load_all(yaml_content))

        # T001 should call both T002 and T003
        t001 = next(d for d in documents if d["name"] == "T001")
        calls = [s.get("call") for s in t001["steps"] if s.get("call")]
        assert "T002" in calls
        assert "T003" in calls

        # Both children should depend on pre-sync (parallel)
        call_t002 = next(s for s in t001["steps"] if s.get("call") == "T002")
        call_t003 = next(s for s in t001["steps"] if s.get("call") == "T003")
        assert call_t002["depends"] == ["pre-sync"]
        assert call_t003["depends"] == ["pre-sync"]
