"""Pytest configuration and shared fixtures for agent-arborist tests."""

import subprocess
from pathlib import Path
from dataclasses import dataclass, field

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
PROJECT_ROOT = Path(__file__).parent.parent


@pytest.fixture(autouse=True)
def _guard_project_repo(tmp_path, monkeypatch):
    """Prevent tests from accidentally modifying the project repo."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def git_repo(tmp_path):
    """Create a fresh git repo in an isolated temp directory."""
    repo_dir = tmp_path / "test-repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init", str(repo_dir)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"],
                   cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"],
                   cwd=repo_dir, check=True, capture_output=True)
    # Create initial commit so main exists
    (repo_dir / "README.md").write_text("# Test Repo\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial commit"],
                   cwd=repo_dir, check=True, capture_output=True)
    # Ensure branch is called main
    subprocess.run(["git", "branch", "-M", "main"],
                   cwd=repo_dir, check=True, capture_output=True)
    # Sanity: confirm this is NOT the project repo
    assert str(repo_dir) != str(PROJECT_ROOT)
    assert not (repo_dir / "pyproject.toml").exists()
    return repo_dir


@dataclass
class MockRunner:
    """Mock runner for testing."""
    implement_ok: bool = True
    review_ok: bool = True
    review_sequence: list[bool] = field(default_factory=list)
    _review_call: int = 0
    name: str = "mock"
    model: str = "mock-model"
    command: str = "mock"

    def run(self, prompt, timeout=60, cwd=None, container_workspace=None, **kwargs):
        from agent_arborist.runner import RunResult
        if "Review" in prompt or "review" in prompt:
            if self.review_sequence:
                ok = self.review_sequence[self._review_call % len(self.review_sequence)]
                self._review_call += 1
            else:
                ok = self.review_ok
            return RunResult(
                success=ok,
                output="APPROVED" if ok else "REJECTED: needs work",
            )
        return RunResult(
            success=self.implement_ok,
            output="Implementation complete",
        )

    def is_available(self):
        return True


@pytest.fixture
def mock_runner_all_pass():
    return MockRunner(implement_ok=True, review_ok=True)


@pytest.fixture
def mock_runner_reject_then_pass():
    return MockRunner(implement_ok=True, review_sequence=[False, True])


@pytest.fixture
def mock_runner_always_reject():
    return MockRunner(implement_ok=True, review_ok=False)


@dataclass
class TrackingRunner:
    """Runner that records all prompts it receives."""
    implement_ok: bool = True
    review_ok: bool = True
    prompts: list = field(default_factory=list)
    timeouts: list = field(default_factory=list)
    name: str = "tracking"
    model: str = "mock-model"
    command: str = "mock"

    def run(self, prompt, timeout=600, cwd=None, container_workspace=None, **kwargs):
        from agent_arborist.runner import RunResult
        self.prompts.append(prompt)
        self.timeouts.append(timeout)
        if "review" in prompt.lower():
            ok = self.review_ok
            return RunResult(success=ok, output="APPROVED" if ok else "REJECTED: needs work")
        return RunResult(success=self.implement_ok, output="Implementation complete")

    def is_available(self):
        return True


@dataclass
class CrashingRunner:
    """Runner that raises after N successful run() calls."""
    crash_after: int = 1
    _call_count: int = 0
    name: str = "crashing"
    model: str = "mock-model"
    command: str = "mock"

    def run(self, prompt, timeout=60, cwd=None, container_workspace=None, **kwargs):
        from agent_arborist.runner import RunResult
        self._call_count += 1
        if self._call_count > self.crash_after:
            raise RuntimeError(f"CrashingRunner: boom on call {self._call_count}")
        if "Review" in prompt or "review" in prompt:
            return RunResult(success=True, output="APPROVED")
        return RunResult(success=True, output="Implementation complete")

    def is_available(self):
        return True
