# DevContainer Implementation Review

**Date:** 2026-01-28
**Scope:** Comprehensive review of devcontainer support implementation
**Purpose:** Assess current implementation for potential refactoring

---

## Executive Summary

Devcontainer support was implemented across 9 commits (Jan 26-27, 2026), introducing the ability to run Arborist tasks inside the target project's devcontainer. The implementation **works functionally** but exhibits **architectural brittleness** with scattered concerns, defensive coding, and workarounds for devcontainer CLI limitations.

**Key Finding:** The integration is more invasive than necessary. Arborist has become "container-aware" throughout its codebase when it should simply **delegate execution** to devcontainer CLI and trust it to handle the details.

---

## Part 1: Current Implementation Analysis

### 1.1 Component Overview

The devcontainer support touches 8 files across the codebase:

```
src/agent_arborist/
├── container_runner.py      558 lines  (NEW) - Container operations
├── runner.py                 441 lines  (+138) - Container-aware runners
├── dag_builder.py            508 lines  (+156) - Container lifecycle in DAGs
├── dag_generator.py          N/A lines  (+131) - AI-generated DAG support
├── cli.py                    N/A lines  (+119) - Container CLI commands
├── step_results.py           N/A lines  (+26)  - Container step results

tests/
├── test_container_runner.py  703 lines  (NEW) - Container runner tests
├── test_e2e_devcontainer.py  501 lines  (NEW) - End-to-end integration
└── test_runner.py            144 lines  (+82)  - Runner container tests
```

**Total Addition:** ~1,300 lines of new code + extensive modifications.

### 1.2 Architecture: How It Works

#### Current Flow

```
┌─────────────────────────────────────────────────────────────┐
│ DAG Builder (dag_builder.py)                                │
│ - Detects .devcontainer in target project                   │
│ - Adds container-up/container-down steps to DAG             │
│ - Injects ARBORIST_WORKTREE env var                        │
│ - Passes runner/model config through all commands           │
└─────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ CLI Commands (cli.py)                                        │
│ - arborist task container-up <task_id>                      │
│   • Creates .devcontainer symlink if needed                 │
│   • Validates devcontainer config                           │
│   • Calls DevContainerRunner.container_up()                 │
│ - arborist task run <task_id> --runner --model              │
│   • Gets runner instance with model                          │
│   • Passes worktree as cwd to runner                        │
│ - arborist task container-down <task_id>                    │
└─────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ Container Runner (container_runner.py)                       │
│ - container_up(worktree_path)                               │
│   • validate_devcontainer_config() - check WORKDIR/folder   │
│   • _ensure_devcontainer_accessible() - symlink logic       │
│   • devcontainer up --workspace-folder --remote-env         │
│   • wait_for_container_ready() - polls until responsive     │
│ - container_down(worktree_path)                             │
│   • docker ps -q --filter label=devcontainer.local_folder   │
│   • docker stop <container_id>                              │
└─────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ Runner Instances (runner.py)                                 │
│ ClaudeRunner / OpencodeRunner / GeminiRunner                 │
│ - run(prompt, cwd=worktree_path)                            │
│   • _check_container_running(worktree_path)                 │
│   • If container: _wrap_in_container(cmd, worktree_path)    │
│   • subprocess.run(cmd, cwd=None if using_container)        │
└─────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ _wrap_in_container() Helper                                  │
│ - Check if container running (docker ps)                     │
│ - Read devcontainer.json for workspaceFolder                │
│ - Build: devcontainer exec --workspace-folder <path> \      │
│         bash -lc "cd <workspace_folder> && <command>"        │
│ - Returns wrapped command list                               │
└─────────────────────────────────────────────────────────────┘
```

#### Key Integration Points

1. **DAG Generation Time**: `dag_builder.py` detects `.devcontainer/` and modifies DAG structure
2. **Container Lifecycle**: Arborist CLI provides `container-up` and `container-down` commands
3. **Runner Execution**: Each runner checks for running containers and wraps commands
4. **Command Wrapping**: `_wrap_in_container()` handles `devcontainer exec` with working directory hack

### 1.3 What Works Well (Streamlined Aspects)

#### ✅ Clear Separation of Responsibilities

The **concept** is clean:
- Arborist runs on the host
- Tasks execute inside containers
- Each worktree gets its own container instance

#### ✅ Using devcontainer CLI (Not Docker Directly)

Leveraging `devcontainer up/exec` rather than raw `docker run` commands:
- Respects target's devcontainer.json configuration
- Handles features, mounts, and environment properly
- Standard tooling that VS Code/Codespaces use

#### ✅ Transparent Auto-Detection

```python
class ContainerMode(Enum):
    AUTO = "auto"     # Use if .devcontainer exists
    ENABLED = "enabled"  # Require .devcontainer
    DISABLED = "disabled"  # Never use
```

Users don't need to think about containers if `.devcontainer/` exists - it "just works".

#### ✅ CLI Command Abstraction

Instead of embedding shell commands in DAG YAML:
```yaml
# Good: Uses arborist CLI
- name: container-up
  command: arborist task container-up T001

# Instead of: Raw devcontainer commands (brittle)
- name: container-up
  command: |
    cd $WORKTREE
    devcontainer up --workspace-folder . --remote-env OPENAI_API_KEY=$OPENAI_API_KEY
```

This allows Python logic (symlinks, validation) to run before container startup.

#### ✅ Comprehensive Testing

- 16 unit tests in `test_container_runner.py`
- Full e2e test in `test_e2e_devcontainer.py`
- Validates DAG structure, container lifecycle, commit generation

---

## Part 2: Brittleness Analysis

### 2.1 Scattered Container-Awareness

**Problem:** Container logic is spread across multiple modules instead of being centralized.

#### container_runner.py
- `has_devcontainer()` - Detection
- `validate_devcontainer_config()` - Validation
- `DevContainerRunner.container_up()` - Startup
- `_ensure_devcontainer_accessible()` - Symlink management

#### runner.py
- `_check_container_running()` - Detection (duplicate concept)
- `get_workspace_folder()` - Path resolution
- `_wrap_in_container()` - Command wrapping
- All three runner classes: Container-awareness in `.run()` methods

#### dag_builder.py
- `should_use_container()` - Decision logic
- Container lifecycle step injection
- `ARBORIST_WORKTREE` environment variable management

#### cli.py
- `task_container_up()` - CLI wrapper
- `task_container_down()` - CLI wrapper
- `_count_changed_files()` - Modified to work with worktrees
- Runner/model config threading through multiple commands

**Why This Is Brittle:**
- **No single source of truth** for "is this task using a container?"
- **Duplicate detection logic** in multiple places
- **Difficult to change** - modifying container behavior requires touching 5+ files
- **Hard to test** - integration tests required to verify behavior

### 2.2 Defensive Coding and Workarounds

#### Workspace Folder Resolution (3 different places)

**container_runner.py:61-130 - validate_devcontainer_config()**
```python
# Check workspaceFolder
workspace_folder = dc_config.get("workspaceFolder")

# Check Dockerfile WORKDIR
if dockerfile.exists():
    for line in dockerfile_content.split('\n'):
        if line.lower().startswith('workdir'):
            workdir_match = line.split(maxsplit=1)[1]

# If workspaceFolder is set, WORKDIR must match
if workdir_match and workspace_folder:
    if workdir_match.replace('\\', '') != workspace_folder:
        errors.append(f"Dockerfile WORKDIR '{workdir_match}' does not match...")
```

**runner.py:38-63 - get_workspace_folder()**
```python
def get_workspace_folder(git_root: Path) -> str:
    devcontainer_json = git_root / ".devcontainer" / "devcontainer.json"
    if devcontainer_json.exists():
        try:
            content = json.loads(devcontainer_json.read_text())
            configured = content.get("workspaceFolder")
            if configured:
                return configured
        except (json.JSONDecodeError, IOError):
            pass

    repo_name = git_root.name if git_root.name else "workspace"
    return f"/workspaces/{repo_name}"
```

**runner.py:66-95 - _wrap_in_container() (duplicates above)**
```python
devcontainer_json = git_root / ".devcontainer" / "devcontainer.json"
if devcontainer_json.exists():
    try:
        content = json.loads(devcontainer_json.read_text())
        configured_workspace = content.get("workspaceFolder")
        if configured_workspace:
            workspace_folder = configured_workspace
        else:
            workspace_folder = f"/workspaces/{worktree_path.name}"
    except (json.JSONDecodeError, IOError):
        workspace_folder = f"/workspaces/{worktree_path.name}"
```

