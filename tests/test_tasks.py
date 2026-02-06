"""Tests for tasks module."""

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from agent_arborist.tasks import (
    JJResult,
    ChangeInfo,
    TaskChange,
    is_jj_installed,
    is_jj_repo,
    is_colocated,
    run_jj,
    get_change_id,
    get_commit_id,
    get_change_info,
    get_description,
    has_conflicts,
    create_change,
    create_task_change,
    describe_change,
    edit_change,
    squash_into_parent,
    rebase_change,
    get_workspace_path,
    list_workspaces,
    workspace_exists,
    create_workspace,
    complete_task,
    sync_parent,
    find_pending_children,
    find_tasks_by_spec,
    find_task_change,
    get_task_status,
    get_operation_log,
    undo_operation,
    restore_operation,
    init_colocated,
    JJNotInstalledError,
)


class TestJJInstallation:
    """Tests for jj installation detection."""

    def test_is_jj_installed_true(self):
        """Returns True when jj is available."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert is_jj_installed() is True

    def test_is_jj_installed_false(self):
        """Returns False when jj is not found."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            assert is_jj_installed() is False


class TestRunJJ:
    """Tests for run_jj helper function."""

    def test_run_jj_success(self):
        """Runs jj command successfully."""
        with patch("agent_arborist.tasks.is_jj_installed", return_value=True):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout="output",
                    stderr="",
                )
                with patch("agent_arborist.tasks.get_git_root", return_value=Path("/tmp")):
                    result = run_jj("log")
                    assert result.returncode == 0
                    mock_run.assert_called_once()

    def test_run_jj_not_installed(self):
        """Raises JJNotInstalledError when jj not installed."""
        with patch("agent_arborist.tasks.is_jj_installed", return_value=False):
            with pytest.raises(JJNotInstalledError):
                run_jj("log")


class TestChangeOperations:
    """Tests for change creation and management."""

    def test_get_change_id(self):
        """Gets change ID from revset."""
        with patch("agent_arborist.tasks.run_jj") as mock_run:
            mock_run.return_value = MagicMock(stdout="qpvuntsm\n")
            result = get_change_id("@")
            assert result == "qpvuntsm"

    def test_get_commit_id(self):
        """Gets commit ID from revset."""
        with patch("agent_arborist.tasks.run_jj") as mock_run:
            mock_run.return_value = MagicMock(stdout="abc123def456\n")
            result = get_commit_id("@")
            assert result == "abc123def456"

    def test_get_description(self):
        """Gets description from change."""
        with patch("agent_arborist.tasks.run_jj") as mock_run:
            mock_run.return_value = MagicMock(stdout="spec:123:T001\n")
            result = get_description("qpvuntsm")
            assert result == "spec:123:T001"

    def test_has_conflicts_true(self):
        """Detects conflicts in a change."""
        with patch("agent_arborist.tasks.run_jj") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="qpvuntsm\n",
            )
            result = has_conflicts("qpvuntsm")
            assert result is True

    def test_has_conflicts_false(self):
        """No conflicts detected."""
        with patch("agent_arborist.tasks.run_jj") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="",
            )
            result = has_conflicts("qpvuntsm")
            assert result is False


class TestCreateChange:
    """Tests for change creation."""

    def test_create_change(self):
        """Creates a new change."""
        with patch("agent_arborist.tasks.run_jj"):
            with patch("agent_arborist.tasks.get_change_id", return_value="newchange"):
                result = create_change(parent="main", description="test")
                assert result == "newchange"

    def test_create_task_change(self):
        """Creates a task change with proper description."""
        with patch("agent_arborist.tasks.create_change", return_value="taskchange") as mock_create:
            result = create_task_change(
                spec_id="002-feature",
                task_id="T001",
                parent_change="main",
            )
            assert result == "taskchange"
            mock_create.assert_called_once()
            # Check description format - now uses hierarchical format spec_id:task_path
            call_args = mock_create.call_args
            assert "002-feature:T001" in call_args.kwargs["description"]

    def test_create_task_change_with_task_path(self):
        """Creates task change with hierarchical task path."""
        with patch("agent_arborist.tasks.create_change", return_value="taskchange") as mock_create:
            create_task_change(
                spec_id="002-feature",
                task_id="T004",
                parent_change="t001change",
                task_path=["T001", "T004"],  # T004 is child of T001
            )
            call_args = mock_create.call_args
            # Should use full hierarchical path
            assert "002-feature:T001:T004" in call_args.kwargs["description"]


