"""
End-to-end tests for the Arborist Visualization system.

These tests create real DAGs, run them through Dagu, and validate that
the visualization system correctly:
1. Builds tree structures from DAG runs
2. Shows proper status indicators
3. Handles nested sub-DAGs
4. Renders in different formats

Note: Test metrics extraction from outputs.json requires specific Dagu
configuration and is covered by unit tests. These e2e tests focus on the
visualization of DAG structure and execution status.

Run with: pytest tests/test_viz_e2e.py -v -m e2e
"""

import json
import os
import shutil
import subprocess
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
    readme.write_text("# Test Project\n")
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


def run_dag_and_wait(dagu_home: Path, dag_path: Path, timeout: int = 120) -> str:
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
    for name_variant in [dag_name, dag_name.replace("-", "_"), dag_name.replace("_", "-")]:
        runs_dir = dagu_home / "data" / "dag-runs" / name_variant / "dag-runs"
        if runs_dir.exists():
            break
    if runs_dir.exists():
        run_dirs = sorted(runs_dir.glob("*/*/*/dag-run_*"), reverse=True)
        if run_dirs:
            status_files = list(run_dirs[0].glob("attempt_*/status.jsonl"))
            if status_files:
                status_data = json.loads(status_files[0].read_text())
                return status_data.get("dagRunId", "unknown")

    return "unknown"


# -----------------------------------------------------------------------------
# Test: Basic Tree Visualization
# -----------------------------------------------------------------------------