**Why This Is Brittle:**
- **Three different implementations** of the same logic
- **Inconsistent fallback behavior** (repo name vs worktree name)
- **No caching** - reads devcontainer.json multiple times per task
- **Error handling variations** - some raise, some fallback, some return None

#### Login Shell Hack

**runner.py:102-109**
```python
# Use bash -lc instead of bash -c
# Workaround for: https://github.com/devcontainers/cli/issues/703
exec_cmd = [
    "devcontainer",
    "exec",
    "--workspace-folder",
    str(worktree_path.resolve()),
    "bash",
    "-lc",  # ← Login shell to get proper PATH
    f"cd {workspace_folder} && {shell_cmd}",
]
```

**Why This Is Brittle:**
- **Workaround for devcontainer CLI limitation** - no native `--workdir` flag
- **Shell-specific** - assumes bash is available
- **PATH dependent** - relies on login shell sourcing `/etc/profile`
- **Fragile quoting** - uses `shlex.quote()` but complex nested commands

### 2.3 Environment Variable Juggling

Multiple mechanisms for passing configuration:

#### At Container Startup (container_runner.py:281-288)
```python
# Pass through OPENAI_API_KEY if available
import os
has_key = "OPENAI_API_KEY" in os.environ
print(f"DEBUG container_up: has OPENAI_API_KEY = {has_key}", file=sys.stderr)
if has_key:
    key_val = os.environ['OPENAI_API_KEY']
    print(f"DEBUG container_up: key length = {len(key_val)}", file=sys.stderr)
    cmd.extend(["--remote-env", f"OPENAI_API_KEY={key_val}"])
```

#### In DAG Leaf Subdags (dag_builder.py:263-266)
```python
# Pass through OPENAI_API_KEY if available
import os
if "OPENAI_API_KEY" in os.environ:
    env_vars.append(f"OPENAI_API_KEY={os.environ['OPENAI_API_KEY']}")
```

#### Via Runner/Model CLI Flags (dag_builder.py:192-196)
```python
run_cmd = f"arborist task run {task_id}"
if self.config.runner:
    run_cmd += f" --runner {self.config.runner}"
if self.config.model:
    run_cmd += f" --model '{self.config.model}'"
```

**Why This Is Brittle:**
- **Duplicate logic** for API key passing
- **DEBUG code in production** - print statements with DEBUG prefix
- **String concatenation** for command building (prone to quoting issues)
- **No validation** - doesn't check if API key is valid format

### 2.4 Symlink Management Complexity

**container_runner.py:508-526**
```python
def _ensure_devcontainer_accessible(self, worktree_path: Path) -> None:
    """Ensure worktree can access .devcontainer config.

    Git worktrees share .git with main repo, so .devcontainer
    should be accessible. If not, create symlink.
    """
    target = worktree_path / ".devcontainer"
    if target.exists():
        return

    # Find repo root's .devcontainer
    git_root = get_git_root()
    source = git_root / ".devcontainer"

    if source.exists() and source != target:
        target.symlink_to(source)
```

**Why This Is Brittle:**
- **Mutates worktree state** - creates symlinks silently
- **Assumes git worktree behavior** - comment says "should be accessible" but then creates symlink anyway
- **No cleanup** - symlinks persist after container-down
- **Platform-specific** - symlink behavior differs on Windows

### 2.5 Container Detection Redundancy

**Two separate functions that do the same thing:**

**runner.py:18-35**
```python
def _check_container_running(worktree_path: Path) -> bool:
    """Check if a devcontainer is running for the given worktree."""
    try:
        result = subprocess.run(
            ["docker", "ps", "-q", "--filter",
             f"label=devcontainer.local_folder={worktree_path.resolve()}"],
            capture_output=True, text=True, timeout=5,
        )
        return bool(result.stdout.strip())
    except Exception:
        return False
```

**container_runner.py:453-507 - wait_for_container_ready()**
```python
def wait_for_container_ready(self, worktree_path: Path, timeout: int = 30) -> ContainerResult:
    while time.time() - start_time < timeout:
        check_cmd = [
            "docker", "ps", "-q", "--filter",
            f"label=devcontainer.local_folder={worktree_path}",
        ]
        result = subprocess.run(check_cmd, capture_output=True, text=True, timeout=5)
        if result.stdout.strip():
            # Container found, test if it's responsive
            test_result = self.exec(worktree_path, ["echo", "ready"], timeout=5)
```

**Why This Is Brittle:**
- **Duplicate Docker command** for checking container existence
- **Different timeout handling** (5s vs 30s)
- **Different return types** (bool vs ContainerResult)
- **Inconsistent error handling** (swallow all exceptions vs return error details)

### 2.6 Runner-Model Config Threading

**Added in commits: 6cff69c, d9a7fdf**

After the initial devcontainer implementation, runner/model configuration was threaded through the entire system to ensure tasks use the correct AI runner inside containers.

#### Changes Made

**1. DagConfig expansion (dag_builder.py)**
```python
@dataclass
class DagConfig:
    name: str
    description: str = ""
    spec_id: str = ""
    container_mode: ContainerMode = ContainerMode.AUTO
    repo_path: Path | None = None
    runner: str | None = None  # ← Added
    model: str | None = None   # ← Added
```

**2. CLI flag additions (cli.py)**
```python
# Added to task run
@click.option("--model", "-m", default=None, help="Model to use")
def task_run(ctx, task_id: str, timeout: int, runner: str | None, model: str | None):
    resolved_model = model if model is not None else get_default_model()
    runner_instance = get_runner(runner_type, model=resolved_model)

# Added to post-merge
@click.option("--runner", "-r", type=click.Choice([...]))
@click.option("--model", "-m", default=None, help="Model to use")
def task_post_merge(ctx, task_id: str, timeout: int, runner: str | None, model: str | None):
    runner_type = runner if runner is not None else get_default_runner()
    resolved_model = model if model is not None else get_default_model()
```

**3. DAG command generation (dag_builder.py)**
```python
# Commands now include runner/model flags
run_cmd = f"arborist task run {task_id}"
if self.config.runner:
    run_cmd += f" --runner {self.config.runner}"
if self.config.model:
    run_cmd += f" --model '{self.config.model}'"
```

#### Why This Was Added

**Problem:** Without explicit config passing, tasks inside containers relied on environment variables:
```bash
# Container environment from devcontainer.json
"remoteEnv": {
  "ARBORIST_DEFAULT_RUNNER": "opencode",
  "ARBORIST_DEFAULT_MODEL": "openai/gpt-4o-mini"
}
```

This approach had issues:
- ❌ User's command-line flags (`--runner claude`) ignored inside container
- ❌ DAG YAML doesn't show which runner is actually used
- ❌ Hard to override per-task without changing devcontainer.json

**Solution:** Pass runner/model explicitly via CLI flags in generated commands:
```yaml
# DAG shows exactly what runs
- name: run
  command: arborist task run T001 --runner opencode --model openai/gpt-4o-mini
```

#### Is This Good Design?

**✅ Advantages:**
- Explicit configuration in DAG YAML (visible, auditable)
- Command-line flags override environment defaults
- Per-task runner selection possible
- Consistent with Arborist's explicit-over-implicit philosophy

**⚠️ But Also:**
- Adds complexity to DagConfig (2 more fields)
- String concatenation for command building (fragile)
- Config threaded through 3 layers (CLI → DagConfig → DAG commands)
- Duplicate model resolution logic in multiple commands

#### Alternative Approaches

**Option 1: Trust environment variables (simpler)**
```python
# No --runner or --model flags needed
run_cmd = f"arborist task run {task_id}"
# Relies on ARBORIST_DEFAULT_RUNNER in container environment
```

**Option 2: Config file per worktree**
```bash
# .arborist/worktrees/T001/.arborist-config.json
{"runner": "opencode", "model": "openai/gpt-4o-mini"}

# Commands read config from worktree
arborist task run T001  # Reads config from T001's worktree
```

**Option 3: Keep current approach but simplify**
- Keep explicit flags (good for visibility)
- Use helper function to build commands (avoid string concat)
- Centralize model resolution (remove duplicates)

#### Recommendation for Refactoring

**Keep the runner-model config threading** - it's good explicit design. But simplify implementation:

```python
# Centralized command builder
def build_task_command(
    task_id: str,
    command: str,  # "run", "post-merge", etc.
    runner: str | None = None,
    model: str | None = None
) -> str:
    """Build task command with runner/model flags."""
    cmd = f"arborist task {command} {task_id}"
    if runner:
        cmd += f" --runner {runner}"
    if model:
        cmd += f" --model {shlex.quote(model)}"
    return cmd

# Usage in dag_builder.py
run_cmd = build_task_command(task_id, "run",
                             runner=self.config.runner,
                             model=self.config.model)
```

