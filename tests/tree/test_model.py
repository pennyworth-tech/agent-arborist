# Copyright 2026 Pennyworth Technologies, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for tree/model.py."""

import json

from agent_arborist.tree.model import TaskNode, TaskTree, TestCommand, TestType


def _make_tree():
    """Helper: phase1 -> T001, T002 (T002 depends on T001)."""
    tree = TaskTree()
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


def test_compute_execution_order_respects_deps():
    tree = _make_tree()
    order = tree.compute_execution_order()
    assert order == ["T001", "T002"]


def test_compute_execution_order_no_deps():
    tree = TaskTree()
    tree.nodes["phase1"] = TaskNode(id="phase1", name="P", children=["T001", "T002"])
    tree.nodes["T001"] = TaskNode(id="T001", name="A", parent="phase1")
    tree.nodes["T002"] = TaskNode(id="T002", name="B", parent="phase1")
    order = tree.compute_execution_order()
    # Both have no deps, preserves insertion order from tree.nodes
    assert order == ["T001", "T002"]


def test_compute_execution_order_diamond():
    """T001 -> T002, T003 -> T004 (diamond dependency)."""
    tree = TaskTree()
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


def _deep_tree():
    """Ragged deep tree: phase1 -> group1 -> T001, T002; phase1 -> T003."""
    tree = TaskTree()
    tree.nodes["phase1"] = TaskNode(
        id="phase1", name="Setup", children=["group1", "T003"]
    )
    tree.nodes["group1"] = TaskNode(
        id="group1", name="Backend", parent="phase1", children=["T001", "T002"]
    )
    tree.nodes["T001"] = TaskNode(id="T001", name="Schema", parent="group1")
    tree.nodes["T002"] = TaskNode(id="T002", name="Models", parent="group1", depends_on=["T001"])
    tree.nodes["T003"] = TaskNode(id="T003", name="Frontend", parent="phase1")
    return tree


def test_root_phase_resolves_deep_descendants():
    tree = _deep_tree()
    assert tree.root_phase("T001") == "phase1"
    assert tree.root_phase("T002") == "phase1"
    assert tree.root_phase("T003") == "phase1"
    assert tree.root_phase("group1") == "phase1"
    assert tree.root_phase("phase1") == "phase1"


def test_leaves_under_collects_all_deep_leaves():
    tree = _deep_tree()
    leaves = tree.leaves_under("phase1")
    assert {l.id for l in leaves} == {"T001", "T002", "T003"}


def test_leaves_under_subgroup():
    tree = _deep_tree()
    leaves = tree.leaves_under("group1")
    assert {l.id for l in leaves} == {"T001", "T002"}


def test_to_dict_and_from_dict_roundtrip():
    tree = _make_tree()
    tree.compute_execution_order()
    data = tree.to_dict()
    json_str = json.dumps(data)
    restored = TaskTree.from_dict(json.loads(json_str))
    assert set(restored.nodes.keys()) == set(tree.nodes.keys())
    assert restored.nodes["T002"].depends_on == ["T001"]
    assert restored.execution_order == ["T001", "T002"]


def test_compute_execution_order_preserves_spec_order():
    """Test that execution order preserves spec insertion order, not lexicographic."""
    tree = TaskTree()
    # Insert tasks in a specific order: T003, T001, T002
    tree.nodes["root"] = TaskNode(id="root", name="Root", children=["T003", "T001", "T002"])
    tree.nodes["T003"] = TaskNode(id="T003", name="Third", parent="root")
    tree.nodes["T001"] = TaskNode(id="T001", name="First", parent="root")
    tree.nodes["T002"] = TaskNode(id="T002", name="Second", parent="root")

    order = tree.compute_execution_order()
    # Should preserve insertion order (T003, T001, T002), not sort alphabetically
    assert order == ["T003", "T001", "T002"]
    assert order != sorted(order), "Order should not be sorted alphabetically"


# --- TestCommand / TestType tests ---


def test_test_command_round_trip():
    tc = TestCommand(type=TestType.UNIT, command="pytest -x", framework="pytest", timeout=60)
    d = tc.to_dict()
    assert d == {"type": "unit", "command": "pytest -x", "framework": "pytest", "timeout": 60}
    restored = TestCommand.from_dict(d)
    assert restored.type == TestType.UNIT
    assert restored.command == "pytest -x"
    assert restored.framework == "pytest"
    assert restored.timeout == 60


def test_test_command_minimal_round_trip():
    tc = TestCommand(type=TestType.E2E, command="npm run e2e")
    d = tc.to_dict()
    assert "framework" not in d
    assert "timeout" not in d
    restored = TestCommand.from_dict(d)
    assert restored.framework is None
    assert restored.timeout is None


