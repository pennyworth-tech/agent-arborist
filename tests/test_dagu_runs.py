"""Unit tests for Dagu runs data layer."""

import pytest
from pathlib import Path
from agent_arborist import dagu_runs


@pytest.fixture
def fixtures_dir():
    """Path to test fixtures."""
    return Path(__file__).parent / "fixtures"


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

    @pytest.fixture
    def dagu_home(self):
        return Path("/tmp/arborist-test-repo/.arborist/dagu")

    def test_load_dag_run_without_children(self, dagu_home):
        """Test loading a DAG run without children."""
        run = dagu_runs.load_dag_run(
            dagu_home,
            "001_hello_world",
            "019bf33d-a303-7af0-91c8-0fa5f28ae023",
            expand_subdags=False
        )
        assert run is not None
        assert run.dag_name == "001_hello_world"
        assert len(run.children) == 0

    def test_load_dag_run_with_children(self, dagu_home):
        """Test loading a DAG run with children."""
        run = dagu_runs.load_dag_run(
            dagu_home,
            "001_hello_world",
            "019bf33d-a303-7af0-91c8-0fa5f28ae023",
            expand_subdags=True
        )
        assert run is not None
        assert len(run.children) > 0

        # Verify child structure
        child = run.children[0]
        assert child.parent_dag_name == "001_hello_world"
        assert child.root_dag_name == "001_hello_world"

    def test_load_nonexistent_run(self, dagu_home):
        """Test loading a run that doesn't exist."""
        run = dagu_runs.load_dag_run(
            dagu_home,
            "nonexistent_dag",
            "nonexistent_run_id",
            expand_subdags=False
        )
        assert run is None


class TestListDagRuns:
    """Tests for listing DAG runs."""

    @pytest.fixture
    def dagu_home(self):
        return Path("/tmp/arborist-test-repo/.arborist/dagu")

    def test_list_all_runs(self, dagu_home):
        """Test listing all DAG runs."""
        runs = dagu_runs.list_dag_runs(dagu_home, limit=10)
        assert len(runs) > 0

        # Verify runs are sorted by started_at descending
        if len(runs) > 1:
            assert runs[0].latest_attempt.started_at >= runs[1].latest_attempt.started_at

    def test_list_runs_filter_by_dag_name(self, dagu_home):
        """Test filtering runs by DAG name."""
        runs = dagu_runs.list_dag_runs(dagu_home, dag_name="001_hello_world", limit=10)
        assert len(runs) > 0
        for run in runs:
            assert run.dag_name == "001_hello_world"

    def test_list_runs_filter_by_status(self, dagu_home):
        """Test filtering runs by status."""
        runs = dagu_runs.list_dag_runs(dagu_home, status=dagu_runs.DaguStatus.SUCCESS, limit=10)
        assert len(runs) > 0
        for run in runs:
            assert run.latest_attempt.status == dagu_runs.DaguStatus.SUCCESS

    def test_list_runs_respects_limit(self, dagu_home):
        """Test that limit parameter is respected."""
        runs = dagu_runs.list_dag_runs(dagu_home, limit=2)
        assert len(runs) <= 2

    def test_list_runs_empty_dagu_home(self, tmp_path):
        """Test listing runs with empty Dagu home."""
        runs = dagu_runs.list_dag_runs(tmp_path)
        assert len(runs) == 0