**Benefits:**
- ✅ Keeps explicit configuration (good for debugging)
- ✅ Centralizes command building (no string concat in multiple places)
- ✅ Proper quoting (shlex.quote for model names with spaces)
- ✅ Easy to extend (add more flags in one place)

### 2.7 Config Validation Over-Engineering

**container_runner.py:61-131 - validate_devcontainer_config()**

This 70-line function checks for:
- devcontainer.json existence and parsing
- workspaceFolder configuration
- Dockerfile existence
- WORKDIR directive parsing
- Mismatch detection between workspaceFolder and WORKDIR

**Problems:**
- **Assumes too much** about devcontainer.json structure
- **Parses Dockerfile with string splitting** (fragile)
- **Warns about mismatches** that devcontainer CLI would handle correctly
- **Not comprehensive** - doesn't validate features, mounts, other fields

**Reality Check:**
The devcontainer CLI **already validates configuration** when you run `devcontainer up`. This validation duplicates work and can give **false positives** (warnings about things that work fine).

---

## Part 3: Conclusion - A Fresh Approach

### 3.1 Core Problem: Over-Complicated Implementation, Not Architecture

**Important Realization:** The container lifecycle management (up/down) is **actually correct design**, not over-engineering.

**Why Container Lifecycle Is Necessary:**

Given that multiple steps may run in parallel on the same worktree:
```yaml
# Task T001 subdag - multiple steps may run in parallel
- name: container-up      # Start ONE long-running container
  command: arborist task container-up T001

- name: run              # Uses the container
  command: arborist task run T001
  depends: [container-up]

- name: run-test         # May run in parallel with other steps
  command: arborist task run-test T001
  depends: [run]

- name: post-merge       # May run in parallel with other tasks
  command: arborist task post-merge T001
  depends: [run-test]

- name: container-down   # Stop container after ALL steps complete
  command: arborist task container-down T001
  depends: [post-merge]
```

**If we eliminated container-up/down:**
- ❌ Every `devcontainer exec` would need container already running
- ❌ Each parallel step might try to start its own container (conflicts)
- ❌ No clear ownership of when container should stop
- ❌ Container might stop while parallel steps still running

**With explicit lifecycle:**
- ✅ ONE container-up ensures container exists before any exec
- ✅ Multiple parallel steps all use the SAME running container
- ✅ ONE container-down cleanly shuts down after all steps complete
- ✅ Clear dependency graph: up → [exec steps] → down

**Conclusion:** Keep container-up/down. The brittleness is in the **implementation details**, not the architecture.

### 3.2 What Devcontainer CLI Already Does

The devcontainer CLI is **designed to handle**:
- ✅ Parsing devcontainer.json
- ✅ Building/pulling Docker images
- ✅ Mounting workspace folders correctly
- ✅ Setting up environment variables
- ✅ Running commands inside containers
- ✅ Validating configuration

**Arborist should:**
- ✅ Manage container lifecycle (start/stop) - **necessary for parallel execution**
- ✅ Wrap commands in `devcontainer exec` - **centralized, consistent**
- ❌ NOT duplicate validation, workspace resolution, or configuration parsing

### 3.3 Separation of Concerns - Ideal Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Arborist Responsibility                                      │
│ ─────────────────────────                                   │
│ 1. Detect if .devcontainer/ exists                          │
│ 2. Manage container lifecycle (start one, stop one)         │
│    - arborist task container-up T001                        │
│    - arborist task container-down T001                      │
│ 3. Wrap runner commands in devcontainer exec                │
│    - Centralized in ONE place (runner.py)                   │
│    - Consistent across all runners                          │
│ 4. Manage worktree lifecycle (create, cleanup)              │
│ 5. Orchestrate task dependencies via Dagu                   │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ Devcontainer CLI Responsibility                              │
│ ────────────────────────────────                            │
│ 1. Parse devcontainer.json                                  │
│ 2. Build/start containers (via devcontainer up)             │
│ 3. Mount workspaces correctly                               │
│ 4. Set up environment variables                             │
│ 5. Execute commands in correct working directory            │
│ 6. Handle PATH, shell initialization, etc.                  │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ Arborist Should NOT Do (Currently Does)                     │
│ ────────────────────────────────────────────                │
│ ✗ Validate devcontainer.json / Dockerfile consistency       │
│ ✗ Resolve workspace folder paths from config                │
│ ✗ Check for WORKDIR/workspaceFolder mismatches             │
│ ✗ Manage .devcontainer symlinks in worktrees               │
│ ✗ Duplicate container detection in multiple places          │
│ ✗ Parse Dockerfile for WORKDIR directives                   │
│ ✗ Implement login shell hacks for PATH setup                │
└─────────────────────────────────────────────────────────────┘
```

### 3.4 Proposed Refactoring Strategy

#### Phase 1: Simplify Runner Integration (Highest Impact)

**Current:** 441 lines in `runner.py` with container-awareness duplicated in every runner

**Problem:** Each runner (Claude/OpenCode/Gemini) has identical container-wrapping logic:
- `_check_container_running(worktree_path)` - duplicate detection
- `get_workspace_folder()` reading devcontainer.json
- `_wrap_in_container()` with bash -lc hack
- 3x implementations of the same logic

**Proposed:** Single execution wrapper, keep devcontainer exec wrapping

```python
# In runner.py - ONE function centralizes container logic
def _execute_command(cmd: list[str], cwd: Path | None = None, timeout: int = 60) -> RunResult:
    """Execute command, wrapping in devcontainer exec if container is running.

    Checks if a container is running for the given worktree and wraps the
    command accordingly. This is the ONLY place that knows about containers.
    """
    if cwd and _is_container_running(cwd):
        # Container is running - wrap the command
        wrapped_cmd = [
            "devcontainer", "exec",
            "--workspace-folder", str(cwd),
        ] + cmd
        result = subprocess.run(wrapped_cmd, capture_output=True, text=True, timeout=timeout)
    else:
        # No container - run directly on host
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)

    return RunResult(
        success=result.returncode == 0,
        output=result.stdout,
        error=result.stderr if result.returncode != 0 else None,
        exit_code=result.returncode
    )

def _is_container_running(worktree_path: Path) -> bool:
    """Check if devcontainer is running for this worktree."""
    try:
        result = subprocess.run(
            ["docker", "ps", "-q", "--filter",
             f"label=devcontainer.local_folder={worktree_path.resolve()}"],
            capture_output=True, text=True, timeout=5,
        )
        return bool(result.stdout.strip())
    except Exception:
        return False

# All runners delegate to this - NO per-runner container logic
class ClaudeRunner(Runner):
    def run(self, prompt: str, timeout: int = 60, cwd: Path | None = None) -> RunResult:
        cmd = ["claude", "--dangerously-skip-permissions", "-p", prompt]
        if self.model:
            cmd.extend(["--model", self.model])
        return _execute_command(cmd, cwd=cwd, timeout=timeout)

class OpencodeRunner(Runner):
    def run(self, prompt: str, timeout: int = 60, cwd: Path | None = None) -> RunResult:
        cmd = ["opencode", "run"]
        if self.model:
            cmd.extend(["-m", self.model])
        cmd.append(prompt)
        return _execute_command(cmd, cwd=cwd, timeout=timeout)

# Note: For devcontainer e2e tests, we'll focus on ClaudeRunner only
# OpenCode/Gemini support remains but won't be tested in devcontainer context

class GeminiRunner(Runner):
    def run(self, prompt: str, timeout: int = 60, cwd: Path | None = None) -> RunResult:
        cmd = ["gemini", "--yolo"]
        if self.model:
            cmd.extend(["-m", self.model])
        cmd.append(prompt)
        return _execute_command(cmd, cwd=cwd, timeout=timeout)
