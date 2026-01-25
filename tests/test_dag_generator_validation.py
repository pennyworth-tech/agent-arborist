"""Tests for DAG generator validation and fixing functions."""

import pytest
import yaml

from agent_arborist.dag_generator import (
    _fix_env_format,
    _topological_sort_steps,
    _remove_empty_depends,
    validate_and_fix_dag,
    validate_and_fix_multi_doc,
)


class TestFixEnvFormat:
    """Tests for _fix_env_format function."""

    def test_already_correct_format(self):
        """Test that correct KEY=value format is preserved."""
        dag = {"env": ["ARBORIST_MANIFEST=test.json"]}
        fixes = _fix_env_format(dag)

        assert dag["env"] == ["ARBORIST_MANIFEST=test.json"]
        assert len(fixes) == 0

    def test_fixes_colon_format(self):
        """Test that KEY: value format is converted to KEY=value."""
        dag = {"env": ["ARBORIST_MANIFEST: test.json"]}
        fixes = _fix_env_format(dag)

        assert dag["env"] == ["ARBORIST_MANIFEST=test.json"]
        assert len(fixes) == 1
        assert "Converted" in fixes[0]

    def test_fixes_dict_format(self):
        """Test that dict format {KEY: value} is converted to KEY=value."""
        dag = {"env": [{"ARBORIST_MANIFEST": "test.json"}]}
        fixes = _fix_env_format(dag)

        assert dag["env"] == ["ARBORIST_MANIFEST=test.json"]
        assert len(fixes) == 1

    def test_removes_duplicates(self):
        """Test that duplicate env keys are removed."""
        dag = {"env": [
            "ARBORIST_MANIFEST=test1.json",
            "ARBORIST_MANIFEST=test2.json",
        ]}
        fixes = _fix_env_format(dag)

        assert len(dag["env"]) == 1
        assert dag["env"][0] == "ARBORIST_MANIFEST=test1.json"
        assert any("duplicate" in f.lower() for f in fixes)

    def test_removes_duplicate_with_different_formats(self):
        """Test that duplicates are removed even with different formats."""
        dag = {"env": [
            "ARBORIST_MANIFEST=test1.json",
            {"ARBORIST_MANIFEST": "test2.json"},
        ]}
        fixes = _fix_env_format(dag)

        assert len(dag["env"]) == 1
        assert dag["env"][0] == "ARBORIST_MANIFEST=test1.json"

    def test_handles_missing_env(self):
        """Test that missing env section is handled gracefully."""
        dag = {"name": "test"}
        fixes = _fix_env_format(dag)

        assert fixes == []
        assert "env" not in dag


