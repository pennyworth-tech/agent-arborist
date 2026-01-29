# DevContainer Support for Agent Arborist Runners

**Version:** 1.0
**Status:** Implementation Spec
**Branch:** `feature/devpod-for-runners`

---

## Terminology

| Term | Description |
|------|-------------|
| **Arborist** | This CLI tool - orchestrates task execution via Dagu |
| **Target Project** | The user's repository where arborist operates |
| **Target's DevContainer** | The `.devcontainer/` in the target project (user-provided) |
| **Runner** | CLI tool that executes tasks: `claude`, `opencode`, or `gemini` |

---

## Overview

Arborist can optionally run tasks inside the **target project's devcontainer** instead of directly on the host. This provides:

- Consistent, reproducible build environments
- Isolation between tasks
- Access to project-specific tooling defined in the target's devcontainer

**Key principle:** Arborist does NOT provide a devcontainer. It **detects and uses** the target project's existing `.devcontainer/` configuration.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    TARGET PROJECT REPOSITORY                    │
│                                                                 │
│  <target-repo>/                                                 │
│    ├── .devcontainer/        ← User's devcontainer (has runners)│
│    │   ├── Dockerfile                                          │
│    │   └── devcontainer.json                                   │
│    ├── .arborist/                                              │
│    │   └── worktrees/                                          │
│    │       └── <spec-id>/                                      │
│    │           ├── T001/     ← Worktree (mounted in container) │
│    │           ├── T002/     ← Worktree (mounted in container) │
│    │           └── T003/     ← Worktree (mounted in container) │
│    └── src/                                                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ devcontainer up --workspace-folder <worktree>
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│  Container-T001  │ │  Container-T002  │ │  Container-T003  │
│  (target's image)│ │  (target's image)│ │  (target's image)│
│                  │ │                  │ │                  │
│  Volume mount:   │ │  Volume mount:   │ │  Volume mount:   │
│  worktrees/T001/ │ │  worktrees/T002/ │ │  worktrees/T003/ │
│  → /workspace    │ │  → /workspace    │ │  → /workspace    │
│                  │ │                  │ │                  │
│  Target's tools  │ │  Target's tools  │ │  Target's tools  │
│  + runners       │ │  + runners       │ │  + runners       │
└──────────────────┘ └──────────────────┘ └──────────────────┘
         │                   │                   │
         └───────────────────┴───────────────────┘
                             │
                     Parallel Execution
                     (Dagu orchestrates)
```

**Key Points:**
- Arborist uses the **target project's** `.devcontainer/`
- Each worktree spawns its own container instance
- Containers are isolated (separate processes, volumes)
- Target's devcontainer must include runner CLIs
- `.env` files inherited from parent worktree

---

## Container Mode Flag

Arborist supports three container modes via `--container-mode` / `-c`:

| Mode | Behavior |
|------|----------|
| `auto` (default) | Use devcontainer if target has `.devcontainer/`, otherwise run on host |
| `enabled` | Require devcontainer - fail if `.devcontainer/` not present |
| `disabled` | Never use devcontainer - always run on host |

```bash
# Auto-detect (default) - uses devcontainer if present
arborist build spec/tasks.md

# Explicitly enable - fails if no devcontainer
arborist build spec/tasks.md --container-mode enabled

# Explicitly disable - ignores devcontainer even if present
arborist build spec/tasks.md --container-mode disabled
arborist build spec/tasks.md -c disabled
```

---

## Target Project Requirements

For devcontainer support to work, the **target project** must:

1. Have a `.devcontainer/` directory with valid configuration
2. Include runner CLIs (claude, opencode, gemini) in the container image
3. Configure git for worktree operations

### Example Target DevContainer

The target project should have something like:

**File: `<target-project>/.devcontainer/devcontainer.json`**

```json
{
  "name": "my-project-dev",
  "build": {
    "dockerfile": "Dockerfile"
  },
  "workspaceFolder": "/workspace",
  "remoteEnv": {
    "CLAUDE_CODE_OAUTH_TOKEN": "${localEnv:CLAUDE_CODE_OAUTH_TOKEN}",
    "OPENAI_API_KEY": "${localEnv:OPENAI_API_KEY}",
    "GOOGLE_API_KEY": "${localEnv:GOOGLE_API_KEY}"
  },
  "postCreateCommand": "git config --global --add safe.directory /workspace",
  "features": {
    "ghcr.io/devcontainers/features/node:1": {}
  }
}
```

**File: `<target-project>/.devcontainer/Dockerfile`**

```dockerfile
FROM mcr.microsoft.com/devcontainers/base:ubuntu

# Project-specific dependencies
RUN apt-get update && apt-get install -y \
    python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

# ============================================================
# RUNNER CLIs (required for arborist devcontainer support)
# ============================================================

# Claude CLI
RUN npm install -g @anthropic-ai/claude-code

# OpenCode CLI (optional) - use opencode-ai npm package
RUN npm install -g opencode-ai@latest \
    || echo "OpenCode not installed"

# Gemini CLI (optional)
RUN pip3 install --break-system-packages google-generativeai \
    || echo "Gemini not installed"

# Git config for worktree operations
RUN git config --global --add safe.directory /workspace

WORKDIR /workspace
```

---

## Runner Installation Best Practices

When adding runner CLIs to your devcontainer, follow these recommendations for reproducible and reliable builds.

### Version Pinning

**Recommended**: Pin runner versions for reproducible builds:

```dockerfile
# Pin specific versions
RUN npm install -g @anthropic-ai/claude-code@1.2.3
RUN npm install -g opencode-ai@2.1.0

# Or use version ranges
RUN npm install -g opencode-ai@^2.0.0
```

**Why**: Ensures consistent behavior across team members and CI/CD pipelines. Without pinning, different team members may get different runner versions, leading to inconsistent results.

### Installation Methods by Runner

#### Claude CLI
```dockerfile
# NPM (recommended for version control)
RUN npm install -g @anthropic-ai/claude-code@latest

# Or via install script (always latest)
RUN curl -fsSL https://claude.ai/install | bash
```

#### OpenCode CLI
```dockerfile
# NPM (recommended - use opencode-ai package)
RUN npm install -g opencode-ai@latest

# Or via install script
RUN curl -fsSL https://opencode.ai/install | bash
```

**Important**: Use `opencode-ai` (not `opencode-cli`) from npm.

#### Gemini CLI
```dockerfile
# Python pip
RUN pip3 install --break-system-packages google-generativeai

# Or without --break-system-packages if using venv
RUN python3 -m venv /opt/venv && \
    /opt/venv/bin/pip install google-generativeai
```

### Installation Verification

Always verify installation in Dockerfile:

```dockerfile
RUN opencode --version || echo "WARNING: OpenCode installation may have failed"
RUN claude --version || echo "WARNING: Claude installation may have failed"
```

This catches installation failures at build time rather than runtime.

### Multi-Runner Support

Include multiple runners for flexibility:

```dockerfile
# Install all runners (team can choose per-task)
RUN npm install -g @anthropic-ai/claude-code@latest
RUN npm install -g opencode-ai@latest
RUN pip3 install --break-system-packages google-generativeai

# Verify all
RUN claude --version && opencode --version && python3 -c "import google.generativeai"
```

### Minimal vs Full Installation

**Minimal (Single Runner)**:
- Faster builds (~2-3 minutes)
- Smaller images (~500MB)
- Recommended for CI/CD pipelines
- Example: `tests/fixtures/devcontainers/minimal-opencode/`

**Full (All Runners)**:
- Slower builds (~5-7 minutes)
- Larger images (~2GB)
- Recommended for local development
- Maximum flexibility per task

---

## External DevContainer Repository

The target project's `.devcontainer/` can be maintained in a separate repository using:

### Option 1: Git Submodule (Recommended)

```bash
# In target project
git submodule add https://github.com/your-org/shared-devcontainer.git .devcontainer
```

**Compatibility:** Works with arborist - submodules are shared across worktrees.

**CI/CD Note:** Add `submodules: true` to checkout:
```yaml
- uses: actions/checkout@v4
  with:
    submodules: true
```

### Option 2: Git Subtree

```bash
git subtree add --prefix .devcontainer https://github.com/your-org/shared-devcontainer.git main --squash
```

**Compatibility:** Works with arborist - subtree content is part of repo.

### Option 3: Symlink

```bash
ln -s /path/to/shared/devcontainer .devcontainer
```

**Compatibility:** Does NOT work reliably with worktrees. Avoid this approach.

---

## Implementation Checklist

### Files to Create (in arborist)

| File | Purpose |
|------|---------|
| `src/agent_arborist/container_runner.py` | DevContainer detection and execution wrapper |
| `tests/test_container_runner.py` | Unit tests for container runner |

### Files to Modify (in arborist)

| File | Changes |
|------|---------|
| `src/agent_arborist/dag_builder.py` | Add `container_mode` parameter, wrap commands |
| `src/agent_arborist/git_tasks.py` | Add `.env` file inheritance, devcontainer detection |
| `src/agent_arborist/cli.py` | Add `--container-mode` flag |
| `src/agent_arborist/checks.py` | Add `check_devcontainer()`, `check_docker()` |

---

## Container Lifecycle Management

### Automatic Cleanup

Arborist **always stops containers** after task completion, regardless of success or failure:

```yaml
steps:
  - name: container-up
    command: devcontainer up --workspace-folder "${ARBORIST_WORKTREE}"

  # ... task steps ...

  - name: container-down
    command: docker stop $(docker ps -q --filter label=devcontainer.local_folder="${ARBORIST_WORKTREE}") 2>/dev/null || true
    depends: [post-merge]  # Runs even if previous steps fail (Dagu behavior)
```

**Why no debug flag?**
- Containers are stopped automatically to prevent resource leaks
- Simplifies workflow - no need to remember cleanup flags
- Consistent behavior across all execution modes

### Container Reuse

Arborist does NOT reuse containers between tasks:
- Each task execution starts a fresh container
- Prevents state leakage between tasks
- Ensures reproducible builds

### Debugging Failed Containers

If a task fails, the container is stopped but not removed. To inspect:

```bash
# Find stopped containers
docker ps -a --filter label=devcontainer.local_folder

# Start a stopped container for debugging
docker start <container_id>
docker exec -it <container_id> /bin/bash

# Remove when done
docker rm <container_id>
```

### Manual Container Management

For development/testing:

```bash
# Keep container running (manual mode)
devcontainer up --workspace-folder .arborist/worktrees/spec1/T001

# Your work here...

# Stop when done
docker stop $(docker ps -q --filter label=devcontainer.local_folder=$(pwd)/.arborist/worktrees/spec1/T001)
```

---

## Test Fixtures

Arborist includes test fixtures to validate devcontainer support:

### Minimal OpenCode Fixture

**Location**: `tests/fixtures/devcontainers/minimal-opencode/`

A minimal devcontainer with OpenCode CLI for integration testing:

```
tests/fixtures/devcontainers/minimal-opencode/
├── .devcontainer/
│   ├── Dockerfile         # Node 18 + opencode-ai
│   └── devcontainer.json  # Workspace config
├── .env.example           # API key template
├── README.md              # Setup instructions
└── test_spec.md           # Simple test tasks
```

**Features**:
- Node 18 slim base image
- OpenCode CLI (`opencode-ai` npm package)
- Pre-configured for zai-coding-plan/glm-4.7 model
- Minimal footprint for fast testing

**Usage**:
```bash
cd tests/fixtures/devcontainers/minimal-opencode
cp .env.example .env
# Add your ZAI_API_KEY to .env
devcontainer up --workspace-folder .
```

### Running Integration Tests

```bash
# All container integration tests
pytest -m integration tests/test_container_runner.py

# Only OpenCode container tests
pytest -m opencode tests/test_container_runner.py

# Only mechanics tests (no API calls)
pytest -m "integration and not opencode" tests/test_container_runner.py
```

See `tests/test_container_runner.py` for test implementation.

---

## Step 1: Create `src/agent_arborist/container_runner.py`

```python
"""DevContainer detection and execution for target projects.

This module detects if the target project has a .devcontainer/ and
wraps runner execution in devcontainer commands.

Arborist does NOT provide a devcontainer - it uses the target's.
"""

import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from agent_arborist.home import get_git_root


class ContainerMode(Enum):
    """Container execution mode for DAG steps."""
    AUTO = "auto"           # Use devcontainer if target has .devcontainer/
    ENABLED = "enabled"     # Require devcontainer, fail if not present
    DISABLED = "disabled"   # Never use devcontainer


@dataclass
class ContainerConfig:
    """Configuration for DevContainer execution."""

    # Container mode
    mode: ContainerMode = ContainerMode.AUTO

    # Timeout for devcontainer up (seconds)
    up_timeout: int = 300

    # Timeout for devcontainer exec (seconds)
    exec_timeout: int = 3600


@dataclass
class ContainerResult:
    """Result from a container operation."""

    success: bool
    output: str
    error: str | None = None
    exit_code: int = 0


def has_devcontainer(repo_path: Path | None = None) -> bool:
    """Check if target project has a .devcontainer/ directory.

    Args:
        repo_path: Path to target repo. Defaults to git root.

    Returns:
        True if .devcontainer/ exists with valid config.
    """
    repo_path = repo_path or get_git_root()
    devcontainer_dir = repo_path / ".devcontainer"

    if not devcontainer_dir.is_dir():
        return False

    # Check for devcontainer.json or Dockerfile
    has_config = (devcontainer_dir / "devcontainer.json").exists()
    has_dockerfile = (devcontainer_dir / "Dockerfile").exists()

    return has_config or has_dockerfile


def should_use_container(mode: ContainerMode, repo_path: Path | None = None) -> bool:
    """Determine if container mode should be used.

    Args:
        mode: The configured container mode.
        repo_path: Path to target repo.

    Returns:
        True if commands should run in devcontainer.

    Raises:
        RuntimeError: If mode is ENABLED but no devcontainer found.
    """
    if mode == ContainerMode.DISABLED:
        return False

    has_dc = has_devcontainer(repo_path)

    if mode == ContainerMode.ENABLED and not has_dc:
        raise RuntimeError(
            "Container mode is 'enabled' but target project has no .devcontainer/. "
            "Either add a .devcontainer/ to the target project or use --container-mode auto"
        )

    if mode == ContainerMode.AUTO:
        return has_dc

    return True  # mode == ENABLED and has_dc


def check_devcontainer_cli() -> tuple[bool, str]:
    """Check if devcontainer CLI is installed.

    Returns:
        Tuple of (is_installed, version_or_error)
    """
    if not shutil.which("devcontainer"):
        return False, "devcontainer CLI not found. Install: npm install -g @devcontainers/cli"

    try:
        result = subprocess.run(
            ["devcontainer", "--version"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, result.stderr.strip()
    except Exception as e:
        return False, str(e)


def check_docker() -> tuple[bool, str]:
    """Check if Docker is running.

    Returns:
        Tuple of (is_running, version_or_error)
    """
    if not shutil.which("docker"):
        return False, "Docker not found in PATH"

    try:
        result = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, "Docker daemon not running"
    except Exception as e:
        return False, str(e)


class DevContainerRunner:
    """Wraps runner execution in the target project's devcontainer.

    Each worktree gets its own container instance using the
    target project's .devcontainer/ configuration.
    """

    def __init__(self, config: ContainerConfig | None = None):
        self.config = config or ContainerConfig()

    def container_up(self, worktree_path: Path) -> ContainerResult:
        """Start devcontainer for a worktree.

        Uses the target project's .devcontainer/ configuration.
        Container is named based on worktree folder.

        Args:
            worktree_path: Absolute path to the worktree directory.

        Returns:
            ContainerResult with success/failure and output.
        """
        worktree_path = worktree_path.resolve()

        # Ensure worktree has access to .devcontainer (symlink if needed)
        self._ensure_devcontainer_accessible(worktree_path)

        cmd = [
            "devcontainer", "up",
            "--workspace-folder", str(worktree_path),
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.config.up_timeout,
            )

            return ContainerResult(
                success=result.returncode == 0,
                output=result.stdout,
                error=result.stderr if result.returncode != 0 else None,
                exit_code=result.returncode,
            )

        except subprocess.TimeoutExpired:
            return ContainerResult(
                success=False,
                output="",
                error=f"Container startup timed out after {self.config.up_timeout}s",
                exit_code=-1,
            )
        except Exception as e:
            return ContainerResult(
                success=False,
                output="",
                error=str(e),
                exit_code=-1,
            )

    def exec(
        self,
        worktree_path: Path,
        command: list[str],
        env: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> ContainerResult:
        """Execute command in running devcontainer.

        Args:
            worktree_path: Path to the worktree.
            command: Command and arguments to execute.
            env: Additional environment variables.
            timeout: Command timeout in seconds.

        Returns:
            ContainerResult with command output.
        """
        worktree_path = worktree_path.resolve()
        timeout = timeout or self.config.exec_timeout

        cmd = [
            "devcontainer", "exec",
            "--workspace-folder", str(worktree_path),
        ]

        if env:
            for key, value in env.items():
                cmd.extend(["--remote-env", f"{key}={value}"])

        cmd.extend(command)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            return ContainerResult(
                success=result.returncode == 0,
                output=result.stdout,
                error=result.stderr if result.returncode != 0 else None,
                exit_code=result.returncode,
            )

        except subprocess.TimeoutExpired:
            return ContainerResult(
                success=False,
                output="",
                error=f"Command timed out after {timeout}s",
                exit_code=-1,
            )
        except Exception as e:
            return ContainerResult(
                success=False,
                output="",
                error=str(e),
                exit_code=-1,
            )

    def container_down(self, worktree_path: Path) -> ContainerResult:
        """Stop devcontainer for a worktree.

        Args:
            worktree_path: Path to the worktree.

        Returns:
            ContainerResult with success/failure.
        """
        worktree_path = worktree_path.resolve()

        # Find container by devcontainer label
        find_cmd = [
            "docker", "ps", "-q",
            "--filter", f"label=devcontainer.local_folder={worktree_path}",
        ]

        try:
            find_result = subprocess.run(find_cmd, capture_output=True, text=True)
            container_id = find_result.stdout.strip()

            if not container_id:
                return ContainerResult(
                    success=True,
                    output="No container found (already stopped)",
                )

            stop_result = subprocess.run(
                ["docker", "stop", container_id],
                capture_output=True,
                text=True,
            )

            return ContainerResult(
                success=stop_result.returncode == 0,
                output=f"Stopped container {container_id}" if stop_result.returncode == 0 else stop_result.stdout,
                error=stop_result.stderr if stop_result.returncode != 0 else None,
                exit_code=stop_result.returncode,
            )

        except Exception as e:
            return ContainerResult(
                success=False,
                output="",
                error=str(e),
                exit_code=-1,
            )

    def _ensure_devcontainer_accessible(self, worktree_path: Path) -> None:
        """Ensure worktree can access .devcontainer config.

        Git worktrees share .git with main repo, so .devcontainer
        should be accessible. If not, create symlink.

        Args:
            worktree_path: Path to the worktree.
        """
        target = worktree_path / ".devcontainer"
        if target.exists():
            return

        # Find repo root's .devcontainer
        git_root = get_git_root()
        source = git_root / ".devcontainer"

        if source.exists() and source != target:
            target.symlink_to(source)


# ============================================================
# SHELL COMMAND GENERATORS (for DAG steps)
# ============================================================

def devcontainer_up_command(worktree_env_var: str = "${ARBORIST_WORKTREE}") -> str:
    """Generate shell command for container-up step."""
    return f'devcontainer up --workspace-folder "{worktree_env_var}"'


def devcontainer_exec_command(
    command: str,
    worktree_env_var: str = "${ARBORIST_WORKTREE}",
) -> str:
    """Generate shell command wrapping a command in devcontainer exec."""
    return f'devcontainer exec --workspace-folder "{worktree_env_var}" {command}'


def devcontainer_down_command(worktree_env_var: str = "${ARBORIST_WORKTREE}") -> str:
    """Generate shell command for container-down step."""
    return (
        f'docker stop $(docker ps -q --filter '
        f'label=devcontainer.local_folder="{worktree_env_var}") 2>/dev/null || true'
    )
```

---

## Step 2: Modify `dag_builder.py`

### 2.1 Import ContainerMode

```python
from agent_arborist.container_runner import ContainerMode
```

### 2.2 Update DagConfig

```python
@dataclass
class DagConfig:
    """Configuration for DAG generation."""

    name: str
    description: str = ""
    spec_id: str = ""

    # Container mode - determines if commands run in target's devcontainer
    container_mode: ContainerMode = ContainerMode.AUTO
```

### 2.3 Add Container Detection at Build Time

In the `build()` method:

```python
def build(self, spec: TaskSpec, task_tree: TaskTree) -> DagBundle:
    # Resolve container mode at build time
    from agent_arborist.container_runner import should_use_container

    self._use_container = should_use_container(self.config.container_mode)

    # ... rest of build logic
```

### 2.4 Update `_build_leaf_subdag` Method

```python
def _build_leaf_subdag(self, task_id: str) -> SubDag:
    """Build a leaf subdag with individual command nodes.

    When container mode is active, wraps commands in devcontainer exec
    and adds container-up/container-down lifecycle steps.
    """
    steps: list[SubDagStep] = []
    use_container = getattr(self, '_use_container', False)

    # Container-up step (only when using target's devcontainer)
    if use_container:
        steps.append(SubDagStep(
            name="container-up",
            command='devcontainer up --workspace-folder "${ARBORIST_WORKTREE}"',
        ))

    # Pre-sync step
    pre_sync_cmd = f"arborist task pre-sync {task_id}"
    if use_container:
        pre_sync_cmd = f'devcontainer exec --workspace-folder "${{ARBORIST_WORKTREE}}" {pre_sync_cmd}'
    steps.append(SubDagStep(
        name="pre-sync",
        command=pre_sync_cmd,
        depends=["container-up"] if use_container else [],
    ))

    # Run step (runner executes inside container)
    run_cmd = f"arborist task run {task_id}"
    if use_container:
        run_cmd = f'devcontainer exec --workspace-folder "${{ARBORIST_WORKTREE}}" {run_cmd}'
    steps.append(SubDagStep(
        name="run",
        command=run_cmd,
        depends=["pre-sync"],
    ))

    # Run-test step
    test_cmd = f"arborist task run-test {task_id}"
    if use_container:
        test_cmd = f'devcontainer exec --workspace-folder "${{ARBORIST_WORKTREE}}" {test_cmd}'
    steps.append(SubDagStep(
        name="run-test",
        command=test_cmd,
        depends=["run"],
    ))

    # Post-merge step
    merge_cmd = f"arborist task post-merge {task_id}"
    if use_container:
        merge_cmd = f'devcontainer exec --workspace-folder "${{ARBORIST_WORKTREE}}" {merge_cmd}'
    steps.append(SubDagStep(
        name="post-merge",
        command=merge_cmd,
        depends=["run-test"],
    ))

    # Container-down step
    if use_container:
        steps.append(SubDagStep(
            name="container-down",
            command=(
                'docker stop $(docker ps -q --filter '
                'label=devcontainer.local_folder="${ARBORIST_WORKTREE}") 2>/dev/null || true'
            ),
            depends=["post-merge"],
        ))

    # Post-cleanup (always on host - removes worktree)
    steps.append(SubDagStep(
        name="post-cleanup",
        command=f"arborist task post-cleanup {task_id}",
        depends=["container-down" if use_container else "post-merge"],
    ))

    return SubDag(name=task_id, steps=steps)
```

---

## Step 3: Modify `git_tasks.py` for `.env` Inheritance

```python
def copy_env_from_parent(
    worktree_path: Path,
    parent_worktree_path: Path | None,
    cwd: Path | None = None,
) -> GitResult:
    """Copy .env file from parent worktree to child.

    Credentials flow through the worktree hierarchy:
    - Root tasks inherit from target repo root .env
    - Child tasks inherit from parent worktree .env

    Args:
        worktree_path: Path to the new worktree.
        parent_worktree_path: Path to parent worktree (None for root tasks).
        cwd: Working directory (defaults to git root).

    Returns:
        GitResult with success/failure.
    """
    import shutil

    git_root = cwd or get_git_root()

    # Determine source .env file
    if parent_worktree_path and (parent_worktree_path / ".env").exists():
        source_env = parent_worktree_path / ".env"
    elif (git_root / ".env").exists():
        source_env = git_root / ".env"
    else:
        return GitResult(success=True, message="No .env file to inherit")

    # Copy to worktree
    target_env = worktree_path / ".env"
    try:
        shutil.copy(source_env, target_env)
        return GitResult(success=True, message=f"Inherited .env from {source_env}")
    except Exception as e:
        return GitResult(success=False, message="Failed to copy .env", error=str(e))
```

---

## Step 4: Update CLI with `--container-mode` Flag

```python
@app.command()
def build(
    spec_path: Path = typer.Argument(..., help="Path to task spec file or directory"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Output file path"),
    container_mode: str = typer.Option(
        "auto",
        "--container-mode", "-c",
        help="Container mode: auto (use if .devcontainer exists), enabled (require), disabled (never)",
    ),
) -> None:
    """Build DAG YAML from task specification."""
    from agent_arborist.container_runner import ContainerMode
    from agent_arborist.dag_builder import DagConfig, DagBuilder

    # Parse container mode
    try:
        mode = ContainerMode(container_mode)
    except ValueError:
        typer.echo(f"Invalid container mode: {container_mode}", err=True)
        typer.echo("Valid options: auto, enabled, disabled", err=True)
        raise typer.Exit(1)

    config = DagConfig(
        name=spec_name,
        description=f"Generated from {spec_path}",
        spec_id=spec_id,
        container_mode=mode,
    )

    # ... continue with build ...
```

---

## Step 5: Create Unit Tests

**File:** `tests/test_container_runner.py`

```python
"""Tests for container_runner module."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_arborist.container_runner import (
    ContainerConfig,
    ContainerMode,
    ContainerResult,
    DevContainerRunner,
    has_devcontainer,
    should_use_container,
    devcontainer_up_command,
    devcontainer_exec_command,
    devcontainer_down_command,
)


class TestContainerMode:
    """Tests for ContainerMode enum and detection."""

    def test_container_mode_values(self):
        assert ContainerMode.AUTO.value == "auto"
        assert ContainerMode.ENABLED.value == "enabled"
        assert ContainerMode.DISABLED.value == "disabled"

    @patch("agent_arborist.container_runner.get_git_root")
    def test_has_devcontainer_true(self, mock_git_root, tmp_path):
        mock_git_root.return_value = tmp_path
        (tmp_path / ".devcontainer").mkdir()
        (tmp_path / ".devcontainer" / "devcontainer.json").touch()

        assert has_devcontainer(tmp_path) is True

    @patch("agent_arborist.container_runner.get_git_root")
    def test_has_devcontainer_false(self, mock_git_root, tmp_path):
        mock_git_root.return_value = tmp_path

        assert has_devcontainer(tmp_path) is False

    @patch("agent_arborist.container_runner.has_devcontainer")
    def test_should_use_container_auto_with_devcontainer(self, mock_has):
        mock_has.return_value = True
        assert should_use_container(ContainerMode.AUTO) is True

    @patch("agent_arborist.container_runner.has_devcontainer")
    def test_should_use_container_auto_without_devcontainer(self, mock_has):
        mock_has.return_value = False
        assert should_use_container(ContainerMode.AUTO) is False

    @patch("agent_arborist.container_runner.has_devcontainer")
    def test_should_use_container_disabled(self, mock_has):
        mock_has.return_value = True  # Even with devcontainer
        assert should_use_container(ContainerMode.DISABLED) is False

    @patch("agent_arborist.container_runner.has_devcontainer")
    def test_should_use_container_enabled_raises_without_devcontainer(self, mock_has):
        mock_has.return_value = False
        with pytest.raises(RuntimeError, match="no .devcontainer"):
            should_use_container(ContainerMode.ENABLED)


class TestDevContainerRunner:
    """Tests for DevContainerRunner class."""

    @patch("subprocess.run")
    @patch("agent_arborist.container_runner.get_git_root")
    def test_container_up_success(self, mock_git_root, mock_run, tmp_path):
        mock_git_root.return_value = tmp_path
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"outcome": "success"}',
            stderr="",
        )

        runner = DevContainerRunner()
        result = runner.container_up(tmp_path / "worktree")

        assert result.success is True
        assert result.exit_code == 0
        mock_run.assert_called_once()

    @patch("subprocess.run")
    @patch("agent_arborist.container_runner.get_git_root")
    def test_container_up_failure(self, mock_git_root, mock_run, tmp_path):
        mock_git_root.return_value = tmp_path
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Error: Docker not running",
        )

        runner = DevContainerRunner()
        result = runner.container_up(tmp_path / "worktree")

        assert result.success is False
        assert "Docker not running" in result.error

    @patch("subprocess.run")
    @patch("agent_arborist.container_runner.get_git_root")
    def test_exec_success(self, mock_git_root, mock_run, tmp_path):
        mock_git_root.return_value = tmp_path
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Command output",
            stderr="",
        )

        runner = DevContainerRunner()
        result = runner.exec(tmp_path / "worktree", ["echo", "hello"])

        assert result.success is True
        assert result.output == "Command output"

    @patch("subprocess.run")
    @patch("agent_arborist.container_runner.get_git_root")
    def test_exec_with_env(self, mock_git_root, mock_run, tmp_path):
        mock_git_root.return_value = tmp_path
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        runner = DevContainerRunner()
        runner.exec(tmp_path / "worktree", ["cmd"], env={"KEY": "value"})

        call_args = mock_run.call_args[0][0]
        assert "--remote-env" in call_args
        assert "KEY=value" in call_args

    @patch("subprocess.run")
    def test_container_down_no_container(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        runner = DevContainerRunner()
        result = runner.container_down(Path("/tmp/worktree"))

        assert result.success is True
        assert "already stopped" in result.output


class TestCommandGenerators:
    """Tests for shell command generator functions."""

    def test_devcontainer_up_command_default(self):
        cmd = devcontainer_up_command()
        assert cmd == 'devcontainer up --workspace-folder "${ARBORIST_WORKTREE}"'

    def test_devcontainer_up_command_custom(self):
        cmd = devcontainer_up_command("${MY_PATH}")
        assert cmd == 'devcontainer up --workspace-folder "${MY_PATH}"'

    def test_devcontainer_exec_command(self):
        cmd = devcontainer_exec_command("pytest tests/")
        assert 'devcontainer exec --workspace-folder "${ARBORIST_WORKTREE}" pytest tests/' == cmd

    def test_devcontainer_down_command(self):
        cmd = devcontainer_down_command()
        assert "docker stop" in cmd
        assert "devcontainer.local_folder" in cmd


class TestDagBuilderContainerMode:
    """Tests for DAG builder container mode integration."""

    @patch("agent_arborist.container_runner.has_devcontainer")
    def test_dag_with_container_mode_auto_has_devcontainer(self, mock_has):
        """When auto mode and devcontainer exists, DAG should have container steps."""
        mock_has.return_value = True

        from agent_arborist.dag_builder import DagConfig, SubDagBuilder
        from agent_arborist.container_runner import ContainerMode

        config = DagConfig(
            name="test",
            spec_id="test",
            container_mode=ContainerMode.AUTO,
        )
        # Test would verify container-up step exists in generated DAG

    @patch("agent_arborist.container_runner.has_devcontainer")
    def test_dag_with_container_mode_disabled(self, mock_has):
        """When disabled, DAG should not have container steps."""
        mock_has.return_value = True  # Even with devcontainer present

        from agent_arborist.dag_builder import DagConfig
        from agent_arborist.container_runner import ContainerMode

        config = DagConfig(
            name="test",
            spec_id="test",
            container_mode=ContainerMode.DISABLED,
        )
        # Test would verify no container-up step in generated DAG
```

### Integration Test (Manual)

To manually test devcontainer support end-to-end:

```bash
# 1. Create a target project with devcontainer
mkdir -p /tmp/test-target/.devcontainer
cat > /tmp/test-target/.devcontainer/devcontainer.json << 'EOF'
{
  "name": "test",
  "image": "mcr.microsoft.com/devcontainers/base:ubuntu",
  "postCreateCommand": "git config --global --add safe.directory /workspace"
}
EOF

# 2. Initialize git repo
cd /tmp/test-target
git init
git add .
git commit -m "Initial"

# 3. Create a simple task spec
mkdir spec
cat > spec/tasks.md << 'EOF'
# Test Tasks

## T001: Test task
Echo hello world
EOF

# 4. Build DAG with auto mode (should detect devcontainer)
arborist build spec/tasks.md -o test.yaml
grep "container-up" test.yaml  # Should find container steps

# 5. Build DAG with disabled mode
arborist build spec/tasks.md -c disabled -o test-no-container.yaml
grep "container-up" test-no-container.yaml  # Should NOT find container steps

# 6. Test container startup manually
devcontainer up --workspace-folder .

# 7. Test exec in container
devcontainer exec --workspace-folder . echo "Hello from container"

# 8. Cleanup
docker stop $(docker ps -q --filter label=devcontainer.local_folder=/tmp/test-target)
```

---

## Generated DAG Structure

When container mode is active (target has `.devcontainer/`):

```yaml
name: T001
steps:
  - name: container-up
    command: devcontainer up --workspace-folder "${ARBORIST_WORKTREE}"

  - name: pre-sync
    command: devcontainer exec --workspace-folder "${ARBORIST_WORKTREE}" arborist task pre-sync T001
    depends: [container-up]

  - name: run
    command: devcontainer exec --workspace-folder "${ARBORIST_WORKTREE}" arborist task run T001
    depends: [pre-sync]

  - name: run-test
    command: devcontainer exec --workspace-folder "${ARBORIST_WORKTREE}" arborist task run-test T001
    depends: [run]

  - name: post-merge
    command: devcontainer exec --workspace-folder "${ARBORIST_WORKTREE}" arborist task post-merge T001
    depends: [run-test]

  - name: container-down
    command: docker stop $(docker ps -q --filter label=devcontainer.local_folder="${ARBORIST_WORKTREE}") 2>/dev/null || true
    depends: [post-merge]

  - name: post-cleanup
    command: arborist task post-cleanup T001
    depends: [container-down]
```

When container mode is disabled (or target has no `.devcontainer/`):

```yaml
name: T001
steps:
  - name: pre-sync
    command: arborist task pre-sync T001

  - name: run
    command: arborist task run T001
    depends: [pre-sync]

  - name: run-test
    command: arborist task run-test T001
    depends: [run]

  - name: post-merge
    command: arborist task post-merge T001
    depends: [run-test]

  - name: post-cleanup
    command: arborist task post-cleanup T001
    depends: [post-merge]
```

---

## Container Isolation Model

Each worktree gets its own container instance:

```
┌─────────────────────────────────────────────────────────────┐
│  Target Project's .devcontainer/                            │
│  (User-provided Dockerfile + devcontainer.json)             │
└─────────────────────────────────────────────────────────────┘
                           │
                    Shared image definition
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ Container    │  │ Container    │  │ Container    │
│ for T001     │  │ for T002     │  │ for T003     │
│              │  │              │  │              │
│ Volume:      │  │ Volume:      │  │ Volume:      │
│ worktrees/   │  │ worktrees/   │  │ worktrees/   │
│ T001/        │  │ T002/        │  │ T003/        │
│ → /workspace │  │ → /workspace │  │ → /workspace │
└──────────────┘  └──────────────┘  └──────────────┘
```

- **Shared:** Same `.devcontainer/` definition, same built image
- **Isolated:** Separate container instances, separate volume mounts
- **Parallel:** Dagu can run multiple containers simultaneously

---

## Usage Examples

### Target Project with DevContainer (auto mode)

```bash
# Target has .devcontainer/ - automatically uses it
cd /path/to/target-project
arborist build spec/tasks.md
# → DAG will run tasks in containers
```

### Target Project without DevContainer (auto mode)

```bash
# Target has no .devcontainer/ - runs on host
cd /path/to/target-project
arborist build spec/tasks.md
# → DAG will run tasks directly on host
```

### Force Container Mode

```bash
# Require container - fails if no .devcontainer/
arborist build spec/tasks.md --container-mode enabled
# → Error: Container mode is 'enabled' but target project has no .devcontainer/
```

### Disable Container Mode

```bash
# Ignore .devcontainer/ even if present
arborist build spec/tasks.md --container-mode disabled
# → DAG will run tasks directly on host
```

---

## Troubleshooting

### "Container mode is 'enabled' but target project has no .devcontainer/"

The target project needs a `.devcontainer/` directory. Either:
- Add one to the target project
- Use `--container-mode auto` or `--container-mode disabled`

### Runner not found in container

The target's devcontainer must include runner CLIs. Add to Dockerfile:

```dockerfile
RUN npm install -g @anthropic-ai/claude-code
```

### Container startup fails

```bash
# Check Docker is running
docker ps

# Check devcontainer CLI
devcontainer --version

# Try manual start
devcontainer up --workspace-folder .arborist/worktrees/spec1/T001
```

### .devcontainer not accessible in worktree

Arborist creates a symlink from worktree to repo root's `.devcontainer/`. If this fails:

```bash
# Manual symlink
ln -s /path/to/target/.devcontainer .arborist/worktrees/spec1/T001/.devcontainer
```

---

## Summary

| Aspect | Description |
|--------|-------------|
| **Who provides devcontainer?** | Target project (user's repo) |
| **What arborist does** | Detects and uses target's `.devcontainer/` |
| **Default behavior** | `auto` - use if present, otherwise host |
| **Target requirements** | `.devcontainer/` with runner CLIs installed |
| **External devcontainer** | Submodule (recommended) or subtree |
| **Container isolation** | One container per worktree |