```

**Key Simplifications:**
- ✅ Removes `get_workspace_folder()` - devcontainer CLI handles working directory
- ✅ Removes `_wrap_in_container()` complex logic with bash -lc hack
- ✅ Removes duplicate container detection in each runner
- ✅ Trust devcontainer CLI to handle PATH, working directory, environment
- ✅ Single `_is_container_running()` function (20 lines) replaces 150+ lines

**Benefits:**
- ✅ Eliminates ~200 lines of duplicate container-awareness code
- ✅ No more workspace folder resolution from devcontainer.json
- ✅ No more login shell hack - devcontainer CLI handles PATH
- ✅ Consistent behavior across all runners
- ✅ **Still wraps with devcontainer exec** - centralized in ONE place

#### Phase 2: Simplify Container Lifecycle Commands (Keep Them!)

**Current:** Arborist provides `arborist task container-up/down` with extensive validation and symlink management

**Important:** We **keep** these commands because:
- ✅ Necessary for parallel execution (one container, multiple steps)
- ✅ Provides clean abstraction in DAG YAML
- ✅ Allows Python logic before/after container operations

**Proposed:** Simplify implementation, remove validation/symlink complexity

```python
# In cli.py - Simplified container-up (was 100+ lines with validation)
@task.command("container-up")
@click.argument("task_id")
@click.pass_context
def task_container_up(ctx: click.Context, task_id: str) -> None:
    """Start devcontainer for task worktree."""
    manifest = _load_manifest(ctx)
    worktree_path = _get_worktree_path(manifest.spec_id, task_id)

    # Trust devcontainer CLI to validate config, handle mounts, etc.
    cmd = ["devcontainer", "up", "--workspace-folder", str(worktree_path)]

    # Pass through API keys if available
    env_vars = {}
    if key := os.environ.get("OPENAI_API_KEY"):
        env_vars["OPENAI_API_KEY"] = key
    # Add other API keys as needed

    if env_vars:
        for key, val in env_vars.items():
            cmd.extend(["--remote-env", f"{key}={val}"])

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    if result.returncode != 0:
        console.print(f"[red]Container startup failed:[/red] {result.stderr}")
        raise SystemExit(1)

    console.print(f"[green]✓[/green] Container started for {task_id}")

# In cli.py - Simplified container-down (was 50+ lines)
@task.command("container-down")
@click.argument("task_id")
@click.pass_context
def task_container_down(ctx: click.Context, task_id: str) -> None:
    """Stop devcontainer for task worktree."""
    manifest = _load_manifest(ctx)
    worktree_path = _get_worktree_path(manifest.spec_id, task_id)

    # Find and stop container
    find_cmd = ["docker", "ps", "-q", "--filter",
                f"label=devcontainer.local_folder={worktree_path}"]
    result = subprocess.run(find_cmd, capture_output=True, text=True)

    if container_id := result.stdout.strip():
        subprocess.run(["docker", "stop", container_id], check=True)
        console.print(f"[green]✓[/green] Container stopped for {task_id}")
    else:
        console.print(f"[yellow]![/yellow] No container running for {task_id}")
```

**Removed from Implementation:**
- ❌ `validate_devcontainer_config()` - 70 lines of validation logic
- ❌ `_ensure_devcontainer_accessible()` - symlink creation
- ❌ `wait_for_container_ready()` - polling logic (devcontainer up waits for readiness)
- ❌ DEBUG print statements throughout
- ❌ Dockerfile WORKDIR parsing
- ❌ workspaceFolder mismatch detection

**Benefits:**
- ✅ Reduces cli.py container code from ~120 lines to ~40 lines (67% reduction)
- ✅ **Keeps lifecycle management** (necessary for parallel execution)
- ✅ Trust devcontainer CLI to validate and handle configuration
- ✅ Cleaner, more maintainable code
- ✅ Still provides clean abstraction in DAG YAML

#### Phase 3: Drastically Simplify container_runner.py

**Current:** 558 lines with validation, workspace resolution, symlink management, DevContainerRunner class

**Proposed:** ~50 lines with simple detection only

```python
# container_runner.py - Simplified to bare essentials
"""DevContainer detection for target projects."""

from pathlib import Path
from enum import Enum

class ContainerMode(Enum):
    """Container execution mode."""
    AUTO = "auto"
    ENABLED = "enabled"
    DISABLED = "disabled"

def has_devcontainer(repo_path: Path) -> bool:
    """Check if path has .devcontainer/ directory."""
    devcontainer_dir = repo_path / ".devcontainer"
    return (
        devcontainer_dir.is_dir() and
        (devcontainer_dir / "devcontainer.json").exists()
    )

def should_use_container(mode: ContainerMode, repo_path: Path | None = None) -> bool:
    """Determine if container mode should be used."""
    if mode == ContainerMode.DISABLED:
        return False

    has_dc = has_devcontainer(repo_path)

    if mode == ContainerMode.ENABLED and not has_dc:
        raise RuntimeError(
            "Container mode is 'enabled' but target project has no .devcontainer/. "
            "Either add a .devcontainer/ or use --container-mode auto"
        )

    return has_dc if mode == ContainerMode.AUTO else True

# That's it! Everything else is removed.
```

**Removed from container_runner.py:**
- ❌ `validate_devcontainer_config()` - 70 lines
- ❌ `_ensure_devcontainer_accessible()` - 18 lines
- ❌ `DevContainerRunner` class - 225 lines
- ❌ `wait_for_container_ready()` - 54 lines
- ❌ `get_workspace_folder()` - duplicate of runner.py version
- ❌ `devcontainer_up_command()` / `devcontainer_down_command()` - unused
- ❌ `check_devcontainer_cli()` / `check_docker()` - CLI checks
- ❌ All dataclasses: `ContainerConfig`, `ContainerResult`, `ValidationStatus`

**Benefits:**
- ✅ Reduces container_runner.py from 558 lines to ~50 lines (91% reduction!)
- ✅ Single source of truth for detection
- ✅ No duplicate validation (devcontainer CLI validates)
- ✅ No workspace resolution (devcontainer CLI resolves)
- ✅ No symlink management (git worktrees share files)
- ✅ Much easier to understand and maintain

#### Phase 4: Simplify DAG Builder (Keep Structure, Clean Implementation)

**Current:** `dag_builder.py` conditionally adds container lifecycle steps with complex logic

**Important:** We **keep** the DAG structure (container-up/down steps) because it's correct for parallel execution

**Proposed:** Simplify the implementation, remove environment variable complexity

```python
# In dag_builder.py - Simplified leaf subdag building
def _build_leaf_subdag(self, task_id: str) -> SubDag:
    """Build leaf subdag - structure depends on container mode."""
    steps: list[SubDagStep] = []

    # Pre-sync (always on host)
    steps.append(SubDagStep(
        name="pre-sync",
        command=f"arborist task pre-sync {task_id}",
    ))

    # Container lifecycle if using containers
    if self._use_containers:
        steps.append(SubDagStep(
            name="container-up",
            command=f"arborist task container-up {task_id}",
            depends=["pre-sync"],
        ))
        prev_step = "container-up"
    else:
        prev_step = "pre-sync"

    # Task execution steps (run in container if available)
    steps.extend([
        SubDagStep(
            name="run",
            command=self._build_run_command(task_id),
            depends=[prev_step],
        ),
        SubDagStep(
            name="commit",
            command=f"arborist task commit {task_id}",
            depends=["run"],
        ),
        SubDagStep(
            name="run-test",
            command=f"arborist task run-test {task_id}",
            depends=["commit"],
        ),
        SubDagStep(
            name="post-merge",
            command=self._build_post_merge_command(task_id),
            depends=["run-test"],
        ),
    ])

    # Container cleanup if using containers
    if self._use_containers:
        steps.append(SubDagStep(
            name="container-down",
            command=f"arborist task container-down {task_id}",
            depends=["post-merge"],
        ))
        prev_step = "container-down"
    else:
        prev_step = "post-merge"

    # Final cleanup (always on host)
    steps.append(SubDagStep(
        name="post-cleanup",
        command=f"arborist task post-cleanup {task_id}",
        depends=[prev_step],
    ))

    # Simplified environment - no more API key juggling here
    spec_id = self.config.spec_id or self.config.name
    env_vars = [f"ARBORIST_MANIFEST={spec_id}.json"]

    return SubDag(name=task_id, steps=steps, env=env_vars)

def _build_run_command(self, task_id: str) -> str:
    """Build run command with runner/model flags."""
    cmd = f"arborist task run {task_id}"
    if self.config.runner:
        cmd += f" --runner {self.config.runner}"
    if self.config.model:
        cmd += f" --model '{self.config.model}'"
    return cmd

def _build_post_merge_command(self, task_id: str) -> str:
    """Build post-merge command with runner/model flags."""
    cmd = f"arborist task post-merge {task_id}"
    if self.config.runner:
        cmd += f" --runner {self.config.runner}"
    if self.config.model:
        cmd += f" --model '{self.config.model}'"
    return cmd