def test_task_node_with_test_commands_serializes():
    tree = TaskTree()
    tree.nodes["T001"] = TaskNode(
        id="T001", name="Test task",
        test_commands=[
            TestCommand(type=TestType.UNIT, command="pytest -x", framework="pytest"),
            TestCommand(type=TestType.INTEGRATION, command="pytest tests/integration/"),
        ],
    )
    data = tree.to_dict()
    tcs = data["nodes"]["T001"]["test_commands"]
    assert len(tcs) == 2
    assert tcs[0]["type"] == "unit"
    assert tcs[1]["type"] == "integration"

    restored = TaskTree.from_dict(data)
    assert len(restored.nodes["T001"].test_commands) == 2
    assert restored.nodes["T001"].test_commands[0].type == TestType.UNIT


def _make_milestone_tree(milestone_count: int, tasks_per_milestone: int = 2):
    """Build a tree with M0..M{n-1} milestones, each with leaf tasks.

    Mimics real-world task trees where double-digit milestone IDs (M10, M11)
    sort lexicographically before single-digit ones (M2, M3).
    """
    tree = TaskTree()
    for m in range(milestone_count):
        mid = f"M{m}"
        children = [f"M{m}-T{t:03d}" for t in range(1, tasks_per_milestone + 1)]
        tree.nodes[mid] = TaskNode(id=mid, name=f"Milestone {m}", children=children)
        for child_id in children:
            tree.nodes[child_id] = TaskNode(id=child_id, name=child_id, parent=mid)
    return tree


def test_execution_order_numeric_milestones():
    """M0 through M12: execution must follow numeric milestone order, not lex."""
    tree = _make_milestone_tree(13)
    order = tree.compute_execution_order()
    # Extract milestone numbers in the order tasks appear
    seen_milestones = []
    for tid in order:
        m = tid.split("-")[0]
        if not seen_milestones or seen_milestones[-1] != m:
            seen_milestones.append(m)
    expected = [f"M{i}" for i in range(13)]
    assert seen_milestones == expected, (
        f"Milestones out of order: {seen_milestones}"
    )


def test_execution_order_not_lexicographic():
    """Lex sort puts M10 before M2. Structural sort must not."""
    tree = _make_milestone_tree(12)
    order = tree.compute_execution_order()
    m2_first = next(i for i, t in enumerate(order) if t.startswith("M2-"))
    m10_first = next(i for i, t in enumerate(order) if t.startswith("M10-"))
    assert m2_first < m10_first, (
        f"M2 tasks (pos {m2_first}) must come before M10 tasks (pos {m10_first})"
    )


def test_execution_order_lex_sorted_json_keys_still_correct():
    """Simulate JSON parsed with lex-sorted keys (M0, M1, M10, M2...).

    Even if the nodes dict has lex key order, structural sort uses children
    lists and root_ids (also from dict order), so we need root milestones
    to appear in numeric order in the dict — which they do in real JSON
    because the AI planner inserts them sequentially.
    """
    tree = _make_milestone_tree(13)
    # Verify the tree itself has correct root order
    roots = tree.root_ids
    expected_roots = [f"M{i}" for i in range(13)]
    assert roots == expected_roots, f"Root order wrong: {roots}"
    # And execution order follows that
    order = tree.compute_execution_order()
    m2_first = next(i for i, t in enumerate(order) if t.startswith("M2-"))
    m10_first = next(i for i, t in enumerate(order) if t.startswith("M10-"))
    assert m2_first < m10_first


def test_execution_order_children_order_within_milestone():
    """Tasks within a milestone follow the children list order."""
    tree = _make_milestone_tree(3, tasks_per_milestone=4)
    order = tree.compute_execution_order()
    # Check that within each milestone, tasks appear in children order
    for m in range(3):
        milestone_tasks = [t for t in order if t.startswith(f"M{m}-")]
        expected = [f"M{m}-T{t:03d}" for t in range(1, 5)]
        assert milestone_tasks == expected, (
            f"Tasks within M{m} out of order: {milestone_tasks}"
        )


def test_execution_order_roundtrip_json_matches():
    """compute_execution_order before and after JSON roundtrip must match."""
    tree = _make_milestone_tree(13)
    tree.compute_execution_order()
    data = tree.to_dict()
    json_str = json.dumps(data)
    restored = TaskTree.from_dict(json.loads(json_str))
    # The restored tree has the serialized order; recomputing must agree
    recomputed = restored.compute_execution_order()
    assert recomputed == data["execution_order"], (
        "Recomputed order after JSON roundtrip doesn't match original"
    )


def test_from_dict_missing_test_commands_defaults_empty():
    data = {
        "nodes": {
            "T001": {"id": "T001", "name": "Old task"},
        },
    }
    tree = TaskTree.from_dict(data)
    assert tree.nodes["T001"].test_commands == []
