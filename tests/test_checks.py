"""Tests for dependency checks."""

from unittest.mock import patch, MagicMock
import subprocess

from agent_arborist.checks import (
    DependencyStatus,
    check_dagu,
    check_claude,
    check_opencode,
    check_gemini,
    check_runtimes,
    _version_lt,
)


class TestVersionComparison:
    def test_version_lt_simple(self):
        assert _version_lt("1.0.0", "2.0.0")
        assert _version_lt("1.0.0", "1.1.0")
        assert _version_lt("1.0.0", "1.0.1")

    def test_version_not_lt(self):
        assert not _version_lt("2.0.0", "1.0.0")
        assert not _version_lt("1.1.0", "1.0.0")
        assert not _version_lt("1.0.1", "1.0.0")

    def test_version_equal(self):
        assert not _version_lt("1.0.0", "1.0.0")
        assert not _version_lt("1.30.3", "1.30.3")

    def test_version_with_prefix(self):
        assert _version_lt("v1.0.0", "v2.0.0")
        assert _version_lt("v1.0.0", "2.0.0")

    def test_version_with_suffix(self):
        assert _version_lt("1.0.0-beta", "1.0.1")
        assert _version_lt("1.0.0-rc1", "1.0.1")


class TestDependencyStatus:
    def test_ok_when_installed_no_error(self):
        status = DependencyStatus(name="test", installed=True, version="1.0.0")
        assert status.ok

    def test_not_ok_when_not_installed(self):
        status = DependencyStatus(name="test", installed=False)
        assert not status.ok

    def test_not_ok_when_error(self):
        status = DependencyStatus(name="test", installed=True, error="some error")
        assert not status.ok


class TestCheckDagu:
    @patch("agent_arborist.checks.shutil.which")
    def test_dagu_not_found(self, mock_which):
        mock_which.return_value = None
        result = check_dagu()
        assert not result.installed
        assert result.error == "dagu not found in PATH"

    @patch("agent_arborist.checks.subprocess.run")
    @patch("agent_arborist.checks.shutil.which")
    def test_dagu_found_version_ok(self, mock_which, mock_run):
        mock_which.return_value = "/usr/bin/dagu"
        mock_run.return_value = MagicMock(stdout="1.30.3", stderr="")

        result = check_dagu(min_version="1.30.3")
        assert result.installed
        assert result.ok
        assert result.version == "1.30.3"
        assert result.path == "/usr/bin/dagu"

    @patch("agent_arborist.checks.subprocess.run")
    @patch("agent_arborist.checks.shutil.which")
    def test_dagu_version_too_old(self, mock_which, mock_run):
        mock_which.return_value = "/usr/bin/dagu"
        mock_run.return_value = MagicMock(stdout="1.20.0", stderr="")

        result = check_dagu(min_version="1.30.3")
        assert result.installed
        assert not result.ok
        assert "1.20.0 < required 1.30.3" in result.error

    @patch("agent_arborist.checks.subprocess.run")
    @patch("agent_arborist.checks.shutil.which")
    def test_dagu_timeout(self, mock_which, mock_run):
        mock_which.return_value = "/usr/bin/dagu"
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="dagu", timeout=10)

        result = check_dagu()
        assert result.installed
        assert not result.ok
        assert "timed out" in result.error


class TestCheckRuntimes:
    @patch("agent_arborist.checks.shutil.which")
    def test_no_runtimes_found(self, mock_which):
        mock_which.return_value = None
        results = check_runtimes()
        assert len(results) == 3
        assert all(not r.installed for r in results)

    @patch("agent_arborist.checks.subprocess.run")
    @patch("agent_arborist.checks.shutil.which")
    def test_one_runtime_found(self, mock_which, mock_run):
        def which_side_effect(name):
            return "/usr/bin/claude" if name == "claude" else None

        mock_which.side_effect = which_side_effect
        mock_run.return_value = MagicMock(stdout="1.0.0", stderr="")

        results = check_runtimes()
        assert len(results) == 3

        claude = next(r for r in results if r.name == "claude")
        assert claude.installed
        assert claude.ok

        opencode = next(r for r in results if r.name == "opencode")
        assert not opencode.installed

    @patch("agent_arborist.checks.subprocess.run")
    @patch("agent_arborist.checks.shutil.which")
    def test_all_runtimes_found(self, mock_which, mock_run):
        mock_which.return_value = "/usr/bin/runtime"
        mock_run.return_value = MagicMock(stdout="1.0.0", stderr="")

        results = check_runtimes()
        assert len(results) == 3
        assert all(r.installed for r in results)
        assert all(r.ok for r in results)