```

**Removed Complexity:**
- ❌ No more `ARBORIST_WORKTREE` env var juggling in DAG
- ❌ No more duplicate `OPENAI_API_KEY` passing in DAG env vars
- ❌ No more absolute path computation in DAG builder
- ❌ Worktree path is managed by CLI commands, not DAG

**Benefits:**
- ✅ **Keeps correct structure** (container-up → exec → container-down)
- ✅ Cleaner implementation without env var complexity
- ✅ API keys handled by devcontainer up, not DAG environment
- ✅ Runner/model config passed via CLI flags, not embedded in commands
- ✅ More maintainable - clear separation of concerns

### 3.5 Code Reduction Estimate

| Module | Current Lines | Proposed Lines | Reduction | What's Removed |
|--------|--------------|----------------|-----------|----------------|
| `container_runner.py` | 558 | ~50 | -508 (-91%) | Validation, DevContainerRunner class, workspace resolution, symlink mgmt |
| `runner.py` | 441 | ~200 | -241 (-55%) | Duplicate detection, workspace resolution, bash -lc hack, per-runner logic |
| `dag_builder.py` | 508 | ~450 | -58 (-11%) | Env var complexity, absolute path computation |
| `cli.py` | ~120 (container) | ~40 | -80 (-67%) | Validation calls, symlink logic, DEBUG prints |
| **Total** | ~1,627 | ~740 | **-887 lines (-54%)** |

**What We're Keeping:**
- ✅ Container lifecycle commands (arborist task container-up/down) - **necessary for parallel execution**
- ✅ Devcontainer exec wrapping in runners - **centralized in one place**
- ✅ Container mode detection in DAG builder - **determines DAG structure**
- ✅ Container-up/down steps in generated DAGs - **correct architecture**

**What We're Removing:**
- ❌ DevContainerRunner class (225 lines) - replaced by simple CLI commands
- ❌ validate_devcontainer_config() (70 lines) - trust devcontainer CLI
- ❌ Workspace folder resolution (3 duplicate implementations ~80 lines)
- ❌ _wrap_in_container() complexity with bash -lc hack (~50 lines)
- ❌ Symlink management (_ensure_devcontainer_accessible) (18 lines)
- ❌ wait_for_container_ready() polling (54 lines) - devcontainer up waits
- ❌ DEBUG print statements throughout
- ❌ Environment variable juggling in multiple places

### 3.6 Risks and Trade-offs

#### ✅ Benefits of Refactoring

1. **Drastically simpler code** - 54% reduction in container-related code (~900 lines)
2. **Centralized container logic** - ONE place for devcontainer exec wrapping (runner.py)
3. **No duplicate logic** - workspace folder resolution, validation, detection consolidated
4. **Easier to maintain** - changes to container behavior touch 1-2 files, not 5+
5. **Trust the tool** - devcontainer CLI is mature and handles edge cases we were re-implementing
6. **Better error messages** - devcontainer CLI errors are clearer than our validation errors
7. **Keeps correct architecture** - Container lifecycle (up/down) preserved for parallel execution

#### ⚠️ Trade-offs and Concerns

1. **Loss of Python-side validation**
   - Current: `validate_devcontainer_config()` catches WORKDIR/workspaceFolder mismatches
   - Proposed: Rely on devcontainer CLI errors
   - **Reality Check:** devcontainer CLI already validates; our validation sometimes gives false positives
   - **Mitigation:** If users hit config errors, devcontainer CLI will report them clearly

2. **Loss of symlink auto-creation**
   - Current: `_ensure_devcontainer_accessible()` creates symlinks for worktrees missing .devcontainer
   - Proposed: Assume .devcontainer is accessible (git worktrees share tracked files)
   - **Reality Check:** Git worktrees DO share all tracked files - symlinks only needed if .devcontainer is gitignored (bad practice)
   - **Mitigation:** Document that .devcontainer should be committed to repo

3. **Loss of bash -lc workaround**
   - Current: `bash -lc "cd /workspace && command"` ensures PATH and working directory
   - Proposed: Trust `devcontainer exec` to handle environment and working directory
   - **Test Required:** Verify that `devcontainer exec --workspace-folder <path> opencode run "..."` works without shell wrapper
   - **Mitigation:** If devcontainer CLI doesn't handle PATH, we can add back a minimal wrapper

4. **Loss of readiness polling**
   - Current: `wait_for_container_ready()` polls until container responds
   - Proposed: Trust `devcontainer up` to return when container is ready
   - **Reality Check:** devcontainer CLI already waits for container readiness before returning
   - **Mitigation:** If timing issues occur, add simple retry logic in CLI commands

5. **Less granular logging**
   - Current: DEBUG prints show API key lengths, container checks, command construction
   - Proposed: Less verbose output, cleaner logs
   - **Mitigation:** Add `--verbose` flag to cli.py that shows devcontainer commands before execution

#### ❓ Key Question to Validate

**Does `devcontainer exec` work without the bash -lc wrapper?**

Current implementation:
```bash
devcontainer exec --workspace-folder /path bash -lc "cd /workspace && opencode run 'task'"
```

Proposed simplification:
```bash
devcontainer exec --workspace-folder /path opencode run "task"
```

**Testing Required:** Run spike test (see Step 1 in implementation plan) to verify devcontainer CLI handles:
- ✓ Working directory (respects workspaceFolder from devcontainer.json)
- ✓ PATH setup (includes globally installed npm packages)
- ✓ Environment variables (from remoteEnv in devcontainer.json)

**If devcontainer CLI handles all three:** Proceed with simplification
**If not:** Keep minimal wrapper, but still remove validation/workspace resolution complexity

### 3.7 External DevContainer Definition for Testing

#### The Testing Challenge

**Original Approach:** Each test fixture had its own `.devcontainer/` directory embedded in the test tree:
```
tests/fixtures/devcontainers/
└── minimal-opencode/
    ├── .devcontainer/
    │   ├── Dockerfile
    │   └── devcontainer.json
    ├── .env
    └── README.md
```

**Problems:**
- ❌ Duplicates devcontainer config across test fixtures
- ❌ Hard to maintain (update Claude Code version = edit multiple Dockerfiles)
- ❌ Doesn't reflect real-world usage (users have one devcontainer, not per-fixture)
- ❌ Testing arborist's devcontainer logic, not realistic project scenarios

#### New Approach: Use Existing backlit-devpod Repository

**Actual Setup:** Use the existing production devcontainer from https://github.com/pennyworth-tech/backlit-devpod

**Repository Structure:**
```
https://github.com/pennyworth-tech/backlit-devpod
├── .devcontainer/
│   ├── Dockerfile            # Includes Claude Code CLI
│   └── devcontainer.json     # Production config
└── ... (other backlit project files)
```

**Local Development Context:**
```
~/dev/pw/
├── agent-arborist/           # This repo
└── backlit-devpod/           # Sibling directory (../backlit-devpod)
```

**Testing Focus:** Claude Code only (not OpenCode/Gemini) - matches production usage

#### Implementation Options

##### Option 1: Git Submodule (Standard Approach)

**Setup:**
```bash
# In arborist repo
git submodule add https://github.com/pennyworth-tech/backlit-devpod \
  tests/fixtures/backlit-devpod
```

**Test Usage:**
```python
# tests/conftest.py
@pytest.fixture
def e2e_project(tmp_path):
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()

    # Copy devcontainer from submodule
    submodule_dc = Path(__file__).parent / "fixtures" / "backlit-devpod" / ".devcontainer"
    shutil.copytree(submodule_dc, project_dir / ".devcontainer")

    # ... rest of test setup
```

**CI Configuration:**
```yaml
# .github/workflows/test.yml
- name: Checkout with submodules
  uses: actions/checkout@v4
  with:
    submodules: true
```

**Pros:**
- ✅ Git-native, well-understood approach
- ✅ Version pinned in arborist repo (specific commit)
- ✅ Works offline after initial clone
- ✅ Standard for cross-repo dependencies

**Cons:**
- ⚠️ Developers must remember `git clone --recurse-submodules`
- ⚠️ Submodule management learning curve
- ⚠️ Must `git submodule update` to get latest backlit-devpod changes

##### Option 2: Sibling Directory Reference (Recommended for Local Dev)

**Setup:** Assumes `backlit-devpod` is already cloned at `../backlit-devpod`

```python
# tests/conftest.py
import pytest
from pathlib import Path
import shutil

@pytest.fixture(scope="session")
def backlit_devcontainer() -> Path:
    """Get devcontainer from sibling backlit-devpod repo."""
    # Look for sibling directory
    arborist_root = Path(__file__).parent.parent
    sibling_path = arborist_root.parent / "backlit-devpod" / ".devcontainer"

    if not sibling_path.exists():
        pytest.skip(
            "backlit-devpod not found at ../backlit-devpod\n"
            "Clone it: git clone https://github.com/pennyworth-tech/backlit-devpod ../backlit-devpod"
        )

    return sibling_path

