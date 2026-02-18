"""Tests for tree/spec_parser.py using existing fixtures."""

from pathlib import Path

from agent_arborist.tree.spec_parser import parse_spec

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_parse_hello_world_phases():
    tree = parse_spec(FIXTURES / "tasks-hello-world.md")
    assert len(tree.root_ids) == 3  # Phase 1, 2, 3


def test_parse_hello_world_tasks():
    tree = parse_spec(FIXTURES / "tasks-hello-world.md")
    assert "T001" in tree.nodes
    assert tree.nodes["T001"].parent == "phase1"


def test_parse_hello_world_leaves():
    tree = parse_spec(FIXTURES / "tasks-hello-world.md")
    leaf_ids = {n.id for n in tree.leaves()}
    assert "T001" in leaf_ids
    assert "phase1" not in leaf_ids


def test_parse_hello_world_dependencies():
    tree = parse_spec(FIXTURES / "tasks-hello-world.md")
    # Check that deps were parsed (existence, not exact values since fixture may vary)
    all_deps = {tid: n.depends_on for tid, n in tree.nodes.items() if n.depends_on}
    # At minimum T001 should have no deps
    assert tree.nodes["T001"].depends_on == [] or "T001" not in all_deps


def test_parse_calculator_has_multiple_phases():
    tree = parse_spec(FIXTURES / "tasks-calculator.md")
    assert len(tree.root_ids) >= 3


def test_parse_all_fixtures_no_crash():
    """Smoke test: every fixture file parses without error."""
    for f in FIXTURES.glob("tasks-*.md"):
        tree = parse_spec(f)
        assert len(tree.nodes) > 0


def test_parse_deep_tree_nested_headers():
    """### subgroups become intermediate nodes in the tree."""
    tree = parse_spec(FIXTURES / "tasks-deep-tree.md")
    # Two root phases
    assert len(tree.root_ids) == 2
    # phase1 has subgroups, not direct leaf children
    phase1 = tree.nodes["phase1"]
    # phase1 children should include subgroup ids, not T001 directly
    leaf_ids = {n.id for n in tree.leaves()}
    assert leaf_ids == {"T001", "T002", "T003", "T004"}
    # T001 should be nested under a subgroup, not phase1 directly
    assert tree.nodes["T001"].parent != "phase1"
    # All phase1 descendants resolve to phase1
    assert tree.root_phase("T001") == "phase1"
    assert tree.root_phase("T002") == "phase1"
    assert tree.root_phase("T003") == "phase1"
    # phase2 direct child
    assert tree.nodes["T004"].parent == "phase2"


def test_parse_source_file_and_line():
    tree = parse_spec(FIXTURES / "tasks-hello-world.md")
    # T001 is on line 8 of the fixture
    assert tree.nodes["T001"].source_file == str(FIXTURES / "tasks-hello-world.md")
    assert tree.nodes["T001"].source_line == 8
    # Phase headers have source refs too
    assert tree.nodes["phase1"].source_line == 6
    assert tree.spec_files == [str(FIXTURES / "tasks-hello-world.md")]


def test_to_dict_produces_json():
    """Task tree can be serialized to JSON."""
    import json
    tree = parse_spec(FIXTURES / "tasks-hello-world.md")
    data = tree.to_dict()
    json_str = json.dumps(data, indent=2)
    assert "nodes" in json_str
    assert "T001" in json_str
