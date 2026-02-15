"""Tests for tree/ai_planner.py - _build_tree_from_json and prompt generation."""

from agent_arborist.tree.ai_planner import _build_tree_from_json, _read_spec_contents


def test_build_tree_populates_source_fields():
    data = {
        "tasks": [
            {"id": "Phase1", "description": "Setup", "children": ["T001"],
             "source_file": "tasks.md", "source_line": 5},
            {"id": "T001", "description": "Create dir", "parent": "Phase1",
             "source_file": "tasks.md", "source_line": 7},
        ]
    }
    tree = _build_tree_from_json(data, "test", "feature")
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
    tree = _build_tree_from_json(data, "test", "feature")
    assert tree.spec_files == ["a.md", "b.md"]


def test_build_tree_missing_source_fields():
    data = {
        "tasks": [
            {"id": "T001", "description": "No source"},
        ]
    }
    tree = _build_tree_from_json(data, "test", "feature")
    assert tree.nodes["T001"].source_file is None
    assert tree.nodes["T001"].source_line is None
    assert tree.spec_files == []


def test_read_spec_contents_includes_line_numbers(tmp_path):
    md = tmp_path / "tasks.md"
    md.write_text("# Title\n- [ ] T001 Do thing\n")
    result = _read_spec_contents(tmp_path)
    assert "1: # Title" in result
    assert "2: - [ ] T001 Do thing" in result
    assert "--- tasks.md ---" in result