@pytest.fixture
def e2e_project(tmp_path, backlit_devcontainer):
    """Create test project with backlit devcontainer."""
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()

    # Copy devcontainer from sibling repo
    shutil.copytree(backlit_devcontainer, project_dir / ".devcontainer")

    # ... rest of test setup
    yield project_dir
```

**CI Configuration:**
```yaml
# .github/workflows/test.yml
- name: Checkout agent-arborist
  uses: actions/checkout@v4
  with:
    path: agent-arborist

- name: Checkout backlit-devpod
  uses: actions/checkout@v4
  with:
    repository: pennyworth-tech/backlit-devpod
    path: backlit-devpod

- name: Run tests
  working-directory: agent-arborist
  run: pytest tests/test_e2e_devcontainer.py
```

**Pros:**
- ✅ Matches your actual local setup (`../backlit-devpod`)
- ✅ No submodule complexity
- ✅ Always uses latest backlit-devpod from your local checkout
- ✅ Easy to test devcontainer changes before committing to backlit-devpod
- ✅ Clear error message if sibling repo missing

**Cons:**
- ⚠️ Requires manual clone of backlit-devpod
- ⚠️ Slightly more complex CI configuration (two checkouts)

##### Option 3: Hybrid Approach (Sibling Fallback to Clone)

**Best of both worlds:** Check for sibling directory first, clone if not found

```python
# tests/conftest.py
import pytest
from pathlib import Path
import subprocess
import shutil

BACKLIT_DEVPOD_REPO = "https://github.com/pennyworth-tech/backlit-devpod"
BACKLIT_DEVPOD_REF = "main"  # or specific commit/tag

@pytest.fixture(scope="session")
def backlit_devcontainer(tmp_path_factory) -> Path:
    """Get backlit devcontainer from sibling dir or clone."""
    # Try sibling directory first (local dev)
    arborist_root = Path(__file__).parent.parent
    sibling_path = arborist_root.parent / "backlit-devpod" / ".devcontainer"

    if sibling_path.exists():
        print(f"\nUsing backlit-devpod from sibling directory: {sibling_path}")
        return sibling_path

    # Fall back to cloning (CI or first-time setup)
    print(f"\nSibling backlit-devpod not found, cloning from {BACKLIT_DEVPOD_REPO}")
    cache_dir = tmp_path_factory.mktemp("backlit_devpod_cache")
    clone_path = cache_dir / "backlit-devpod"

    subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", BACKLIT_DEVPOD_REF,
         BACKLIT_DEVPOD_REPO, str(clone_path)],
        check=True, capture_output=True
    )

    return clone_path / ".devcontainer"
```

**Pros:**
- ✅ Works for both local dev (uses `../backlit-devpod`) and CI (clones)
- ✅ No submodule complexity
- ✅ Automatic fallback behavior
- ✅ Matches your workflow

**Cons:**
- ⚠️ Slightly more complex fixture logic
- ⚠️ Network required if sibling not present

#### Recommended Approach: Option 3 (Hybrid Sibling Fallback to Clone)

**Rationale:**
1. **Matches actual workflow** - uses `../backlit-devpod` for local dev
2. **No submodule complexity** - developers clone backlit-devpod themselves
3. **Automatic fallback** - clones if sibling not present (CI, first-time setup)
4. **Production devcontainer** - tests with actual backlit production environment
5. **Easy to iterate** - modify backlit-devpod locally, tests see changes immediately
6. **Realistic testing** - exactly how users would reference external devcontainer

#### Test Structure with backlit-devpod DevContainer

```python
# tests/conftest.py
BACKLIT_DEVPOD_REPO = "https://github.com/pennyworth-tech/backlit-devpod"
BACKLIT_DEVPOD_REF = "main"  # or specific commit for pinning

@pytest.fixture(scope="session")
def backlit_devcontainer(tmp_path_factory) -> Path:
    """Get backlit devcontainer from sibling dir or clone."""
    # Try sibling directory first
    arborist_root = Path(__file__).parent.parent
    sibling_path = arborist_root.parent / "backlit-devpod" / ".devcontainer"

    if sibling_path.exists():
        return sibling_path

    # Fall back to cloning for CI
    cache_dir = tmp_path_factory.mktemp("backlit_devpod_cache")
    clone_path = cache_dir / "backlit-devpod"
    subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", BACKLIT_DEVPOD_REF,
         BACKLIT_DEVPOD_REPO, str(clone_path)],
        check=True, capture_output=True
    )
    return clone_path / ".devcontainer"

# tests/test_e2e_devcontainer.py
@pytest.fixture
def e2e_project(tmp_path, backlit_devcontainer):
    """Create test project with backlit devcontainer."""
    project_dir = tmp_path / "calculator-project"
    project_dir.mkdir()

    # Copy backlit devcontainer into test project
    shutil.copytree(backlit_devcontainer, project_dir / ".devcontainer")

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=project_dir, check=True)
    # ... git config, initial commit ...

    # Create test spec
    (project_dir / "specs" / "001-calculator" / "tasks.md").write_text(...)

    return project_dir

def test_full_dag_workflow(e2e_project):
    """Test complete workflow with backlit devcontainer."""
    # Test expects Claude Code to be available in container
    # (installed in backlit-devpod devcontainer definition)
    result = subprocess.run(
        ["arborist", "dag", "run", "001-calculator"],
        cwd=e2e_project,
        capture_output=True,
        text=True
    )
    # Verify Claude Code executed tasks successfully
    ...
```

#### backlit-devpod Repository Assumptions

The test expects the `backlit-devpod/.devcontainer/` to provide:

**Required Tools:**
- ✅ Claude Code CLI (installed and in PATH)
- ✅ Git (for worktree operations)
- ✅ Git configured for commits (user.name, user.email)

**Required Environment:**
- ✅ `ANTHROPIC_API_KEY` passed through from host (via .env file)
- ✅ Node.js or compatible runtime for Claude Code

**What Tests Will Verify:**
```bash
# Inside the devcontainer, these should succeed:
which claude           # Claude Code available
claude --version       # Working installation
git config user.name   # Git configured
echo $ANTHROPIC_API_KEY  # Environment variable available
```

**Note:** Tests do NOT modify `backlit-devpod` repo. They copy `.devcontainer/` into test fixture projects.

#### Environment Variable Strategy: .env File Approach

**Pattern:** Tests create a `.env` file and modify devcontainer.json to use it via `runArgs`.

**Critical Timing Understanding:**

Environment variables from `.env` are set at **container creation time** (`devcontainer up`), NOT at execution time (`devcontainer exec`).

```bash
# Timeline:
1. Create .env file with ANTHROPIC_API_KEY
2. devcontainer up --workspace-folder /test-project
   ↓ Docker reads .env file via runArgs: ["--env-file", ".env"]
   ↓ Container starts with ANTHROPIC_API_KEY in environment
3. devcontainer exec ... claude -p "..."
   ↓ Command inherits container's environment
   ↓ ANTHROPIC_API_KEY is available ✓
4. devcontainer exec ... arborist task run T001
   ↓ Also inherits container's environment
   ↓ ANTHROPIC_API_KEY is available ✓
```

**Key Implications:**

1. **✅ All exec commands see the variables** - No special handling per command
2. **✅ Variables persist for container lifetime** - Set once at up, available everywhere
3. **⚠️ Changes require container restart** - Modifying .env after up won't take effect
4. **✅ Git-safe** - .env file created in tmp_path, never committed

**Test Implementation:**

```python
# tests/conftest.py
@pytest.fixture
def e2e_project(tmp_path, backlit_devcontainer):
    """Create test project with backlit devcontainer and .env file."""
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()

    # Copy backlit devcontainer
    shutil.copytree(backlit_devcontainer, project_dir / ".devcontainer")

    # Create .env file with API key from host environment
    env_file = project_dir / ".env"
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        pytest.skip("ANTHROPIC_API_KEY not set in environment")
    env_file.write_text(f"ANTHROPIC_API_KEY={api_key}\n")

    # Modify devcontainer.json to use .env file
    dc_json = project_dir / ".devcontainer" / "devcontainer.json"
    with open(dc_json, "r") as f:
        config = json.load(f)

    # Add runArgs to pass .env file to Docker
    config["runArgs"] = config.get("runArgs", []) + [
        "--env-file", "${localWorkspaceFolder}/.env"
    ]

    with open(dc_json, "w") as f:
        json.dump(config, f, indent=2)

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=project_dir, check=True)
    # ... rest of setup

    yield project_dir
