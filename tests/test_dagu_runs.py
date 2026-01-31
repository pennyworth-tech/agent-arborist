"""Unit tests for Dagu runs data layer."""

import pytest
import shutil
from pathlib import Path
from agent_arborist import dagu_runs


@pytest.fixture
def fixtures_dir():
    """Path to test fixtures."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def dagu_home_with_runs(tmp_path, fixtures_dir):
    """Create a temporary dagu home with test run data.

    Creates structure matching Dagu's actual layout:
        dagu/
        └── data/
            └── dag-runs/
                ├── 001_hello_world/
                │   └── dag-runs/
                │       └── 2026/
                │           └── 01/
                │               └── 25/
                │                   └── dag-run_20260125_034101Z_019bf33d-a303-7af0-91c8-0fa5f28ae023/
                │                       └── attempt_1/
                │                           └── status.jsonl (with children)
                └── 002_simple_dag/
                    └── dag-runs/
                        └── 2026/
                            └── 01/
                                └── 25/
                                    └── dag-run_20260125_034000Z_019bf33d-0000-0000-0000-000000000000/
                                        └── attempt_1/
                                            └── status.jsonl (no children)
    """
    dagu_home = tmp_path / "dagu"
    data_dir = dagu_home / "data" / "dag-runs"

    # Create 001_hello_world run with children
    hello_world_run_dir = (
        data_dir / "001_hello_world" / "dag-runs" / "2026" / "01" / "25" /
        "dag-run_20260125_034101Z_019bf33d-a303-7af0-91c8-0fa5f28ae023"
    )
    hello_world_run = hello_world_run_dir / "attempt_1"
    hello_world_run.mkdir(parents=True, exist_ok=True)
    shutil.copy(
        fixtures_dir / "status_with_children.jsonl",
        hello_world_run / "status.jsonl"
    )

    # Create a child run for the hello_world run
    child_run = hello_world_run_dir / "children" / "child_child123" / "attempt_1"
    child_run.mkdir(parents=True, exist_ok=True)
    shutil.copy(
        fixtures_dir / "status_child.jsonl",
        child_run / "status.jsonl"
    )

    # Create 002_simple_dag run without children
    simple_dag_run = (
        data_dir / "002_simple_dag" / "dag-runs" / "2026" / "01" / "25" /
        "dag-run_20260125_034000Z_019bf33d-0000-0000-0000-000000000000" / "attempt_1"
    )
    simple_dag_run.mkdir(parents=True, exist_ok=True)
    shutil.copy(
        fixtures_dir / "status_success.jsonl",
        simple_dag_run / "status.jsonl"
    )

    return dagu_home


class TestDaguStatus:
    """Tests for DaguStatus enum."""

    def test_from_name(self):
        """Test converting status names to enum values."""
        assert dagu_runs.DaguStatus.from_name("pending") == dagu_runs.DaguStatus.PENDING
        assert dagu_runs.DaguStatus.from_name("running") == dagu_runs.DaguStatus.RUNNING
        assert dagu_runs.DaguStatus.from_name("failed") == dagu_runs.DaguStatus.FAILED
        assert dagu_runs.DaguStatus.from_name("skipped") == dagu_runs.DaguStatus.SKIPPED
        assert dagu_runs.DaguStatus.from_name("success") == dagu_runs.DaguStatus.SUCCESS

    def test_from_name_case_insensitive(self):
        """Test status name conversion is case insensitive."""
        assert dagu_runs.DaguStatus.from_name("SUCCESS") == dagu_runs.DaguStatus.SUCCESS
        assert dagu_runs.DaguStatus.from_name("Failed") == dagu_runs.DaguStatus.FAILED

    def test_from_name_invalid(self):
        """Test invalid status name returns None."""
        assert dagu_runs.DaguStatus.from_name("invalid") is None

    def test_to_name(self):
        """Test converting enum to status name."""
        assert dagu_runs.DaguStatus.SUCCESS.to_name() == "success"
        assert dagu_runs.DaguStatus.FAILED.to_name() == "failed"
        assert dagu_runs.DaguStatus.RUNNING.to_name() == "running"


class TestFormatDuration:
    """Tests for _format_duration function."""

    def test_format_duration_less_than_second(self):
        """Test formatting duration less than 1 second."""
        start = dagu_runs._parse_datetime("2026-01-24T20:41:01-07:00")
        end = dagu_runs._parse_datetime("2026-01-24T20:41:01.5-07:00")
        result = dagu_runs._format_duration(start, end)
        assert result == "<1s"

    def test_format_duration_seconds(self):
        """Test formatting duration in seconds."""
        start = dagu_runs._parse_datetime("2026-01-24T20:41:01-07:00")
        end = dagu_runs._parse_datetime("2026-01-24T20:41:05-07:00")
        result = dagu_runs._format_duration(start, end)
        assert result == "4s"

    def test_format_duration_minutes(self):
        """Test formatting duration in minutes."""
        start = dagu_runs._parse_datetime("2026-01-24T20:41:01-07:00")
        end = dagu_runs._parse_datetime("2026-01-24T20:42:07-07:00")
        result = dagu_runs._format_duration(start, end)
        assert result == "1m 6s"

    def test_format_duration_hours(self):
        """Test formatting duration in hours."""
        start = dagu_runs._parse_datetime("2026-01-24T20:41:01-07:00")
        end = dagu_runs._parse_datetime("2026-01-24T21:41:01-07:00")
        result = dagu_runs._format_duration(start, end)
        assert result == "1h 0m"

    def test_format_duration_none(self):
        """Test formatting duration with None values."""
        result = dagu_runs._format_duration(None, None)
        assert result == "N/A"

        result = dagu_runs._format_duration(
            dagu_runs._parse_datetime("2026-01-24T20:41:01-07:00"),
            None
        )
        assert result == "N/A"


class TestParseStatusJsonl:
    """Tests for parsing status.jsonl files."""

    def test_parse_simple_status(self, fixtures_dir):
        """Test parsing a simple status file."""
        path = fixtures_dir / "status_success.jsonl"
        attempt = dagu_runs.parse_status_jsonl(path)

        assert attempt.attempt_id == "att1"
        assert attempt.status == dagu_runs.DaguStatus.SUCCESS
        assert len(attempt.steps) == 2
        assert attempt.started_at is not None
        assert attempt.finished_at is not None

        # Check first step
        step1 = attempt.steps[0]
        assert step1.name == "step1"
        assert step1.status == dagu_runs.DaguStatus.SUCCESS
        assert step1.child_dag_name is None
        assert len(step1.child_run_ids) == 0

    def test_parse_status_with_children(self, fixtures_dir):
        """Test parsing status file with child DAGs."""
        path = fixtures_dir / "status_with_children.jsonl"
        attempt = dagu_runs.parse_status_jsonl(path)

        assert attempt.attempt_id == "att1"
        assert attempt.status == dagu_runs.DaguStatus.SUCCESS
        assert len(attempt.steps) == 1

        # Check call step
        call_step = attempt.steps[0]
        assert call_step.name == "call-child1"
        assert call_step.child_dag_name == "child1"
        assert len(call_step.child_run_ids) == 1
        assert call_step.child_run_ids[0] == "child123"

    def test_parse_nonexistent_file(self, fixtures_dir):
        """Test parsing a file that doesn't exist."""
        path = fixtures_dir / "nonexistent.jsonl"
        with pytest.raises(FileNotFoundError):
            dagu_runs.parse_status_jsonl(path)

    def test_parse_empty_file(self, tmp_path):
        """Test parsing an empty file."""
        empty_file = tmp_path / "empty.jsonl"
        empty_file.write_text("")

        with pytest.raises(ValueError):
            dagu_runs.parse_status_jsonl(empty_file)


