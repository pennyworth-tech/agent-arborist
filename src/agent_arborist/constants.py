"""Constants for arborist directory structure and git tracking.

This module centralizes the definitions of which files and directories
within .arborist/ should be tracked by git vs ignored.

Git Tracking Rules for .arborist/:
- By default, everything in .arborist/ is ignored
- Specific paths listed in TRACKED_PATHS are "un-ignored" (tracked)
- These are relative to the .arborist/ directory
"""

from pathlib import Path
from typing import Final

# Directory names
ARBORIST_DIR_NAME: Final = ".arborist"
DAGU_DIR_NAME: Final = "dagu"

# Files and directories within .arborist/ that should be tracked by git
# These paths are relative to .arborist/
TRACKED_PATHS: Final[list[str]] = [
    "config.json",
    "dagu/dags/",
    "dagu/dags/**",
]

# Additional tracked patterns for specific file types
# (these are also relative to .arborist/)
TRACKED_PATTERNS: Final[list[str]] = [
    # YAML files in dags directory
    "dagu/dags/*.yaml",
    "dagu/dags/*.yml",
    # Manifest files
    "dagu/dags/*_manifest.json",
]


def get_tracked_paths() -> list[str]:
    """Get list of paths that should be tracked within .arborist/.

    Returns:
        List of path strings relative to .arborist/ directory.
    """
    return TRACKED_PATHS.copy()


def get_tracked_patterns() -> list[str]:
    """Get list of glob patterns for tracked files.

    Returns:
        List of glob patterns relative to .arborist/ directory.
    """
    return TRACKED_PATTERNS.copy()


def is_path_tracked(path: str | Path) -> bool:
    """Check if a path within .arborist/ should be tracked.

    Args:
        path: Path relative to .arborist/ (can be string or Path).

    Returns:
        True if the path should be tracked by git.
    """
    path_str = str(path).replace("\\", "/").rstrip("/")

    # Check exact matches
    for tracked in TRACKED_PATHS:
        tracked_clean = tracked.rstrip("/")
        if path_str == tracked_clean:
            return True
        # Check if path is within a tracked directory
        if tracked_clean.endswith("**") or tracked_clean.endswith("*"):
            prefix = tracked_clean.rstrip("*/")
            if path_str.startswith(prefix):
                return True
        elif path_str.startswith(tracked_clean + "/"):
            return True

    return False


def generate_gitignore_content(add_header: bool = True) -> str:
    """Generate the .gitignore content for .arborist/ directory.

    This creates a gitignore that:
    1. Does NOT ignore .arborist/ itself (so we can track specific files)
    2. Ignores specific subdirectories that shouldn't be tracked
    3. Tracks only the files/directories listed in TRACKED_PATHS

    This approach is more reliable than ignoring .arborist/ and trying to
    un-ignore specific paths within it (git's negation patterns are tricky
    with nested directories).

    Args:
        add_header: Whether to add a comment header explaining the format.

    Returns:
        Gitignore content as a string.
    """
    lines = []

    if add_header:
        lines.append("# Arborist configuration and DAGs are tracked")
        lines.append("# Other .arborist/ contents are ignored")
        lines.append("")

    # Ignore specific subdirectories that should not be tracked
    # Note: We do NOT ignore .arborist/ itself so we can track specific files
    lines.append(f"{ARBORIST_DIR_NAME}/dagu/data/")
    lines.append(f"{ARBORIST_DIR_NAME}/prompts/")
    lines.append(f"{ARBORIST_DIR_NAME}/worktrees/")
    lines.append(f"{ARBORIST_DIR_NAME}/*.log")

    return "\n".join(lines) + "\n"


def parse_gitignore_content(content: str) -> dict:
    """Parse gitignore content to check arborist tracking status.

    Args:
        content: The content of .gitignore file.

    Returns:
        Dictionary with keys:
        - has_arborist_ignore: bool - whether .arborist/ subdirs are ignored
        - tracked_paths: list - paths that are properly set up to track
        - missing_paths: list - ignore rules that are missing
    """
    lines = content.splitlines()

    result = {
        "has_arborist_ignore": False,
        "tracked_paths": [],
        "missing_paths": [],
    }

    # Check if the new format is being used (ignoring specific subdirs)
    # Old format would have .arborist/ or .arborist/*
    expected_ignores = [
        f"{ARBORIST_DIR_NAME}/dagu/data/",
        f"{ARBORIST_DIR_NAME}/prompts/",
        f"{ARBORIST_DIR_NAME}/worktrees/",
    ]

    found_ignores = []
    for line in lines:
        line = line.strip()
        # Check if using old format (ignoring entire .arborist/)
        if line in (f"{ARBORIST_DIR_NAME}/", ARBORIST_DIR_NAME, f"{ARBORIST_DIR_NAME}/*"):
            result["has_arborist_ignore"] = True
            result["missing_paths"] = expected_ignores
            return result
        # Check for expected ignore patterns
        if line in expected_ignores:
            found_ignores.append(line)

    # Check if all expected ignores are present
    if len(found_ignores) == len(expected_ignores):
        result["has_arborist_ignore"] = True
        result["tracked_paths"] = TRACKED_PATHS.copy()
    else:
        # Some ignores are missing
        result["has_arborist_ignore"] = len(found_ignores) > 0
        result["missing_paths"] = [e for e in expected_ignores if e not in found_ignores]
        result["tracked_paths"] = TRACKED_PATHS.copy()

    return result