class TestDescribeChange:
    """Tests for describe_change."""

    def test_describe_change_success(self):
        """Successfully updates description."""
        with patch("agent_arborist.tasks.run_jj") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = describe_change("new description", "@")
            assert result.success is True

    def test_describe_change_failure(self):
        """Handles describe failure."""
        with patch("agent_arborist.tasks.run_jj") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
            result = describe_change("new description", "@")
            assert result.success is False
            assert result.error == "error"


class TestSquashAndRebase:
    """Tests for squash and rebase operations."""

    def test_squash_into_parent_success(self):
        """Successfully squashes child into parent."""
        with patch("agent_arborist.tasks.run_jj") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            with patch("agent_arborist.tasks.has_conflicts", return_value=False):
                result = squash_into_parent("child", "parent")
                assert result.success is True
                assert "Squashed child into parent" in result.message

    def test_squash_with_conflicts(self):
        """Detects conflicts after squash."""
        with patch("agent_arborist.tasks.run_jj") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            with patch("agent_arborist.tasks.has_conflicts", return_value=True):
                result = squash_into_parent("child", "parent")
                assert result.success is True
                assert "conflicts detected" in result.message

    def test_rebase_change_success(self):
        """Successfully rebases change."""
        with patch("agent_arborist.tasks.run_jj") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = rebase_change("change", "destination")
            assert result.success is True


class TestWorkspaceManagement:
    """Tests for workspace operations."""

    def test_get_workspace_path(self, tmp_path, monkeypatch):
        """Returns correct workspace path."""
        from agent_arborist import tasks
        monkeypatch.setattr(tasks, "get_arborist_home", lambda: tmp_path)

        path = get_workspace_path("002-feature", "T001")
        expected = tmp_path / "workspaces" / "002-feature" / "T001"
        assert path == expected

    def test_list_workspaces(self):
        """Lists workspaces from jj output."""
        with patch("agent_arborist.tasks.run_jj") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="default: /path/to/repo\nws-T001: /path/to/ws1\n",
            )
            workspaces = list_workspaces()
            assert "default" in workspaces
            assert "ws-T001" in workspaces

    def test_workspace_exists_true(self):
        """Returns True for existing workspace."""
        with patch("agent_arborist.tasks.list_workspaces", return_value=["default", "ws-T001"]):
            assert workspace_exists("ws-T001") is True

    def test_workspace_exists_false(self):
        """Returns False for non-existent workspace."""
        with patch("agent_arborist.tasks.list_workspaces", return_value=["default"]):
            assert workspace_exists("ws-T001") is False


class TestTaskLifecycle:
    """Tests for task lifecycle operations."""

    def test_complete_task(self):
        """Marks task complete and squashes."""
        with patch("agent_arborist.tasks.get_description", return_value="spec:123:T001"):
            with patch("agent_arborist.tasks.describe_change"):
                with patch("agent_arborist.tasks.squash_into_parent") as mock_squash:
                    mock_squash.return_value = JJResult(success=True, message="ok")
                    result = complete_task("T001", "child", "parent")
                    assert result.success is True
                    mock_squash.assert_called_once()

    def test_sync_parent_no_conflicts(self):
        """Syncs parent without conflicts."""
        with patch("agent_arborist.tasks.has_conflicts", return_value=False):
            with patch("agent_arborist.tasks.find_pending_children", return_value=["child1"]):
                with patch("agent_arborist.tasks.rebase_change") as mock_rebase:
                    mock_rebase.return_value = JJResult(success=True, message="ok")
                    result = sync_parent("parent", "spec123")
                    assert result["conflicts_found"] is False
                    assert "child1" in result["children_rebased"]

    def test_sync_parent_with_conflicts(self):
        """Syncs parent and detects conflicts."""
        with patch("agent_arborist.tasks.has_conflicts", return_value=True):
            with patch("agent_arborist.tasks.get_description", return_value="spec:123:T002"):
                with patch("agent_arborist.tasks.describe_change"):
                    with patch("agent_arborist.tasks.find_pending_children", return_value=[]):
                        result = sync_parent("parent", "spec123")
                        assert result["conflicts_found"] is True
                        assert result["needs_resolution"] is True


