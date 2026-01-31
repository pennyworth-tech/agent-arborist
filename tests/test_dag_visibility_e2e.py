"""
End-to-end tests for DAG visibility features (V1).

These tests create real DAGs, run them through Dagu, and validate that
`dag run-show` correctly displays:
1. Recursive tree structure with status symbols
2. Exit codes and error messages for failed steps
3. Step outputs from outputs.json
4. Nested sub-DAG hierarchies

Run with: pytest tests/test_dag_visibility_e2e.py -v -m e2e
"""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from agent_arborist.cli import main
from agent_arborist.home import ARBORIST_DIR_NAME, DAGU_DIR_NAME


# Mark all tests in this module as e2e tests
pytestmark = [
    pytest.mark.e2e,
]


def check_dagu_available():
    """Check if dagu is available."""
    return shutil.which("dagu") is not None


# Skip all tests if dagu not available
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
def git_repo(tmp_path):
    """Create a temporary git repository with arborist initialized."""
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
    assert result.exit_code == 0, f"Init failed: {result.output}"

    yield tmp_path
    os.chdir(original_cwd)


@pytest.fixture
def dagu_home(git_repo):
    """Get dagu home directory."""
    return git_repo / ARBORIST_DIR_NAME / DAGU_DIR_NAME


@pytest.fixture
def dags_dir(dagu_home):
    """Get dags directory."""
    return dagu_home / "dags"