class TestTopologicalSortSteps:
    """Tests for _topological_sort_steps function."""

    def test_already_sorted(self):
        """Test that already sorted steps are not changed."""
        steps = [
            {"name": "step1", "command": "echo 1"},
            {"name": "step2", "command": "echo 2", "depends": ["step1"]},
            {"name": "step3", "command": "echo 3", "depends": ["step2"]},
        ]
        sorted_steps, fixes = _topological_sort_steps(steps)

        assert [s["name"] for s in sorted_steps] == ["step1", "step2", "step3"]

    def test_sorts_out_of_order_steps(self):
        """Test that out of order steps are sorted correctly."""
        steps = [
            {"name": "step3", "command": "echo 3", "depends": ["step2"]},
            {"name": "step1", "command": "echo 1"},
            {"name": "step2", "command": "echo 2", "depends": ["step1"]},
        ]
        sorted_steps, fixes = _topological_sort_steps(steps)

        names = [s["name"] for s in sorted_steps]
        assert names.index("step1") < names.index("step2")
        assert names.index("step2") < names.index("step3")
        assert len(fixes) == 1
        assert "Reordered" in fixes[0]

    def test_handles_parallel_dependencies(self):
        """Test sorting with parallel branches."""
        steps = [
            {"name": "complete", "command": "echo done", "depends": ["branch-a", "branch-b"]},
            {"name": "root", "command": "echo start"},
            {"name": "branch-a", "command": "echo a", "depends": ["root"]},
            {"name": "branch-b", "command": "echo b", "depends": ["root"]},
        ]
        sorted_steps, fixes = _topological_sort_steps(steps)

        names = [s["name"] for s in sorted_steps]
        # root must come before both branches
        assert names.index("root") < names.index("branch-a")
        assert names.index("root") < names.index("branch-b")
        # both branches must come before complete
        assert names.index("branch-a") < names.index("complete")
        assert names.index("branch-b") < names.index("complete")

    def test_detects_cycle(self):
        """Test that cycles are detected."""
        steps = [
            {"name": "step1", "command": "echo 1", "depends": ["step2"]},
            {"name": "step2", "command": "echo 2", "depends": ["step1"]},
        ]
        sorted_steps, fixes = _topological_sort_steps(steps)

        assert any("Cycle detected" in f for f in fixes)

    def test_handles_string_depends(self):
        """Test that string (non-list) depends is handled."""
        steps = [
            {"name": "step1", "command": "echo 1"},
            {"name": "step2", "command": "echo 2", "depends": "step1"},
        ]
        sorted_steps, fixes = _topological_sort_steps(steps)

        names = [s["name"] for s in sorted_steps]
        assert names.index("step1") < names.index("step2")

    def test_ignores_external_deps(self):
        """Test that dependencies on non-existent steps are ignored."""
        steps = [
            {"name": "step1", "command": "echo 1", "depends": ["external"]},
            {"name": "step2", "command": "echo 2", "depends": ["step1"]},
        ]
        sorted_steps, fixes = _topological_sort_steps(steps)

        names = [s["name"] for s in sorted_steps]
        assert names.index("step1") < names.index("step2")


class TestRemoveEmptyDepends:
    """Tests for _remove_empty_depends function."""

    def test_removes_empty_depends(self):
        """Test that empty depends arrays are removed."""
        dag = {"steps": [
            {"name": "step1", "command": "echo 1", "depends": []},
            {"name": "step2", "command": "echo 2", "depends": ["step1"]},
        ]}
        fixes = _remove_empty_depends(dag)

        assert "depends" not in dag["steps"][0]
        assert dag["steps"][1]["depends"] == ["step1"]
        assert len(fixes) == 1

    def test_preserves_non_empty_depends(self):
        """Test that non-empty depends are preserved."""
        dag = {"steps": [
            {"name": "step1", "command": "echo 1"},
            {"name": "step2", "command": "echo 2", "depends": ["step1"]},
        ]}
        fixes = _remove_empty_depends(dag)

        assert dag["steps"][1]["depends"] == ["step1"]
        assert len(fixes) == 0


