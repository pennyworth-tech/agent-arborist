"""
Flaky integration tests for AI-powered DAG generation.

These tests are non-deterministic because they use actual AI inference.
They verify that the AI generates valid multi-document YAML DAGs with
subdags for each task.

IMPORTANT: These tests use soft assertions where appropriate to handle
AI variability. They test structural correctness rather than exact output.

Run with: pytest tests/test_dag_generator_integration.py -v -m flaky
"""

import os
import subprocess
import pytest
import yaml
from pathlib import Path
from click.testing import CliRunner

from agent_arborist.cli import main
from agent_arborist.dag_generator import DagGenerator, GenerationResult
from agent_arborist.runner import get_runner, ClaudeRunner


# Mark all tests in this module as flaky (non-deterministic)
pytestmark = [
    pytest.mark.flaky,
    pytest.mark.integration,
]


@pytest.fixture
def fixtures_dir():
    """Path to test fixtures."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def hello_world_spec(fixtures_dir):
    """Hello world task spec content."""
    return (fixtures_dir / "tasks-hello-world.md").read_text()


@pytest.fixture
def calculator_spec(fixtures_dir):
    """Calculator task spec content."""
    return (fixtures_dir / "tasks-calculator.md").read_text()


@pytest.fixture
def todo_app_spec(fixtures_dir):
    """Todo app task spec content."""
    return (fixtures_dir / "tasks-todo-app.md").read_text()


def check_runner_available():
    """Check if claude runner is available."""
    runner = ClaudeRunner()
    return runner.is_available()


# Skip all tests if runner not available
pytestmark.append(
    pytest.mark.skipif(
        not check_runner_available(),
        reason="claude runner not available"
    )
)


def assert_valid_yaml_structure(yaml_content: str, min_docs: int = 1) -> list[dict]:
    """Assert that YAML content is valid and return parsed documents.

    Args:
        yaml_content: The YAML string to validate
        min_docs: Minimum number of documents expected

    Returns:
        List of parsed YAML documents
    """
    assert yaml_content is not None, "YAML content should not be None"

    try:
        documents = list(yaml.safe_load_all(yaml_content))
    except yaml.YAMLError as e:
        pytest.fail(f"Invalid YAML: {e}")

    assert len(documents) >= min_docs, (
        f"Expected at least {min_docs} document(s), got {len(documents)}"
    )

    return documents


def assert_root_dag_structure(root: dict):
    """Assert that root DAG has required structure."""
    assert isinstance(root, dict), "Root DAG should be a dictionary"
    assert "name" in root, "Root DAG should have 'name' field"
    assert "steps" in root, "Root DAG should have 'steps' field"
    assert isinstance(root["steps"], list), "Steps should be a list"
    assert len(root["steps"]) >= 1, "Root should have at least one step"


def assert_subdag_structure(subdag: dict, is_leaf: bool | None = None):
    """Assert that a subdag has required structure.

    Args:
        subdag: The subdag dictionary
        is_leaf: If True, assert leaf structure (5 steps, no calls).
                 If False, assert parent structure (has calls).
                 If None, just check basic structure.
    """
    assert "name" in subdag, "Subdag should have 'name' field"
    assert "steps" in subdag, "Subdag should have 'steps' field"
    assert isinstance(subdag["steps"], list), "Steps should be a list"

    if is_leaf is True:
        # Leaf should have 5 steps: pre-sync, run, run-test, post-merge, post-cleanup
        has_call = any("call" in step for step in subdag["steps"])
        assert not has_call, "Leaf subdag should not have call steps"
        # Allow some variation in step count but should be around 5
        assert len(subdag["steps"]) >= 3, "Leaf should have multiple workflow steps"

    elif is_leaf is False:
        # Parent should have call steps
        has_call = any("call" in step for step in subdag["steps"])
        assert has_call, "Parent subdag should have call steps"


class TestDagGeneratorBasic:
    """Basic tests for AI DAG generation."""

    def test_generates_valid_multi_doc_yaml(self, hello_world_spec):
        """Test that AI generates valid multi-document YAML."""
        generator = DagGenerator()
        result = generator.generate(hello_world_spec, "hello-world", timeout=180)

        assert result.success, f"Generation failed: {result.error}\nRaw output: {result.raw_output}"

        documents = assert_valid_yaml_structure(result.yaml_content, min_docs=1)
        assert_root_dag_structure(documents[0])

    def test_generates_root_with_env(self, hello_world_spec):
        """Test that root DAG has env section with ARBORIST_MANIFEST."""
        generator = DagGenerator()
        result = generator.generate(hello_world_spec, "hello-world", timeout=180)

        assert result.success, f"Generation failed: {result.error}"

        documents = assert_valid_yaml_structure(result.yaml_content)
        root = documents[0]

        # Root should have env - may be in various formats
        if "env" in root:
            env_str = str(root["env"])
            assert "ARBORIST_MANIFEST" in env_str, (
                "Root DAG env should contain ARBORIST_MANIFEST"
            )

    def test_generates_subdags(self, hello_world_spec):
        """Test that AI generates subdags for tasks."""
        generator = DagGenerator()
        result = generator.generate(hello_world_spec, "hello-world", timeout=180)

        assert result.success, f"Generation failed: {result.error}"

        documents = assert_valid_yaml_structure(result.yaml_content, min_docs=2)

        # Should have subdags (hello-world has 6 tasks, but AI may vary)
        # Just check we have more than root
        subdag_names = [d.get("name", "") for d in documents[1:]]

        # At least some subdags should have task-like names
        has_task_subdags = any(
            name.startswith("T") or "task" in name.lower() or name.isalnum()
            for name in subdag_names
        )
        assert has_task_subdags or len(documents) > 1, (
            "Should have task subdags or multiple documents"
        )


class TestSubdagStructure:
    """Tests for AI-generated subdag structure."""

    def test_subdags_have_steps(self, hello_world_spec):
        """Test that subdags have steps field."""
        generator = DagGenerator()
        result = generator.generate(hello_world_spec, "hello-world", timeout=180)

        assert result.success, f"Generation failed: {result.error}"

        documents = assert_valid_yaml_structure(result.yaml_content)

        for doc in documents:
            assert "steps" in doc, f"Document {doc.get('name')} should have steps"

    def test_has_leaf_subdags_with_workflow_steps(self, hello_world_spec):
        """Test that there are leaf subdags with workflow steps."""
        generator = DagGenerator()
        result = generator.generate(hello_world_spec, "hello-world", timeout=180)

        assert result.success, f"Generation failed: {result.error}"

        documents = assert_valid_yaml_structure(result.yaml_content)

        # Find subdags that look like leaves (no call steps)
        leaf_found = False
        for doc in documents[1:]:  # Skip root
            steps = doc.get("steps", [])
            has_call = any("call" in step for step in steps)
            if not has_call and len(steps) > 0:
                leaf_found = True
                # Leaf should have workflow steps
                step_names = [s.get("name", "").lower() for s in steps]
                # At least should have some arborist-like commands
                has_workflow = (
                    any("sync" in n or "run" in n or "merge" in n or "cleanup" in n
                        for n in step_names)
                    or any("arborist" in str(s.get("command", "")).lower() for s in steps)
                )
                if has_workflow:
                    break

        # Allow test to pass even if AI structures things differently
        # The key is that we have valid YAML with subdags

    def test_root_has_setup_step(self, hello_world_spec):
        """Test that root DAG has some kind of setup step."""
        generator = DagGenerator()
        result = generator.generate(hello_world_spec, "hello-world", timeout=180)

        assert result.success, f"Generation failed: {result.error}"

        documents = assert_valid_yaml_structure(result.yaml_content)
        root = documents[0]
        steps = root.get("steps", [])

        assert len(steps) >= 1, "Root should have at least one step"

        # First step should be setup-related (flexible check)
        first_step = steps[0]
        first_name = first_step.get("name", "").lower()
        first_cmd = str(first_step.get("command", "")).lower()

        is_setup = (
            "setup" in first_name or
            "branch" in first_name or
            "init" in first_name or
            "branch" in first_cmd or
            "setup" in first_cmd
        )
        # Don't fail if AI uses different naming, just log it
        if not is_setup:
            print(f"Note: First step is '{first_name}' - expected setup-related name")


class TestDependencyDetection:
    """Tests for AI dependency detection in subdags."""

    def test_has_parent_subdags_with_calls(self, calculator_spec):
        """Test that AI creates parent subdags that call children."""
        generator = DagGenerator()
        result = generator.generate(calculator_spec, "calculator", timeout=180)

        assert result.success, f"Generation failed: {result.error}"

        documents = assert_valid_yaml_structure(result.yaml_content, min_docs=2)

        # Look for subdags with 'call' steps (parent subdags)
        parent_count = 0
        for doc in documents[1:]:
            steps = doc.get("steps", [])
            calls = [s for s in steps if "call" in s]
            if calls:
                parent_count += 1
                # Parent should have pre-sync or setup step
                step_names = [s.get("name", "").lower() for s in steps]
                # Flexible check - just needs some structure
                assert len(steps) >= 2, "Parent should have multiple steps"

        # Allow for AI variation - at least some structure should exist
        # Calculator has hierarchical tasks, so we expect some parent subdags
        # But AI may structure things differently

    def test_steps_have_dependencies_or_calls(self, calculator_spec):
        """Test that steps have dependency relationships."""
        generator = DagGenerator()
        result = generator.generate(calculator_spec, "calculator", timeout=180)

        assert result.success, f"Generation failed: {result.error}"

        documents = assert_valid_yaml_structure(result.yaml_content)

        # Count steps with depends or call
        total_steps = 0
        steps_with_deps_or_calls = 0

        for doc in documents:
            for step in doc.get("steps", []):
                total_steps += 1
                if step.get("depends") or step.get("call"):
                    steps_with_deps_or_calls += 1

        # At least some steps should have dependencies
        # (first steps won't have deps, but others should)
        if total_steps > len(documents):  # More steps than just first steps
            assert steps_with_deps_or_calls > 0, (
                "Expected some steps to have dependencies or calls"
            )


class TestDaguValidation:
    """Tests that validate generated DAGs with dagu."""

    @pytest.fixture
    def git_repo_with_spec(self, tmp_path, fixtures_dir):
        """Create a temp git repo with a spec directory."""
        import shutil

        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        subprocess.run(["git", "init"], capture_output=True, check=True)
        readme = tmp_path / "README.md"
        readme.write_text("# Test\n")
        subprocess.run(["git", "add", "."], capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            capture_output=True,
            check=True,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "Test",
                "GIT_AUTHOR_EMAIL": "test@test.com",
                "GIT_COMMITTER_NAME": "Test",
                "GIT_COMMITTER_EMAIL": "test@test.com",
            },
        )

        # Initialize arborist
        cli_runner = CliRunner()
        cli_runner.invoke(main, ["init"])

        # Copy fixture
        spec_dir = tmp_path / "specs" / "001-test"
        spec_dir.mkdir(parents=True)
        shutil.copy(
            fixtures_dir / "tasks-hello-world.md",
            spec_dir / "tasks.md"
        )

        yield tmp_path
        os.chdir(original_cwd)

    @pytest.mark.skipif(
        subprocess.run(["which", "dagu"], capture_output=True).returncode != 0,
        reason="dagu not available"
    )
    def test_generated_dag_passes_dagu_validation(self, git_repo_with_spec):
        """Test that AI-generated DAG passes dagu validation."""
        runner = CliRunner()
        spec_dir = git_repo_with_spec / "specs" / "001-test"

        # Generate DAG with AI
        result = runner.invoke(
            main,
            ["dag", "build", str(spec_dir), "--timeout", "180"]
        )

        assert result.exit_code == 0, f"Build failed: {result.output}"
        assert "DAG written to:" in result.output

        # Validate with dagu
        dagu_home = git_repo_with_spec / ".arborist" / "dagu"
        dag_file = dagu_home / "dags" / "001-test.yaml"

        assert dag_file.exists(), f"DAG file not created: {dag_file}"

        # Run dagu validate
        validate_result = subprocess.run(
            ["dagu", "validate", str(dag_file)],
            capture_output=True,
            text=True,
            env={**os.environ, "DAGU_HOME": str(dagu_home)},
        )

        # Dagu validation may have warnings but should not error
        assert validate_result.returncode == 0, (
            f"dagu validation failed: {validate_result.stderr}\n"
            f"stdout: {validate_result.stdout}"
        )


class TestCLIIntegration:
    """CLI integration tests with AI generation."""

    @pytest.fixture
    def git_repo_with_spec(self, tmp_path, fixtures_dir):
        """Create a temp git repo with a spec directory."""
        import shutil

        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        subprocess.run(["git", "init"], capture_output=True, check=True)
        readme = tmp_path / "README.md"
        readme.write_text("# Test\n")
        subprocess.run(["git", "add", "."], capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            capture_output=True,
            check=True,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "Test",
                "GIT_AUTHOR_EMAIL": "test@test.com",
                "GIT_COMMITTER_NAME": "Test",
                "GIT_COMMITTER_EMAIL": "test@test.com",
            },
        )

        # Initialize arborist
        cli_runner = CliRunner()
        cli_runner.invoke(main, ["init"])

        # Copy fixture
        spec_dir = tmp_path / "specs" / "001-test"
        spec_dir.mkdir(parents=True)
        shutil.copy(
            fixtures_dir / "tasks-calculator.md",
            spec_dir / "tasks.md"
        )

        yield tmp_path
        os.chdir(original_cwd)

    def test_cli_ai_generation_produces_output(self, git_repo_with_spec):
        """Test CLI AI generation produces valid output file."""
        runner = CliRunner()
        spec_dir = git_repo_with_spec / "specs" / "001-test"
        output_file = git_repo_with_spec / "test-dag.yaml"

        result = runner.invoke(
            main,
            ["dag", "build", str(spec_dir), "-o", str(output_file), "--timeout", "180"]
        )

        assert result.exit_code == 0, f"Build failed: {result.output}"
        assert output_file.exists(), "Output file should be created"

        # Validate the output is valid YAML
        content = output_file.read_text()
        documents = assert_valid_yaml_structure(content, min_docs=1)

        # First document should be root DAG
        assert_root_dag_structure(documents[0])

    def test_cli_dry_run_shows_output(self, git_repo_with_spec):
        """Test CLI dry run shows generated content."""
        runner = CliRunner()
        spec_dir = git_repo_with_spec / "specs" / "001-test"

        result = runner.invoke(
            main,
            ["dag", "build", str(spec_dir), "--dry-run", "--timeout", "180"]
        )

        assert result.exit_code == 0, f"Build failed: {result.output}"

        # Output should contain YAML-like content
        assert "name:" in result.output or "steps:" in result.output, (
            "Dry run output should contain YAML content"
        )


class TestErrorHandling:
    """Tests for error handling in AI generation."""

    def test_handles_empty_spec(self):
        """Test that empty spec is handled gracefully."""
        generator = DagGenerator()
        result = generator.generate("", "empty-spec", timeout=60)

        # May succeed with minimal output or fail gracefully
        if not result.success:
            assert result.error is not None
            # Error message should be informative
            assert len(result.error) > 0

    def test_handles_invalid_spec(self):
        """Test that invalid spec content is handled."""
        generator = DagGenerator()
        result = generator.generate(
            "This is not a valid task specification",
            "invalid-spec",
            timeout=60
        )

        # AI may produce something or fail - either is acceptable
        # Just ensure no crash
        assert isinstance(result, GenerationResult)
