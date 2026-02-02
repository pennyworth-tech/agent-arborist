"""Unit tests for the visualization module."""

import json
import pytest
import shutil
from datetime import datetime, timezone
from pathlib import Path

from agent_arborist.viz.models.metrics import NodeMetrics, AggregatedMetrics
from agent_arborist.viz.models.tree import MetricsNode, MetricsTree
from agent_arborist.viz.extraction.extractor import MetricsExtractor, extract_metrics_from_step
from agent_arborist.viz.aggregation.aggregator import (
    AggregationStrategy,
    TotalsAggregator,
    AveragesAggregator,
    aggregate_tree,
)
from agent_arborist.viz.tree.builder import TreeBuilder, build_metrics_tree
from agent_arborist.viz.renderers.ascii import ASCIIRenderer
from agent_arborist.viz.renderers.json_renderer import JSONRenderer
from agent_arborist.viz import (
    render_tree,
    render_metrics,
    OutputFormat,
)
from agent_arborist.dagu_runs import DaguStatus, StepNode, DagRunAttempt, DagRun


# -----------------------------------------------------------------------------
# Model Tests
# -----------------------------------------------------------------------------


class TestNodeMetrics:
    """Tests for NodeMetrics dataclass."""

    def test_default_values(self):
        """Test default values are set correctly."""
        metrics = NodeMetrics(task_id="T001")
        assert metrics.tests_run == 0
        assert metrics.tests_passed == 0
        assert metrics.tests_failed == 0
        assert metrics.tests_skipped == 0
        assert metrics.duration_seconds == 0.0
        assert metrics.status == "pending"

    def test_pass_rate_calculation(self):
        """Test pass rate calculation."""
        metrics = NodeMetrics(
            task_id="T001",
            tests_run=100,
            tests_passed=80,
            tests_failed=15,
            tests_skipped=5,
        )
        assert metrics.pass_rate == 0.8

    def test_pass_rate_zero_tests(self):
        """Test pass rate returns None when no tests run."""
        metrics = NodeMetrics(task_id="T001", tests_run=0)
        assert metrics.pass_rate is None

    def test_has_test_metrics(self):
        """Test has_test_metrics detection."""
        empty = NodeMetrics(task_id="T001")
        assert not empty.has_test_metrics()

        with_tests = NodeMetrics(task_id="T001", tests_run=10)
        assert with_tests.has_test_metrics()


class TestAggregatedMetrics:
    """Tests for AggregatedMetrics dataclass."""

    def test_total_pass_rate(self):
        """Test aggregated pass rate calculation."""
        own = NodeMetrics(task_id="root")
        agg = AggregatedMetrics(
            own=own,
            total_tests_run=100,
            total_tests_passed=75,
            total_tests_failed=25,
        )
        assert agg.total_pass_rate == 0.75

    def test_total_pass_rate_zero_tests(self):
        """Test aggregated pass rate with no tests."""
        own = NodeMetrics(task_id="root")
        agg = AggregatedMetrics(own=own, total_tests_run=0)
        assert agg.total_pass_rate is None


class TestMetricsNode:
    """Tests for MetricsNode class."""

    def test_is_leaf(self):
        """Test leaf node detection."""
        leaf = MetricsNode(id="leaf", name="Leaf")
        assert leaf.is_leaf

        parent = MetricsNode(id="parent", name="Parent")
        child = MetricsNode(id="child", name="Child")
        parent.add_child(child)
        assert not parent.is_leaf

    def test_add_child_sets_parent(self):
        """Test that add_child sets parent reference."""
        parent = MetricsNode(id="parent", name="Parent")
        child = MetricsNode(id="child", name="Child")

        parent.add_child(child)

        assert child.parent == parent
        assert child in parent.children

    def test_depth_calculation(self):
        """Test depth calculation from root."""
        root = MetricsNode(id="root", name="Root")
        level1 = MetricsNode(id="l1", name="Level 1")
        level2 = MetricsNode(id="l2", name="Level 2")

        root.add_child(level1)
        level1.add_child(level2)

        assert root.depth == 0
        assert level1.depth == 1
        assert level2.depth == 2

    def test_to_dict(self):
        """Test conversion to dictionary."""
        node = MetricsNode(
            id="T001",
            name="Test Task",
            status="success",
            node_type="step",
        )
        node.metrics = NodeMetrics(
            task_id="T001",
            tests_run=10,
            tests_passed=8,
            tests_failed=2,
        )

        d = node.to_dict()

        assert d["id"] == "T001"
        assert d["name"] == "Test Task"
        assert d["status"] == "success"
        assert d["metrics"]["testsRun"] == 10
        assert d["metrics"]["testsPassed"] == 8