class TestLoadDagRun:
    """Tests for loading DAG runs."""

    def test_load_dag_run_without_children(self, dagu_home_with_runs):
        """Test loading a DAG run without children."""
        run = dagu_runs.load_dag_run(
            dagu_home_with_runs,
            "002_simple_dag",
            "019bf33d-0000-0000-0000-000000000000",
            expand_subdags=False
        )
        assert run is not None
        assert run.dag_name == "002_simple_dag"
        assert len(run.children) == 0

    def test_load_dag_run_with_children(self, dagu_home_with_runs):
        """Test loading a DAG run with children."""
        run = dagu_runs.load_dag_run(
            dagu_home_with_runs,
            "001_hello_world",
            "019bf33d-a303-7af0-91c8-0fa5f28ae023",
            expand_subdags=True
        )
        assert run is not None
        assert len(run.children) > 0

        # Verify child structure
        child = run.children[0]
        assert child.parent_dag_name == "parent_dag"
        assert child.root_dag_name == "parent_dag"

    def test_load_nonexistent_run(self, dagu_home_with_runs):
        """Test loading a run that doesn't exist."""
        run = dagu_runs.load_dag_run(
            dagu_home_with_runs,
            "nonexistent_dag",
            "nonexistent_run_id",
            expand_subdags=False
        )
        assert run is None


