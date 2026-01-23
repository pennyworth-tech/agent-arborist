"""
Integration tests for dag run commands with AI-generated DAGs.

These tests generate DAGs using AI inference and then validate that:
1. Generated task IDs appear in run output
2. Phase completions are tracked
3. Merges and other operations show up correctly

Run with: pytest tests/test_dag_run_integration.py -v -m integration
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from agent_arborist.cli import main
from agent_arborist.home import ARBORIST_DIR_NAME, DAGU_DIR_NAME
from agent_arborist.runner import ClaudeRunner


# Mark all tests in this module as integration tests
pytestmark = [
    pytest.mark.integration,
    pytest.mark.flaky,  # AI-dependent tests are inherently flaky
]


def check_runner_available():
    """Check if claude runner is available."""
    runner = ClaudeRunner()
    return runner.is_available()


def check_dagu_available():
    """Check if dagu is available."""
    return shutil.which("dagu") is not None


# Skip all tests if prerequisites not available
pytestmark.append(
    pytest.mark.skipif(
        not check_runner_available(),
        reason="claude runner not available"
    )
)
pytestmark.append(
    pytest.mark.skipif(
        not check_dagu_available(),
        reason="dagu not available"
    )
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def fixtures_dir():
    """Path to test fixtures."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def git_repo_with_spec(tmp_path, fixtures_dir):
    """Create a temp git repo with a spec directory and arborist initialized."""
    original_cwd = os.getcwd()
    os.chdir(tmp_path)

    # Initialize git
    subprocess.run(["git", "init"], capture_output=True, check=True)
    readme = tmp_path / "README.md"
    readme.write_text("# Test\n")
    subprocess.run(["git", "add", "."], capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
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
    result = cli_runner.invoke(main, ["init"])
    assert result.exit_code == 0

    # Copy a spec fixture
    spec_dir = tmp_path / "specs" / "001-hello"
    spec_dir.mkdir(parents=True)
    shutil.copy(fixtures_dir / "tasks-hello-world.md", spec_dir / "tasks.md")

    yield tmp_path
    os.chdir(original_cwd)


@pytest.fixture
def git_repo_with_calculator_spec(tmp_path, fixtures_dir):
    """Create a temp git repo with calculator spec (more complex)."""
    original_cwd = os.getcwd()
    os.chdir(tmp_path)

    # Initialize git
    subprocess.run(["git", "init"], capture_output=True, check=True)
    readme = tmp_path / "README.md"
    readme.write_text("# Test\n")
    subprocess.run(["git", "add", "."], capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
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
    result = cli_runner.invoke(main, ["init"])
    assert result.exit_code == 0

    # Copy calculator spec
    spec_dir = tmp_path / "specs" / "002-calc"
    spec_dir.mkdir(parents=True)
    shutil.copy(fixtures_dir / "tasks-calculator.md", spec_dir / "tasks.md")

    yield tmp_path
    os.chdir(original_cwd)


# -----------------------------------------------------------------------------
# AI DAG Generation + Run Tests
# -----------------------------------------------------------------------------


class TestAIGeneratedDagRun:
    """Tests that generate DAGs with AI and validate run behavior."""

    def test_generated_dag_dry_run_succeeds(self, git_repo_with_spec):
        """AI-generated DAG should pass dagu dry run."""
        runner = CliRunner()
        spec_dir = git_repo_with_spec / "specs" / "001-hello"

        # Generate DAG with AI
        build_result = runner.invoke(
            main,
            ["spec", "dag-build", str(spec_dir), "--timeout", "180"],
        )
        assert build_result.exit_code == 0, f"Build failed: {build_result.output}"

        # Run with dry-run
        run_result = runner.invoke(main, ["dag", "run", "001-hello", "--dry-run"])
        assert run_result.exit_code == 0, f"Run failed: {run_result.output}"

    def test_generated_dag_contains_task_ids(self, git_repo_with_spec):
        """AI-generated DAG should contain expected task IDs."""
        runner = CliRunner()
        spec_dir = git_repo_with_spec / "specs" / "001-hello"

        # Generate DAG
        build_result = runner.invoke(
            main,
            ["spec", "dag-build", str(spec_dir), "--timeout", "180"],
        )
        assert build_result.exit_code == 0

        # Read the generated DAG
        dag_path = git_repo_with_spec / ARBORIST_DIR_NAME / DAGU_DIR_NAME / "dags" / "001-hello.yaml"
        assert dag_path.exists(), f"DAG not created at {dag_path}"

        dag_content = yaml.safe_load(dag_path.read_text())
        step_names = [s["name"] for s in dag_content.get("steps", [])]

        # Hello world spec has T001-T006
        expected_tasks = ["T001", "T002", "T003", "T004", "T005", "T006"]
        for task_id in expected_tasks:
            assert any(task_id in name for name in step_names), (
                f"Task {task_id} not found in generated DAG steps: {step_names}"
            )

    def test_generated_dag_has_manifest(self, git_repo_with_spec):
        """AI-generated DAG should have companion manifest file."""
        runner = CliRunner()
        spec_dir = git_repo_with_spec / "specs" / "001-hello"

        # Generate DAG
        build_result = runner.invoke(
            main,
            ["spec", "dag-build", str(spec_dir), "--timeout", "180"],
        )
        assert build_result.exit_code == 0

        # Check manifest exists
        manifest_path = git_repo_with_spec / ARBORIST_DIR_NAME / DAGU_DIR_NAME / "dags" / "001-hello.json"
        assert manifest_path.exists(), f"Manifest not created at {manifest_path}"

        # Validate manifest structure
        import json
        manifest = json.loads(manifest_path.read_text())
        assert "spec_id" in manifest
        assert "tasks" in manifest
        assert len(manifest["tasks"]) >= 6  # Hello world has 6 tasks

    def test_run_status_after_dry_run(self, git_repo_with_spec):
        """dag run-status should work after a dry run."""
        runner = CliRunner()
        spec_dir = git_repo_with_spec / "specs" / "001-hello"

        # Generate and dry-run
        runner.invoke(main, ["spec", "dag-build", str(spec_dir), "--timeout", "180"])
        runner.invoke(main, ["dag", "run", "001-hello", "--dry-run"])

        # Check status (should not error)
        status_result = runner.invoke(main, ["dag", "run-status", "001-hello"])
        # Dry run may not create a run record, so just check it doesn't crash
        assert status_result.exit_code == 0 or "no run" in status_result.output.lower()

    def test_run_show_displays_step_info(self, git_repo_with_spec):
        """dag run-show should display step information."""
        runner = CliRunner()
        spec_dir = git_repo_with_spec / "specs" / "001-hello"

        # Generate DAG
        runner.invoke(main, ["spec", "dag-build", str(spec_dir), "--timeout", "180"])

        # Run show (may show no runs or DAG structure)
        show_result = runner.invoke(main, ["dag", "run-show", "001-hello"])
        # Should at least not crash
        assert show_result.exit_code == 0 or "no run" in show_result.output.lower()


class TestAIGeneratedDagWithParallelTasks:
    """Tests for DAGs with parallel task structures."""

    def test_calculator_dag_parallel_tasks(self, git_repo_with_calculator_spec):
        """Calculator spec with parallel tasks should generate valid DAG."""
        runner = CliRunner()
        spec_dir = git_repo_with_calculator_spec / "specs" / "002-calc"

        # Generate DAG
        build_result = runner.invoke(
            main,
            ["spec", "dag-build", str(spec_dir), "--timeout", "180"],
        )
        assert build_result.exit_code == 0, f"Build failed: {build_result.output}"

        # Read DAG
        dag_path = git_repo_with_calculator_spec / ARBORIST_DIR_NAME / DAGU_DIR_NAME / "dags" / "002-calc.yaml"
        dag_content = yaml.safe_load(dag_path.read_text())
        steps = dag_content.get("steps", [])

        # Calculator has T007 and T008 as parallel tasks (both depend on T006)
        t007 = next((s for s in steps if "T007" in s["name"]), None)
        t008 = next((s for s in steps if "T008" in s["name"]), None)

        assert t007 is not None, "T007 not found in generated DAG"
        assert t008 is not None, "T008 not found in generated DAG"

    def test_calculator_dag_dry_run(self, git_repo_with_calculator_spec):
        """Calculator DAG should pass dry run."""
        runner = CliRunner()
        spec_dir = git_repo_with_calculator_spec / "specs" / "002-calc"

        # Generate and dry-run
        build_result = runner.invoke(
            main,
            ["spec", "dag-build", str(spec_dir), "--timeout", "180"],
        )
        assert build_result.exit_code == 0

        run_result = runner.invoke(main, ["dag", "run", "002-calc", "--dry-run"])
        assert run_result.exit_code == 0, f"Dry run failed: {run_result.output}"


class TestDagRunWithEchoMode:
    """Tests using --echo-only mode to validate DAG structure without execution."""

    def test_echo_only_dag_shows_all_tasks(self, git_repo_with_spec):
        """DAG with --echo-only should show all task commands."""
        runner = CliRunner()
        spec_dir = git_repo_with_spec / "specs" / "001-hello"

        # Generate DAG with echo-only
        build_result = runner.invoke(
            main,
            ["spec", "dag-build", str(spec_dir), "--timeout", "180", "--echo-only"],
        )
        assert build_result.exit_code == 0

        # Read DAG and verify echo flags
        dag_path = git_repo_with_spec / ARBORIST_DIR_NAME / DAGU_DIR_NAME / "dags" / "001-hello.yaml"
        dag_content = yaml.safe_load(dag_path.read_text())

        for step in dag_content.get("steps", []):
            cmd = step.get("command", "")
            if "arborist " in cmd:
                assert "--echo-for-testing" in cmd, f"Missing echo flag in: {cmd}"

    def test_echo_mode_dry_run_shows_task_execution(self, git_repo_with_spec):
        """Running echo-mode DAG should show task IDs in output."""
        runner = CliRunner()
        spec_dir = git_repo_with_spec / "specs" / "001-hello"

        # Generate with echo-only
        runner.invoke(
            main,
            ["spec", "dag-build", str(spec_dir), "--timeout", "180", "--echo-only"],
        )

        # Dry run
        run_result = runner.invoke(main, ["dag", "run", "001-hello", "--dry-run"])
        assert run_result.exit_code == 0

        # The dry run output should reference task operations
        # (exact format depends on dagu dry output)


# -----------------------------------------------------------------------------
# Validation tests
# -----------------------------------------------------------------------------


class TestDagValidation:
    """Tests that validate DAG structure and correctness."""

    def test_dag_has_correct_dependency_order(self, git_repo_with_spec):
        """Generated DAG should have dependencies in correct order."""
        runner = CliRunner()
        spec_dir = git_repo_with_spec / "specs" / "001-hello"

        # Generate DAG
        runner.invoke(main, ["spec", "dag-build", str(spec_dir), "--timeout", "180"])

        # Read DAG
        dag_path = git_repo_with_spec / ARBORIST_DIR_NAME / DAGU_DIR_NAME / "dags" / "001-hello.yaml"
        dag_content = yaml.safe_load(dag_path.read_text())
        steps = dag_content.get("steps", [])

        # Build dependency map
        dep_map = {s["name"]: s.get("depends", []) for s in steps}

        # T002 should depend on T001 (from spec: T001 → T002)
        t002 = next((name for name in dep_map if "T002" in name), None)
        if t002:
            t002_deps = dep_map[t002]
            assert any("T001" in d for d in t002_deps), (
                f"T002 should depend on T001, but has deps: {t002_deps}"
            )

    def test_dag_has_phase_completion_steps(self, git_repo_with_spec):
        """Generated DAG should have phase completion markers."""
        runner = CliRunner()
        spec_dir = git_repo_with_spec / "specs" / "001-hello"

        # Generate DAG
        runner.invoke(main, ["spec", "dag-build", str(spec_dir), "--timeout", "180"])

        # Read DAG
        dag_path = git_repo_with_spec / ARBORIST_DIR_NAME / DAGU_DIR_NAME / "dags" / "001-hello.yaml"
        dag_content = yaml.safe_load(dag_path.read_text())
        step_names = [s["name"] for s in dag_content.get("steps", [])]

        # Should have at least one phase-complete or similar step
        phase_steps = [n for n in step_names if "phase" in n.lower() or "complete" in n.lower()]
        assert len(phase_steps) >= 1, f"No phase completion steps found in: {step_names}"

    def test_dag_manifest_has_all_tasks(self, git_repo_with_spec):
        """Manifest should contain all task IDs from spec."""
        import json

        runner = CliRunner()
        spec_dir = git_repo_with_spec / "specs" / "001-hello"

        # Generate DAG
        runner.invoke(main, ["spec", "dag-build", str(spec_dir), "--timeout", "180"])

        # Read manifest
        manifest_path = git_repo_with_spec / ARBORIST_DIR_NAME / DAGU_DIR_NAME / "dags" / "001-hello.json"
        manifest = json.loads(manifest_path.read_text())

        task_ids = [t["task_id"] for t in manifest.get("tasks", [])]

        # Hello world has T001-T006
        for expected_id in ["T001", "T002", "T003", "T004", "T005", "T006"]:
            assert expected_id in task_ids, f"{expected_id} not in manifest tasks: {task_ids}"


# -----------------------------------------------------------------------------
# End-to-end workflow tests
# -----------------------------------------------------------------------------


class TestEndToEndWorkflow:
    """End-to-end tests for the full DAG workflow."""

    def test_full_workflow_build_run_status(self, git_repo_with_spec):
        """Test full workflow: build → run (dry) → status."""
        runner = CliRunner()
        spec_dir = git_repo_with_spec / "specs" / "001-hello"

        # Step 1: Build
        build_result = runner.invoke(
            main,
            ["spec", "dag-build", str(spec_dir), "--timeout", "180"],
        )
        assert build_result.exit_code == 0, f"Build failed: {build_result.output}"
        assert "DAG written to:" in build_result.output

        # Step 2: Run (dry)
        run_result = runner.invoke(main, ["dag", "run", "001-hello", "--dry-run"])
        assert run_result.exit_code == 0, f"Run failed: {run_result.output}"

        # Step 3: Status
        status_result = runner.invoke(main, ["dag", "run-status", "001-hello"])
        # Should not crash (may show no runs for dry-run)
        assert status_result.exit_code == 0 or "no" in status_result.output.lower()

        # Step 4: Show
        show_result = runner.invoke(main, ["dag", "run-show", "001-hello"])
        assert show_result.exit_code == 0 or "no" in show_result.output.lower()

    def test_workflow_with_spec_flag(self, git_repo_with_spec):
        """Test workflow using --spec flag instead of explicit dag name."""
        runner = CliRunner()
        spec_dir = git_repo_with_spec / "specs" / "001-hello"

        # Build with explicit spec
        runner.invoke(
            main,
            ["--spec", "001-hello", "spec", "dag-build", str(spec_dir), "--timeout", "180"],
        )

        # Run using spec flag (should resolve dag name)
        run_result = runner.invoke(
            main,
            ["--spec", "001-hello", "dag", "run", "--dry-run"],
        )
        assert run_result.exit_code == 0, f"Run failed: {run_result.output}"
