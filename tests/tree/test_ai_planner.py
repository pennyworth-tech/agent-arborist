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

"""Tests for tree/ai_planner.py - _build_tree_from_json and prompt generation."""

from agent_arborist.tree.ai_planner import _build_tree_from_json


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
