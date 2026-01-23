"""Dependency checks for Agent Arborist."""

import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class DependencyStatus:
    """Status of a required dependency."""

    name: str
    installed: bool
    version: str | None = None
    path: str | None = None
    min_version: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        """Check if dependency is installed and meets version requirements."""
        return self.installed and self.error is None


def check_dagu(min_version: str = "1.30.3") -> DependencyStatus:
    """Check if dagu is installed and meets minimum version requirement."""
    path = shutil.which("dagu")

    if not path:
        return DependencyStatus(
            name="dagu",
            installed=False,
            min_version=min_version,
            error="dagu not found in PATH",
        )

    try:
        result = subprocess.run(
            ["dagu", "version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        version = result.stdout.strip() or result.stderr.strip()

        if not version:
            return DependencyStatus(
                name="dagu",
                installed=True,
                path=path,
                min_version=min_version,
                error="Could not determine dagu version",
            )

        if _version_lt(version, min_version):
            return DependencyStatus(
                name="dagu",
                installed=True,
                version=version,
                path=path,
                min_version=min_version,
                error=f"dagu version {version} < required {min_version}",
            )

        return DependencyStatus(
            name="dagu",
            installed=True,
            version=version,
            path=path,
            min_version=min_version,
        )

    except subprocess.TimeoutExpired:
        return DependencyStatus(
            name="dagu",
            installed=True,
            path=path,
            min_version=min_version,
            error="dagu version check timed out",
        )
    except Exception as e:
        return DependencyStatus(
            name="dagu",
            installed=True,
            path=path,
            min_version=min_version,
            error=str(e),
        )


def check_claude() -> DependencyStatus:
    """Check if claude CLI is installed."""
    path = shutil.which("claude")

    if not path:
        return DependencyStatus(
            name="claude",
            installed=False,
        )

    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        version = result.stdout.strip() or result.stderr.strip()

        return DependencyStatus(
            name="claude",
            installed=True,
            version=version or "unknown",
            path=path,
        )

    except Exception as e:
        return DependencyStatus(
            name="claude",
            installed=True,
            path=path,
            error=str(e),
        )


def check_opencode() -> DependencyStatus:
    """Check if opencode CLI is installed."""
    path = shutil.which("opencode")

    if not path:
        return DependencyStatus(
            name="opencode",
            installed=False,
        )

    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        version = result.stdout.strip() or result.stderr.strip()

        return DependencyStatus(
            name="opencode",
            installed=True,
            version=version or "unknown",
            path=path,
        )

    except Exception as e:
        return DependencyStatus(
            name="opencode",
            installed=True,
            path=path,
            error=str(e),
        )


def check_gemini() -> DependencyStatus:
    """Check if gemini CLI is installed."""
    path = shutil.which("gemini")

    if not path:
        return DependencyStatus(
            name="gemini",
            installed=False,
        )

    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        version = result.stdout.strip() or result.stderr.strip()

        return DependencyStatus(
            name="gemini",
            installed=True,
            version=version or "unknown",
            path=path,
        )

    except Exception as e:
        return DependencyStatus(
            name="gemini",
            installed=True,
            path=path,
            error=str(e),
        )


def check_runtimes() -> list[DependencyStatus]:
    """Check all runtime CLIs. At least one must be available."""
    return [check_claude(), check_opencode(), check_gemini()]


def _version_lt(v1: str, v2: str) -> bool:
    """Check if version v1 < v2 using simple semver comparison."""

    def parse(v: str) -> tuple[int, ...]:
        v = v.lstrip("v")
        parts = []
        for part in v.split("."):
            num = ""
            for c in part:
                if c.isdigit():
                    num += c
                else:
                    break
            parts.append(int(num) if num else 0)
        return tuple(parts)

    return parse(v1) < parse(v2)
