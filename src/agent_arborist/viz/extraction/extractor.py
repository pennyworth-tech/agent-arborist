"""Metrics extraction from DAG run step outputs."""

import json
from typing import Any

from agent_arborist.dagu_runs import DagRun, DagRunAttempt, StepNode
from agent_arborist.viz.models.metrics import NodeMetrics


class MetricsExtractor:
    """Extracts metrics from DAG run step outputs.

    Supports extracting:
    - Test metrics from RunTestResult JSON outputs
    - Quality metrics from LLM eval hook outputs
    - Timing metrics from step timestamps
    """

    def extract_from_step(self, step: StepNode) -> NodeMetrics:
        """Extract metrics from a single step.

        Args:
            step: The step node with optional output data

        Returns:
            NodeMetrics with extracted values
        """
        metrics = NodeMetrics(
            task_id=step.name,
            status=step.status.to_name(),
            duration_seconds=self._calculate_duration(step),
        )

        # Extract from step output if available
        if step.output:
            self._extract_test_metrics(step.output, metrics)
            self._extract_quality_metrics(step.output, metrics)
            metrics.raw_output = step.output

        return metrics

    def _calculate_duration(self, step: StepNode) -> float:
        """Calculate step duration from timestamps."""
        if step.started_at and step.finished_at:
            return (step.finished_at - step.started_at).total_seconds()
        return 0.0

    def _extract_test_metrics(self, output: dict[str, Any], metrics: NodeMetrics) -> None:
        """Extract test metrics from RunTestResult-style output."""
        # Check for test result fields
        if "test_count" in output or "passed" in output or "failed" in output:
            metrics.tests_run = output.get("test_count", 0) or 0
            metrics.tests_passed = output.get("passed", 0) or 0
            metrics.tests_failed = output.get("failed", 0) or 0
            metrics.tests_skipped = output.get("skipped", 0) or 0

            # If test_count not provided, calculate from pass/fail/skip
            if metrics.tests_run == 0 and (metrics.tests_passed or metrics.tests_failed or metrics.tests_skipped):
                metrics.tests_run = metrics.tests_passed + metrics.tests_failed + metrics.tests_skipped

    def _extract_quality_metrics(self, output: dict[str, Any], metrics: NodeMetrics) -> None:
        """Extract quality metrics from LLM eval hook output."""
        # Check for LLM eval result fields
        if "score" in output:
            # Try to determine the type of score
            score = output.get("score", 0)
            if isinstance(score, (int, float)):
                # Assume code quality score if present with certain keys
                if "code_quality" in output.get("type", "").lower():
                    metrics.code_quality_score = float(score)
                elif "task_completion" in output.get("type", "").lower():
                    metrics.task_completion_score = float(score)
                elif "coverage" in output.get("type", "").lower():
                    metrics.test_coverage_delta = float(score)
                else:
                    # Default to code quality if type not specified
                    metrics.code_quality_score = float(score)


def extract_metrics_from_step(step: StepNode) -> NodeMetrics:
    """Convenience function to extract metrics from a step.

    Args:
        step: The step node

    Returns:
        NodeMetrics for the step
    """
    extractor = MetricsExtractor()
    return extractor.extract_from_step(step)


def extract_metrics_from_dag_run(dag_run: DagRun) -> dict[str, NodeMetrics]:
    """Extract metrics from all steps in a DAG run.

    Args:
        dag_run: The DAG run to extract metrics from

    Returns:
        Dictionary mapping step name to NodeMetrics
    """
    extractor = MetricsExtractor()
    metrics_by_step: dict[str, NodeMetrics] = {}

    if dag_run.latest_attempt:
        for step in dag_run.latest_attempt.steps:
            metrics_by_step[step.name] = extractor.extract_from_step(step)

    return metrics_by_step
