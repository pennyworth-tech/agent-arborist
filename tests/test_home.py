"""Tests for arborist home directory management."""

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_arborist.home import (
    get_git_root,
    get_arborist_home,
    get_dagu_home,
    is_initialized,
    init_arborist_home,
    ArboristHomeError,
    ARBORIST_DIR_NAME,
    DAGU_DIR_NAME,
    ENV_VAR_NAME,
)


@pytest.fixture
def git_repo(tmp_path):
    """Create a temporary git repository."""
    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    subprocess.run(["git", "init"], capture_output=True, check=True)
    # Create initial commit so HEAD exists
    readme = tmp_path / "README.md"
    readme.write_text("# Test\n")
    subprocess.run(["git", "add", "."], capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        capture_output=True,
        check=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@test.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@test.com",
        },
    )
    yield tmp_path
    os.chdir(original_cwd)


@pytest.fixture
def non_git_dir(tmp_path):
    """Create a temporary directory that is not a git repo."""
    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    yield tmp_path
    os.chdir(original_cwd)


class TestGetGitRoot:
    def test_returns_git_root(self, git_repo):
        result = get_git_root()
        assert result == git_repo

    def test_returns_git_root_from_subdirectory(self, git_repo):
        subdir = git_repo / "subdir" / "nested"
        subdir.mkdir(parents=True)
        os.chdir(subdir)
        result = get_git_root()
        assert result == git_repo

    def test_returns_none_outside_git_repo(self, non_git_dir):
        result = get_git_root()
        assert result is None


class TestGetArboristHome:
    def test_explicit_override_takes_precedence(self, git_repo):
        override = Path("/custom/path")
        result = get_arborist_home(override=override)
        assert result == override

    def test_env_var_takes_precedence_over_git(self, git_repo, monkeypatch):
        env_path = "/env/arborist/home"
        monkeypatch.setenv(ENV_VAR_NAME, env_path)
        result = get_arborist_home()
        assert result == Path(env_path)

    def test_uses_git_root_by_default(self, git_repo):
        result = get_arborist_home()
        assert result == git_repo / ARBORIST_DIR_NAME

    def test_raises_when_not_in_git_and_no_env(self, non_git_dir, monkeypatch):
        monkeypatch.delenv(ENV_VAR_NAME, raising=False)
        with pytest.raises(ArboristHomeError) as exc_info:
            get_arborist_home()
        assert "git repository" in str(exc_info.value).lower()

    def test_override_string_converted_to_path(self, git_repo):
        result = get_arborist_home(override="/some/path")
        assert result == Path("/some/path")
        assert isinstance(result, Path)


class TestGetDaguHome:
    def test_returns_dagu_subdir(self, git_repo):
        arborist_home = git_repo / ARBORIST_DIR_NAME
        result = get_dagu_home(arborist_home)
        assert result == arborist_home / DAGU_DIR_NAME

    def test_uses_get_arborist_home_by_default(self, git_repo):
        result = get_dagu_home()
        expected = git_repo / ARBORIST_DIR_NAME / DAGU_DIR_NAME
        assert result == expected


class TestIsInitialized:
    def test_returns_false_when_not_initialized(self, git_repo):
        assert not is_initialized()

    def test_returns_true_when_initialized(self, git_repo):
        arborist_dir = git_repo / ARBORIST_DIR_NAME
        arborist_dir.mkdir()
        assert is_initialized()

    def test_returns_false_outside_git_repo(self, non_git_dir):
        assert not is_initialized()

    def test_accepts_explicit_path(self, tmp_path):
        assert not is_initialized(tmp_path / "nonexistent")

        existing = tmp_path / "existing"
        existing.mkdir()
        assert is_initialized(existing)


class TestInitArboristHome:
    def test_creates_arborist_directory(self, git_repo):
        home, result = init_arborist_home()
        expected = git_repo / ARBORIST_DIR_NAME
        assert home == expected
        assert expected.is_dir()

    def test_creates_dagu_subdirectory(self, git_repo):
        home, result = init_arborist_home()
        dagu_dir = home / DAGU_DIR_NAME
        assert dagu_dir.is_dir()

    def test_creates_dagu_dags_subdirectory(self, git_repo):
        home, result = init_arborist_home()
        dags_dir = home / DAGU_DIR_NAME / "dags"
        assert dags_dir.is_dir()

    def test_creates_dagu_data_subdirectory(self, git_repo):
        home, result = init_arborist_home()
        data_dir = home / DAGU_DIR_NAME / "data"
        assert data_dir.is_dir()

    def test_creates_prompts_subdirectory(self, git_repo):
        home, result = init_arborist_home()
        prompts_dir = home / "prompts"
        assert prompts_dir.is_dir()

    def test_creates_default_config(self, git_repo):
        home, result = init_arborist_home()
        config_path = home / "config.json"
        assert config_path.exists()
        # Verify it's valid JSON
        import json
        config = json.loads(config_path.read_text())
        assert "version" in config
        assert config["defaults"]["runner"] == "claude"

    def test_creates_config_with_custom_runner(self, git_repo):
        home, result = init_arborist_home(runner="opencode", model="test-model")
        config_path = home / "config.json"
        import json
        config = json.loads(config_path.read_text())
        assert config["defaults"]["runner"] == "opencode"
        assert config["defaults"]["model"] == "test-model"

    def test_fails_if_not_in_git_repo(self, non_git_dir):
        with pytest.raises(ArboristHomeError) as exc_info:
            init_arborist_home()
        assert "git repository" in str(exc_info.value).lower()

    def test_fails_if_already_initialized(self, git_repo):
        arborist_dir = git_repo / ARBORIST_DIR_NAME
        arborist_dir.mkdir()

        with pytest.raises(ArboristHomeError) as exc_info:
            init_arborist_home()
        assert "already initialized" in str(exc_info.value).lower()

    def test_accepts_explicit_path(self, git_repo):
        custom_path = git_repo / "custom" / "arborist"
        home, result = init_arborist_home(home=custom_path)
        assert home == custom_path
        assert custom_path.is_dir()

    def test_explicit_path_works_outside_git(self, non_git_dir):
        custom_path = non_git_dir / "arborist"
        home, result = init_arborist_home(home=custom_path)
        assert home == custom_path
        assert custom_path.is_dir()

    def test_creates_parent_directories(self, git_repo):
        custom_path = git_repo / "deep" / "nested" / "arborist"
        home, result = init_arborist_home(home=custom_path)
        assert home == custom_path
        assert custom_path.is_dir()

    def test_returns_result_dict(self, git_repo):
        home, result = init_arborist_home()
        assert "created_dirs" in result
        assert "created_files" in result
        assert "gitignore" in result
        assert home in result["created_dirs"]


