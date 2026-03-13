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

"""Tests for tree/ai_planner.py - _build_tree_from_json, prompt generation, and test-plan merge."""

import json

from agent_arborist.tree.ai_planner import _build_tree_from_json, _merge_test_plan, _find_test_plan
from agent_arborist.tree.model import TaskNode, TaskTree, TestCommand, TestType


def test_build_tree_populates_source_fields():
    data = {
        "tasks": [
            {"id": "Phase1", "description": "Setup", "children": ["T001"],
             "source_file": "tasks.md", "source_line": 5},
            {"id": "T001", "description": "Create dir", "parent": "Phase1",
             "source_file": "tasks.md", "source_line": 7},
        ]
    }
    tree = _build_tree_from_json(data)
    assert tree.nodes["T001"].source_file == "tasks.md"
    assert tree.nodes["T001"].source_line == 7
    assert tree.nodes["Phase1"].source_file == "tasks.md"
    assert tree.nodes["Phase1"].source_line == 5


def test_build_tree_populates_spec_files():
    data = {
        "tasks": [
            {"id": "T001", "description": "A", "source_file": "a.md", "source_line": 1},
            {"id": "T002", "description": "B", "source_file": "b.md", "source_line": 2},
        ]
    }
    tree = _build_tree_from_json(data)
    assert tree.spec_files == ["a.md", "b.md"]


def test_build_tree_missing_source_fields():
    data = {
        "tasks": [
            {"id": "T001", "description": "No source"},
        ]
    }
    tree = _build_tree_from_json(data)
    assert tree.nodes["T001"].source_file is None
    assert tree.nodes["T001"].source_line is None
    assert tree.spec_files == []


def test_build_tree_from_json_with_test_commands():
    data = {
        "tasks": [
            {
                "id": "T001", "description": "Create API",
                "test_commands": [
                    {"type": "unit", "command": "pytest tests/ -x", "framework": "pytest"},
                    {"type": "integration", "command": "pytest tests/integration/"},
                ],
            },
        ]
    }
    tree = _build_tree_from_json(data)
    assert len(tree.nodes["T001"].test_commands) == 2
    assert tree.nodes["T001"].test_commands[0].type.value == "unit"
    assert tree.nodes["T001"].test_commands[0].framework == "pytest"
    assert tree.nodes["T001"].test_commands[1].type.value == "integration"


def test_build_tree_from_json_without_test_commands():
    data = {
        "tasks": [
            {"id": "T001", "description": "Old format task"},
        ]
    }
    tree = _build_tree_from_json(data)
    assert tree.nodes["T001"].test_commands == []


def test_build_tree_from_json_invalid_test_command_skipped():
    data = {
        "tasks": [
            {
                "id": "T001", "description": "Task",
                "test_commands": [
                    {"type": "bogus", "command": "bad"},  # invalid type
                    {"type": "unit", "command": "pytest"},  # valid
                ],
            },
        ]
    }
    tree = _build_tree_from_json(data)
    assert len(tree.nodes["T001"].test_commands) == 1
    assert tree.nodes["T001"].test_commands[0].command == "pytest"


def test_build_tree_from_json_with_requirement_ids():
    data = {
        "tasks": [
            {"id": "Phase1", "description": "Setup", "children": ["T001"]},
            {"id": "T001", "description": "Create API", "parent": "Phase1",
             "requirement_ids": ["REQ-001", "REQ-002"]},
        ]
    }
    tree = _build_tree_from_json(data)
    assert tree.nodes["T001"].requirement_ids == ["REQ-001", "REQ-002"]
    assert tree.nodes["Phase1"].requirement_ids == []


# --- _find_test_plan tests ---


def test_find_test_plan_quality_dir(tmp_path):
    quality = tmp_path / "quality"
    quality.mkdir()
    tp = quality / "test-plan.json"
    tp.write_text("{}")
    assert _find_test_plan(tmp_path) == tp


def test_find_test_plan_root(tmp_path):
    tp = tmp_path / "test-plan.json"
    tp.write_text("{}")
    assert _find_test_plan(tmp_path) == tp


def test_find_test_plan_none(tmp_path):
    assert _find_test_plan(tmp_path) is None


# --- _merge_test_plan tests ---


def _make_test_plan(tests):
    return json.dumps({"tests": tests})