```

**Why This Works:**

1. **At test time:** Create .env with ANTHROPIC_API_KEY from host
2. **At container-up:** Docker reads .env, sets variables in container environment
3. **At exec time:** All commands (arborist, claude) inherit container environment
4. **Result:** No special environment handling needed in runner.py or dag_builder.py

#### Benefits of This Approach

1. **Uses Production DevContainer**
   - Tests with actual backlit production environment
   - Ensures arborist works with real-world devcontainer setups
   - No test-specific devcontainer to maintain

2. **Separation of Concerns**
   - Arborist tests container **orchestration** (lifecycle, wrapping)
   - backlit-devpod defines container **environment** (tools, config)
   - Changes to backlit devcontainer don't require arborist changes

3. **Realistic Testing**
   - Exactly mirrors how users would reference external devcontainer
   - Tests the "bring your own devcontainer" philosophy
   - Validates cross-repo devcontainer workflow

4. **Local Development Workflow**
   - Uses `../backlit-devpod` that developers already have cloned
   - Easy to test devcontainer changes (edit backlit-devpod, rerun tests)
   - No submodules or complex setup

5. **CI/CD Friendly**
   - Simple two-repo checkout in GitHub Actions
   - No submodule recursion complexity
   - Can pin to specific backlit-devpod commit if needed

6. **Claude Code Focus**
   - Tests only with Claude Code (production runner)
   - Simpler test setup (no multi-runner matrix)
   - Matches actual backlit usage patterns

### 3.8 Branching Strategy

#### Recommended Branch Point: `ff37f35` (Add container mode integration)

**Branch from:** `ff37f35` - The initial working container integration, before additional fixes

```bash
# Stash any uncommitted DEBUG changes
git stash push -m "WIP: DEBUG logging - will remove in refactoring"

# Branch from the clean container integration commit
git checkout ff37f35
git checkout -b refactor/simplify-devcontainer-implementation

