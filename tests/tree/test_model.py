"""Tests for tree/model.py."""

import json

from agent_arborist.tree.model import TaskNode, TaskTree


def _make_tree():
    """Helper: phase1 -> T001, T002 (T002 depends on T001)."""
    tree = TaskTree(spec_id="test", namespace="feature")
    tree.root_ids = ["phase1"]
    tree.nodes["phase1"] = TaskNode(
        id="phase1", name="Setup", children=["T001", "T002"]
    )
    tree.nodes["T001"] = TaskNode(
        id="T001", name="Create dirs", parent="phase1"
    )
    tree.nodes["T002"] = TaskNode(
        id="T002", name="Create config", parent="phase1", depends_on=["T001"]
    )
    return tree


def test_leaves_returns_only_leaf_nodes():
    tree = _make_tree()
    leaves = tree.leaves()
    assert {l.id for l in leaves} == {"T001", "T002"}


def test_is_leaf():
    tree = _make_tree()
    assert tree.nodes["T001"].is_leaf is True
    assert tree.nodes["phase1"].is_leaf is False


def test_ready_leaves_respects_dependencies():
    tree = _make_tree()
    ready = tree.ready_leaves(completed=set())
    assert [r.id for r in ready] == ["T001"]


def test_ready_leaves_after_completion():
    tree = _make_tree()
    ready = tree.ready_leaves(completed={"T001"})
    assert "T002" in [r.id for r in ready]


def test_ready_leaves_skips_completed():
    tree = _make_tree()
    ready = tree.ready_leaves(completed={"T001", "T002"})
    assert ready == []


def test_branch_name_phase():
    tree = _make_tree()
    assert tree.branch_name("phase1") == "feature/test/phase1"


def test_branch_name_leaf_inherits_parent():
    tree = _make_tree()
    # Leaf tasks inherit their parent's branch
    assert tree.branch_name("T001") == "feature/test/phase1"
    assert tree.branch_name("T002") == "feature/test/phase1"


def test_compute_execution_order_respects_deps():
    tree = _make_tree()
    order = tree.compute_execution_order()
    assert order == ["T001", "T002"]


def test_compute_execution_order_no_deps():
    tree = TaskTree(spec_id="test")
    tree.root_ids = ["phase1"]
    tree.nodes["phase1"] = TaskNode(id="phase1", name="P", children=["T001", "T002"])
    tree.nodes["T001"] = TaskNode(id="T001", name="A", parent="phase1")
    tree.nodes["T002"] = TaskNode(id="T002", name="B", parent="phase1")
    order = tree.compute_execution_order()
    # Both have no deps, sorted alphabetically
    assert order == ["T001", "T002"]


def test_compute_execution_order_diamond():
    """T001 -> T002, T003 -> T004 (diamond dependency)."""
    tree = TaskTree(spec_id="test")
    tree.root_ids = ["phase1"]
    tree.nodes["phase1"] = TaskNode(id="phase1", name="P", children=["T001", "T002", "T003", "T004"])
    tree.nodes["T001"] = TaskNode(id="T001", name="A", parent="phase1")
    tree.nodes["T002"] = TaskNode(id="T002", name="B", parent="phase1", depends_on=["T001"])
    tree.nodes["T003"] = TaskNode(id="T003", name="C", parent="phase1", depends_on=["T001"])
    tree.nodes["T004"] = TaskNode(id="T004", name="D", parent="phase1", depends_on=["T002", "T003"])
    order = tree.compute_execution_order()
    assert order[0] == "T001"
    assert order[-1] == "T004"
    assert set(order[1:3]) == {"T002", "T003"}


def test_to_dict_includes_execution_order():
    tree = _make_tree()
    tree.compute_execution_order()
    data = tree.to_dict()
    assert data["execution_order"] == ["T001", "T002"]


def test_to_dict_and_from_dict_roundtrip():
    tree = _make_tree()
    tree.compute_execution_order()
    data = tree.to_dict()
    json_str = json.dumps(data)
    restored = TaskTree.from_dict(json.loads(json_str))
    assert restored.spec_id == tree.spec_id
    assert set(restored.nodes.keys()) == set(tree.nodes.keys())
    assert restored.nodes["T002"].depends_on == ["T001"]
    assert restored.execution_order == ["T001", "T002"]
    assert restored.branch_name("T001") == tree.branch_name("T001")
