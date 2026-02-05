"""Tests for jj_manifest module."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from agent_arborist.jj_manifest import (
    TaskChangeInfo,
    ChangeManifest,
    generate_manifest,
    save_manifest,
    load_manifest,
    get_manifest_path,
    get_manifest_path_from_env,
    load_manifest_from_env,
    find_manifest_path,
    topological_sort,
    create_all_changes_from_manifest,
    refresh_manifest_from_repo,
    is_jj_manifest,
    detect_manifest_type,
)
from agent_arborist.task_state import TaskTree, TaskNode


class TestTaskChangeInfo:
    """Tests for TaskChangeInfo dataclass."""

    def test_create_task_change_info(self):
        """Creates TaskChangeInfo with all fields."""
        info = TaskChangeInfo(
            task_id="T001",
            change_id="qpvuntsm",
            parent_change="main",
            parent_task=None,
            children=["T004", "T005"],
            depends_on=["T002"],
        )
        assert info.task_id == "T001"
        assert info.change_id == "qpvuntsm"
        assert info.parent_change == "main"
        assert info.parent_task is None
        assert info.children == ["T004", "T005"]
        assert info.depends_on == ["T002"]


class TestChangeManifest:
    """Tests for ChangeManifest dataclass."""

    def test_create_manifest(self):
        """Creates ChangeManifest with tasks."""
        manifest = ChangeManifest(
            spec_id="002-feature",
            base_change="mainchange",
            source_rev="main",
            created_at="2025-01-01T00:00:00Z",
        )
        manifest.tasks["T001"] = TaskChangeInfo(
            task_id="T001",
            change_id="qpvuntsm",
            parent_change="mainchange",
            parent_task=None,
        )

        assert manifest.spec_id == "002-feature"
        assert manifest.vcs == "jj"
        assert manifest.get_task("T001") is not None
        assert manifest.get_change_id("T001") == "qpvuntsm"
        assert manifest.get_parent_change("T001") == "mainchange"

    def test_get_task_not_found(self):
        """Returns None for non-existent task."""
        manifest = ChangeManifest(
            spec_id="002-feature",
            base_change="main",
            source_rev="main",
            created_at="2025-01-01T00:00:00Z",
        )
        assert manifest.get_task("T999") is None
        assert manifest.get_change_id("T999") is None
        assert manifest.get_parent_change("T999") is None


class TestGenerateManifest:
    """Tests for manifest generation."""

    def test_generate_manifest_without_creating_changes(self):
        """Generates manifest with placeholder IDs."""
        tree = TaskTree(spec_id="002-feature")
        tree.tasks["T001"] = TaskNode(
            task_id="T001",
            description="First task",
            parent_id=None,
            children=["T004"],
        )
        tree.tasks["T004"] = TaskNode(
            task_id="T004",
            description="Child task",
            parent_id="T001",
            children=[],
        )
        tree.root_tasks = ["T001"]

        manifest = generate_manifest(
            spec_id="002-feature",
            task_tree=tree,
            source_rev="main",
            create_changes=False,  # Don't actually create jj changes
        )

        assert manifest.spec_id == "002-feature"
        assert manifest.source_rev == "main"
        assert manifest.vcs == "jj"

        # Check tasks
        assert "T001" in manifest.tasks
        assert "T004" in manifest.tasks

        t001 = manifest.tasks["T001"]
        assert t001.parent_change == "main"  # Base change
        assert t001.parent_task is None

        t004 = manifest.tasks["T004"]
        assert t004.parent_change == t001.change_id  # Parent task's change
        assert t004.parent_task == "T001"

    def test_generate_manifest_multiple_roots(self):
        """Generates manifest with multiple root tasks."""
        tree = TaskTree(spec_id="002-feature")
        tree.tasks["T001"] = TaskNode(
            task_id="T001",
            description="First root",
            parent_id=None,
            children=[],
        )
        tree.tasks["T002"] = TaskNode(
            task_id="T002",
            description="Second root",
            parent_id=None,
            children=[],
        )
        tree.root_tasks = ["T001", "T002"]

        manifest = generate_manifest(
            spec_id="002-feature",
            task_tree=tree,
            source_rev="main",
            create_changes=False,
        )

        # Both should have base as parent
        assert manifest.tasks["T001"].parent_change == "main"
        assert manifest.tasks["T002"].parent_change == "main"


class TestSaveAndLoadManifest:
    """Tests for manifest persistence."""

    def test_save_manifest(self, tmp_path):
        """Saves manifest to JSON file."""
        manifest = ChangeManifest(
            spec_id="002-feature",
            base_change="mainchange",
            source_rev="main",
            created_at="2025-01-01T00:00:00Z",
        )
        manifest.tasks["T001"] = TaskChangeInfo(
            task_id="T001",
            change_id="qpvuntsm",
            parent_change="mainchange",
            parent_task=None,
            children=["T004"],
        )

        manifest_path = tmp_path / "manifest.json"
        save_manifest(manifest, manifest_path)

        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text())
        assert data["spec_id"] == "002-feature"
        assert data["vcs"] == "jj"
        assert "T001" in data["tasks"]

    def test_load_manifest(self, tmp_path):
        """Loads manifest from JSON file."""
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps({
            "spec_id": "002-feature",
            "base_change": "mainchange",
            "source_rev": "main",
            "created_at": "2025-01-01T00:00:00Z",
            "vcs": "jj",
            "tasks": {
                "T001": {
                    "task_id": "T001",
                    "change_id": "qpvuntsm",
                    "parent_change": "mainchange",
                    "parent_task": None,
                    "children": ["T004"],
                    "depends_on": [],
                }
            }
        }))

        manifest = load_manifest(manifest_path)
        assert manifest.spec_id == "002-feature"
        assert manifest.vcs == "jj"
        assert manifest.tasks["T001"].change_id == "qpvuntsm"

    def test_load_manifest_not_found(self, tmp_path):
        """Raises FileNotFoundError for missing manifest."""
        with pytest.raises(FileNotFoundError):
            load_manifest(tmp_path / "nonexistent.json")

    def test_load_manifest_not_jj(self, tmp_path):
        """Raises ValueError for non-jj manifest."""
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps({
            "spec_id": "002-feature",
            "source_branch": "main",
            "base_branch": "main_a",
            "created_at": "2025-01-01T00:00:00Z",
            # No "vcs" field, defaults to "git"
        }))

        with pytest.raises(ValueError, match="Not a jj manifest"):
            load_manifest(manifest_path)


class TestManifestPathFunctions:
    """Tests for manifest path functions."""

    def test_get_manifest_path(self, tmp_path, monkeypatch):
        """Returns correct manifest path."""
        from agent_arborist import jj_manifest
        monkeypatch.setattr(jj_manifest, "get_arborist_home", lambda: tmp_path)

        path = get_manifest_path("002-feature")
        expected = tmp_path / "dagu" / "dags" / "002-feature.json"
        assert path == expected

    def test_get_manifest_path_from_env(self, monkeypatch):
        """Gets path from environment variable."""
        monkeypatch.setenv("ARBORIST_MANIFEST", "/path/to/manifest.json")
        path = get_manifest_path_from_env()
        assert path == Path("/path/to/manifest.json")

    def test_get_manifest_path_from_env_not_set(self, monkeypatch):
        """Returns None when env var not set."""
        monkeypatch.delenv("ARBORIST_MANIFEST", raising=False)
        path = get_manifest_path_from_env()
        assert path is None

    def test_load_manifest_from_env(self, tmp_path, monkeypatch):
        """Loads manifest from env var path."""
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps({
            "spec_id": "002-feature",
            "base_change": "main",
            "source_rev": "main",
            "created_at": "2025-01-01T00:00:00Z",
            "vcs": "jj",
            "tasks": {},
        }))

        monkeypatch.setenv("ARBORIST_MANIFEST", str(manifest_path))
        manifest = load_manifest_from_env()
        assert manifest.spec_id == "002-feature"

    def test_load_manifest_from_env_not_set(self, monkeypatch):
        """Raises ValueError when env var not set."""
        monkeypatch.delenv("ARBORIST_MANIFEST", raising=False)
        with pytest.raises(ValueError, match="not set"):
            load_manifest_from_env()

    def test_find_manifest_path(self, tmp_path):
        """Finds manifest in search paths."""
        # Create manifest in first search location
        dags_dir = tmp_path / ".arborist" / "dagu" / "dags"
        dags_dir.mkdir(parents=True)
        manifest_path = dags_dir / "002-feature.json"
        manifest_path.write_text("{}")

        found = find_manifest_path("002-feature", tmp_path)
        assert found == manifest_path

    def test_find_manifest_path_not_found(self, tmp_path):
        """Returns None when manifest not found."""
        found = find_manifest_path("nonexistent", tmp_path)
        assert found is None


class TestTopologicalSort:
    """Tests for topological sort."""

    def test_topological_sort_simple(self):
        """Sorts parent before child."""
        tasks = {
            "T001": TaskChangeInfo(
                task_id="T001",
                change_id="a",
                parent_change="main",
                parent_task=None,
                children=["T004"],
            ),
            "T004": TaskChangeInfo(
                task_id="T004",
                change_id="b",
                parent_change="a",
                parent_task="T001",
                children=[],
            ),
        }

        order = topological_sort(tasks)
        assert order.index("T001") < order.index("T004")

    def test_topological_sort_multiple_roots(self):
        """Handles multiple root tasks."""
        tasks = {
            "T001": TaskChangeInfo(
                task_id="T001",
                change_id="a",
                parent_change="main",
                parent_task=None,
            ),
            "T002": TaskChangeInfo(
                task_id="T002",
                change_id="b",
                parent_change="main",
                parent_task=None,
            ),
        }

        order = topological_sort(tasks)
        assert len(order) == 2
        assert set(order) == {"T001", "T002"}

    def test_topological_sort_deep_hierarchy(self):
        """Handles deep task hierarchies."""
        tasks = {
            "T001": TaskChangeInfo(
                task_id="T001",
                change_id="a",
                parent_change="main",
                parent_task=None,
                children=["T002"],
            ),
            "T002": TaskChangeInfo(
                task_id="T002",
                change_id="b",
                parent_change="a",
                parent_task="T001",
                children=["T003"],
            ),
            "T003": TaskChangeInfo(
                task_id="T003",
                change_id="c",
                parent_change="b",
                parent_task="T002",
            ),
        }

        order = topological_sort(tasks)
        assert order.index("T001") < order.index("T002")
        assert order.index("T002") < order.index("T003")


class TestCreateAllChanges:
    """Tests for create_all_changes_from_manifest."""

    def test_create_all_changes_existing(self):
        """Verifies existing changes."""
        manifest = ChangeManifest(
            spec_id="002-feature",
            base_change="main",
            source_rev="main",
            created_at="2025-01-01T00:00:00Z",
        )
        manifest.tasks["T001"] = TaskChangeInfo(
            task_id="T001",
            change_id="existing",
            parent_change="main",
            parent_task=None,
        )

        with patch("agent_arborist.jj_tasks.run_jj") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="existing\n",
            )
            result = create_all_changes_from_manifest(manifest)
            assert "existing" in result["verified"]
            assert len(result["created"]) == 0

    def test_create_all_changes_missing(self):
        """Creates missing changes."""
        manifest = ChangeManifest(
            spec_id="002-feature",
            base_change="main",
            source_rev="main",
            created_at="2025-01-01T00:00:00Z",
        )
        manifest.tasks["T001"] = TaskChangeInfo(
            task_id="T001",
            change_id="missing",
            parent_change="main",
            parent_task=None,
        )

        with patch("agent_arborist.jj_tasks.run_jj") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,  # Change not found
                stdout="",
            )
            with patch("agent_arborist.jj_tasks.create_task_change", return_value="newchange"):
                result = create_all_changes_from_manifest(manifest)
                assert "newchange" in result["created"]


class TestRefreshManifest:
    """Tests for refresh_manifest_from_repo."""

    def test_refresh_manifest_no_tasks(self):
        """Returns None when no tasks found."""
        with patch("agent_arborist.jj_tasks.find_tasks_by_spec", return_value=[]):
            result = refresh_manifest_from_repo("002-feature")
            assert result is None

    def test_refresh_manifest_with_tasks(self):
        """Rebuilds manifest from repo."""
        from agent_arborist.jj_tasks import TaskChange

        mock_tasks = [
            TaskChange(
                change_id="a",
                task_id="T001",
                spec_id="002-feature",
                parent_change=None,
                status="pending",
            ),
            TaskChange(
                change_id="b",
                task_id="T002",
                spec_id="002-feature",
                parent_change=None,
                status="done",
            ),
        ]

        with patch("agent_arborist.jj_tasks.find_tasks_by_spec", return_value=mock_tasks):
            with patch("agent_arborist.jj_tasks.get_change_id", return_value="mainchange"):
                with patch("agent_arborist.jj_tasks.run_jj") as mock_run:
                    mock_run.return_value = MagicMock(returncode=0, stdout="")
                    manifest = refresh_manifest_from_repo("002-feature")

                    assert manifest is not None
                    assert manifest.spec_id == "002-feature"
                    assert "T001" in manifest.tasks
                    assert "T002" in manifest.tasks


class TestManifestTypeDetection:
    """Tests for manifest type detection."""

    def test_is_jj_manifest_true(self, tmp_path):
        """Returns True for jj manifest."""
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps({"vcs": "jj"}))
        assert is_jj_manifest(manifest_path) is True

    def test_is_jj_manifest_false(self, tmp_path):
        """Returns False for git manifest."""
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps({"source_branch": "main"}))
        assert is_jj_manifest(manifest_path) is False

    def test_is_jj_manifest_not_found(self, tmp_path):
        """Returns False for missing file."""
        assert is_jj_manifest(tmp_path / "nonexistent.json") is False

    def test_detect_manifest_type_jj(self, tmp_path):
        """Detects jj manifest type."""
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps({"vcs": "jj"}))
        assert detect_manifest_type(manifest_path) == "jj"

    def test_detect_manifest_type_git(self, tmp_path):
        """Detects git manifest type."""
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps({
            "source_branch": "main",
            "base_branch": "main_a",
        }))
        assert detect_manifest_type(manifest_path) == "git"

    def test_detect_manifest_type_unknown(self, tmp_path):
        """Returns unknown for unrecognized format."""
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps({"foo": "bar"}))
        assert detect_manifest_type(manifest_path) == "unknown"