class TestListDagRuns:
    """Tests for listing DAG runs."""

    def test_list_all_runs(self, dagu_home_with_runs):
        """Test listing all DAG runs."""
        runs = dagu_runs.list_dag_runs(dagu_home_with_runs, limit=10)
        assert len(runs) > 0
        assert len(runs) == 2  # We have 2 runs in our fixture

        # Verify runs are sorted by started_at descending
        if len(runs) > 1:
            assert runs[0].latest_attempt.started_at >= runs[1].latest_attempt.started_at

    def test_list_runs_filter_by_dag_name(self, dagu_home_with_runs):
        """Test filtering runs by DAG name."""
        runs = dagu_runs.list_dag_runs(dagu_home_with_runs, dag_name="001_hello_world", limit=10)
        assert len(runs) > 0
        for run in runs:
            assert run.dag_name == "001_hello_world"

    def test_list_runs_filter_by_status(self, dagu_home_with_runs):
        """Test filtering runs by status."""
        runs = dagu_runs.list_dag_runs(dagu_home_with_runs, status=dagu_runs.DaguStatus.SUCCESS, limit=10)
        assert len(runs) > 0
        for run in runs:
            assert run.latest_attempt.status == dagu_runs.DaguStatus.SUCCESS

    def test_list_runs_respects_limit(self, dagu_home_with_runs):
        """Test that limit parameter is respected."""
        runs = dagu_runs.list_dag_runs(dagu_home_with_runs, limit=2)
        assert len(runs) <= 2

    def test_list_runs_empty_dagu_home(self, tmp_path):
        """Test listing runs with empty Dagu home."""
        runs = dagu_runs.list_dag_runs(tmp_path)
        assert len(runs) == 0


class TestOutputsParsing:
    """Tests for outputs.json parsing (V1 feature)."""

    def test_parse_outputs_json_valid(self, tmp_path):
        """Test parsing valid outputs.json."""
        import json
        outputs_content = {
            "metadata": {"dagName": "test", "dagRunId": "abc123"},
            "outputs": {"result": "success", "count": 42}
        }
        outputs_file = tmp_path / "outputs.json"
        outputs_file.write_text(json.dumps(outputs_content))

        result = dagu_runs.parse_outputs_json(outputs_file)
        assert result == outputs_content

    def test_parse_outputs_json_missing(self, tmp_path):
        """Test parsing missing outputs.json returns empty dict."""
        result = dagu_runs.parse_outputs_json(tmp_path / "missing.json")
        assert result == {}

    def test_parse_outputs_json_invalid(self, tmp_path):
        """Test parsing invalid JSON handles errors gracefully."""
        outputs_file = tmp_path / "invalid.json"
        outputs_file.write_text("{ invalid json")
        result = dagu_runs.parse_outputs_json(outputs_file)
        assert result == {}

    def test_load_step_output(self):
        """Test extracting step output from outputs dict."""
        outputs = {"outputs": {"step1": {"result": "ok"}, "step2": {"value": 42}}}
        assert dagu_runs.load_step_output(outputs, "step1") == {"result": "ok"}
        assert dagu_runs.load_step_output(outputs, "step2") == {"value": 42}
        assert dagu_runs.load_step_output(outputs, "missing") is None

    def test_load_step_output_empty_outputs(self):
        """Test extracting step output from empty outputs dict."""
        assert dagu_runs.load_step_output({}, "step1") is None
        assert dagu_runs.load_step_output({"outputs": {}}, "step1") is None