# -----------------------------------------------------------------------------
# Extraction Tests
# -----------------------------------------------------------------------------


class TestMetricsExtractor:
    """Tests for MetricsExtractor."""

    def test_extract_test_metrics_from_output(self):
        """Test extraction of test metrics from step output."""
        step = StepNode(
            name="run-tests",
            status=DaguStatus.SUCCESS,
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            child_dag_name=None,
            child_run_ids=[],
            output={
                "test_count": 20,
                "passed": 18,
                "failed": 1,
                "skipped": 1,
            },
        )

        metrics = extract_metrics_from_step(step)

        assert metrics.tests_run == 20
        assert metrics.tests_passed == 18
        assert metrics.tests_failed == 1
        assert metrics.tests_skipped == 1

    def test_extract_calculates_duration(self):
        """Test that duration is calculated from timestamps."""
        start = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        end = datetime(2025, 1, 15, 10, 0, 30, tzinfo=timezone.utc)

        step = StepNode(
            name="timed-step",
            status=DaguStatus.SUCCESS,
            started_at=start,
            finished_at=end,
            child_dag_name=None,
            child_run_ids=[],
        )

        metrics = extract_metrics_from_step(step)

        assert metrics.duration_seconds == 30.0

    def test_extract_handles_missing_output(self):
        """Test extraction when step has no output."""
        step = StepNode(
            name="no-output",
            status=DaguStatus.SUCCESS,
            started_at=None,
            finished_at=None,
            child_dag_name=None,
            child_run_ids=[],
            output=None,
        )

        metrics = extract_metrics_from_step(step)

        assert metrics.tests_run == 0
        assert metrics.tests_passed == 0


# -----------------------------------------------------------------------------
# Aggregation Tests
# -----------------------------------------------------------------------------


class TestTotalsAggregator:
    """Tests for TotalsAggregator."""

    def test_aggregates_single_node(self):
        """Test aggregation of a single leaf node."""
        node = MetricsNode(id="leaf", name="Leaf")
        node.metrics = NodeMetrics(
            task_id="leaf",
            tests_run=10,
            tests_passed=8,
            tests_failed=2,
        )

        aggregator = TotalsAggregator()
        agg = aggregator.aggregate(node)

        assert agg.total_tests_run == 10
        assert agg.total_tests_passed == 8
        assert agg.total_tests_failed == 2

    def test_aggregates_parent_with_children(self):
        """Test aggregation rolls up from children."""
        parent = MetricsNode(id="parent", name="Parent")
        parent.metrics = NodeMetrics(task_id="parent", tests_run=5, tests_passed=5)

        child1 = MetricsNode(id="child1", name="Child 1", status="success")
        child1.metrics = NodeMetrics(task_id="child1", tests_run=10, tests_passed=8, tests_failed=2)

        child2 = MetricsNode(id="child2", name="Child 2", status="failed")
        child2.metrics = NodeMetrics(task_id="child2", tests_run=20, tests_passed=15, tests_failed=5)

        parent.add_child(child1)
        parent.add_child(child2)

        aggregator = TotalsAggregator()
        agg = aggregator.aggregate(parent)

        # Parent (5) + Child1 (10) + Child2 (20) = 35
        assert agg.total_tests_run == 35
        assert agg.total_tests_passed == 28  # 5 + 8 + 15
        assert agg.total_tests_failed == 7  # 0 + 2 + 5
        assert agg.child_count == 2
        assert agg.children_succeeded == 1
        assert agg.children_failed == 1


class TestAveragesAggregator:
    """Tests for AveragesAggregator."""

    def test_computes_quality_averages(self):
        """Test that quality scores are averaged."""
        parent = MetricsNode(id="parent", name="Parent")
        parent.metrics = NodeMetrics(task_id="parent", code_quality_score=8.0)

        child1 = MetricsNode(id="child1", name="Child 1")
        child1.metrics = NodeMetrics(task_id="child1", code_quality_score=6.0)

        child2 = MetricsNode(id="child2", name="Child 2")
        child2.metrics = NodeMetrics(task_id="child2", code_quality_score=10.0)

        parent.add_child(child1)
        parent.add_child(child2)

        aggregator = AveragesAggregator()
        agg = aggregator.aggregate(parent)

        # Average of 8.0, 6.0, 10.0 = 8.0
        assert agg.avg_code_quality == 8.0


# -----------------------------------------------------------------------------
# Tree Builder Tests
# -----------------------------------------------------------------------------


