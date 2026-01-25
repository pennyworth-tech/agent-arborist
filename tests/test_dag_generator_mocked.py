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


# Sample valid JSON response (new two-step format)
VALID_JSON_RESPONSE = """{
  "description": "Test DAG",
  "tasks": [
    {"id": "T001", "description": "First task", "depends_on": [], "parallel_with": []},
    {"id": "T002", "description": "Second task", "depends_on": ["T001"], "parallel_with": []}
  ]
}"""

# JSON response with parallel tasks
JSON_RESPONSE_WITH_PARALLEL = """{
  "description": "Test DAG with parallel tasks",
  "tasks": [
    {"id": "T001", "description": "Setup", "depends_on": [], "parallel_with": []},
    {"id": "T002", "description": "Task A", "depends_on": ["T001"], "parallel_with": ["T003"]},
    {"id": "T003", "description": "Task B", "depends_on": ["T001"], "parallel_with": ["T002"]},
    {"id": "T004", "description": "Final", "depends_on": ["T002", "T003"], "parallel_with": []}
  ]
}"""

# JSON response wrapped in markdown code block
JSON_IN_CODE_BLOCK = """Here's the task analysis:

```json
{
  "description": "Test DAG",
  "tasks": [
    {"id": "T001", "description": "First task", "depends_on": [], "parallel_with": []}
  ]
}
```

This represents the task structure.
"""

# JSON with cyclic dependencies (unfixable)
JSON_WITH_CYCLE = """{
  "description": "Cyclic DAG",
  "tasks": [
    {"id": "T001", "description": "Task 1", "depends_on": ["T002"], "parallel_with": []},
    {"id": "T002", "description": "Task 2", "depends_on": ["T001"], "parallel_with": []}
  ]
}"""

# Invalid JSON
INVALID_JSON_RESPONSE = """not valid json {{{"""

# JSON missing tasks array
JSON_MISSING_TASKS = """{
  "description": "No tasks here"
}"""

# Empty tasks array
JSON_EMPTY_TASKS = """{
  "description": "Empty tasks",
  "tasks": []
}"""


class TestDagGeneratorWithMockRunner:
    """Tests for DagGenerator using mocked runners."""

    def test_generates_valid_multi_doc_yaml(self, tmp_path):
        """Test successful generation of multi-document YAML from JSON."""
        runner = MockRunner(VALID_JSON_RESPONSE)
        generator = DagGenerator(runner=runner)

        result = generator.generate(tmp_path, "test_dag")

        assert result.success, f"Generation failed: {result.error}"
        assert result.yaml_content is not None

        # Parse multi-document YAML
        documents = list(yaml.safe_load_all(result.yaml_content))
        assert len(documents) == 3  # root + 2 subdags

        # Check root DAG
        root = documents[0]
        assert root["name"] == "test_dag"
        assert "env" in root

        # Check subdags exist
        subdag_names = [d["name"] for d in documents[1:]]
        assert "T001" in subdag_names
        assert "T002" in subdag_names

    def test_generates_dag_with_parallel_tasks(self, tmp_path):
        """Test generation handles parallel task dependencies."""
        runner = MockRunner(JSON_RESPONSE_WITH_PARALLEL)
        generator = DagGenerator(runner=runner)

        result = generator.generate(tmp_path, "test_dag")

        assert result.success, f"Generation failed: {result.error}"
        documents = list(yaml.safe_load_all(result.yaml_content))

        # Should have root + 4 subdags
        assert len(documents) == 5

        # Check all tasks are present
        subdag_names = [d["name"] for d in documents[1:]]
        assert "T001" in subdag_names
        assert "T002" in subdag_names
        assert "T003" in subdag_names
        assert "T004" in subdag_names

    def test_extracts_json_from_code_block(self, tmp_path):
        """Test that JSON is extracted from markdown code blocks."""
        runner = MockRunner(JSON_IN_CODE_BLOCK)
        generator = DagGenerator(runner=runner)

        result = generator.generate(tmp_path, "test")

        assert result.success, f"Generation failed: {result.error}"
        documents = list(yaml.safe_load_all(result.yaml_content))
        assert documents[0]["name"] == "test"

    def test_runner_failure_returns_error(self, tmp_path):
        """Test that runner failure is properly reported."""
        runner = MockRunner("", success=False, error="Runner timeout")
        generator = DagGenerator(runner=runner)

        result = generator.generate(tmp_path, "test")

        assert not result.success
        assert "Runner timeout" in result.error

    def test_invalid_json_returns_error(self, tmp_path):
        """Test that invalid JSON is reported."""
        runner = MockRunner(INVALID_JSON_RESPONSE)
        generator = DagGenerator(runner=runner)

        result = generator.generate(tmp_path, "test")

        assert not result.success
        assert "JSON" in result.error

    def test_missing_tasks_returns_error(self, tmp_path):
        """Test that missing tasks array is reported."""
        runner = MockRunner(JSON_MISSING_TASKS)
        generator = DagGenerator(runner=runner)

        result = generator.generate(tmp_path, "test")

        assert not result.success
        assert "tasks" in result.error.lower()

    def test_empty_tasks_returns_error(self, tmp_path):
        """Test that empty tasks array is reported."""
        runner = MockRunner(JSON_EMPTY_TASKS)
        generator = DagGenerator(runner=runner)

        result = generator.generate(tmp_path, "test")

        assert not result.success
        assert "No valid tasks" in result.error or "tasks" in result.error.lower()


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

        runner = MockRunner(VALID_JSON_RESPONSE)
        generator = DagGenerator(runner=runner)

        result = generator.generate_from_file(spec_file, dag_name="test")

        assert result.success, f"Generation failed: {result.error}"
        documents = list(yaml.safe_load_all(result.yaml_content))
        assert len(documents) >= 1

    def test_generate_from_file_default_name(self, tmp_path):
        """Test that dag name is derived from filename."""
        spec_file = tmp_path / "tasks-my-feature.md"
        spec_file.write_text("# Tasks\n- T001: Do something")

        runner = MockRunner(VALID_JSON_RESPONSE)
        generator = DagGenerator(runner=runner)

        # Should use "my-feature" as dag name
        result = generator.generate_from_file(spec_file)

        assert result.success, f"Generation failed: {result.error}"


class TestGeneratorFromDirectory:
    """Tests for generate_from_directory method."""

    def test_generate_from_directory(self, tmp_path):
        """Test generating from a spec directory."""
        spec_dir = tmp_path / "spec"
        spec_dir.mkdir()
        (spec_dir / "tasks.md").write_text("# Tasks\n- T001: Do something")

        runner = MockRunner(VALID_JSON_RESPONSE)
        generator = DagGenerator(runner=runner)

        result = generator.generate_from_directory(spec_dir)

        assert result.success, f"Generation failed: {result.error}"

    def test_generate_from_directory_no_files(self, tmp_path):
        """Test error when no spec files found."""
        spec_dir = tmp_path / "empty"
        spec_dir.mkdir()

        runner = MockRunner(VALID_JSON_RESPONSE)
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