class TestQueryFunctions:
    """Tests for revset query functions."""

    def test_find_tasks_by_spec(self):
        """Finds tasks by spec ID."""
        with patch("agent_arborist.tasks.run_jj") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="qpvuntsm|spec:002-feature:T001\nrrrrrrrr|spec:002-feature:T002 [DONE]\n",
            )
            with patch("agent_arborist.tasks.has_conflicts", return_value=False):
                tasks = find_tasks_by_spec("002-feature")
                assert len(tasks) == 2
                assert tasks[0].task_id == "T001"
                assert tasks[0].status == "pending"
                assert tasks[1].task_id == "T002"
                assert tasks[1].status == "done"

    def test_find_task_change(self):
        """Finds specific task change."""
        with patch("agent_arborist.tasks.run_jj") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="qpvuntsm\n",
            )
            with patch("agent_arborist.tasks.get_description", return_value="spec:002:T001"):
                with patch("agent_arborist.tasks.has_conflicts", return_value=False):
                    task = find_task_change("002", "T001")
                    assert task is not None
                    assert task.change_id == "qpvuntsm"
                    assert task.task_id == "T001"

    def test_find_task_change_not_found(self):
        """Returns None when task not found."""
        with patch("agent_arborist.tasks.run_jj") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="",
            )
            task = find_task_change("002", "T999")
            assert task is None

    def test_get_task_status(self):
        """Gets task status summary."""
        mock_tasks = [
            TaskChange(
                change_id="a",
                task_id="T001",
                spec_id="002",
                parent_change=None,
                status="pending",
            ),
            TaskChange(
                change_id="b",
                task_id="T002",
                spec_id="002",
                parent_change=None,
                status="done",
            ),
            TaskChange(
                change_id="c",
                task_id="T003",
                spec_id="002",
                parent_change=None,
                status="conflict",
            ),
        ]
        with patch("agent_arborist.tasks.find_tasks_by_spec", return_value=mock_tasks):
            status = get_task_status("002")
            assert status["total"] == 3
            assert status["pending"] == 1
            assert status["done"] == 1
            assert status["conflict"] == 1


class TestOperationLog:
    """Tests for operation log functions."""

    def test_get_operation_log(self):
        """Gets recent operations."""
        with patch("agent_arborist.tasks.run_jj") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="abc123|new commit\ndef456|rebase\n",
            )
            ops = get_operation_log(limit=5)
            assert len(ops) == 2
            assert ops[0]["id"] == "abc123"
            assert ops[0]["description"] == "new commit"

    def test_undo_operation(self):
        """Undoes last operation."""
        with patch("agent_arborist.tasks.run_jj") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = undo_operation()
            assert result.success is True

    def test_restore_operation(self):
        """Restores to specific operation."""
        with patch("agent_arborist.tasks.run_jj") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = restore_operation("abc123")
            assert result.success is True


class TestInitColocated:
    """Tests for colocated initialization."""

    def test_init_colocated_already_exists(self, tmp_path):
        """Handles already colocated repo."""
        # Create .jj and .git dirs
        (tmp_path / ".jj").mkdir()
        (tmp_path / ".git").mkdir()

        with patch("agent_arborist.tasks.get_git_root", return_value=tmp_path):
            result = init_colocated(tmp_path)
            assert result.success is True
            assert "already colocated" in result.message

    def test_init_colocated_jj_only(self, tmp_path):
        """Handles jj-only repo (not colocated)."""
        (tmp_path / ".jj").mkdir()

        with patch("agent_arborist.tasks.get_git_root", return_value=tmp_path):
            result = init_colocated(tmp_path)
            assert result.success is False
            assert "not a colocated repo" in result.message


class TestChangeInfo:
    """Tests for ChangeInfo dataclass."""

    def test_get_change_info(self):
        """Parses change info from jj output."""
        with patch("agent_arborist.tasks.run_jj") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="qpvuntsm\nabc123\nMy commit\ntest@test.com\nfalse\nfalse",
            )
            info = get_change_info("@")
            assert info.change_id == "qpvuntsm"
            assert info.commit_id == "abc123"
            assert info.description == "My commit"
            assert info.author == "test@test.com"
            assert info.is_empty is False
            assert info.has_conflict is False


class TestFindPendingChildren:
    """Tests for find_pending_children."""

    def test_find_pending_children(self):
        """Finds pending children of a change."""
        with patch("agent_arborist.tasks.run_jj") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="child1\nchild2\n",
            )
            children = find_pending_children("parent")
            assert len(children) == 2
            assert "child1" in children
            assert "child2" in children

    def test_find_pending_children_empty(self):
        """Returns empty list when no children."""
        with patch("agent_arborist.tasks.run_jj") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="",
            )
            children = find_pending_children("parent")
            assert len(children) == 0
