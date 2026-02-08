# Sequential Execution Simplification Plan

## Overview

This document outlines the complete rework of Agent Arborist from parallel jj-based execution to sequential git-based execution.

## Core Philosophy

- **Sequential only**: One worker, one task at a time
- **Plain git**: No jj dependency
- **DAGU orchestrates**: Hierarchy expressed via subdags
- **No custom state**: DAGU + git commits = all state
- **Container optional**: `container_mode: auto|enabled|disabled`

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│   .arborist/dagu/dags/spec-003.yaml                        │
│   ├── Hierarchy via subdags (phases, tasks, subtasks)      │
│   ├── Sequential execution (depends chains)                │
│   └── Hooks, tests at any level                            │
├─────────────────────────────────────────────────────────────┤
│   .arborist/dagu/data/  (DAGU execution state/logs)        │
├─────────────────────────────────────────────────────────────┤
│   .arborist/config.json (container_mode, runner, etc.)     │
├─────────────────────────────────────────────────────────────┤
│   Git (plain) → linear commits                             │
└─────────────────────────────────────────────────────────────┘
```

## What Gets Deleted

| Component | File | Lines | Reason |
|-----------|------|-------|--------|
| jj operations | tasks.py | ~1500 | Plain git replaces |
| Workspace mgmt | tasks.py | ~300 | No workspaces needed |
| Merge commits | tasks.py | ~200 | Linear history |
| Status markers | tasks.py | ~150 | DAGU tracks state |
| Revset queries | tasks.py | ~200 | Git log suffices |
| Parallel subdags | dag_builder.py | ~400 | Sequential deps |
| jj CLI commands | task_cli.py | ~800 | Simplified commands |
| jj init commands | cli.py | ~200 | No jj initialization |

## What Gets Kept

| Component | File | Reason |
|-----------|------|--------|
| Home/config | home.py, config.py | Directory structure, settings |
| Constants | constants.py | Path definitions |
| Runners | runner.py | AI execution abstraction |
| Container support | container_runner.py | Devcontainer integration |
| DAGU runs | dagu_runs.py | Status parsing |
| Task specs | task_spec.py, spec.py | Spec file handling |
| Task tree | task_state.py | Hierarchy representation |
| Viz system | viz/ | Visualization |
| Hooks | hooks/ | Hook injection |

## New DAG Structure

### Before (Parallel)
```yaml
# Root DAG with parallel children
steps:
  - name: c-Phase1
    call: Phase1
  - name: c-Phase2
    call: Phase2
    # NO depends - parallel!
```

### After (Sequential)
```yaml
# Root DAG with sequential phases
steps:
  - name: c-Phase1
    call: Phase1
  - name: c-Phase2
    call: Phase2
    depends: [c-Phase1]  # Sequential!
  - name: finalize
    command: arborist spec finalize
    depends: [c-Phase2]
---
# Phase1 subdag - sequential tasks
name: Phase1
steps:
  - name: T1
    command: arborist task run T1
  - name: T2
    command: arborist task run T2
    depends: [T1]
  - name: phase-tests
    command: pytest tests/phase1/
    depends: [T2]
```

## New Task Commands

### Simplified Commands

| Command | Purpose |
|---------|---------|
| `arborist task run <id>` | Execute task, git commit |
| `arborist task run-test <id>` | Run tests for task |
| `arborist spec finalize` | Final cleanup/push |

### Removed Commands

- `arborist task pre-sync` - No workspaces
- `arborist task create-merge` - No merges
- `arborist task complete` - Run handles commit
- `arborist task cleanup` - No workspace cleanup
- `arborist task container-up/stop` - Container managed per-task
- `arborist task setup-spec` - No change creation

## New tasks.py Structure

```python
"""Git operations for sequential task execution."""

def git_commit(message: str, cwd: Path) -> bool:
    """Stage all and commit."""

def git_status(cwd: Path) -> dict:
    """Get working directory status."""

def run_task(task_id: str, spec_id: str, runner: str, model: str) -> RunResult:
    """Execute a task and commit changes."""

def run_tests(test_cmd: str, cwd: Path) -> TestResult:
    """Run test command."""
```

## New dag_builder.py Structure

```python
"""Sequential DAG builder for DAGU."""

def build_sequential_dag(task_tree: TaskTree, config: DagConfig) -> str:
    """Build sequential DAGU YAML with subdags."""

def _build_phase_subdag(phase: TaskNode, children: list) -> SubDag:
    """Build subdag for a phase with sequential tasks."""

def _build_task_step(task: TaskNode) -> SubDagStep:
    """Build step for a leaf task."""
```

## Implementation Order

1. **tasks.py** - Replace jj with git (new file, ~200 lines)
2. **dag_builder.py** - Sequential subdags (~400 lines)
3. **task_cli.py** - Simplified commands (~400 lines)
4. **cli.py** - Remove jj commands
5. **Tests** - Update for sequential model

## Test Strategy

- Keep e2e tests that create git repos in /tmp
- Rewrite tests that depend on jj
- Remove workspace-related tests
- Add new sequential execution tests