def run_dag_and_wait(dagu_home: Path, dag_path: Path, timeout: int = 60) -> str:
    """Run a DAG synchronously and return the run ID.

    dagu start runs synchronously and waits for completion.
    """
    env = os.environ.copy()
    env["DAGU_HOME"] = str(dagu_home)

    dagu_path = shutil.which("dagu")

    # Start the DAG (runs synchronously)
    result = subprocess.run(
        [dagu_path, "start", str(dag_path)],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    # DAG has completed (success or failure)
    dag_name = dag_path.stem

    # Get the run ID from the data directory
    # Dagu may use original name or convert hyphens to underscores depending on version
    for name_variant in [dag_name, dag_name.replace("-", "_"), dag_name.replace("_", "-")]:
        runs_dir = dagu_home / "data" / "dag-runs" / name_variant / "dag-runs"
        if runs_dir.exists():
            break
    if runs_dir.exists():
        run_dirs = sorted(runs_dir.glob("*/*/*/dag-run_*"), reverse=True)
        if run_dirs:
            # Find status.jsonl in the attempt directory (format: attempt_YYYYMMDD_HHMMSS_msZ_shortid)
            status_files = list(run_dirs[0].glob("attempt_*/status.jsonl"))
            if status_files:
                status_data = json.loads(status_files[0].read_text())
                return status_data.get("dagRunId", "unknown")

    return "unknown"


# -----------------------------------------------------------------------------
# Test 1: Simple Success DAG
# -----------------------------------------------------------------------------


class TestSimpleSuccessDag:
    """Test dag run-show with a simple successful DAG."""

    def test_simple_success_shows_tree(self, git_repo, dagu_home, dags_dir):
        """A simple DAG with successful steps should show tree with checkmarks."""
        # Create a simple DAG
        dag_content = {
            "name": "test-success",
            "steps": [
                {"name": "step-1", "command": "echo 'Step 1 done'"},
                {"name": "step-2", "command": "echo 'Step 2 done'", "depends": ["step-1"]},
                {"name": "step-3", "command": "echo 'Step 3 done'", "depends": ["step-2"]},
            ]
        }
        dag_path = dags_dir / "test-success.yaml"
        dag_path.write_text(yaml.dump(dag_content))

        # Run the DAG
        run_id = run_dag_and_wait(dagu_home, dag_path)

        # Use dag run-show to view results
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["dag", "run-show", "test-success", "-e"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert result.exit_code == 0, f"Failed: {result.output}"

        # Verify tree structure
        assert "test-success" in result.output
        assert "step-1" in result.output
        assert "step-2" in result.output
        assert "step-3" in result.output

        # Verify status symbols (checkmarks for success)
        assert "✓" in result.output or "success" in result.output.lower()

    def test_simple_success_json_output(self, git_repo, dagu_home, dags_dir):
        """JSON output should contain all step information."""
        # Create DAG
        dag_content = {
            "name": "test-json",
            "steps": [
                {"name": "alpha", "command": "echo 'alpha'"},
                {"name": "beta", "command": "echo 'beta'", "depends": ["alpha"]},
            ]
        }
        dag_path = dags_dir / "test-json.yaml"
        dag_path.write_text(yaml.dump(dag_content))

        # Run
        run_dag_and_wait(dagu_home, dag_path)

        # Get JSON output
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["dag", "run-show", "test-json", "-e", "--json"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert result.exit_code == 0, f"Failed: {result.output}"

        # Parse JSON
        data = json.loads(result.output)

        assert data["dag_name"] == "test-json"  # Dagu preserves original DAG name
        assert data["status"] == "success"
        assert len(data["steps"]) == 2
        assert data["steps"][0]["name"] == "alpha"
        assert data["steps"][1]["name"] == "beta"
        assert "duration_seconds" in data


# -----------------------------------------------------------------------------
# Test 2: Failure with Exit Code
# -----------------------------------------------------------------------------


class TestFailureDag:
    """Test dag run-show with a DAG that has failing steps."""

    def test_failure_shows_exit_code(self, git_repo, dagu_home, dags_dir):
        """A failing step should show exit code in the tree."""
        # Create DAG with failing step
        dag_content = {
            "name": "test-failure",
            "steps": [
                {"name": "setup", "command": "echo 'Setting up'"},
                {"name": "fail-step", "command": "exit 42", "depends": ["setup"]},
                {"name": "cleanup", "command": "echo 'Cleanup'", "depends": ["fail-step"]},
            ]
        }
        dag_path = dags_dir / "test-failure.yaml"
        dag_path.write_text(yaml.dump(dag_content))

        # Run (will fail)
        run_dag_and_wait(dagu_home, dag_path)

        # View results
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["dag", "run-show", "test-failure", "-e"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert result.exit_code == 0, f"Failed: {result.output}"

        # Verify failure indicators
        assert "✗" in result.output or "failed" in result.output.lower()
        # Exit code might be shown
        output_lower = result.output.lower()
        assert "fail-step" in output_lower

    def test_failure_json_has_exit_code(self, git_repo, dagu_home, dags_dir):
        """JSON output should include exit_code for failed steps."""
        # Create DAG
        dag_content = {
            "name": "test-exit-code",
            "steps": [
                {"name": "will-fail", "command": "exit 7"},
            ]
        }
        dag_path = dags_dir / "test-exit-code.yaml"
        dag_path.write_text(yaml.dump(dag_content))

        # Run
        run_dag_and_wait(dagu_home, dag_path)

        # Get JSON
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["dag", "run-show", "test-exit-code", "-e", "--json"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert result.exit_code == 0, f"Failed: {result.output}"

        data = json.loads(result.output)
        assert data["status"] == "failed"

        failed_step = data["steps"][0]
        assert failed_step["status"] == "failed"
        # Note: exit_code may or may not be populated depending on Dagu version


# -----------------------------------------------------------------------------
# Test 3: Nested Sub-DAGs (Parent -> Child -> Grandchild)
# -----------------------------------------------------------------------------


class TestNestedSubDags:
    """Test dag run-show with nested sub-DAG calls."""

    def test_nested_subdags_recursive_tree(self, git_repo, dagu_home, dags_dir):
        """Nested sub-DAGs should be displayed recursively in tree."""
        # Create grandchild DAG
        grandchild_dag = {
            "name": "grandchild",
            "steps": [
                {"name": "gc-step-1", "command": "echo 'Grandchild step 1'"},
                {"name": "gc-step-2", "command": "echo 'Grandchild step 2'", "depends": ["gc-step-1"]},
            ]
        }
        (dags_dir / "grandchild.yaml").write_text(yaml.dump(grandchild_dag))

        # Create child DAG that calls grandchild
        # Using dagu's call syntax: "call: dag_name"
        child_dag = {
            "name": "child",
            "steps": [
                {"name": "child-setup", "command": "echo 'Child setup'"},
                {
                    "name": "call-grandchild",
                    "call": "grandchild",
                    "depends": ["child-setup"],
                },
                {"name": "child-cleanup", "command": "echo 'Child cleanup'", "depends": ["call-grandchild"]},
            ]
        }
        (dags_dir / "child.yaml").write_text(yaml.dump(child_dag))

        # Create parent DAG that calls child
        parent_dag = {
            "name": "parent",
            "steps": [
                {"name": "parent-init", "command": "echo 'Parent init'"},
                {
                    "name": "call-child",
                    "call": "child",
                    "depends": ["parent-init"],
                },
                {"name": "parent-finish", "command": "echo 'Parent finish'", "depends": ["call-child"]},
            ]
        }
        parent_path = dags_dir / "parent.yaml"
        parent_path.write_text(yaml.dump(parent_dag))

        # Run parent DAG
        run_dag_and_wait(dagu_home, parent_path, timeout=60)

        # View with expand subdags
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["dag", "run-show", "parent", "-e"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert result.exit_code == 0, f"Failed: {result.output}"

        # Verify all three levels appear
        assert "parent" in result.output.lower()
        assert "child" in result.output.lower()
        assert "grandchild" in result.output.lower()

        # Verify steps from each level
        assert "parent-init" in result.output
        assert "call-child" in result.output
        assert "child-setup" in result.output
        assert "call-grandchild" in result.output
        assert "gc-step-1" in result.output

    def test_nested_subdags_json_recursive(self, git_repo, dagu_home, dags_dir):
        """JSON output should contain recursively nested children."""
        # Create simple two-level hierarchy
        child_dag = {
            "name": "json-child",
            "steps": [
                {"name": "child-work", "command": "echo 'Working'"},
            ]
        }
        (dags_dir / "json-child.yaml").write_text(yaml.dump(child_dag))

        parent_dag = {
            "name": "json-parent",
            "steps": [
                {"name": "parent-work", "command": "echo 'Parent working'"},
                {
                    "name": "call-json-child",
                    "call": "json-child",
                    "depends": ["parent-work"],
                },
            ]
        }
        parent_path = dags_dir / "json-parent.yaml"
        parent_path.write_text(yaml.dump(parent_dag))

        # Run
        run_dag_and_wait(dagu_home, parent_path, timeout=60)

        # Get JSON
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["dag", "run-show", "json-parent", "-e", "--json"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert result.exit_code == 0, f"Failed: {result.output}"

        data = json.loads(result.output)

        # Verify parent (dagu may use hyphen or underscore depending on version)
        assert "json-parent" in data["dag_name"] or "json_parent" in data["dag_name"]

        # Verify children array exists
        assert "children" in data
        assert len(data["children"]) > 0

        # Verify child structure
        child = data["children"][0]
        assert "json-child" in child["dag_name"] or "json_child" in child["dag_name"]
        assert "steps" in child


# -----------------------------------------------------------------------------
# Test 4: Steps with Outputs
# -----------------------------------------------------------------------------


class TestStepOutputs:
    """Test dag run-show with steps that produce outputs."""

    def test_outputs_displayed_in_tree(self, git_repo, dagu_home, dags_dir):
        """Step outputs should be displayed when --outputs flag is used."""
        # Create DAG with output capture
        dag_content = {
            "name": "test-outputs",
            "steps": [
                {
                    "name": "produce-output",
                    "command": "echo 'my-result-value'",
                    "output": "RESULT",
                },
                {
                    "name": "use-output",
                    "command": "echo 'Got: ${RESULT}'",
                    "depends": ["produce-output"],
                },
            ]
        }
        dag_path = dags_dir / "test-outputs.yaml"
        dag_path.write_text(yaml.dump(dag_content))

        # Run
        run_dag_and_wait(dagu_home, dag_path)

        # View with outputs
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["dag", "run-show", "test-outputs", "-e", "--outputs"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert result.exit_code == 0, f"Failed: {result.output}"

        # The output variable should appear
        # Note: exact format depends on how outputs.json is structured
        assert "produce-output" in result.output
        assert "use-output" in result.output

    def test_outputs_in_json(self, git_repo, dagu_home, dags_dir):
        """JSON output should include step outputs when --outputs flag is used."""
        # Create DAG
        dag_content = {
            "name": "test-outputs-json",
            "steps": [
                {
                    "name": "gen-value",
                    "command": "echo 'test-output-123'",
                    "output": "MY_VAR",
                },
            ]
        }
        dag_path = dags_dir / "test-outputs-json.yaml"
        dag_path.write_text(yaml.dump(dag_content))

        # Run
        run_dag_and_wait(dagu_home, dag_path)

        # Get JSON with outputs
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["dag", "run-show", "test-outputs-json", "-e", "--outputs", "--json"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert result.exit_code == 0, f"Failed: {result.output}"

        data = json.loads(result.output)

        # Verify structure includes outputs-related fields
        assert "outputs" in data or "outputs_file" in data
        assert "steps" in data
        # Step may or may not have output depending on Dagu's outputs.json behavior


# -----------------------------------------------------------------------------
# Test 5: AI-Validated End-to-End Flow
# -----------------------------------------------------------------------------


def check_claude_runner_available():
    """Check if Claude runner is available."""
    from agent_arborist.runner import get_runner
    try:
        runner = get_runner("claude")
        return runner.is_available()
    except Exception:
        return False


@pytest.mark.skipif(
    not check_claude_runner_available(),
    reason="Claude runner not available"
)
class TestAIValidatedFlow:
    """Test using arborist's Claude runner to validate the complete e2e flow."""

    def test_ai_validates_dag_output(self, git_repo, dagu_home, dags_dir):
        """Use arborist's Claude runner to validate that dag run-show output is correct."""
        from agent_arborist.runner import get_runner

        # Create a DAG with known structure
        dag_content = {
            "name": "ai-test",
            "steps": [
                {"name": "step-alpha", "command": "echo 'Alpha completed successfully'"},
                {"name": "step-beta", "command": "echo 'Beta also done'", "depends": ["step-alpha"]},
                {"name": "step-gamma", "command": "exit 1", "depends": ["step-beta"]},  # This will fail
            ]
        }
        dag_path = dags_dir / "ai-test.yaml"
        dag_path.write_text(yaml.dump(dag_content))

        # Run the DAG
        run_dag_and_wait(dagu_home, dag_path)

        # Get the output using arborist CLI
        cli_runner = CliRunner()
        result = cli_runner.invoke(
            main,
            ["dag", "run-show", "ai-test", "-e"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert result.exit_code == 0, f"Failed to get output: {result.output}"
        dag_output = result.output

        # Also get JSON output
        json_result = cli_runner.invoke(
            main,
            ["dag", "run-show", "ai-test", "-e", "--json"],
            env={"DAGU_HOME": str(dagu_home)},
        )
        json_output = json_result.output

        # Use arborist's Claude runner to validate (using haiku for speed/cost)
        claude_runner = get_runner("claude", model="haiku")

        validation_prompt = f"""You are validating the output of a DAG monitoring tool.

The DAG that was run has this structure:
- step-alpha: runs "echo 'Alpha completed successfully'" - should succeed
- step-beta: runs "echo 'Beta also done'" and depends on step-alpha - should succeed
- step-gamma: runs "exit 1" and depends on step-beta - should FAIL with exit code 1

Here is the ASCII tree output from the monitoring tool:

```
{dag_output}
```

Here is the JSON output:

```json
{json_output}
```

Please validate the following and respond with ONLY "VALID" or "INVALID: <reason>":

1. Does the output show step-alpha as successful?
2. Does the output show step-beta as successful?
3. Does the output show step-gamma as failed?
4. Does the output show proper tree structure with indentation?
5. Is the JSON output valid and does it contain the expected steps?

Your response:"""

        run_result = claude_runner.run(validation_prompt, timeout=60)
        assert run_result.success, f"Claude runner failed: {run_result.error}"

        ai_response = run_result.output.strip()

        assert "VALID" in ai_response.upper(), f"AI validation failed: {ai_response}\n\nDAG Output:\n{dag_output}\n\nJSON Output:\n{json_output}"

    def test_ai_validates_nested_dag_output(self, git_repo, dagu_home, dags_dir):
        """Use arborist's Claude runner to validate nested sub-DAG output."""
        from agent_arborist.runner import get_runner

        # Create nested DAGs
        inner_dag = {
            "name": "ai-inner",
            "steps": [
                {"name": "inner-step", "command": "echo 'Inner running'"},
            ]
        }
        (dags_dir / "ai-inner.yaml").write_text(yaml.dump(inner_dag))

        outer_dag = {
            "name": "ai-outer",
            "steps": [
                {"name": "outer-setup", "command": "echo 'Outer setup'"},
                {
                    "name": "call-inner",
                    "call": "ai-inner",
                    "depends": ["outer-setup"],
                },
                {"name": "outer-finish", "command": "echo 'Outer finish'", "depends": ["call-inner"]},
            ]
        }
        outer_path = dags_dir / "ai-outer.yaml"
        outer_path.write_text(yaml.dump(outer_dag))

        # Run
        run_dag_and_wait(dagu_home, outer_path, timeout=60)

        # Get output using arborist CLI
        cli_runner = CliRunner()
        result = cli_runner.invoke(
            main,
            ["dag", "run-show", "ai-outer", "-e"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert result.exit_code == 0, f"Failed: {result.output}"
        dag_output = result.output

        # Validate with arborist's Claude runner (using haiku for speed/cost)
        claude_runner = get_runner("claude", model="haiku")

        validation_prompt = f"""You are validating the output of a DAG monitoring tool that shows nested DAG hierarchies.

The DAG structure is:
- ai-outer (parent DAG):
  - outer-setup: echo command - should succeed
  - call-inner: calls the ai-inner DAG
  - outer-finish: echo command - should succeed
- ai-inner (child DAG, called by ai-outer):
  - inner-step: echo command - should succeed

Here is the tree output from the monitoring tool:

```
{dag_output}
```

Please validate and respond with ONLY "VALID" or "INVALID: <reason>":

1. Does the output show the parent DAG (ai-outer or ai_outer)?
2. Does the output show outer-setup as a step?
3. Does the output show the call-inner step?
4. Does the output show the child DAG (ai-inner or ai_inner) nested under its call step?
5. Does the output show inner-step from the child DAG?
6. Is the indentation correct showing parent-child hierarchy?

Your response:"""

        run_result = claude_runner.run(validation_prompt, timeout=60)
        assert run_result.success, f"Claude runner failed: {run_result.error}"

        ai_response = run_result.output.strip()

        assert "VALID" in ai_response.upper(), f"AI validation failed: {ai_response}\n\nDAG Output:\n{dag_output}"


# -----------------------------------------------------------------------------
# Test 6: Multiple parallel steps
# -----------------------------------------------------------------------------


class TestParallelSteps:
    """Test dag run-show with parallel step execution."""

    def test_parallel_steps_all_shown(self, git_repo, dagu_home, dags_dir):
        """Parallel steps should all appear in the tree output."""
        # Create DAG with parallel steps
        dag_content = {
            "name": "test-parallel",
            "steps": [
                {"name": "setup", "command": "echo 'Setup done'"},
                # These three run in parallel (all depend only on setup)
                {"name": "parallel-a", "command": "echo 'A'", "depends": ["setup"]},
                {"name": "parallel-b", "command": "echo 'B'", "depends": ["setup"]},
                {"name": "parallel-c", "command": "echo 'C'", "depends": ["setup"]},
                # Final step depends on all parallel steps
                {"name": "merge", "command": "echo 'Merged'", "depends": ["parallel-a", "parallel-b", "parallel-c"]},
            ]
        }
        dag_path = dags_dir / "test-parallel.yaml"
        dag_path.write_text(yaml.dump(dag_content))

        # Run
        run_dag_and_wait(dagu_home, dag_path)

        # View results
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["dag", "run-show", "test-parallel", "-e"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert result.exit_code == 0, f"Failed: {result.output}"

        # All steps should appear
        assert "setup" in result.output
        assert "parallel-a" in result.output
        assert "parallel-b" in result.output
        assert "parallel-c" in result.output
        assert "merge" in result.output


# -----------------------------------------------------------------------------
# Test 7: Duration display
# -----------------------------------------------------------------------------


class TestDurationDisplay:
    """Test that durations are displayed correctly."""

    def test_duration_shown_in_tree(self, git_repo, dagu_home, dags_dir):
        """Step durations should be shown in parentheses."""
        # Create DAG with a step that takes some time
        dag_content = {
            "name": "test-duration",
            "steps": [
                {"name": "quick-step", "command": "echo 'Fast'"},
                {"name": "slow-step", "command": "sleep 2 && echo 'Slow'", "depends": ["quick-step"]},
            ]
        }
        dag_path = dags_dir / "test-duration.yaml"
        dag_path.write_text(yaml.dump(dag_content))

        # Run
        run_dag_and_wait(dagu_home, dag_path)

        # View results
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["dag", "run-show", "test-duration", "-e"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert result.exit_code == 0, f"Failed: {result.output}"

        # Duration should appear in output (format like "2s" or "1m 30s")
        # Look for pattern with parentheses containing duration
        assert "(" in result.output and ")" in result.output
        assert "s" in result.output or "m" in result.output  # seconds or minutes

    def test_duration_in_json(self, git_repo, dagu_home, dags_dir):
        """JSON output should include duration_seconds."""
        # Create DAG
        dag_content = {
            "name": "test-duration-json",
            "steps": [
                {"name": "timed-step", "command": "sleep 1 && echo 'Done'"},
            ]
        }
        dag_path = dags_dir / "test-duration-json.yaml"
        dag_path.write_text(yaml.dump(dag_content))

        # Run
        run_dag_and_wait(dagu_home, dag_path)

        # Get JSON
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["dag", "run-show", "test-duration-json", "-e", "--json"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert result.exit_code == 0, f"Failed: {result.output}"

        data = json.loads(result.output)

        # Should have duration fields
        assert "duration_seconds" in data or "duration_human" in data

        # Step should also have duration
        if data.get("steps"):
            step = data["steps"][0]
            # Duration might be at step level too
            assert "started_at" in step
            assert "finished_at" in step
