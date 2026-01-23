"""Spec detection and management for Agent Arborist."""

import re
import subprocess
from dataclasses import dataclass


# Spec ID pattern: NNN-anything (3 digits followed by dash and rest)
SPEC_ID_PATTERN = re.compile(r"^(\d{3})-(.+)$")


@dataclass
class SpecInfo:
    """Information about the current spec."""

    spec_id: str | None = None
    name: str | None = None
    source: str | None = None  # "git", "config", "argument"
    branch: str | None = None
    error: str | None = None

    @property
    def found(self) -> bool:
        """Check if spec was successfully detected."""
        return self.spec_id is not None


def parse_spec_from_string(value: str) -> tuple[str, str] | None:
    """Parse spec ID and name from a string.

    Expected format: NNN-specname-could-be-anything
    Returns: (spec_id, name) tuple or None if not matching.
    """
    match = SPEC_ID_PATTERN.match(value)
    if match:
        return (match.group(1), match.group(2))
    return None


def get_git_branch() -> str | None:
    """Get current git branch name."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def detect_spec_from_git() -> SpecInfo:
    """Try to detect spec from git branch name.

    Looks for branch names matching patterns like:
    - 002-my-feature
    - 002-my-feature/phase-1
    - 002-my-feature/phase-1/T001
    - feature/002-my-feature
    """
    branch = get_git_branch()

    if not branch:
        return SpecInfo(
            error="Not in a git repository or git not available",
            source="git",
        )

    # Try to find spec pattern in branch name
    # Check each segment of the branch path
    segments = branch.split("/")

    for segment in segments:
        parsed = parse_spec_from_string(segment)
        if parsed:
            spec_id, name = parsed
            return SpecInfo(
                spec_id=spec_id,
                name=name,
                source="git",
                branch=branch,
            )

    return SpecInfo(
        error=f"Branch '{branch}' does not contain spec pattern (NNN-name)",
        source="git",
        branch=branch,
    )