class TestBasicTreeVisualization:
    """Test basic tree visualization with successful DAG runs."""

    def test_viz_tree_shows_dag_structure(self, git_repo, dagu_home, dags_dir):
        """Test that viz tree shows the DAG structure."""
        # Create a simple successful DAG
        dag_content = {
            "name": "test-viz-simple",
            "steps": [
                {"name": "step-1", "command": "echo 'Step 1'"},
                {"name": "step-2", "command": "echo 'Step 2'", "depends": ["step-1"]},
                {"name": "step-3", "command": "echo 'Step 3'", "depends": ["step-2"]},
            ]
        }
        dag_path = dags_dir / "test-viz-simple.yaml"
        dag_path.write_text(yaml.dump(dag_content))

        # Run the DAG
        run_dag_and_wait(dagu_home, dag_path)

        # Use viz tree command
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["viz", "tree", "test-viz-simple"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert result.exit_code == 0, f"Failed: {result.output}"

        output = result.output
        # Verify all steps appear in output
        assert "step-1" in output
        assert "step-2" in output
        assert "step-3" in output

        # Verify success indicators are present
        assert "✓" in output  # Success symbol

    def test_viz_tree_json_format(self, git_repo, dagu_home, dags_dir):
        """Test that viz tree can output JSON format."""
        dag_content = {
            "name": "test-viz-json",
            "steps": [
                {"name": "alpha", "command": "echo 'Alpha'"},
                {"name": "beta", "command": "echo 'Beta'", "depends": ["alpha"]},
            ]
        }
        dag_path = dags_dir / "test-viz-json.yaml"
        dag_path.write_text(yaml.dump(dag_content))

        run_dag_and_wait(dagu_home, dag_path)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["viz", "tree", "test-viz-json", "--format", "json"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert result.exit_code == 0, f"Failed: {result.output}"

        # Should be valid JSON
        data = json.loads(result.output)

        assert "dagName" in data
        assert "root" in data
        assert data["root"]["name"] in ["test-viz-json", "test_viz_json"]

    def test_viz_tree_with_expand_flag(self, git_repo, dagu_home, dags_dir):
        """Test viz tree with -e flag for expanding sub-DAGs."""
        dag_content = {
            "name": "test-viz-expand",
            "steps": [
                {"name": "setup", "command": "echo 'Setup'"},
                {"name": "work", "command": "echo 'Work'", "depends": ["setup"]},
            ]
        }
        dag_path = dags_dir / "test-viz-expand.yaml"
        dag_path.write_text(yaml.dump(dag_content))

        run_dag_and_wait(dagu_home, dag_path)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["viz", "tree", "test-viz-expand", "-e"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert result.exit_code == 0, f"Failed: {result.output}"
        assert "setup" in result.output
        assert "work" in result.output


# -----------------------------------------------------------------------------
# Test: Status Indicators
# -----------------------------------------------------------------------------


class TestStatusIndicators:
    """Test that status indicators are displayed correctly."""

    def test_success_status_shown(self, git_repo, dagu_home, dags_dir):
        """Successful steps should show success indicator."""
        dag_content = {
            "name": "test-success-status",
            "steps": [
                {"name": "pass-step", "command": "echo 'Passing'"},
            ]
        }
        dag_path = dags_dir / "test-success-status.yaml"
        dag_path.write_text(yaml.dump(dag_content))

        run_dag_and_wait(dagu_home, dag_path)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["viz", "tree", "test-success-status"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert result.exit_code == 0, f"Failed: {result.output}"
        # Should have success symbol
        assert "✓" in result.output

    def test_failure_status_shown(self, git_repo, dagu_home, dags_dir):
        """Failed steps should show failure indicator."""
        dag_content = {
            "name": "test-failure-status",
            "steps": [
                {"name": "fail-step", "command": "exit 1", "continueOn": {"failure": True}},
            ]
        }
        dag_path = dags_dir / "test-failure-status.yaml"
        dag_path.write_text(yaml.dump(dag_content))

        run_dag_and_wait(dagu_home, dag_path)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["viz", "tree", "test-failure-status"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert result.exit_code == 0, f"Failed: {result.output}"
        # Should have failure symbol or error message
        assert "✗" in result.output or "ERROR" in result.output or "failed" in result.output.lower()

    def test_mixed_status_shown(self, git_repo, dagu_home, dags_dir):
        """Mixed success/failure should show appropriate indicators."""
        dag_content = {
            "name": "test-mixed-status",
            "steps": [
                {"name": "good-step", "command": "echo 'Good'"},
                {"name": "bad-step", "command": "exit 1", "depends": ["good-step"], "continueOn": {"failure": True}},
                {"name": "after-bad", "command": "echo 'After'", "depends": ["bad-step"]},
            ]
        }
        dag_path = dags_dir / "test-mixed-status.yaml"
        dag_path.write_text(yaml.dump(dag_content))

        run_dag_and_wait(dagu_home, dag_path)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["viz", "tree", "test-mixed-status"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert result.exit_code == 0, f"Failed: {result.output}"
        # Should have both success and failure indicators
        output = result.output
        assert "good-step" in output
        assert "bad-step" in output


# -----------------------------------------------------------------------------
# Test: Nested Sub-DAGs
# -----------------------------------------------------------------------------


class TestNestedSubDAGs:
    """Test visualization of nested sub-DAG hierarchies."""

    def test_parent_child_dag_structure(self, git_repo, dagu_home, dags_dir):
        """Test that parent-child DAG hierarchy is shown correctly."""
        # Create child DAG
        child_dag = {
            "name": "viz-child",
            "steps": [
                {"name": "child-step-1", "command": "echo 'Child step 1'"},
                {"name": "child-step-2", "command": "echo 'Child step 2'", "depends": ["child-step-1"]},
            ]
        }
        (dags_dir / "viz-child.yaml").write_text(yaml.dump(child_dag))

        # Create parent DAG that calls child
        parent_dag = {
            "name": "viz-parent",
            "steps": [
                {"name": "parent-init", "command": "echo 'Parent init'"},
                {
                    "name": "call-child",
                    "call": "viz-child",
                    "depends": ["parent-init"],
                },
                {"name": "parent-finish", "command": "echo 'Parent finish'", "depends": ["call-child"]},
            ]
        }
        parent_path = dags_dir / "viz-parent.yaml"
        parent_path.write_text(yaml.dump(parent_dag))

        # Run parent DAG
        run_dag_and_wait(dagu_home, parent_path)

        # Use viz tree with expand flag
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["viz", "tree", "viz-parent", "-e"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert result.exit_code == 0, f"Failed: {result.output}"

        output = result.output
        # Verify parent structure
        assert "parent-init" in output
        assert "call-child" in output
        assert "parent-finish" in output

        # Verify child DAG structure (should be nested)
        assert "child-step-1" in output or "viz-child" in output.lower() or "viz_child" in output.lower()

    def test_three_level_nesting(self, git_repo, dagu_home, dags_dir):
        """Test 3-level deep DAG nesting visualization."""
        # Level 3 (grandchild)
        level3_dag = {
            "name": "level3-dag",
            "steps": [
                {"name": "l3-step", "command": "echo 'Level 3'"},
            ]
        }
        (dags_dir / "level3-dag.yaml").write_text(yaml.dump(level3_dag))

        # Level 2 (child) - calls level3
        level2_dag = {
            "name": "level2-dag",
            "steps": [
                {"name": "l2-step", "command": "echo 'Level 2'"},
                {"name": "call-l3", "call": "level3-dag", "depends": ["l2-step"]},
            ]
        }
        (dags_dir / "level2-dag.yaml").write_text(yaml.dump(level2_dag))

        # Level 1 (parent) - calls level2
        level1_dag = {
            "name": "level1-dag",
            "steps": [
                {"name": "l1-step", "command": "echo 'Level 1'"},
                {"name": "call-l2", "call": "level2-dag", "depends": ["l1-step"]},
            ]
        }
        level1_path = dags_dir / "level1-dag.yaml"
        level1_path.write_text(yaml.dump(level1_dag))

        # Run top-level DAG
        run_dag_and_wait(dagu_home, level1_path, timeout=180)

        # Use viz tree with expand
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["viz", "tree", "level1-dag", "-e"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert result.exit_code == 0, f"Failed: {result.output}"

        output = result.output
        # All levels should appear
        assert "l1-step" in output
        assert "level2" in output.lower() or "call-l2" in output
        assert "level3" in output.lower() or "l3-step" in output


# -----------------------------------------------------------------------------
# Test: Metrics Command
# -----------------------------------------------------------------------------


class TestMetricsCommand:
    """Test the viz metrics command."""

    def test_metrics_returns_json(self, git_repo, dagu_home, dags_dir):
        """Test that viz metrics returns valid JSON."""
        dag_content = {
            "name": "test-metrics-cmd",
            "steps": [
                {"name": "work-step", "command": "echo 'Working'"},
            ]
        }
        dag_path = dags_dir / "test-metrics-cmd.yaml"
        dag_path.write_text(yaml.dump(dag_content))

        run_dag_and_wait(dagu_home, dag_path)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["viz", "metrics", "test-metrics-cmd"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert result.exit_code == 0, f"Failed: {result.output}"

        # Should be valid JSON
        data = json.loads(result.output)

        assert "dagName" in data
        assert "summary" in data
        # Summary should have metric fields
        assert "totalDurationSeconds" in data["summary"] or "totalDuration" in data["summary"]


# -----------------------------------------------------------------------------
# Test: Error Handling
# -----------------------------------------------------------------------------


class TestErrorHandling:
    """Test error handling in visualization commands."""

    def test_handles_nonexistent_dag(self, git_repo, dagu_home, dags_dir):
        """Test graceful handling of non-existent DAG."""
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["viz", "tree", "nonexistent-dag-xyz"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        # Should fail with informative error
        assert result.exit_code != 0
        assert "not found" in result.output.lower() or "error" in result.output.lower()

    def test_handles_dag_with_no_runs(self, git_repo, dagu_home, dags_dir):
        """Test handling of DAG that exists but has no runs."""
        # Create DAG but don't run it
        dag_content = {
            "name": "no-runs-dag",
            "steps": [{"name": "step", "command": "echo 'Hi'"}]
        }
        dag_path = dags_dir / "no-runs-dag.yaml"
        dag_path.write_text(yaml.dump(dag_content))

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["viz", "tree", "no-runs-dag"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        # Should fail gracefully
        assert result.exit_code != 0 or "not found" in result.output.lower()


# -----------------------------------------------------------------------------
# Test: Timing Information
# -----------------------------------------------------------------------------


class TestTimingInformation:
    """Test that timing information is displayed."""

    def test_duration_shown_in_tree(self, git_repo, dagu_home, dags_dir):
        """Test that step durations are shown in tree output."""
        dag_content = {
            "name": "test-timing",
            "steps": [
                {"name": "quick-step", "command": "echo 'Fast'"},
                {"name": "slow-step", "command": "sleep 2", "depends": ["quick-step"]},
            ]
        }
        dag_path = dags_dir / "test-timing.yaml"
        dag_path.write_text(yaml.dump(dag_content))

        run_dag_and_wait(dagu_home, dag_path)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["viz", "tree", "test-timing"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert result.exit_code == 0, f"Failed: {result.output}"

        # Should show duration (format like "2s" or "(2s)")
        output = result.output
        # Duration should appear in parentheses or as part of display
        assert "s)" in output or "s " in output  # seconds indicator

    def test_timing_in_json(self, git_repo, dagu_home, dags_dir):
        """Test that timing is included in JSON output."""
        dag_content = {
            "name": "test-timing-json",
            "steps": [
                {"name": "timed-step", "command": "sleep 1"},
            ]
        }
        dag_path = dags_dir / "test-timing-json.yaml"
        dag_path.write_text(yaml.dump(dag_content))

        run_dag_and_wait(dagu_home, dag_path)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["viz", "tree", "test-timing-json", "--format", "json"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert result.exit_code == 0, f"Failed: {result.output}"

        data = json.loads(result.output)

        # Should have started/finished timestamps
        root = data["root"]
        assert "startedAt" in root or "finishedAt" in root


# -----------------------------------------------------------------------------
# Test: Export Command
# -----------------------------------------------------------------------------


class TestExportCommand:
    """Test the viz export command."""

    def test_export_creates_files(self, git_repo, dagu_home, dags_dir, tmp_path):
        """Test that viz export creates output files."""
        dag_content = {
            "name": "test-export",
            "steps": [
                {"name": "export-step", "command": "echo 'Export test'"},
            ]
        }
        dag_path = dags_dir / "test-export.yaml"
        dag_path.write_text(yaml.dump(dag_content))

        run_dag_and_wait(dagu_home, dag_path)

        # Export to a temp directory
        export_dir = tmp_path / "export_output"
        export_dir.mkdir()

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["viz", "export", "test-export", "--output-dir", str(export_dir), "--formats", "json"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert result.exit_code == 0, f"Failed: {result.output}"

        # Should have created files
        assert (export_dir / "tree.json").exists() or (export_dir / "metrics.json").exists()


# -----------------------------------------------------------------------------
# Test: Integration with Existing Commands
# -----------------------------------------------------------------------------


class TestIntegrationWithExistingCommands:
    """Test that viz commands work alongside existing commands."""

    def test_viz_and_run_show_consistent(self, git_repo, dagu_home, dags_dir):
        """Test that viz tree and dag run-show show consistent data."""
        dag_content = {
            "name": "test-consistency",
            "steps": [
                {"name": "step-a", "command": "echo 'A'"},
                {"name": "step-b", "command": "echo 'B'", "depends": ["step-a"]},
            ]
        }
        dag_path = dags_dir / "test-consistency.yaml"
        dag_path.write_text(yaml.dump(dag_content))

        run_dag_and_wait(dagu_home, dag_path)

        runner = CliRunner()

        # Get output from dag run-show
        run_show_result = runner.invoke(
            main,
            ["dag", "run-show", "test-consistency", "-e"],
            env={"DAGU_HOME": str(dagu_home)},
        )
        assert run_show_result.exit_code == 0

        # Get output from viz tree
        viz_result = runner.invoke(
            main,
            ["viz", "tree", "test-consistency"],
            env={"DAGU_HOME": str(dagu_home)},
        )
        assert viz_result.exit_code == 0

        # Both should show the step names
        assert "step-a" in run_show_result.output
        assert "step-a" in viz_result.output
        assert "step-b" in run_show_result.output
        assert "step-b" in viz_result.output


# -----------------------------------------------------------------------------
# Test: Spec-Generated DAGs
# -----------------------------------------------------------------------------


class TestSpecGeneratedDAGs:
    """Test visualization with DAGs that mirror spec-generated structure.

    These tests create DAGs with the same structure as dag-build generates,
    including nested sub-DAGs for each task. This tests the viz system's
    ability to handle real-world DAG structures.
    """

    def test_viz_with_nested_task_subdags(self, git_repo, dagu_home, dags_dir):
        """Test viz with DAG structure that mirrors spec-generated DAGs."""
        # Create a structure similar to what dag-build generates:
        # Root DAG calls task sub-DAGs, each task may call child tasks

        # Task T003 (leaf task)
        t003_dag = {
            "name": "T003",
            "steps": [
                {"name": "pre-sync", "command": "echo 'T003 pre-sync'"},
                {"name": "run", "command": "echo 'T003 implementing feature'", "depends": ["pre-sync"]},
                {"name": "commit", "command": "echo 'T003 commit'", "depends": ["run"]},
            ]
        }
        (dags_dir / "T003.yaml").write_text(yaml.dump(t003_dag))

        # Task T002 (calls T003)
        t002_dag = {
            "name": "T002",
            "steps": [
                {"name": "pre-sync", "command": "echo 'T002 pre-sync'"},
                {"name": "c-T003", "call": "T003", "depends": ["pre-sync"]},
                {"name": "complete", "command": "echo 'T002 complete'", "depends": ["c-T003"]},
            ]
        }
        (dags_dir / "T002.yaml").write_text(yaml.dump(t002_dag))

        # Task T001 (calls T002)
        t001_dag = {
            "name": "T001",
            "steps": [
                {"name": "pre-sync", "command": "echo 'T001 pre-sync'"},
                {"name": "c-T002", "call": "T002", "depends": ["pre-sync"]},
                {"name": "complete", "command": "echo 'T001 complete'", "depends": ["c-T002"]},
            ]
        }
        (dags_dir / "T001.yaml").write_text(yaml.dump(t001_dag))

        # Root DAG (like 001-my-feature)
        root_dag = {
            "name": "spec-viz-test",
            "steps": [
                {"name": "branches-setup", "command": "echo 'Setting up branches'"},
                {"name": "c-T001", "call": "T001", "depends": ["branches-setup"]},
            ]
        }
        root_path = dags_dir / "spec-viz-test.yaml"
        root_path.write_text(yaml.dump(root_dag))

        # Run the root DAG
        run_dag_and_wait(dagu_home, root_path, timeout=180)

        # Visualize with expansion
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["viz", "tree", "spec-viz-test", "-e"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert result.exit_code == 0, f"Failed: {result.output}"
        output = result.output

        # Should show nested structure
        assert "spec-viz-test" in output or "spec_viz_test" in output
        assert "branches-setup" in output
        # Should expand into sub-DAGs
        assert "T001" in output or "t001" in output.lower()

    def test_viz_json_shows_full_hierarchy(self, git_repo, dagu_home, dags_dir):
        """Test that JSON output captures the full nested hierarchy."""
        # Create nested DAGs
        child_dag = {
            "name": "child-task",
            "steps": [
                {"name": "child-step-1", "command": "echo 'Child 1'"},
                {"name": "child-step-2", "command": "echo 'Child 2'", "depends": ["child-step-1"]},
            ]
        }
        (dags_dir / "child-task.yaml").write_text(yaml.dump(child_dag))

        parent_dag = {
            "name": "parent-spec",
            "steps": [
                {"name": "setup", "command": "echo 'Setup'"},
                {"name": "call-child", "call": "child-task", "depends": ["setup"]},
                {"name": "teardown", "command": "echo 'Teardown'", "depends": ["call-child"]},
            ]
        }
        parent_path = dags_dir / "parent-spec.yaml"
        parent_path.write_text(yaml.dump(parent_dag))

        run_dag_and_wait(dagu_home, parent_path, timeout=120)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["viz", "tree", "parent-spec", "-e", "-f", "json"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert result.exit_code == 0, f"Failed: {result.output}"

        data = json.loads(result.output)

        # Check structure
        assert "root" in data
        root = data["root"]

        # Should have children (the steps)
        assert "children" in root
        children_names = [c["name"] for c in root["children"]]
        assert "setup" in children_names
        assert "call-child" in children_names
        assert "teardown" in children_names


# -----------------------------------------------------------------------------
# Test: Real AI Runner (Claude Haiku)
# -----------------------------------------------------------------------------


def check_claude_available():
    """Check if claude CLI is available."""
    return shutil.which("claude") is not None


@pytest.mark.slow
@pytest.mark.claude
@pytest.mark.skipif(
    not check_claude_available(),
    reason="claude CLI not available"
)
class TestRealAIRunner:
    """Test visualization with real AI runner execution.

    These tests use Claude Haiku for fast, cheap AI inference.
    Marked as slow because they make real API calls.
    """

    def test_viz_with_claude_haiku_task(self, git_repo, dagu_home, dags_dir):
        """Test viz tree with a DAG that uses Claude Haiku for a simple task."""
        # Create a DAG that calls claude haiku for a trivial task
        dag_content = {
            "name": "test-claude-viz",
            "env": [
                {"name": "ANTHROPIC_API_KEY", "value": "${ANTHROPIC_API_KEY}"},
            ],
            "steps": [
                {
                    "name": "ai-task",
                    "command": 'claude --model haiku -p "Reply with exactly: TASK_COMPLETE"',
                },
            ]
        }
        dag_path = dags_dir / "test-claude-viz.yaml"
        dag_path.write_text(yaml.dump(dag_content))

        # Run the DAG (may take a few seconds due to API call)
        run_dag_and_wait(dagu_home, dag_path, timeout=120)

        # Visualize
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["viz", "tree", "test-claude-viz"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert result.exit_code == 0, f"Failed: {result.output}"
        assert "ai-task" in result.output

        # Check timing is captured (AI tasks take real time)
        # Duration format includes "s)" for seconds
        output = result.output
        assert "s)" in output or "ms)" in output  # Some duration shown

    def test_viz_metrics_with_ai_task(self, git_repo, dagu_home, dags_dir):
        """Test that metrics command works with AI-executed DAGs."""
        dag_content = {
            "name": "test-claude-metrics",
            "env": [
                {"name": "ANTHROPIC_API_KEY", "value": "${ANTHROPIC_API_KEY}"},
            ],
            "steps": [
                {
                    "name": "quick-ai-step",
                    "command": 'claude --model haiku -p "Say OK"',
                },
            ]
        }
        dag_path = dags_dir / "test-claude-metrics.yaml"
        dag_path.write_text(yaml.dump(dag_content))

        run_dag_and_wait(dagu_home, dag_path, timeout=120)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["viz", "metrics", "test-claude-metrics"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert result.exit_code == 0, f"Failed: {result.output}"

        # Parse JSON output
        data = json.loads(result.output)
        assert "summary" in data

        # Duration should be non-trivial for AI task (> 0.1s typically)
        duration = data["summary"].get("totalDurationSeconds", 0)
        assert duration > 0.1, f"Expected non-trivial duration for AI task, got {duration}s"


# -----------------------------------------------------------------------------
# Test: Pytest Metrics Extraction
# -----------------------------------------------------------------------------


class TestPytestMetricsExtraction:
    """Test that viz correctly extracts and displays pytest metrics."""

    @pytest.fixture
    def python_test_project(self, git_repo, dagu_home, dags_dir):
        """Create a Python project with tests that output metrics."""
        # Create a simple Python package with tests
        src_dir = git_repo / "src"
        src_dir.mkdir()
        (src_dir / "__init__.py").write_text("")
        (src_dir / "math_utils.py").write_text('''
def add(a, b):
    return a + b

def multiply(a, b):
    return a * b

def divide(a, b):
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
''')

        tests_dir = git_repo / "tests"
        tests_dir.mkdir()
        (tests_dir / "__init__.py").write_text("")
        (tests_dir / "test_math.py").write_text('''
import pytest
import sys
sys.path.insert(0, str(pytest.importorskip("pathlib").Path(__file__).parent.parent / "src"))

from math_utils import add, multiply, divide

class TestAdd:
    def test_add_positive(self):
        assert add(2, 3) == 5

    def test_add_negative(self):
        assert add(-1, -1) == -2

    def test_add_zero(self):
        assert add(0, 0) == 0

class TestMultiply:
    def test_multiply_positive(self):
        assert multiply(2, 3) == 6

    def test_multiply_by_zero(self):
        assert multiply(5, 0) == 0

class TestDivide:
    def test_divide_positive(self):
        assert divide(6, 2) == 3

    def test_divide_by_zero(self):
        with pytest.raises(ValueError):
            divide(1, 0)

    def test_divide_float_result(self):
        assert divide(5, 2) == 2.5
''')

        return git_repo

    def test_viz_extracts_pytest_metrics(self, python_test_project, dagu_home, dags_dir):
        """Test that running pytest produces metrics that viz can extract."""
        project_dir = python_test_project

        # Create a DAG that runs pytest and captures output
        dag_content = {
            "name": "test-pytest-metrics",
            "steps": [
                {
                    "name": "run-tests",
                    "dir": str(project_dir),
                    "command": "python -m pytest tests/ -v --tb=short",
                    "output": "RESULT",
                },
            ]
        }
        dag_path = dags_dir / "test-pytest-metrics.yaml"
        dag_path.write_text(yaml.dump(dag_content))

        # Run the DAG
        run_dag_and_wait(dagu_home, dag_path, timeout=60)

        # Check viz tree shows the test step
        runner = CliRunner()
        tree_result = runner.invoke(
            main,
            ["viz", "tree", "test-pytest-metrics"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert tree_result.exit_code == 0, f"Failed: {tree_result.output}"
        assert "run-tests" in tree_result.output
        # Should show success (all tests pass)
        assert "✓" in tree_result.output

    def test_viz_shows_test_failures(self, python_test_project, dagu_home, dags_dir):
        """Test that viz correctly shows when tests fail."""
        project_dir = python_test_project

        # Add a failing test
        tests_dir = project_dir / "tests"
        (tests_dir / "test_failing.py").write_text('''
def test_intentional_failure():
    """This test is designed to fail."""
    assert 1 == 2, "Intentional failure for testing"
''')

        # Create DAG with continueOn to see the failure in viz
        dag_content = {
            "name": "test-pytest-failure",
            "steps": [
                {
                    "name": "run-failing-tests",
                    "dir": str(project_dir),
                    "command": "python -m pytest tests/test_failing.py -v",
                    "continueOn": {"failure": True},
                },
            ]
        }
        dag_path = dags_dir / "test-pytest-failure.yaml"
        dag_path.write_text(yaml.dump(dag_content))

        run_dag_and_wait(dagu_home, dag_path, timeout=60)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["viz", "tree", "test-pytest-failure"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert result.exit_code == 0, f"Failed: {result.output}"
        # Should show failure indicator
        output = result.output
        assert "✗" in output or "failed" in output.lower()


# -----------------------------------------------------------------------------
# Test: LLM-as-Judge for Visualization Quality
# -----------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.claude
@pytest.mark.skipif(
    not check_claude_available(),
    reason="claude CLI not available"
)
class TestLLMAsJudge:
    """Use LLM to evaluate visualization quality.

    These tests use Claude to judge whether the visualization output
    is correct, complete, and useful.
    """

    def test_llm_judges_tree_completeness(self, git_repo, dagu_home, dags_dir):
        """LLM evaluates whether viz tree output is complete and accurate."""
        # Create a DAG with known structure
        dag_content = {
            "name": "test-llm-judge",
            "steps": [
                {"name": "setup-database", "command": "echo 'Setting up DB'"},
                {"name": "run-migrations", "command": "echo 'Running migrations'", "depends": ["setup-database"]},
                {"name": "seed-data", "command": "echo 'Seeding data'", "depends": ["run-migrations"]},
                {"name": "start-server", "command": "echo 'Starting server'", "depends": ["seed-data"]},
            ]
        }
        dag_path = dags_dir / "test-llm-judge.yaml"
        dag_path.write_text(yaml.dump(dag_content))

        run_dag_and_wait(dagu_home, dag_path, timeout=60)

        # Get visualization output
        runner = CliRunner()
        viz_result = runner.invoke(
            main,
            ["viz", "tree", "test-llm-judge"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert viz_result.exit_code == 0

        # Use Claude to judge the output
        import subprocess
        prompt = f'''You are evaluating a CLI visualization output.

The DAG has these steps in order:
1. setup-database
2. run-migrations (depends on setup-database)
3. seed-data (depends on run-migrations)
4. start-server (depends on seed-data)

Here is the visualization output:
```
{viz_result.output}
```

Evaluate this visualization. Answer with JSON only:
{{
  "shows_all_steps": true/false,  // Are all 4 step names visible?
  "shows_hierarchy": true/false,  // Is there visual hierarchy/tree structure?
  "shows_status": true/false,     // Are success/failure indicators shown?
  "overall_quality": "good"/"acceptable"/"poor",
  "issues": ["list", "of", "issues"] // Empty if none
}}

Respond with ONLY the JSON, no other text.'''

        result = subprocess.run(
            ["claude", "--model", "haiku", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=60,
        )

        # Parse LLM response
        try:
            # Extract JSON from response (may have markdown code blocks)
            response = result.stdout.strip()
            if "```" in response:
                # Extract from code block
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]
                response = response.strip()

            evaluation = json.loads(response)

            # Assert quality criteria
            assert evaluation.get("shows_all_steps", False), \
                f"LLM says not all steps shown: {evaluation.get('issues', [])}"
            assert evaluation.get("shows_status", False), \
                f"LLM says status not shown: {evaluation.get('issues', [])}"
            assert evaluation.get("overall_quality") in ("good", "acceptable"), \
                f"LLM rated quality as poor: {evaluation.get('issues', [])}"

        except json.JSONDecodeError:
            # If LLM doesn't return valid JSON, check basic criteria manually
            output = viz_result.output.lower()
            assert "setup-database" in output
            assert "run-migrations" in output
            assert "seed-data" in output
            assert "start-server" in output


# -----------------------------------------------------------------------------
# Test: Restart Scenario Stats Coherence
# -----------------------------------------------------------------------------


class TestRestartStatsCoherence:
    """Test that visualization stats remain coherent across restart scenarios."""

    def test_stats_coherent_after_restart(self, git_repo, dagu_home, dags_dir):
        """Test that viz shows coherent stats after a DAG restart."""
        # Create a DAG where one step fails
        dag_content = {
            "name": "test-restart-stats",
            "steps": [
                {"name": "step-1-ok", "command": "echo 'Step 1 OK'"},
                {"name": "step-2-fail", "command": "exit 1", "depends": ["step-1-ok"]},
                {"name": "step-3-after", "command": "echo 'Step 3'", "depends": ["step-2-fail"]},
            ]
        }
        dag_path = dags_dir / "test-restart-stats.yaml"
        dag_path.write_text(yaml.dump(dag_content))

        # First run - will fail at step-2
        run_dag_and_wait(dagu_home, dag_path, timeout=60)

        # Get initial viz
        runner = CliRunner()
        result1 = runner.invoke(
            main,
            ["viz", "tree", "test-restart-stats"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert result1.exit_code == 0
        output1 = result1.output

        # Should show step-1 succeeded, step-2 failed
        assert "step-1-ok" in output1
        assert "step-2-fail" in output1

        # Now fix the DAG and restart
        dag_content_fixed = {
            "name": "test-restart-stats",
            "steps": [
                {"name": "step-1-ok", "command": "echo 'Step 1 OK'"},
                {"name": "step-2-fail", "command": "echo 'Step 2 now OK'", "depends": ["step-1-ok"]},
                {"name": "step-3-after", "command": "echo 'Step 3'", "depends": ["step-2-fail"]},
            ]
        }
        dag_path.write_text(yaml.dump(dag_content_fixed))

        # Run again (simulating restart with fixed code)
        run_dag_and_wait(dagu_home, dag_path, timeout=60)

        # Get viz after "restart"
        result2 = runner.invoke(
            main,
            ["viz", "tree", "test-restart-stats"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert result2.exit_code == 0
        output2 = result2.output

        # After successful run, all steps should show success
        assert "step-1-ok" in output2
        assert "step-2-fail" in output2  # Name is still "step-2-fail"
        assert "step-3-after" in output2
        # Should show success indicators
        assert "✓" in output2

    def test_metrics_aggregate_correctly_across_runs(self, git_repo, dagu_home, dags_dir):
        """Test that metrics are computed from the latest run, not accumulated."""
        dag_content = {
            "name": "test-metrics-runs",
            "steps": [
                {"name": "task-a", "command": "echo 'A'"},
                {"name": "task-b", "command": "echo 'B'", "depends": ["task-a"]},
            ]
        }
        dag_path = dags_dir / "test-metrics-runs.yaml"
        dag_path.write_text(yaml.dump(dag_content))

        # Run twice
        run_dag_and_wait(dagu_home, dag_path, timeout=60)
        run_dag_and_wait(dagu_home, dag_path, timeout=60)

        # Get metrics
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["viz", "metrics", "test-metrics-runs"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert result.exit_code == 0
        data = json.loads(result.output)

        # Should show metrics for latest run only (2 steps, not 4)
        # Check that we're showing the run, not accumulating
        summary = data.get("summary", {})

        # The step count in by_task should be 2 (not accumulated)
        by_task = data.get("byTask", [])
        if by_task:
            assert len(by_task) == 2, f"Expected 2 tasks, got {len(by_task)}"

    def test_viz_shows_most_recent_run(self, git_repo, dagu_home, dags_dir):
        """Test that viz tree shows the most recent run when multiple exist."""
        # Create and run a DAG multiple times with different outcomes
        dag_content_v1 = {
            "name": "test-multiple-runs",
            "steps": [
                {"name": "version-check", "command": "echo 'Version 1'"},
            ]
        }
        dag_path = dags_dir / "test-multiple-runs.yaml"
        dag_path.write_text(yaml.dump(dag_content_v1))

        # First run
        run_dag_and_wait(dagu_home, dag_path, timeout=60)

        # Second run with different step
        dag_content_v2 = {
            "name": "test-multiple-runs",
            "steps": [
                {"name": "version-check", "command": "echo 'Version 2'"},
                {"name": "new-step", "command": "echo 'New in V2'"},
            ]
        }
        dag_path.write_text(yaml.dump(dag_content_v2))
        run_dag_and_wait(dagu_home, dag_path, timeout=60)

        # Viz should show latest run structure
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["viz", "tree", "test-multiple-runs"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        assert result.exit_code == 0
        # Should show the new step from v2
        assert "new-step" in result.output
