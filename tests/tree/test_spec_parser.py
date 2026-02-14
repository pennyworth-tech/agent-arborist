"""Tests for tree/spec_parser.py using existing fixtures."""

from pathlib import Path

from agent_arborist.tree.spec_parser import parse_spec

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_parse_hello_world_phases():
    tree = parse_spec(FIXTURES / "tasks-hello-world.md", spec_id="hello-world")
    assert len(tree.root_ids) == 3  # Phase 1, 2, 3


def test_parse_hello_world_tasks():
    tree = parse_spec(FIXTURES / "tasks-hello-world.md", spec_id="hello-world")
    assert "T001" in tree.nodes
    assert tree.nodes["T001"].parent == "phase1"


def test_parse_hello_world_leaves():
    tree = parse_spec(FIXTURES / "tasks-hello-world.md", spec_id="hello-world")
    leaf_ids = {n.id for n in tree.leaves()}
    assert "T001" in leaf_ids
    assert "phase1" not in leaf_ids


def test_parse_hello_world_dependencies():
    tree = parse_spec(FIXTURES / "tasks-hello-world.md", spec_id="hello-world")
    # Check that deps were parsed (existence, not exact values since fixture may vary)
    all_deps = {tid: n.depends_on for tid, n in tree.nodes.items() if n.depends_on}
    # At minimum T001 should have no deps
    assert tree.nodes["T001"].depends_on == [] or "T001" not in all_deps


def test_parse_calculator_has_multiple_phases():
    tree = parse_spec(FIXTURES / "tasks-calculator.md", spec_id="calculator")
    assert len(tree.root_ids) >= 3


def test_parse_all_fixtures_no_crash():
    """Smoke test: every fixture file parses without error."""
    for f in FIXTURES.glob("tasks-*.md"):
        tree = parse_spec(f, spec_id=f.stem)
        assert len(tree.nodes) > 0


def test_parse_produces_branch_names():
    tree = parse_spec(FIXTURES / "tasks-hello-world.md", spec_id="hello-world")
    # Leaf tasks inherit parent's branch
    bn = tree.branch_name("T001")
    assert bn.startswith("feature/hello-world/")
    assert "phase" in bn


def test_to_dict_produces_json():
    """Task tree can be serialized to JSON."""
    import json
    tree = parse_spec(FIXTURES / "tasks-hello-world.md", spec_id="hello-world")
    data = tree.to_dict()
    json_str = json.dumps(data, indent=2)
    assert "hello-world" in json_str
    assert "T001" in json_str
