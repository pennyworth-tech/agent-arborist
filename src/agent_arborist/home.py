"""Arborist home directory management."""

import os
import subprocess
from pathlib import Path

from agent_arborist.constants import (
    ARBORIST_DIR_NAME,
    DAGU_DIR_NAME,
    generate_gitignore_content,
    parse_gitignore_content,
)

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


def _update_gitignore_for_arborist(git_root: Path) -> dict:
    """Update .gitignore with arborist ignore rules.

    This function adds rules to ignore specific subdirectories within .arborist/
    that should not be tracked by git (like data/, prompts/, restart-contexts/).

    The config.json and dagu/dags/ are NOT ignored, so they will be tracked.

    Args:
        git_root: Path to the git repository root.

    Returns:
        Dictionary with 'added' (list of new entries), 'existing' (list of
        already present entries), and 'updated' (whether old format was replaced).
    """
    gitignore = git_root / ".gitignore"

    # Generate the arborist gitignore content (rules for what to ignore)
    arborist_gitignore = generate_gitignore_content()

    result = {"added": [], "existing": [], "updated": False}

    if gitignore.exists():
        content = gitignore.read_text()

        # Parse current state
        current_state = parse_gitignore_content(content)

        # Check if already properly configured with new format
        if current_state["has_arborist_ignore"] and not current_state["missing_paths"]:
            # Already properly configured
            result["existing"] = [f"{ARBORIST_DIR_NAME}/dagu/data/", f"{ARBORIST_DIR_NAME}/prompts/"]
            return result

        # Check if old format exists (ignoring entire .arborist/)
        old_format_lines = []
        for line in content.splitlines():
            stripped = line.strip()
            if stripped in (f"{ARBORIST_DIR_NAME}/", ARBORIST_DIR_NAME, f"{ARBORIST_DIR_NAME}/*"):
                old_format_lines.append(stripped)

        if old_format_lines:
            # Replace old format with new format
            lines = content.splitlines()
            new_lines = []
            for line in lines:
                stripped = line.strip()
                # Skip old arborist ignore lines and any old-style un-ignore lines
                if stripped in (f"{ARBORIST_DIR_NAME}/", ARBORIST_DIR_NAME, f"{ARBORIST_DIR_NAME}/*"):
                    continue
                if stripped.startswith(f"!{ARBORIST_DIR_NAME}/"):
                    # Skip old un-ignore lines
                    continue
                new_lines.append(line)

            # Remove trailing empty lines
            while new_lines and not new_lines[-1].strip():
                new_lines.pop()

            # Add new arborist gitignore
            if new_lines:
                content = "\n".join(new_lines) + "\n\n" + arborist_gitignore
            else:
                content = arborist_gitignore

            result["updated"] = True
            result["added"] = [f"{ARBORIST_DIR_NAME}/dagu/data/", f"{ARBORIST_DIR_NAME}/prompts/"]
        else:
            # Just append the arborist gitignore
            if content and not content.endswith("\n"):
                content += "\n"
            content += "\n" + arborist_gitignore
            result["added"] = [f"{ARBORIST_DIR_NAME}/dagu/data/", f"{ARBORIST_DIR_NAME}/prompts/"]
    else:
        # Create new .gitignore
        content = arborist_gitignore
        result["added"] = [f"{ARBORIST_DIR_NAME}/dagu/data/", f"{ARBORIST_DIR_NAME}/prompts/"]

    gitignore.write_text(content)
    return result


def check_gitignore_status(git_root: Path) -> dict:
    """Check the gitignore status for arborist.

    Args:
        git_root: Path to the git repository root.

    Returns:
        Dictionary with:
        - properly_configured: bool - whether gitignore is correct
        - has_arborist_ignore: bool - whether .arborist/ subdirs are ignored
        - tracked_paths: list - which paths are set up to track
        - missing_paths: list - which ignore rules are missing
        - recommendations: list - suggested fixes
    """
    from agent_arborist.constants import get_tracked_paths

    gitignore = git_root / ".gitignore"

    if not gitignore.exists():
        return {
            "properly_configured": False,
            "has_arborist_ignore": False,
            "tracked_paths": [],
            "missing_paths": [],
            "recommendations": ["Create .gitignore with arborist ignore rules"],
        }

    content = gitignore.read_text()
    state = parse_gitignore_content(content)

    recommendations = []

    if not state["has_arborist_ignore"]:
        recommendations.append(f"Add arborist ignore rules to .gitignore to exclude data/, prompts/, etc.")

    if state["missing_paths"]:
        for path in state["missing_paths"]:
            recommendations.append(f"Add '{path}' to .gitignore")

    return {
        "properly_configured": state["has_arborist_ignore"] and not state["missing_paths"],
        "has_arborist_ignore": state["has_arborist_ignore"],
        "tracked_paths": state.get("tracked_paths", get_tracked_paths()),
        "missing_paths": state["missing_paths"],
        "recommendations": recommendations,
    }


def create_default_config(home: Path, runner: str = "claude", model: str = "sonnet") -> Path:
    """Create a default config.json file.

    Args:
        home: Path to the arborist home directory.
        runner: Default runner to use (claude, opencode, or gemini).
        model: Default model to use.

    Returns:
        Path to the created config file.
    """
    from agent_arborist.config import generate_config_template
    import json

    config_path = home / "config.json"
    template = generate_config_template()

    # Set the default runner and model
    template["defaults"]["runner"] = runner
    template["defaults"]["model"] = model

    config_path.write_text(json.dumps(template, indent=2))
    return config_path


def init_arborist_home(
    home: Path | None = None,
    runner: str = "claude",
    model: str = "sonnet",
    create_config: bool = True,
) -> tuple[Path, dict]:
    """Initialize the arborist home directory.

    Creates the .arborist/ directory structure and configures git tracking
    to ignore most files but track config.json and dagu/dags/.

    Args:
        home: Path to initialize. If None, uses get_arborist_home().
        runner: Default runner to use in config (claude, opencode, or gemini).
        model: Default model to use in config.
        create_config: Whether to create a default config.json file.

    Returns:
        Tuple of (path to arborist home, dict with init results including
        gitignore_status and created files).

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

    result = {
        "home": target,
        "created_files": [],
        "created_dirs": [],
        "gitignore": {},
    }

    # Create main directory
    target.mkdir(parents=True)
    result["created_dirs"].append(target)

    # Create dagu subdirectory structure
    # $DAGU_HOME/dags/ is where dagu looks for DAG definitions
    # $DAGU_HOME/data/ is where dagu stores execution history/logs
    dagu_dir = target / DAGU_DIR_NAME
    dagu_dir.mkdir()
    result["created_dirs"].append(dagu_dir)

    dags_dir = dagu_dir / "dags"
    dags_dir.mkdir()
    result["created_dirs"].append(dags_dir)

    data_dir = dagu_dir / "data"
    data_dir.mkdir()
    result["created_dirs"].append(data_dir)

    # Create prompts directory for hooks
    prompts_dir = target / "prompts"
    prompts_dir.mkdir()
    result["created_dirs"].append(prompts_dir)

    # Create default config
    if create_config:
        config_path = create_default_config(target, runner=runner, model=model)
        result["created_files"].append(config_path)

    # Update .gitignore with proper arborist tracking rules
    if git_root:
        gitignore_result = _update_gitignore_for_arborist(git_root)
        result["gitignore"] = gitignore_result

    return target, result
