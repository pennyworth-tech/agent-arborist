"""Pytest configuration and shared fixtures for agent-arborist tests."""

import os
import subprocess
from pathlib import Path

import pytest

# Configuration for backlit-devpod repository
BACKLIT_DEVPOD_REPO = "https://github.com/pennyworth-tech/backlit-devpod"
BACKLIT_DEVPOD_REF = "main"  # Can pin to specific commit/tag if needed


@pytest.fixture(scope="session")
def backlit_devcontainer(tmp_path_factory) -> Path:
    """Get backlit devcontainer from sibling dir or clone.

    This fixture implements a hybrid approach:
    1. First, check for ../backlit-devpod (local development)
    2. If not found, clone from GitHub (CI or first-time setup)

    Returns:
        Path to .devcontainer/ directory from backlit-devpod

    Raises:
        pytest.skip: If neither sibling dir exists nor clone succeeds
    """
    # Try sibling directory first (local development)
    arborist_root = Path(__file__).parent.parent
    sibling_path = arborist_root.parent / "backlit-devpod" / ".devcontainer"

    if sibling_path.exists() and sibling_path.is_dir():
        print(f"\n✓ Using backlit-devpod from sibling directory: {sibling_path}")
        return sibling_path

    # Fall back to cloning (CI or first-time setup)
    print(f"\n⚠ Sibling backlit-devpod not found at {sibling_path}")
    print(f"→ Cloning from {BACKLIT_DEVPOD_REPO}@{BACKLIT_DEVPOD_REF}")

    cache_dir = tmp_path_factory.mktemp("backlit_devpod_cache")
    clone_path = cache_dir / "backlit-devpod"

    try:
        subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                BACKLIT_DEVPOD_REF,
                BACKLIT_DEVPOD_REPO,
                str(clone_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        print(f"✓ Cloned backlit-devpod to {clone_path}")
        return clone_path / ".devcontainer"

    except subprocess.CalledProcessError as e:
        pytest.skip(
            f"Could not access backlit-devpod:\n"
            f"  - Sibling directory not found: {sibling_path}\n"
            f"  - Clone failed: {e.stderr}\n"
            f"To fix: git clone {BACKLIT_DEVPOD_REPO} {arborist_root.parent / 'backlit-devpod'}"
        )
