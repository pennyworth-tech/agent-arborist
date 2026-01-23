"""Arborist home directory management."""

import os
import subprocess
from pathlib import Path

ARBORIST_DIR_NAME = ".arborist"
DAGU_DIR_NAME = "dagu"
ENV_VAR_NAME = "ARBORIST_HOME"
DAGU_HOME_ENV_VAR = "DAGU_HOME"


class ArboristHomeError(Exception):
    """Error related to arborist home directory."""

    pass


def get_git_root() -> Path | None:
    """Get the root directory of the current git repository.

    Returns:
        Path to git root, or None if not in a git repo.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def get_arborist_home(override: str | Path | None = None) -> Path:
    """Get the arborist home directory.

    Resolution order:
    1. Explicit override parameter
    2. ARBORIST_HOME environment variable
    3. Git repo root + .arborist/

    Args:
        override: Explicit path to use as arborist home.

    Returns:
        Path to arborist home directory.

    Raises:
        ArboristHomeError: If home cannot be determined.
    """
    # 1. Explicit override
    if override:
        return Path(override)

    # 2. Environment variable
    env_home = os.environ.get(ENV_VAR_NAME)
    if env_home:
        return Path(env_home)

    # 3. Git repo root + .arborist/
    git_root = get_git_root()
    if git_root:
        return git_root / ARBORIST_DIR_NAME

    raise ArboristHomeError(
        "Cannot determine arborist home. "
        "Not in a git repository and ARBORIST_HOME not set."
    )


def get_dagu_home(arborist_home: Path | None = None) -> Path:
    """Get the dagu home directory.

    Args:
        arborist_home: Arborist home path. If None, uses get_arborist_home().

    Returns:
        Path to dagu home directory ($ARBORIST_HOME/dagu).
    """
    home = arborist_home or get_arborist_home()
    return home / DAGU_DIR_NAME


def is_initialized(home: Path | None = None) -> bool:
    """Check if arborist is initialized in the given home.

    Args:
        home: Path to check. If None, uses get_arborist_home().

    Returns:
        True if .arborist directory exists.
    """
    try:
        path = home or get_arborist_home()
        return path.is_dir()
    except ArboristHomeError:
        return False


def _add_to_gitignore(git_root: Path, entry: str) -> bool:
    """Add an entry to .gitignore if not already present.

    Args:
        git_root: Path to the git repository root.
        entry: The entry to add to .gitignore.

    Returns:
        True if the entry was added, False if it already existed.
    """
    gitignore = git_root / ".gitignore"

    # Check if entry already exists
    if gitignore.exists():
        content = gitignore.read_text()
        lines = content.splitlines()
        # Check for exact match (with or without trailing slash)
        entry_normalized = entry.rstrip("/")
        for line in lines:
            line_normalized = line.strip().rstrip("/")
            if line_normalized == entry_normalized:
                return False
        # Append to existing file
        if content and not content.endswith("\n"):
            content += "\n"
        content += f"{entry}\n"
        gitignore.write_text(content)
    else:
        # Create new .gitignore
        gitignore.write_text(f"{entry}\n")

    return True


def init_arborist_home(home: Path | None = None) -> Path:
    """Initialize the arborist home directory.

    Creates the .arborist/ directory and adds it to .gitignore.

    Args:
        home: Path to initialize. If None, uses get_arborist_home().

    Returns:
        Path to the created arborist home directory.

    Raises:
        ArboristHomeError: If not in a git repo, or directory already exists.
    """
    # Must be in a git repo (unless home is explicitly provided)
    git_root = get_git_root()
    if not git_root and not home:
        raise ArboristHomeError(
            "Not in a git repository. "
            "Run 'arborist init' from the root of a git repository."
        )

    target = home or (git_root / ARBORIST_DIR_NAME)

    if target.exists():
        raise ArboristHomeError(
            f"Arborist already initialized at {target}. "
            "Remove the directory to reinitialize."
        )

    target.mkdir(parents=True)

    # Create dagu subdirectory
    dagu_dir = target / DAGU_DIR_NAME
    dagu_dir.mkdir()

    # Add to .gitignore if we're in a git repo
    if git_root:
        _add_to_gitignore(git_root, f"{ARBORIST_DIR_NAME}/")

    return target
