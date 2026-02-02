"""Tests for arborist constants module."""

import pytest
from pathlib import Path

from agent_arborist.constants import (
    ARBORIST_DIR_NAME,
    DAGU_DIR_NAME,
    TRACKED_PATHS,
    get_tracked_paths,
    get_tracked_patterns,
    is_path_tracked,
    generate_gitignore_content,
    parse_gitignore_content,
)


class TestConstants:
    """Test constant values."""

    def test_arborist_dir_name(self):
        assert ARBORIST_DIR_NAME == ".arborist"

    def test_dagu_dir_name(self):
        assert DAGU_DIR_NAME == "dagu"

    def test_tracked_paths_contains_config(self):
        assert "config.json" in TRACKED_PATHS

    def test_tracked_paths_contains_dags(self):
        assert any("dagu/dags" in path for path in TRACKED_PATHS)


class TestGetTrackedPaths:
    """Test get_tracked_paths function."""

    def test_returns_list(self):
        paths = get_tracked_paths()
        assert isinstance(paths, list)
        assert len(paths) > 0

    def test_returns_copy(self):
        paths1 = get_tracked_paths()
        paths2 = get_tracked_paths()
        assert paths1 is not paths2
        paths1.append("test")
        assert "test" not in get_tracked_paths()


class TestIsPathTracked:
    """Test is_path_tracked function."""

    def test_config_json_is_tracked(self):
        assert is_path_tracked("config.json") is True

    def test_dags_directory_is_tracked(self):
        assert is_path_tracked("dagu/dags") is True
        assert is_path_tracked("dagu/dags/") is True

    def test_data_directory_is_not_tracked(self):
        assert is_path_tracked("dagu/data") is False
        assert is_path_tracked("dagu/data/") is False

    def test_worktrees_is_not_tracked(self):
        assert is_path_tracked("worktrees") is False


class TestGenerateGitignoreContent:
    """Test generate_gitignore_content function."""

    def test_contains_ignore_rule(self):
        content = generate_gitignore_content()
        assert f"{ARBORIST_DIR_NAME}/" in content

    def test_contains_ignore_rules(self):
        content = generate_gitignore_content()
        assert f"{ARBORIST_DIR_NAME}/dagu/data/" in content
        assert f"{ARBORIST_DIR_NAME}/prompts/" in content
        assert f"{ARBORIST_DIR_NAME}/worktrees/" in content

    def test_contains_header_by_default(self):
        content = generate_gitignore_content()
        assert "# Arborist configuration" in content

    def test_no_header_when_disabled(self):
        content = generate_gitignore_content(add_header=False)
        assert "# Arborist" not in content


class TestParseGitignoreContent:
    """Test parse_gitignore_content function."""

    def test_detects_arborist_ignore(self):
        content = generate_gitignore_content()
        result = parse_gitignore_content(content)
        assert result["has_arborist_ignore"] is True

    def test_detects_missing_arborist_ignore(self):
        content = "node_modules/\n"
        result = parse_gitignore_content(content)
        assert result["has_arborist_ignore"] is False

    def test_detects_old_format(self):
        """Old format with .arborist/ should be detected and flagged."""
        content = f"{ARBORIST_DIR_NAME}/\n"
        result = parse_gitignore_content(content)
        assert result["has_arborist_ignore"] is True
        # Should report missing the new format ignores
        assert len(result["missing_paths"]) > 0

    def test_detects_new_format(self):
        """New format should be properly detected."""
        content = generate_gitignore_content()
        result = parse_gitignore_content(content)
        assert result["has_arborist_ignore"] is True
        # New format has tracked_paths populated
        assert len(result["tracked_paths"]) > 0
