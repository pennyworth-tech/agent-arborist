"""Tree builder for constructing MetricsTree from DagRun."""

from agent_arborist.dagu_runs import DagRun, DagRunAttempt, StepNode
from agent_arborist.viz.extraction import extract_metrics_from_step
from agent_arborist.viz.models.metrics import NodeMetrics
from agent_arborist.viz.models.tree import MetricsNode, MetricsTree


class TreeBuilder:
    """Builds a MetricsTree from a DagRun.

    Converts the DagRun structure (which may include nested child DAGs)
    into a MetricsTree with extracted metrics at each node.
    """

    def build(self, dag_run: DagRun) -> MetricsTree:
        """Build a MetricsTree from a DagRun.

        Args:
            dag_run: The DagRun to convert

        Returns:
            MetricsTree with all nodes and extracted metrics
        """
        # Create root node for the DAG
        root = self._create_dag_node(dag_run)

        # Build child nodes from steps
        if dag_run.latest_attempt:
            self._add_step_nodes(root, dag_run.latest_attempt, dag_run.children)

        # Create the tree
        tree = MetricsTree(
            dag_name=dag_run.dag_name,
            run_id=dag_run.run_id,
            root=root,
            started_at=dag_run.latest_attempt.started_at if dag_run.latest_attempt else None,
            finished_at=dag_run.latest_attempt.finished_at if dag_run.latest_attempt else None,
            status=dag_run.latest_attempt.status.to_name() if dag_run.latest_attempt else "pending",
        )

        return tree

    def _create_dag_node(self, dag_run: DagRun) -> MetricsNode:
        """Create a MetricsNode for a DAG."""
        attempt = dag_run.latest_attempt

        node = MetricsNode(
            id=dag_run.run_id,
            name=dag_run.dag_name,
            node_type="dag",
            status=attempt.status.to_name() if attempt else "pending",
            started_at=attempt.started_at if attempt else None,
            finished_at=attempt.finished_at if attempt else None,
            error=attempt.error if attempt else None,
        )

        # Create own metrics (DAG level - will be aggregated from children)
        node.metrics = NodeMetrics(
            task_id=dag_run.dag_name,
            status=node.status,
            duration_seconds=node.duration_seconds or 0.0,
        )

        return node

    def _add_step_nodes(
        self,
        parent: MetricsNode,
        attempt: DagRunAttempt,
        children: list[DagRun],
    ) -> None:
        """Add step nodes to a parent DAG node.

        Args:
            parent: The parent node to add steps to
            attempt: The DAG attempt containing the steps
            children: Child DAG runs (for expanding call steps)
        """
        # Build a map of child DAGs by their run ID for quick lookup
        children_by_id: dict[str, DagRun] = {}
        for child in children:
            children_by_id[child.run_id] = child

        for step in attempt.steps:
            step_node = self._create_step_node(step)
            parent.add_child(step_node)

            # If this is a call step, add child DAG nodes
            if step.child_dag_name and step.child_run_ids:
                for child_run_id in step.child_run_ids:
                    child_run = children_by_id.get(child_run_id)
                    if child_run:
                        child_dag_node = self._create_dag_node(child_run)
                        step_node.add_child(child_dag_node)

                        # Recursively add child DAG's steps
                        if child_run.latest_attempt:
                            self._add_step_nodes(
                                child_dag_node,
                                child_run.latest_attempt,
                                child_run.children,
                            )

    def _create_step_node(self, step: StepNode) -> MetricsNode:
        """Create a MetricsNode for a step."""
        # Extract metrics from the step
        metrics = extract_metrics_from_step(step)

        node = MetricsNode(
            id=step.name,
            name=step.name,
            node_type="call" if step.child_dag_name else "step",
            status=step.status.to_name(),
            started_at=step.started_at,
            finished_at=step.finished_at,
            metrics=metrics,
            child_dag_name=step.child_dag_name,
            error=step.error,
            exit_code=step.exit_code,
        )

        return node


def build_metrics_tree(dag_run: DagRun) -> MetricsTree:
    """Convenience function to build a MetricsTree from a DagRun.

    Args:
        dag_run: The DagRun to convert

    Returns:
        MetricsTree with all nodes and extracted metrics
    """
    builder = TreeBuilder()
    return builder.build(dag_run)