class TestTreeBuilder:
    """Tests for TreeBuilder."""

    def test_builds_tree_from_simple_dag_run(self):
        """Test building tree from a simple DAG run."""
        # Create a mock DAG run
        attempt = DagRunAttempt(
            attempt_id="att1",
            status=DaguStatus.SUCCESS,
            steps=[
                StepNode(
                    name="step1",
                    status=DaguStatus.SUCCESS,
                    started_at=datetime.now(timezone.utc),
                    finished_at=datetime.now(timezone.utc),
                    child_dag_name=None,
                    child_run_ids=[],
                ),
                StepNode(
                    name="step2",
                    status=DaguStatus.SUCCESS,
                    started_at=datetime.now(timezone.utc),
                    finished_at=datetime.now(timezone.utc),
                    child_dag_name=None,
                    child_run_ids=[],
                ),
            ],
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
        )

        dag_run = DagRun(
            dag_name="test-dag",
            run_id="run123",
            root_dag_name="test-dag",
            root_dag_id="run123",
            parent_dag_name=None,
            parent_dag_id=None,
            latest_attempt=attempt,
            children=[],
        )

        tree = build_metrics_tree(dag_run)

        assert tree.dag_name == "test-dag"
        assert tree.run_id == "run123"
        assert tree.root is not None
        assert len(tree.root.children) == 2
        assert tree.root.children[0].name == "step1"
        assert tree.root.children[1].name == "step2"


# -----------------------------------------------------------------------------
# Renderer Tests
# -----------------------------------------------------------------------------


class TestASCIIRenderer:
    """Tests for ASCIIRenderer."""

    def test_renders_simple_tree(self):
        """Test ASCII rendering of a simple tree."""
        root = MetricsNode(id="root", name="test-dag", status="success", node_type="dag")
        step1 = MetricsNode(id="step1", name="step-1", status="success")
        step2 = MetricsNode(id="step2", name="step-2", status="failed")

        root.add_child(step1)
        root.add_child(step2)

        tree = MetricsTree(
            dag_name="test-dag",
            run_id="run123",
            root=root,
            status="success",
        )

        # Aggregate first
        tree = aggregate_tree(tree)

        renderer = ASCIIRenderer()
        output = renderer.render(tree)

        assert "test-dag" in output
        assert "step-1" in output
        assert "step-2" in output
        assert "✓" in output  # Success symbol
        assert "✗" in output  # Failure symbol


class TestJSONRenderer:
    """Tests for JSONRenderer."""

    def test_renders_valid_json(self):
        """Test that JSON renderer produces valid JSON."""
        root = MetricsNode(id="root", name="test-dag", status="success", node_type="dag")
        root.metrics = NodeMetrics(task_id="root", tests_run=10, tests_passed=10)

        tree = MetricsTree(
            dag_name="test-dag",
            run_id="run123",
            root=root,
            status="success",
        )

        tree = aggregate_tree(tree)

        renderer = JSONRenderer()
        output = renderer.render(tree)

        # Should be valid JSON
        data = json.loads(output)

        assert data["dagName"] == "test-dag"
        assert data["runId"] == "run123"
        assert "root" in data


# -----------------------------------------------------------------------------
# Integration Tests
# -----------------------------------------------------------------------------


class TestFullPipeline:
    """Test the full visualization pipeline."""

    def test_build_aggregate_render(self):
        """Test the complete pipeline: build -> aggregate -> render."""
        # Create a mock DAG run with test outputs
        attempt = DagRunAttempt(
            attempt_id="att1",
            status=DaguStatus.SUCCESS,
            steps=[
                StepNode(
                    name="test-step",
                    status=DaguStatus.SUCCESS,
                    started_at=datetime.now(timezone.utc),
                    finished_at=datetime.now(timezone.utc),
                    child_dag_name=None,
                    child_run_ids=[],
                    output={
                        "test_count": 20,
                        "passed": 18,
                        "failed": 2,
                        "skipped": 0,
                    },
                ),
            ],
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
        )

        dag_run = DagRun(
            dag_name="pipeline-test",
            run_id="run456",
            root_dag_name="pipeline-test",
            root_dag_id="run456",
            parent_dag_name=None,
            parent_dag_id=None,
            latest_attempt=attempt,
            children=[],
        )

        # Build
        tree = build_metrics_tree(dag_run)

        # Aggregate
        tree = aggregate_tree(tree)

        # Render ASCII
        ascii_output = render_tree(tree, format=OutputFormat.ASCII)
        assert "pipeline-test" in ascii_output
        assert "test-step" in ascii_output

        # Render JSON
        json_output = render_tree(tree, format=OutputFormat.JSON)
        data = json.loads(json_output)
        assert data["dagName"] == "pipeline-test"

        # Check metrics
        metrics_output = render_metrics(tree, format=OutputFormat.JSON)
        metrics_data = json.loads(metrics_output)
        assert metrics_data["summary"]["totalTestsRun"] == 20
        assert metrics_data["summary"]["totalTestsPassed"] == 18