def test_merge_test_plan_basic(tmp_path):
    """Tests matched to nodes by requirement_id."""
    quality = tmp_path / "quality"
    quality.mkdir()
    (quality / "test-plan.json").write_text(_make_test_plan([
        {"test_id": "T-001", "name": "Test create", "requirement_ids": ["REQ-001"],
         "test_type": "integration", "command": "vitest run create.test.ts",
         "framework": "vitest", "timeout_s": 120},
        {"test_id": "T-002", "name": "Test list", "requirement_ids": ["REQ-002"],
         "test_type": "unit", "command": "vitest run list.test.ts",
         "framework": "vitest", "timeout_s": 30},
    ]))

    tree = TaskTree()
    tree.nodes["Phase1"] = TaskNode(id="Phase1", name="Setup", children=["T001", "T002"])
    tree.nodes["T001"] = TaskNode(id="T001", name="Create", parent="Phase1",
                                   requirement_ids=["REQ-001"])
    tree.nodes["T002"] = TaskNode(id="T002", name="List", parent="Phase1",
                                   requirement_ids=["REQ-002"])

    _merge_test_plan(tree, tmp_path)

    assert len(tree.nodes["T001"].test_commands) == 1
    assert tree.nodes["T001"].test_commands[0].test_id == "T-001"
    assert tree.nodes["T001"].test_commands[0].name == "Test create"
    assert tree.nodes["T001"].test_commands[0].type == TestType.INTEGRATION

    assert len(tree.nodes["T002"].test_commands) == 1
    assert tree.nodes["T002"].test_commands[0].test_id == "T-002"


def test_merge_test_plan_deduplicates(tmp_path):
    """Same test via multiple req_ids appears once."""
    quality = tmp_path / "quality"
    quality.mkdir()
    (quality / "test-plan.json").write_text(_make_test_plan([
        {"test_id": "T-001", "name": "Test both",
         "requirement_ids": ["REQ-001", "REQ-002"],
         "test_type": "integration", "command": "vitest run both.test.ts",
         "framework": "vitest", "timeout_s": 60},
    ]))

    tree = TaskTree()
    tree.nodes["root"] = TaskNode(id="root", name="R", children=["T001"])
    tree.nodes["T001"] = TaskNode(id="T001", name="Both", parent="root",
                                   requirement_ids=["REQ-001", "REQ-002"])

    _merge_test_plan(tree, tmp_path)

    assert len(tree.nodes["T001"].test_commands) == 1
    assert tree.nodes["T001"].test_commands[0].test_id == "T-001"


def test_merge_test_plan_no_file(tmp_path):
    """No test-plan.json, test_commands unchanged."""
    tree = TaskTree()
    tree.nodes["T001"] = TaskNode(
        id="T001", name="Task", requirement_ids=["REQ-001"],
        test_commands=[TestCommand(type=TestType.UNIT, command="pytest")],
    )

    _merge_test_plan(tree, tmp_path)

    assert len(tree.nodes["T001"].test_commands) == 1
    assert tree.nodes["T001"].test_commands[0].command == "pytest"


def test_merge_test_plan_sorted_by_test_id(tmp_path):
    """Test commands are sorted by test_id for determinism."""
    quality = tmp_path / "quality"
    quality.mkdir()
    (quality / "test-plan.json").write_text(_make_test_plan([
        {"test_id": "T-003", "name": "C", "requirement_ids": ["REQ-001"],
         "test_type": "unit", "command": "c", "framework": "vitest", "timeout_s": 30},
        {"test_id": "T-001", "name": "A", "requirement_ids": ["REQ-001"],
         "test_type": "unit", "command": "a", "framework": "vitest", "timeout_s": 30},
        {"test_id": "T-002", "name": "B", "requirement_ids": ["REQ-001"],
         "test_type": "unit", "command": "b", "framework": "vitest", "timeout_s": 30},
    ]))

    tree = TaskTree()
    tree.nodes["T001"] = TaskNode(id="T001", name="Task",
                                   requirement_ids=["REQ-001"])

    _merge_test_plan(tree, tmp_path)

    ids = [tc.test_id for tc in tree.nodes["T001"].test_commands]
    assert ids == ["T-001", "T-002", "T-003"]


def test_merge_test_plan_replaces_existing_commands(tmp_path):
    """Merge replaces any AI-generated test_commands."""
    quality = tmp_path / "quality"
    quality.mkdir()
    (quality / "test-plan.json").write_text(_make_test_plan([
        {"test_id": "T-001", "name": "Real test", "requirement_ids": ["REQ-001"],
         "test_type": "unit", "command": "vitest run real.test.ts",
         "framework": "vitest", "timeout_s": 30},
    ]))

    tree = TaskTree()
    tree.nodes["T001"] = TaskNode(
        id="T001", name="Task", requirement_ids=["REQ-001"],
        test_commands=[TestCommand(type=TestType.UNIT, command="fake-command")],
    )

    _merge_test_plan(tree, tmp_path)

    assert len(tree.nodes["T001"].test_commands) == 1
    assert tree.nodes["T001"].test_commands[0].command == "vitest run real.test.ts"
    assert tree.nodes["T001"].test_commands[0].test_id == "T-001"
