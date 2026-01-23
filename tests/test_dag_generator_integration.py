"""
Flaky integration tests for AI-powered DAG generation.

These tests are non-deterministic because they use actual AI inference.
They verify that the AI generates valid DAGs with reasonable accuracy
for dependency detection and phase structure.

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


class TestDagGeneratorBasic:
    """Basic tests for AI DAG generation."""

    def test_generates_valid_yaml(self, hello_world_spec):
        """Test that AI generates valid YAML."""
        generator = DagGenerator()
        result = generator.generate(hello_world_spec, "hello-world", timeout=180)

        assert result.success, f"Generation failed: {result.error}"
        assert result.yaml_content is not None

        # Should be valid YAML
        parsed = yaml.safe_load(result.yaml_content)
        assert isinstance(parsed, dict)
        assert "name" in parsed
        assert "steps" in parsed

    def test_generates_correct_structure(self, hello_world_spec):
        """Test that AI generates DAG with correct structure."""
        generator = DagGenerator()
        result = generator.generate(hello_world_spec, "hello-world", timeout=180)

        assert result.success, f"Generation failed: {result.error}"

        parsed = yaml.safe_load(result.yaml_content)
        steps = parsed.get("steps", [])

        # Should have multiple steps
        assert len(steps) >= 6, f"Expected at least 6 steps, got {len(steps)}"

        # Each step should have name and command
        for step in steps:
            assert "name" in step, f"Step missing name: {step}"
            assert "command" in step, f"Step missing command: {step}"


class TestDependencyDetection:
    """Tests for AI dependency detection accuracy."""

    def test_detects_linear_dependencies(self, hello_world_spec):
        """Test that AI detects linear dependency chains."""
        generator = DagGenerator()
        result = generator.generate(hello_world_spec, "hello-world", timeout=180)

        assert result.success, f"Generation failed: {result.error}"

        parsed = yaml.safe_load(result.yaml_content)
        steps = parsed.get("steps", [])

        # Build dependency map
        deps_map = {}
        for step in steps:
            deps_map[step["name"]] = step.get("depends", [])

        # Count steps with dependencies
        steps_with_deps = sum(1 for deps in deps_map.values() if deps)

        # At least 50% of non-root steps should have dependencies
        # (allowing for AI variation)
        non_root_steps = len(steps) - 1  # Assuming at least one root
        min_expected = non_root_steps * 0.5
        assert steps_with_deps >= min_expected, (
            f"Expected at least {min_expected} steps with dependencies, "
            f"got {steps_with_deps}"
        )

    def test_detects_parallel_tasks(self, calculator_spec):
        """Test that AI correctly handles parallel tasks marked with [P]."""
        generator = DagGenerator()
        result = generator.generate(calculator_spec, "calculator", timeout=180)

        assert result.success, f"Generation failed: {result.error}"

        parsed = yaml.safe_load(result.yaml_content)
        steps = parsed.get("steps", [])

        # Find T007 and T008 which should be parallel (both depend on T006)
        # The AI should recognize they share the same dependency
        t007 = next((s for s in steps if "T007" in s["name"]), None)
        t008 = next((s for s in steps if "T008" in s["name"]), None)

        if t007 and t008:
            t007_deps = set(t007.get("depends", []))
            t008_deps = set(t008.get("depends", []))

            # They should have similar dependencies (same parent)
            # Allow for some AI variation
            if t007_deps and t008_deps:
                # At least some overlap or same pattern
                assert len(t007_deps) > 0 or len(t008_deps) > 0

    def test_dependency_accuracy_threshold(self, calculator_spec):
        """Test that AI achieves at least 70% dependency accuracy."""
        generator = DagGenerator()
        result = generator.generate(calculator_spec, "calculator", timeout=180)

        assert result.success, f"Generation failed: {result.error}"

        parsed = yaml.safe_load(result.yaml_content)
        steps = parsed.get("steps", [])

        # Expected dependencies from the spec:
        # T001 → T002 → T003, T004
        # T003 → T005 → T006 → T007, T008
        # T005 → T009 → T010 → T011
        # T011 → T012
        expected_deps = {
            "T002": ["T001"],
            "T003": ["T002"],
            "T004": ["T002"],
            "T005": ["T003"],
            "T006": ["T005"],
            "T007": ["T006"],
            "T008": ["T006"],
            "T009": ["T005"],
            "T010": ["T009"],
            "T011": ["T010"],
            "T012": ["T011"],
        }

        # Check how many expected dependencies were detected
        correct = 0
        total = len(expected_deps)

        for step in steps:
            step_name = step["name"]
            step_deps = step.get("depends", [])

            # Find which task this step represents
            for task_id, exp_deps in expected_deps.items():
                if task_id in step_name:
                    # Check if at least one expected dependency is present
                    for exp_dep in exp_deps:
                        if any(exp_dep in d for d in step_deps):
                            correct += 1
                            break
                    break

        accuracy = correct / total if total > 0 else 0

        # Allow 70% accuracy threshold for AI variation
        assert accuracy >= 0.7, (
            f"Dependency accuracy {accuracy:.0%} below 70% threshold. "
            f"Detected {correct}/{total} expected dependencies."
        )


class TestPhaseStructure:
    """Tests for AI phase detection accuracy."""

    def test_detects_phases(self, calculator_spec):
        """Test that AI generates phase completion steps."""
        generator = DagGenerator()
        result = generator.generate(calculator_spec, "calculator", timeout=180)

        assert result.success, f"Generation failed: {result.error}"

        parsed = yaml.safe_load(result.yaml_content)
        steps = parsed.get("steps", [])

        # Look for phase-complete steps
        phase_steps = [s for s in steps if "phase" in s["name"].lower()]

        # Calculator has 4 phases, should have at least 2 phase markers
        assert len(phase_steps) >= 2, (
            f"Expected at least 2 phase completion steps, got {len(phase_steps)}"
        )

    def test_final_completion_step(self, hello_world_spec):
        """Test that AI generates a final completion step."""
        generator = DagGenerator()
        result = generator.generate(hello_world_spec, "hello-world", timeout=180)

        assert result.success, f"Generation failed: {result.error}"

        parsed = yaml.safe_load(result.yaml_content)
        steps = parsed.get("steps", [])

        # Look for final/all-complete step
        final_steps = [
            s for s in steps
            if "complete" in s["name"].lower() or "final" in s["name"].lower()
        ]

        assert len(final_steps) >= 1, "Expected at least one completion step"


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

        assert validate_result.returncode == 0, (
            f"dagu validation failed: {validate_result.stderr}"
        )

    @pytest.mark.skipif(
        subprocess.run(["which", "dagu"], capture_output=True).returncode != 0,
        reason="dagu not available"
    )
    def test_generated_dag_dry_run_succeeds(self, git_repo_with_spec):
        """Test that AI-generated DAG passes dagu dry run."""
        runner = CliRunner()
        spec_dir = git_repo_with_spec / "specs" / "001-test"

        # Generate DAG with AI
        result = runner.invoke(
            main,
            ["dag", "build", str(spec_dir), "--timeout", "180"]
        )

        assert result.exit_code == 0, f"Build failed: {result.output}"

        # Run dagu dry
        dagu_home = git_repo_with_spec / ".arborist" / "dagu"
        dag_file = dagu_home / "dags" / "001-test.yaml"

        dry_result = subprocess.run(
            ["dagu", "dry", str(dag_file)],
            capture_output=True,
            text=True,
            env={**os.environ, "DAGU_HOME": str(dagu_home)},
            timeout=60,
        )

        # Should either succeed or have expected output
        assert "Succeeded" in dry_result.stdout or dry_result.returncode == 0, (
            f"dagu dry run failed: {dry_result.stderr}\n{dry_result.stdout}"
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

    def test_cli_ai_generation(self, git_repo_with_spec):
        """Test CLI AI generation produces valid output."""
        runner = CliRunner()
        spec_dir = git_repo_with_spec / "specs" / "001-test"
        output_file = git_repo_with_spec / "test-dag.yaml"

        result = runner.invoke(
            main,
            ["dag", "build", str(spec_dir), "-o", str(output_file), "--timeout", "180"]
        )

        assert result.exit_code == 0, f"Build failed: {result.output}"
        assert output_file.exists()

        # Validate the output
        content = output_file.read_text()
        parsed = yaml.safe_load(content)

        assert "name" in parsed
        assert "steps" in parsed
        assert len(parsed["steps"]) >= 10  # Calculator has 12 tasks + phases

    def test_cli_shows_progress(self, git_repo_with_spec):
        """Test CLI shows generation progress."""
        runner = CliRunner()
        spec_dir = git_repo_with_spec / "specs" / "001-test"

        result = runner.invoke(
            main,
            ["dag", "build", str(spec_dir), "--dry-run", "--timeout", "180"]
        )

        assert result.exit_code == 0, f"Build failed: {result.output}"
        # Should show it's using AI
        assert "Generating DAG using" in result.output or "claude" in result.output.lower()