class TestArboristHomeFromSubdirectory:
    """Test that arborist home resolution works from subdirectories."""

    def test_get_home_from_subdirectory(self, git_repo):
        subdir = git_repo / "src" / "app"
        subdir.mkdir(parents=True)
        os.chdir(subdir)

        result = get_arborist_home()
        assert result == git_repo / ARBORIST_DIR_NAME

    def test_init_from_subdirectory(self, git_repo):
        subdir = git_repo / "src" / "app"
        subdir.mkdir(parents=True)
        os.chdir(subdir)

        home, result = init_arborist_home()
        expected = git_repo / ARBORIST_DIR_NAME
        assert home == expected
        assert expected.is_dir()

    def test_is_initialized_from_subdirectory(self, git_repo):
        subdir = git_repo / "src" / "app"
        subdir.mkdir(parents=True)
        os.chdir(subdir)

        assert not is_initialized()

        arborist_dir = git_repo / ARBORIST_DIR_NAME
        arborist_dir.mkdir()

        assert is_initialized()


class TestGitignoreHandling:
    """Test that .gitignore is properly updated during init."""

    def test_creates_gitignore_if_missing(self, git_repo):
        gitignore = git_repo / ".gitignore"
        if gitignore.exists():
            gitignore.unlink()

        home, result = init_arborist_home()

        assert gitignore.exists()
        content = gitignore.read_text()
        # Should have ignore rules for data/, prompts/, worktrees/
        assert f"{ARBORIST_DIR_NAME}/dagu/data/" in content
        assert f"{ARBORIST_DIR_NAME}/prompts/" in content
        assert f"{ARBORIST_DIR_NAME}/worktrees/" in content

    def test_appends_to_existing_gitignore(self, git_repo):
        gitignore = git_repo / ".gitignore"
        gitignore.write_text("node_modules/\n*.log\n")

        home, result = init_arborist_home()

        content = gitignore.read_text()
        assert "node_modules/" in content
        assert "*.log" in content
        assert f"{ARBORIST_DIR_NAME}/dagu/data/" in content
        assert f"{ARBORIST_DIR_NAME}/prompts/" in content

    def test_appends_newline_if_missing(self, git_repo):
        gitignore = git_repo / ".gitignore"
        gitignore.write_text("node_modules/")  # No trailing newline

        home, result = init_arborist_home()

        content = gitignore.read_text()
        lines = content.splitlines()
        assert "node_modules/" in lines
        assert f"{ARBORIST_DIR_NAME}/dagu/data/" in lines

    def test_updates_old_format_gitignore(self, git_repo):
        """Old format with just .arborist/ should be updated to new format."""
        gitignore = git_repo / ".gitignore"
        gitignore.write_text(f"{ARBORIST_DIR_NAME}/\n")

        # Remove existing arborist dir if exists (from previous tests)
        arborist_dir = git_repo / ARBORIST_DIR_NAME
        if arborist_dir.exists():
            import shutil
            shutil.rmtree(arborist_dir)

        home, result = init_arborist_home()

        content = gitignore.read_text()
        # Old format should be removed
        assert f"{ARBORIST_DIR_NAME}/\n" not in content
        # New format should have ignore rules for subdirs
        assert f"{ARBORIST_DIR_NAME}/dagu/data/" in content
        assert f"{ARBORIST_DIR_NAME}/prompts/" in content

    def test_no_duplicate_rules_with_new_format(self, git_repo):
        """If gitignore already has new format, don't duplicate."""
        gitignore = git_repo / ".gitignore"
        from agent_arborist.constants import generate_gitignore_content
        gitignore.write_text(generate_gitignore_content())

        # Remove existing arborist dir if exists (from previous tests)
        arborist_dir = git_repo / ARBORIST_DIR_NAME
        if arborist_dir.exists():
            import shutil
            shutil.rmtree(arborist_dir)

        home, result = init_arborist_home()

        content = gitignore.read_text()
        # Should only have one of each ignore rule
        data_lines = [l for l in content.splitlines() if l.strip() == f"{ARBORIST_DIR_NAME}/dagu/data/"]
        assert len(data_lines) == 1

    def test_no_gitignore_update_for_custom_path(self, non_git_dir):
        """When using explicit path outside git, no .gitignore update."""
        custom_path = non_git_dir / "custom_arborist"
        home, result = init_arborist_home(home=custom_path)

        gitignore = non_git_dir / ".gitignore"
        assert not gitignore.exists()
        # Should have empty gitignore in result
        assert result["gitignore"] == {}