class TestValidateAndFixDag:
    """Tests for validate_and_fix_dag function."""

    def test_fixes_all_issues(self):
        """Test that all issues are fixed in one call."""
        dag = {
            "name": "test",
            "env": [
                "ARBORIST_MANIFEST: test1.json",
                {"ARBORIST_MANIFEST": "test2.json"},
            ],
            "steps": [
                {"name": "step2", "command": "echo 2", "depends": ["step1"]},
                {"name": "step1", "command": "echo 1", "depends": []},
            ],
        }
        fixed_dag, fixes = validate_and_fix_dag(dag)

        # Env should be fixed (one entry, correct format)
        assert len(fixed_dag["env"]) == 1
        assert "=" in fixed_dag["env"][0]

        # Steps should be sorted
        assert fixed_dag["steps"][0]["name"] == "step1"
        assert fixed_dag["steps"][1]["name"] == "step2"

        # Empty depends should be removed
        assert "depends" not in fixed_dag["steps"][0]

        # Should have multiple fixes
        assert len(fixes) >= 3

    def test_returns_cycle_error(self):
        """Test that cycle detection error is propagated."""
        dag = {
            "name": "test",
            "steps": [
                {"name": "step1", "command": "echo 1", "depends": ["step2"]},
                {"name": "step2", "command": "echo 2", "depends": ["step1"]},
            ],
        }
        fixed_dag, fixes = validate_and_fix_dag(dag)

        assert any("Cycle detected" in f for f in fixes)

    def test_real_world_dag_structure(self):
        """Test with a real-world-like DAG structure."""
        dag = {
            "name": "hello_world",
            "description": "Test service",
            "env": [
                "ARBORIST_MANIFEST=hello_world.json",
                "ARBORIST_MANIFEST=hello-world.json",
            ],
            "steps": [
                {"name": "branches-setup", "command": "arborist spec branch-create-all", "depends": []},
                {"name": "T001-setup", "command": "arborist task pre-sync T001", "depends": ["branches-setup"]},
                {"name": "T001-complete", "command": "arborist task post-merge T001", "depends": ["T002-complete"]},
                {"name": "T002-setup", "command": "arborist task pre-sync T002", "depends": ["T001-setup"]},
                {"name": "T002-complete", "command": "arborist task post-merge T002", "depends": ["T003-leaf"]},
                {"name": "T003-leaf", "command": "arborist task run T003", "depends": ["T002-setup"]},
            ],
        }
        fixed_dag, fixes = validate_and_fix_dag(dag)

        # Should have only one env entry
        assert len(fixed_dag["env"]) == 1

        # Steps should be in topological order
        step_names = [s["name"] for s in fixed_dag["steps"]]
        assert step_names.index("branches-setup") < step_names.index("T001-setup")
        assert step_names.index("T001-setup") < step_names.index("T002-setup")
        assert step_names.index("T002-setup") < step_names.index("T003-leaf")
        assert step_names.index("T003-leaf") < step_names.index("T002-complete")
        assert step_names.index("T002-complete") < step_names.index("T001-complete")


class TestValidateAndFixMultiDoc:
    """Tests for validate_and_fix_multi_doc function."""

    def test_fixes_all_documents(self):
        """Test that fixes are applied to all documents."""
        documents = [
            {
                "name": "root",
                "env": ["KEY: value"],
                "steps": [
                    {"name": "step1", "command": "echo 1", "depends": []},
                ],
            },
            {
                "name": "T001",
                "steps": [
                    {"name": "step2", "command": "echo 2", "depends": ["step1"]},
                    {"name": "step1", "command": "echo 1"},
                ],
            },
        ]

        fixed_docs, fixes = validate_and_fix_multi_doc(documents)

        # Root env should be fixed
        assert "=" in fixed_docs[0]["env"][0]

        # Root empty depends should be removed
        assert "depends" not in fixed_docs[0]["steps"][0]

        # Subdag steps should be sorted
        assert fixed_docs[1]["steps"][0]["name"] == "step1"

        # Fixes should be prefixed with document names
        assert any("[root]" in f for f in fixes)
        assert any("[T001]" in f for f in fixes)

    def test_detects_cycle_in_subdag(self):
        """Test that cycle in a subdag is detected."""
        documents = [
            {
                "name": "root",
                "steps": [{"name": "c-T001", "call": "T001"}],
            },
            {
                "name": "T001",
                "steps": [
                    {"name": "step1", "command": "echo 1", "depends": ["step2"]},
                    {"name": "step2", "command": "echo 2", "depends": ["step1"]},
                ],
            },
        ]

        fixed_docs, fixes = validate_and_fix_multi_doc(documents)

        assert any("Cycle detected" in f and "T001" in f for f in fixes)

    def test_empty_documents_handled(self):
        """Test that empty document list is handled."""
        fixed_docs, fixes = validate_and_fix_multi_doc([])

        assert fixed_docs == []
        assert fixes == []