class TestErrorParsing:
    """Tests for error/exit code extraction from status.jsonl (V1 feature)."""

    def test_parse_status_with_error_and_exit_code(self, tmp_path):
        """Test parsing status.jsonl with error and exit code."""
        import json
        status_data = {
            "dagRunId": "test123",
            "attemptId": "att1",
            "status": 2,  # FAILED
            "startedAt": "2026-01-25T00:00:00Z",
            "finishedAt": "2026-01-25T00:00:10Z",
            "error": "DAG failed",
            "nodes": [
                {"step": {"name": "step1"}, "status": 4, "exitCode": 0},
                {"step": {"name": "step2"}, "status": 2, "exitCode": 1, "error": "Command failed"}
            ]
        }
        status_file = tmp_path / "status.jsonl"
        status_file.write_text(json.dumps(status_data))

        attempt = dagu_runs.parse_status_jsonl(status_file)

        assert attempt.status == dagu_runs.DaguStatus.FAILED
        assert attempt.error == "DAG failed"

        # Check step 1 (success)
        step1 = next(s for s in attempt.steps if s.name == "step1")
        assert step1.exit_code == 0
        assert step1.error is None

        # Check step 2 (failed)
        step2 = next(s for s in attempt.steps if s.name == "step2")
        assert step2.exit_code == 1
        assert step2.error == "Command failed"

    def test_parse_status_without_error_fields(self, fixtures_dir):
        """Test parsing status.jsonl without error fields still works."""
        path = fixtures_dir / "status_success.jsonl"
        attempt = dagu_runs.parse_status_jsonl(path)

        assert attempt.error is None
        for step in attempt.steps:
            assert step.exit_code is None
            assert step.error is None


class TestRecursiveLoadingWithOutputs:
    """Tests for recursive child loading with outputs (V1 feature)."""

    def test_load_dag_run_with_outputs(self, tmp_path):
        """Test loading DAG run with outputs enabled."""
        import json

        # Create test structure
        dagu_home = tmp_path / "dagu"
        run_dir = (
            dagu_home / "data" / "dag-runs" / "test_dag" / "dag-runs" /
            "2026" / "01" / "31" / "dag-run_20260131_000000Z_run123"
        )
        attempt_dir = run_dir / "attempt_1"
        attempt_dir.mkdir(parents=True)

        status_data = {
            "dagRunId": "run123", "name": "test_dag", "attemptId": "att1",
            "status": 4, "startedAt": "2026-01-31T00:00:00Z", "finishedAt": "2026-01-31T00:01:00Z",
            "root": {"name": "test_dag", "id": "run123"}, "parent": {},
            "nodes": [{"step": {"name": "step1"}, "status": 4}]
        }
        (attempt_dir / "status.jsonl").write_text(json.dumps(status_data))

        # Add outputs.json
        outputs_data = {
            "metadata": {"dagName": "test_dag"},
            "outputs": {"step1": {"result": "success"}}
        }
        (attempt_dir / "outputs.json").write_text(json.dumps(outputs_data))

        # Load with include_outputs=True
        dag_run = dagu_runs.load_dag_run(
            dagu_home, "test_dag", "run123",
            expand_subdags=False, include_outputs=True
        )

        assert dag_run is not None
        assert dag_run.latest_attempt.outputs is not None
        assert dag_run.latest_attempt.outputs.get("outputs", {}).get("step1") == {"result": "success"}
        assert dag_run.outputs_file is not None
        assert dag_run.run_dir is not None

        # Check per-step output
        step1 = dag_run.latest_attempt.steps[0]
        assert step1.output == {"result": "success"}

    def test_load_dag_run_without_outputs(self, tmp_path):
        """Test loading DAG run with include_outputs=False doesn't load outputs."""
        import json

        # Create test structure
        dagu_home = tmp_path / "dagu"
        run_dir = (
            dagu_home / "data" / "dag-runs" / "test_dag" / "dag-runs" /
            "2026" / "01" / "31" / "dag-run_20260131_000000Z_run456"
        )
        attempt_dir = run_dir / "attempt_1"
        attempt_dir.mkdir(parents=True)

        status_data = {
            "dagRunId": "run456", "name": "test_dag", "attemptId": "att1",
            "status": 4, "startedAt": "2026-01-31T00:00:00Z", "finishedAt": "2026-01-31T00:01:00Z",
            "root": {"name": "test_dag", "id": "run456"}, "parent": {},
            "nodes": [{"step": {"name": "step1"}, "status": 4}]
        }
        (attempt_dir / "status.jsonl").write_text(json.dumps(status_data))

        # Add outputs.json (but should not be loaded)
        outputs_data = {"outputs": {"step1": {"result": "success"}}}
        (attempt_dir / "outputs.json").write_text(json.dumps(outputs_data))

        # Load without include_outputs
        dag_run = dagu_runs.load_dag_run(
            dagu_home, "test_dag", "run456",
            expand_subdags=False, include_outputs=False
        )

        assert dag_run is not None
        assert dag_run.latest_attempt.outputs is None
        assert dag_run.latest_attempt.steps[0].output is None
        # outputs_file should still be set (it exists), just not loaded
        assert dag_run.outputs_file is not None