# Commit the review document first
git add docs/devcontainer-implementation-review.md
git commit -m "docs: Add devcontainer implementation review and refactoring plan"
```

#### What's Included at ff37f35

**✅ Has (good foundation):**
- Initial DevContainerRunner class (container_runner.py)
- Container-aware runners (runner.py)
- Container lifecycle in DAG generation (dag_builder.py)
- E2E test infrastructure (test_e2e_devcontainer.py)
- Container mode CLI flags (--container-mode)

**❌ Doesn't Have (will add during refactoring):**
- bash -lc login shell hack (6cff69c) - will evaluate if needed
- Runner-model config threading (6cff69c, d9a7fdf) - will add cleanly
- Workspace layout migration (179cd00) - will implement correctly
- Configuration validation (63113e7) - won't add (trust devcontainer CLI)
- Test assertion improvements (8996e9a, d9a7fdf) - will add with refactoring
- DEBUG logging (uncommitted) - won't add

#### Commits to Cherry-Pick or Reimplement

After refactoring the core implementation, selectively bring forward improvements:

**1. Runner-Model Config Threading (NEW implementation)**
- Don't cherry-pick 6cff69c or d9a7fdf
- Implement cleanly with centralized command builder
- Add --runner and --model flags to task run/post-merge
- Thread through DagConfig without string concatenation

**2. Test Improvements (cherry-pick)**
```bash
git cherry-pick 8996e9a  # Improve e2e devcontainer test assertions
git cherry-pick d9a7fdf  # Fix e2e test to check merged branch
```

**3. Opencode Config (cherry-pick)**
```bash
git cherry-pick c03851f  # Add opencode.json permissions config
git cherry-pick 8472c22  # Fix file change detection
```

#### What NOT to Bring Forward

**❌ Skip these entirely:**
- 0c1fdbb: Fix devcontainer exec working directory - refactored approach won't need this
- 179cd00: Workspace layout migration - will implement differently
- 63113e7: Configuration validation - removed by design
- 6cff69c (first half): bash -lc hack - test if needed first

#### Why Branch from ff37f35 Instead of HEAD?

**Advantages:**
1. **Clean slate** - Start from working implementation before accumulated fixes
2. **Fewer workarounds** - No bash -lc hack or validation code to remove
3. **Clear vision** - Implement runner-model config correctly from the start
4. **Better history** - Refactoring diff shows clear before/after

**Disadvantages:**
1. Need to selectively reimplement some fixes
2. Test suite not as complete (but we'll improve during refactoring)
3. Slightly more work upfront

**Trade-off Worth It?** Yes - starting from a cleaner base makes the refactoring clearer and the result more maintainable.

### 3.8 Recommended Implementation Path

#### Step 1: Spike - Prove Simplicity Works (1-2 hours)

Create a minimal proof-of-concept using backlit-devpod:

```python
# test_spike_devcontainer.py
def test_simple_execution():
    """Test that devcontainer exec handles everything we need."""
    # Create test project with backlit devcontainer
    project_dir = tmp_path / "spike-test"
    project_dir.mkdir()

    # Copy backlit-devpod devcontainer
    backlit_dc = Path("../backlit-devpod/.devcontainer")
    shutil.copytree(backlit_dc, project_dir / ".devcontainer")

    # Initialize git
    subprocess.run(["git", "init"], cwd=project_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=project_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=project_dir, check=True)

    # Start container
    subprocess.run(
        ["devcontainer", "up", "--workspace-folder", str(project_dir)],
        check=True
    )

    # Run Claude Code - devcontainer CLI should handle:
    # - Working directory
    # - PATH setup (finds claude command)
    # - Environment variables (ANTHROPIC_API_KEY)
    cmd = [
        "devcontainer", "exec",
        "--workspace-folder", str(project_dir),
        "claude", "-p", "Create a simple add function in add.js"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    assert result.returncode == 0, f"Command failed: {result.stderr}"

    # Verify file was created
    assert (project_dir / "add.js").exists()
```

**Test Questions:**
1. Does `devcontainer exec ... claude` work without bash -lc wrapper?
2. Does Claude Code find files in correct working directory?
3. Are environment variables (ANTHROPIC_API_KEY) available?

**If this works:** Proceed with refactoring. Devcontainer CLI handles everything we need.
**If this fails:** Document specific issues and minimal workarounds required.

#### Step 2: Add Runner-Model Config (2-3 hours)

Before refactoring existing code, add the runner-model config threading cleanly:

```python
# In dag_builder.py - Add command builder helper
def _build_task_command(
    self,
    task_id: str,
    command: str,
    include_runner_model: bool = True
) -> str:
    """Build task command with optional runner/model flags."""
    import shlex

    cmd = f"arborist task {command} {task_id}"

    if include_runner_model:
        if self.config.runner:
            cmd += f" --runner {self.config.runner}"
        if self.config.model:
            cmd += f" --model {shlex.quote(self.config.model)}"

    return cmd

# Usage throughout dag_builder.py
run_cmd = self._build_task_command(task_id, "run")
post_merge_cmd = self._build_task_command(task_id, "post-merge")
```

**Add CLI flags:**
- `arborist task run --model <model>`
- `arborist task post-merge --runner <runner> --model <model>`
- Pass runner/model through DagConfig

**Test:**
```bash
pytest tests/test_dag_builder.py -v
```

#### Step 3: Refactor Runners (2-3 hours)

- Create `execute_command()` function
- Update all three runners to use it
- Remove `_check_container_running()`, `_wrap_in_container()`, `get_workspace_folder()`
- Update tests

#### Step 4: Simplify Container Runner Module (1-2 hours)

- Keep only `should_use_devcontainer()` function
- Remove `DevContainerRunner` class
- Remove validation logic
- Remove symlink management
- Update tests to focus on detection only

#### Step 5: Update DAG Builder (2-3 hours)

- Remove container lifecycle steps
- Add devcontainer exec prefix to commands when .devcontainer detected
- Update tests for new DAG structure

#### Step 6: Integration Testing (2-3 hours)

- Run e2e tests with simplified implementation
- Fix any edge cases discovered
- Update documentation

**Total Estimated Effort:** 10-17 hours (6 steps)

**Expected Outcome:** 850 fewer lines of code, clearer architecture, easier to maintain.

---

## Conclusion

The current devcontainer implementation **works** and has **correct architecture** but exhibits **implementation brittleness**:
- Container-awareness scattered across 5+ modules (detection, validation, wrapping in multiple places)
- Duplicate logic for workspace folder resolution (3 different implementations)
- Defensive coding with workarounds (bash -lc, symlink management, manual validation)
- Over-engineering with validation that duplicates what devcontainer CLI already does

### Key Architectural Insight

**Container Lifecycle Management (up/down) is CORRECT**, not over-engineering:
- ✅ Necessary for parallel execution (multiple steps on same container)
- ✅ Provides clean DAG structure with clear dependencies
- ✅ Allows multiple tasks to share containers when appropriate

**The Problem is NOT the architecture - it's the scattered, duplicate implementation.**

### Core Recommendation

**Keep:** Container lifecycle, devcontainer exec wrapping, structure
**Simplify:** Implementation details - remove duplicate logic, validation, complexity

**Refactoring Strategy:**
1. **Centralize** devcontainer exec wrapping in ONE place (runner.py)
2. **Remove** validation/workspace resolution (trust devcontainer CLI)
3. **Simplify** container lifecycle commands (remove symlinks, DEBUG code)
4. **Keep** the overall architecture (it's sound for parallel execution)

This would **reduce implementation complexity by 54%** (~900 lines) while:
- ✅ Maintaining correct architecture for parallel execution
- ✅ Keeping container lifecycle management
- ✅ Centralizing all container logic
- ✅ Trusting devcontainer CLI to handle configuration
- ✅ Eliminating duplicate detection/validation/resolution code

**Branching Strategy:** Branch from `ff37f35` (clean container integration before additional fixes), reimplement runner-model config cleanly during refactoring.

**Estimated Effort:** 10-17 hours across 6 phases, starting with spike test to validate approach.

**Risk Level:** Low - keeps proven architecture, simplifies implementation, cherry-picks necessary fixes.

---

## Appendix: Why Parallel Execution Validates Current Architecture

### The Parallel Execution Requirement

If multiple steps can run in parallel on the same worktree/container (as confirmed by the user), this **validates the current container lifecycle design**:

```yaml
# Task T001 - multiple steps may run concurrently
steps:
  - name: container-up
    command: arborist task container-up T001

  - name: run
    command: arborist task run T001
    depends: [container-up]

  - name: commit
    command: arborist task commit T001
    depends: [run]

  # These could run in parallel across multiple tasks
  - name: run-test
    command: arborist task run-test T001
    depends: [commit]

  - name: another-task-test
    command: arborist task run-test T002
    depends: [T002-commit]

  - name: post-merge
    command: arborist task post-merge T001
    depends: [run-test]

  - name: container-down
    command: arborist task container-down T001
    depends: [post-merge]
```

### Why Container Lifecycle is Necessary

**Without explicit container-up/down:**
```bash
# Option 1: Start container per command (WRONG)
devcontainer up --workspace-folder /worktree/T001  # Step 1 starts container
opencode run "implement task"
devcontainer down /worktree/T001                   # Step 1 stops it

devcontainer up --workspace-folder /worktree/T001  # Step 2 tries to start again
pytest tests/                                       # Container might not be ready
devcontainer down /worktree/T001                   # Step 2 stops it

# Problems:
# - Container startup/shutdown overhead for every step (slow)
# - Race conditions if steps run in parallel
# - Duplicate container startup attempts (conflicts)
```

```bash
# Option 2: Assume container is always running (WRONG)
devcontainer exec --workspace-folder /worktree/T001 opencode run "..."
# ERROR: No container running - devcontainer exec requires existing container
```

**With explicit container-up/down:**
```bash
# Step 1: Start container ONCE
devcontainer up --workspace-folder /worktree/T001

# Steps 2-N: All use the SAME running container
devcontainer exec --workspace-folder /worktree/T001 arborist task run T001
devcontainer exec --workspace-folder /worktree/T001 arborist task commit T001
devcontainer exec --workspace-folder /worktree/T001 pytest tests/
devcontainer exec --workspace-folder /worktree/T001 arborist task post-merge T001

# Final step: Stop container ONCE (after all steps complete)
docker stop <container-id>

# Benefits:
# ✅ Single container startup (fast)
# ✅ All parallel steps use same container (no conflicts)
# ✅ Clear lifecycle ownership (DAG manages start/stop)
# ✅ No race conditions (dependencies ensure ordering)
```

### What This Means for Refactoring

The parallel execution requirement **strengthens the case for keeping lifecycle management** while simplifying implementation:

**Keep:**
- ✅ `arborist task container-up` command
- ✅ `arborist task container-down` command
- ✅ container-up/down steps in DAG structure
- ✅ Dependency management (all exec steps depend on container-up)

**Simplify:**
- ✅ Remove validation (devcontainer CLI handles it)
- ✅ Remove workspace resolution (devcontainer CLI handles it)
- ✅ Remove symlink management (not needed)
- ✅ Centralize devcontainer exec wrapping (one place)

**The refactoring strategy remains valid** - we're simplifying implementation while keeping the correct architecture for parallel execution.

---

## Part 4: Spike Test Validation Results

**Date:** 2026-01-28
**Branch:** refactor/simplify-devcontainer-implementation
**Commits:** 8feeaba, 627fc9a, 791be73

### 4.1 Overview

Before proceeding with the refactoring, we created spike tests to validate three critical assumptions about devcontainer behavior:

1. Environment variables from .env are available at exec time (no special handling needed)
2. Claude Code CLI works without bash -lc wrapper (can remove workaround)
3. Commands execute in correct working directory (no cd command needed)

### 4.2 Test Implementation

**Test Fixture:** `spike_project` in `tests/test_spike_devcontainer.py`
- Creates minimal test project with backlit-devpod devcontainer
- Creates .env file with CLAUDE_CODE_OAUTH_TOKEN from host environment
- Modifies devcontainer.json to add `runArgs: ["--env-file", "${localWorkspaceFolder}/.env"]`
- Initializes git repo with initial commit
- Cleans up container after test

**Environment Setup:**
- `.env` file at repository root (gitignored)
- `python-dotenv` loads .env in `conftest.py`
- `CLAUDE_CODE_OAUTH_TOKEN` required for tests

### 4.3 Test Results

#### Test 1: Environment Variables Available at Exec Time ✅

**Validation:** Environment variables from .env are inherited by all exec commands

```
→ Starting devcontainer...
  Container up exit code: 0
→ Testing environment variable access...
  TEST_VAR value: hello_from_env
PASSED
```

**Key Finding:** Variables set at container creation (devcontainer up) are automatically inherited by all subsequent exec commands. No special handling needed per command.

**Runtime:** 268.98s (4:28) - container startup time

#### Test 2: Claude Code Works Without bash -lc Wrapper ✅

**Validation:** Claude Code CLI is in PATH and works without login shell

```
→ Checking if claude command is available...
  which claude: /home/vscode/.local/bin/claude
→ Checking if CLAUDE_CODE_OAUTH_TOKEN is available...
  OAuth token status: TOKEN_SET
→ Running claude --version...
  Claude version: 2.1.22 (Claude Code)
PASSED
```

**Key Finding:** The bash -lc hack is **NOT NEEDED**. Claude Code is properly installed in PATH by backlit-devpod's install-tools.sh and accessible via plain devcontainer exec.

**Runtime:** 248.74s (4:08) - container startup time

#### Test 3: Working Directory Correct ✅

**Validation:** Commands execute in correct working directory without cd command

```
→ Checking working directory...
  Working directory: /workspaces/spike-test
→ Creating test file...
  ✓ File created successfully in workspace
PASSED
```

**Key Finding:** devcontainer CLI automatically defaults to /workspaces/<folder-name>. No cd command or wrapper needed.

**Runtime:** 252.95s (4:12) - container startup time

### 4.4 Conclusions

**All three assumptions validated!** The spike tests confirm we can proceed with the simplified refactoring approach:

#### Can Remove:
1. ✅ **bash -lc wrapper** - Not needed, Claude Code is in PATH
2. ✅ **Environment variable juggling** - .env at up time handles everything
3. ✅ **Working directory hacks** - devcontainer CLI defaults correctly

#### Implementation Validated:
1. ✅ **.env file approach** - runArgs with --env-file works perfectly
2. ✅ **backlit-devpod integration** - Hybrid sibling/clone strategy works
3. ✅ **Clean test fixture** - Creates proper test environment with .env

#### Next Steps:
With spike tests passing, we can confidently proceed with Step 2 of the refactoring plan:
- Add runner-model config threading
- Simplify container_runner.py
- Remove defensive coding and workarounds
- Centralize command execution logic

**Estimated Code Reduction:** Still targeting 54% reduction (~900 lines), now with empirical validation that the simplified approach works.
