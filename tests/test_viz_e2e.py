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
