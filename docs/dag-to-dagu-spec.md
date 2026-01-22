# DAG-to-Dagu Workflow Generator

**Version:** 1.0
**Status:** Draft
**Last Updated:** 2026-01-21

## Executive Summary

A command-line tool and agent framework that transforms directed acyclic graph (DAG) specifications into executable **Dagu** workflows with LLM assistance. The system provides flexible dependency management, multi-agent orchestration, pluggable runtimes, and leverages Dagu's native scheduling and visualization capabilities.

### Key Capabilities

- **Dynamic DAG Processing**: Generic DAG execution engine that handles any DAG structure.
- **Flexible Dependencies**: Support for task-to-task, phase-to-phase, subtree, checkpoint, and expression-based dependencies.
- **Multi-Agent Orchestration**: Pluggable agent system (builder, reviewer, sherlock, tester, etc.) invoked as CLI steps.
- **Multi-Runtime Support**: Claude Code, Gemini, OpenCode, and custom runtimes.
- **Hierarchical Branching**: Git-based task isolation with structured branch naming.
- **Dagu Integration**: Native generation of Dagu YAML configurations for robust execution and visualization.
- **Configurable Workflows**: Per-task customization of implementation, review, merge, and cleanup steps.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Data Models](#2-data-models)
3. [DAG Specification Format](#3-dag-specification-format)
4. [Agent System](#4-agent-system)
5. [Runtime Abstraction](#5-runtime-abstraction)
6. [Dagu Workflow Generation](#6-dagu-workflow-generation)
7. [CLI Interface](#7-cli-interface)
8. [Monitoring Dashboard](#8-monitoring-dashboard)
9. [Configuration System](#9-configuration-system)
10. [Extension Points](#10-extension-points)
11. [Implementation Roadmap](#11-implementation-roadmap)
12. [Appendix](#12-appendix)

---

## 1. Architecture Overview

### 1.1 System Components

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLI Interface                            │
│  - dagctl init                                                 │
│  - dagctl generate                                             │
│  - dagctl execute                                              │
│  - dagctl monitor                                              │
└────────────────────────┬──────────────────────────────────────┘
                         │
        ┌────────────────┴────────────────┐
        │                                 │
┌───────▼────────┐              ┌────────▼─────────┐
│  DAG Parser    │              │ Config Loader    │
│  - YAML/JSON   │              │  - Project conf  │
│  - Validation  │              │  - Agent conf    │
└───────┬────────┘              └────────┬─────────┘
        │                                 │
        └────────────────┬────────────────┘
                         │
                ┌────────▼─────────┐
                │  DAG Analyzer    │
                │  - Topo sort     │
                │  - Dep resolution│
                │  - Parallelism   │
                └────────┬─────────┘
                         │
        ┌────────────────┴────────────────┐
        │                                 │
┌───────▼────────┐              ┌────────▼─────────┐
│ Dagu YAML      │              │ Agent Manager   │
│ Generator      │              │  - CLI Wrappers │
│  - Steps       │              │  - Context      │
│  - Depends     │              │  - Artifacts    │
└───────┬────────┘              └────────┬─────────┘
        │                                 │
        └────────────────┬────────────────┘
                         │
                ┌────────▼─────────┐
                │  Dagu Engine     │
                │  - Scheduler     │
                │  - Execution     │
                │  - Web UI        │
                └────────┬─────────┘
                         │
        ┌────────────────┴────────────────┐
        │                                 │
┌───────▼────────┐              ┌────────▼─────────┐
│  Runtime Layer │              │  Status/Logs    │
│  - Claude Code │              │  - Files        │
│  - Gemini      │              │  - Dagu API     │
│  - OpenCode    │              │                 │
└────────────────┘              └──────────────────┘
```

### 1.2 Core Principles

1.  **DAG-as-Data**: The project structure is defined in a high-level DAG spec, distinct from the execution engine format.
2.  **Dagu-Native**: Compilation targets standard Dagu YAML files, allowing use of standard Dagu tooling and UI.
3.  **Agent-as-CLI**: Agents are packaged as CLI commands that Dagu steps execute.
4.  **Git-Native**: Every task operates in its own branch/worktree context.
5.  **Observable**: Leverages Dagu's built-in UI for operational monitoring, augmented by `dagctl` for logical project tracking.

---

## 2. Data Models

### 2.1 DAG Specification

```python
from typing import Dict, List, Optional, Union, Literal, Set, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

class DependencyType(Enum):
    TASK_ID = "task_id"           # "T001"
    PHASE = "phase"               # "phase:phase1"
    SUBTREE = "subtree"           # "subtree:phase3/tests"
    EXPRESSION = "expression"     # "T001 & T002" or "T001 | T002"
    CHECKPOINT = "checkpoint"     # "checkpoint:foundation_ready"
    ANY_OF = "any_of"             # ["T001", "T002"]
    ALL_OF = "all_of"             # ["T001", "T002"]

@dataclass
class Dependency:
    type: DependencyType
    value: Union[str, List[str]]  # Task ID, phase name, expression, or list
    optional: bool = False

    def is_satisfied(self,
                    completed_tasks: Set[str],
                    phase_status: Dict[str, bool],
                    checkpoint_status: Dict[str, bool]) -> bool:
        """Check if dependency is satisfied"""
        if self.type == DependencyType.TASK_ID:
            return self.value in completed_tasks
        elif self.type == DependencyType.PHASE:
            return phase_status.get(self.value, False)
        elif self.type == DependencyType.SUBTREE:
            subtree_tasks = get_tasks_in_subtree(self.value)
            return all(t in completed_tasks for t in subtree_tasks)
        elif self.type == DependencyType.CHECKPOINT:
            return checkpoint_status.get(self.value, False)
        elif self.type == DependencyType.ANY_OF:
            return any(v in completed_tasks for v in self.value)
        elif self.type == DependencyType.ALL_OF:
            return all(v in completed_tasks for v in self.value)
        elif self.type == DependencyType.EXPRESSION:
            return evaluate_expression(self.value, completed_tasks, phase_status)
        return True

@dataclass
class TaskStep:
    """A step in task execution (implement, review, merge, etc.)"""
    name: str
    agent: str  # "builder", "reviewer", "sherlock", etc.
    runtime: str  # "claude-code", "gemini", "opencode"
    config: Dict[str, Any] = field(default_factory=dict)
    on_failure: Literal["fail", "skip", "retry"] = "fail"
    max_retries: int = 3
    timeout_seconds: int = 1800

@dataclass
class Task:
    id: str
    title: str
    description: str
    phase: Optional[str] = None
    subtree: Optional[str] = None

    # Flexible dependencies
    dependencies: List[Union[str, Dependency]] = field(default_factory=list)

    # Execution configuration
    steps: List[TaskStep] = field(default_factory=list)
    parallel: bool = False

    # Git configuration
    branch_naming_template: str = "{phase}/{subtree}/{id}"
    create_worktree: bool = True
    merge_to: Optional[str] = None  # Parent branch to merge into
    merge_strategy: Literal["merge", "rebase", "squash"] = "merge"

    # Output
    file_path: Optional[str] = None
    outputs: List[str] = field(default_factory=list)  # Files this task creates

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_dependencies(self) -> List[Dependency]:
        """Parse and return normalized dependencies"""
        deps = []
        for dep in self.dependencies:
            if isinstance(dep, str):
                deps.append(parse_dependency_string(dep))
            elif isinstance(dep, Dependency):
                deps.append(dep)
        return deps

    def can_execute(self,
                   completed_tasks: Set[str],
                   phase_status: Dict[str, bool],
                   checkpoint_status: Dict[str, bool]) -> bool:
        """Check if all dependencies are satisfied"""
        for dep in self.get_dependencies():
            if not dep.is_satisfied(completed_tasks, phase_status, checkpoint_status):
                if not dep.optional:
                    return False
        return True

@dataclass
class Phase:
    id: str
    name: str
    description: str
    tasks: List[str]  # Task IDs
    checkpoint: Optional[str] = None  # Checkpoint name when complete
    parallel: bool = False  # Can all tasks run in parallel?

    def is_complete(self, completed_tasks: Set[str]) -> bool:
        return all(task_id in completed_tasks for task_id in self.tasks)

@dataclass
class DAGSpec:
    """Complete DAG specification"""
    name: str
    version: str
    description: str

    # DAG structure
    tasks: Dict[str, Task]
    phases: List[Phase]
    execution_order: List[str]  # Phase IDs in order

    # Global configuration
    default_runtime: str = "claude-code"
    default_agent: str = "builder"
    default_branch_template: str = "{phase}/{subtree}/{id}"

    # Checkpoints
    checkpoints: Dict[str, str] = field(default_factory=dict)  # phase -> checkpoint name

    # Repository settings
    repo_root: str = "."
    main_branch: str = "main"

    # Execution settings
    auto_commit: bool = True
    auto_merge: bool = False
    keep_worktrees: bool = False

    # Monitoring
    dashboard_port: int = 8501
    log_level: str = "INFO"

    def validate(self) -> List[str]:
        """Validate DAG specification, return list of errors"""
        errors = []

        # Check all task IDs in dependencies exist
        for task_id, task in self.tasks.items():
            for dep in task.get_dependencies():
                if dep.type == DependencyType.TASK_ID:
                    if dep.value not in self.tasks:
                        errors.append(f"Task {task_id} depends on non-existent task {dep.value}")

        # Check for circular dependencies
        if has_cycles(self.tasks):
            errors.append("DAG contains circular dependencies")

        return errors

    def get_ready_tasks(self,
                       completed: Set[str],
                       phase_status: Dict[str, bool],
                       checkpoint_status: Dict[str, bool]) -> List[Task]:
        """Get all tasks whose dependencies are satisfied"""
        ready = []
        for task_id, task in self.tasks.items():
            if task_id not in completed:
                if task.can_execute(completed, phase_status, checkpoint_status):
                    ready.append(task)
        return ready
```

### 2.2 Execution State

```python
@dataclass
class TaskExecutionResult:
    task_id: str
    success: bool
    branch: str
    worktree_path: str

    # Step results
    step_results: Dict[str, Any] = field(default_factory=dict)

    # Output
    files_modified: List[str] = field(default_factory=list)
    output: str = ""
    error: Optional[str] = None

    # Review results
    review_passed: bool = False
    review_summary: Optional[str] = None
    review_issues: List[str] = field(default_factory=list)

    # Merge results
    merge_suggested: bool = False
    merge_completed: bool = False

    # Timing
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

@dataclass
class DAGExecutionState:
    dag_spec: DAGSpec
    execution_id: str

    # State tracking
    completed_tasks: Set[str] = field(default_factory=set)
    failed_tasks: Set[str] = field(default_factory=set)
    in_progress_tasks: Set[str] = field(default_factory=set)

    # Phase/checkpoint status
    phase_status: Dict[str, bool] = field(default_factory=dict)
    checkpoint_status: Dict[str, bool] = field(default_factory=dict)

    # Results
    task_results: Dict[str, TaskExecutionResult] = field(default_factory=dict)

    # Progress
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @property
    def progress_percent(self) -> float:
        total = len(self.dag_spec.tasks)
        if total == 0:
            return 100.0
        return len(self.completed_tasks) / total * 100

    @property
    def is_complete(self) -> bool:
        return len(self.completed_tasks) == len(self.dag_spec.tasks)

    @property
    def has_failures(self) -> bool:
        return len(self.failed_tasks) > 0
```

### 2.3 Execution State in Dagu

Dagu maintains its own state. We map our logical state to Dagu's physical state:

*   **DAG File**: Maps to a generated `dagu.yaml` file.
*   **Dagu Step**: Maps to a specific `TaskStep` (e.g., `T001_implement`, `T001_review`).
*   **Execution ID**: Maps to a Dagu run ID (request ID).
*   **Step Status**: Maps to our `TaskExecutionResult` via the `DaguStatusFetcher`.

---

## 3. DAG Specification Format

### 3.1 YAML Format

```yaml
# dag.yaml
name: "Calculator Project"
version: "1.0.0"
description: "Build a simple calculator with 130 tasks"

# Global settings
defaults:
  runtime: claude-code
  agent: builder
  branch_template: "{phase}/{subtree}/{id}"
  auto_commit: true
  auto_merge: false

# Repository settings
repository:
  root: .
  main_branch: main
  worktree_dir: .worktrees

# Checkpoint mapping
checkpoints:
  phase1: setup_complete
  phase2: foundation_ready
  phase3: mvp_ready
  phase4: enhanced_ready
  phase5: production_ready

# Phases (in execution order)
phases:
  - id: phase1
    name: "Setup"
    description: "Project initialization"
    tasks: [T001, T002, T003, T004, T005, T006, T007, T008]
    checkpoint: setup_complete

  - id: phase2
    name: "Foundational"
    description: "Core infrastructure"
    tasks: [T009, T010, T011, T012, T013, T014, T015, T016, T017, T018, T019, T020]
    checkpoint: foundation_ready

# Task definitions
tasks:
  T001:
    title: "Create directory structure"
    description: "Create src/calculator/, src/cli/, src/lib/, tests/"
    phase: phase1
    subtree: setup
    dependencies: []  # No dependencies
    parallel: true

    steps:
      - name: implement
        agent: builder
        runtime: claude-code
        config:
          context:
            - "This is a Python calculator project"

  T002:
    title: "Create __init__.py files"
    description: "Create __init__.py in all src/ directories"
    phase: phase1
    subtree: setup
    dependencies:
      - T001  # Depends on directory structure existing
    parallel: true

    steps:
      - name: implement
        agent: builder
        runtime: claude-code

  T009:
    title: "Create CalculatorError exception"
    description: "Base exception class"
    phase: phase2
    subtree: exceptions
    dependencies:
      - "phase:phase1"  # Wait for entire phase 1
    file_path: src/lib/errors.py

    steps:
      - name: implement
        agent: builder
        runtime: claude-code

      - name: review
        agent: reviewer
        runtime: claude-code
        config:
          checks:
            - linting
            - style
            - docstrings

  T047:
    title: "Implement _is_empty helper"
    description: "Check if expression is empty"
    phase: phase3
    subtree: validator_impl
    dependencies:
      - "subtree:phase3/validator_tests"  # All tests written first

    steps:
      - name: implement
        agent: builder
        runtime: claude-code

      - name: review
        agent: reviewer
        runtime: claude-code

      - name: test
        agent: tester
        runtime: claude-code
        config:
          test_file: tests/unit/test_validator.py
          test_function: test_validate_empty_string

  T112:
    title: "Implement exit command"
    description: "Add exit/quit commands to CLI"
    phase: phase5
    subtree: exit_functionality
    dependencies:
      - "checkpoint:mvp_ready"  # High-level checkpoint

    steps:
      - name: implement
        agent: builder
        runtime: claude-code

      - name: review
        agent: reviewer
        runtime: gemini  # Use different runtime for diversity

      - name: security_check
        agent: sherlock
        runtime: claude-code
        on_failure: skip  # Don't fail if sherlock finds issues

  T120:
    title: "Quality check"
    description: "Final quality checks"
    phase: phase5
    subtree: quality_checks
    dependencies:
      - type: any_of
        value: [T118, T119]  # Either one satisfies

    steps:
      - name: flake8
        agent: linter
        runtime: local

      - name: black
        agent: formatter
        runtime: local

      - name: pytest
        agent: tester
        runtime: claude-code
        config:
          coverage_threshold: 80
```

### 3.2 JSON Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["name", "version", "tasks", "phases"],
  "properties": {
    "name": {"type": "string"},
    "version": {"type": "string"},
    "description": {"type": "string"},
    "defaults": {
      "type": "object",
      "properties": {
        "runtime": {"type": "string"},
        "agent": {"type": "string"},
        "branch_template": {"type": "string"},
        "auto_commit": {"type": "boolean"},
        "auto_merge": {"type": "boolean"}
      }
    },
    "repository": {
      "type": "object",
      "properties": {
        "root": {"type": "string"},
        "main_branch": {"type": "string"},
        "worktree_dir": {"type": "string"}
      }
    },
    "checkpoints": {
      "type": "object",
      "additionalProperties": {"type": "string"}
    },
    "phases": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "name", "tasks"],
        "properties": {
          "id": {"type": "string"},
          "name": {"type": "string"},
          "description": {"type": "string"},
          "tasks": {"type": "array", "items": {"type": "string"}},
          "checkpoint": {"type": "string"},
          "parallel": {"type": "boolean"}
        }
      }
    },
    "tasks": {
      "type": "object",
      "additionalProperties": {
        "type": "object",
        "required": ["title", "description"],
        "properties": {
          "title": {"type": "string"},
          "description": {"type": "string"},
          "phase": {"type": "string"},
          "subtree": {"type": "string"},
          "dependencies": {
            "oneOf": [
              {"type": "string"},
              {"type": "array", "items": {"type": "string"}},
              {
                "type": "object",
                "required": ["type", "value"],
                "properties": {
                  "type": {"enum": ["task_id", "phase", "subtree", "expression", "checkpoint", "any_of", "all_of"]},
                  "value": {},
                  "optional": {"type": "boolean"}
                }
              }
            ]
          },
          "steps": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["name", "agent", "runtime"],
              "properties": {
                "name": {"type": "string"},
                "agent": {"type": "string"},
                "runtime": {"type": "string"},
                "config": {"type": "object"},
                "on_failure": {"enum": ["fail", "skip", "retry"]},
                "max_retries": {"type": "integer"},
                "timeout_seconds": {"type": "integer"}
              }
            }
          },
          "parallel": {"type": "boolean"},
          "file_path": {"type": "string"},
          "outputs": {"type": "array", "items": {"type": "string"}},
          "metadata": {"type": "object"}
        }
      }
    }
  }
}
```

---

## 4. Agent System

### 4.1 Agent Interface

```python
from abc import ABC, abstractmethod
from typing import Dict, Any, List

class Agent(ABC):
    """Base agent interface"""

    agent_id: str
    name: str
    description: str

    @abstractmethod
    async def execute(self,
                     task: Task,
                     context: Dict[str, Any],
                     runtime: "Runtime") -> Dict[str, Any]:
        """
        Execute agent logic

        Args:
            task: The task to execute
            context: Execution context (files, dependencies, etc.)
            runtime: The runtime to use

        Returns:
            Result dictionary with:
            - success (bool)
            - output (str)
            - error (Optional[str])
            - artifacts (Dict[str, Any])
        """
        pass

    @abstractmethod
    def validate_config(self, config: Dict[str, Any]) -> List[str]:
        """Validate agent configuration, return list of errors"""
        pass
```

### 4.2 Agent CLI Wrapper (Dagu Integration)

Since Dagu executes shell commands, the Agent System is exposed via a CLI entrypoint `dagctl run-agent`.

```bash
# Example Dagu Command
dagctl run-agent \
  --task T001 \
  --step implement \
  --agent builder \
  --runtime claude-code \
  --context ./context.json
```

```python
class AgentCLIWrapper:
    """
    Bridge between Dagu shell commands and Python Agent objects.
    """
    def run(self, task_id: str, step_name: str, agent_name: str, runtime_name: str):
        # 1. Load Project Spec
        spec = load_spec()
        task = spec.tasks[task_id]
        step_config = task.get_step(step_name)

        # 2. Initialize Agent & Runtime
        agent = AgentFactory.create(agent_name)
        runtime = RuntimeManager.get(runtime_name)

        # 3. Prepare Context
        context = self._gather_context(task)

        # 4. Execute
        result = asyncio.run(agent.execute(task, context, runtime))

        # 5. Handle Output
        if not result["success"]:
            sys.exit(1)

        # 6. Save Artifacts (for subsequent steps to use)
        self._save_artifacts(task_id, step_name, result)

    def _gather_context(self, task: Task) -> Dict[str, Any]:
        """Gather execution context for agent"""
        return {
            "task": task,
            "worktree_path": get_worktree_path(task),
            "git_diff": get_git_diff(task),
            "files": get_files_in_worktree(task),
            "previous_results": load_previous_step_results(task.id)
        }

    def _save_artifacts(self, task_id: str, step_name: str, result: Dict[str, Any]):
        """Save artifacts for subsequent steps"""
        artifact_path = Path(f".dagctl/artifacts/{task_id}/{step_name}.json")
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(json.dumps(result, default=str))
```

### 4.3 Built-in Agents

```python
class BuilderAgent(Agent):
    """Generates code based on task description"""

    agent_id = "builder"
    name = "Code Builder"
    description = "Generates implementation code from task specifications"

    async def execute(self, task, context, runtime):
        # Build prompt from task
        prompt = self._build_prompt(task, context)

        # Execute on runtime
        result = await runtime.execute(prompt, worktree_path=context["worktree_path"])

        return {
            "success": result.success,
            "output": result.output,
            "files_modified": result.files_modified,
            "artifacts": {
                "code": result.output,
                "files": result.files_modified
            }
        }

    def _build_prompt(self, task, context):
        return f"""Implement task {task.id}: {task.title}

Description: {task.description}

Context:
{self._format_context(context)}

Please implement this task following best practices."""

    def validate_config(self, config):
        return []  # No required config


class ReviewerAgent(Agent):
    """Reviews code for quality, correctness, style"""

    agent_id = "reviewer"
    name = "Code Reviewer"
    description = "Reviews code changes for quality and correctness"

    async def execute(self, task, context, runtime):
        # Get git diff
        diff = context.get("git_diff", "")

        # Build review prompt
        prompt = f"""Review the changes for task {task.id}

```diff
{diff}
```

Check for:
1. Code quality
2. Style consistency
3. Potential bugs
4. Test coverage
5. Security issues

Respond with JSON:
{{
  "passed": true/false,
  "summary": "Brief summary",
  "issues": ["issue1", "issue2"],
  "suggestions": ["suggestion1"]
}}"""

        result = await runtime.execute(prompt)

        # Parse JSON response
        review_data = parse_json_response(result.output)

        return {
            "success": True,
            "output": review_data.get("summary", ""),
            "artifacts": {
                "passed": review_data.get("passed", False),
                "issues": review_data.get("issues", []),
                "suggestions": review_data.get("suggestions", [])
            }
        }

    def validate_config(self, config):
        return []


class SherlockAgent(Agent):
    """Security-focused code reviewer"""

    agent_id = "sherlock"
    name = "Security Inspector"
    description = "Analyzes code for security vulnerabilities"

    async def execute(self, task, context, runtime):
        diff = context.get("git_diff", "")

        prompt = f"""Perform security analysis of these changes:

```diff
{diff}
```

Check for:
1. SQL injection
2. XSS vulnerabilities
3. Command injection
4. Path traversal
5. Insecure dependencies
6. Sensitive data exposure

Respond with JSON:
{{
  "passed": true/false,
  "vulnerabilities": [
    {{"severity": "high/medium/low", "issue": "...", "fix": "..."}}
  ]
}}"""

        result = await runtime.execute(prompt)

        vuln_data = parse_json_response(result.output)

        return {
            "success": True,
            "artifacts": {
                "passed": len(vuln_data.get("vulnerabilities", [])) == 0,
                "vulnerabilities": vuln_data.get("vulnerabilities", [])
            }
        }

    def validate_config(self, config):
        return []


class TesterAgent(Agent):
    """Generates and runs tests"""

    agent_id = "tester"
    name = "Test Generator"
    description = "Generates and executes tests for code changes"

    async def execute(self, task, context, runtime):
        # Get modified files
        files = context.get("files_modified", [])

        prompt = f"""Generate tests for these modified files: {files}

Task: {task.description}

Generate pytest tests following these conventions:
- Use descriptive test names
- Include edge cases
- Mock external dependencies
- Add docstrings"""

        result = await runtime.execute(prompt, worktree_path=context["worktree_path"])

        # Run tests
        test_result = await runtime.run_command(
            ["pytest", "-v", "--tb=short"],
            cwd=context["worktree_path"]
        )

        return {
            "success": test_result.returncode == 0,
            "output": test_result.stdout,
            "artifacts": {
                "test_code": result.output,
                "test_results": test_result.stdout
            }
        }

    def validate_config(self, config):
        return []


class LinterAgent(Agent):
    """Runs linting tools"""

    agent_id = "linter"
    name = "Code Linter"
    description = "Runs flake8, pylint, or other linters"

    async def execute(self, task, context, runtime):
        files = context.get("files_modified", [])

        # Run flake8
        result = await runtime.run_command(
            ["flake8"] + files + ["--max-line-length=88"],
            cwd=context["worktree_path"]
        )

        passed = result.returncode == 0

        return {
            "success": True,
            "output": result.stdout if not passed else "",
            "artifacts": {
                "passed": passed,
                "issues": result.stdout.split("\n") if not passed else []
            }
        }

    def validate_config(self, config):
        return []


class FormatterAgent(Agent):
    """Formats code using black or similar tools"""

    agent_id = "formatter"
    name = "Code Formatter"
    description = "Formats code using black"

    async def execute(self, task, context, runtime):
        files = context.get("files_modified", [])

        # Run black
        result = await runtime.run_command(
            ["black"] + files + ["--line-length=88"],
            cwd=context["worktree_path"]
        )

        return {
            "success": result.returncode == 0,
            "output": result.stdout,
            "artifacts": {
                "formatted": result.returncode == 0
            }
        }

    def validate_config(self, config):
        return []
```

### 4.4 Agent Configuration

```yaml
# agents.yaml
agents:
  builder:
    class: BuilderAgent
    default_runtime: claude-code
    config:
      temperature: 0.3
      max_tokens: 4000

  reviewer:
    class: ReviewerAgent
    default_runtime: claude-code
    config:
      temperature: 0.1  # Lower temp for consistent reviews
      max_tokens: 2000

  sherlock:
    class: SherlockAgent
    default_runtime: claude-code
    config:
      temperature: 0.2
      max_tokens: 3000
      severity_threshold: medium  # Fail on high/medium vulns

  tester:
    class: TesterAgent
    default_runtime: claude-code
    config:
      test_framework: pytest
      coverage_threshold: 80

  linter:
    class: LinterAgent
    default_runtime: local
    config:
      tool: flake8
      max_line_length: 88

  formatter:
    class: FormatterAgent
    default_runtime: local
    config:
      tool: black
      line_length: 88

# Custom agents can be registered
custom_agents:
  domain_expert:
    class: DomainExpertAgent
    module: ./my_agents.py
    default_runtime: claude-code
    config:
      domain: "finance"
      guidelines: "./finance_guidelines.md"
```

---

## 5. Runtime Abstraction

### 5.1 Runtime Interface

```python
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
import subprocess

@dataclass
class RuntimeResult:
    success: bool
    output: str
    error: Optional[str] = None
    files_modified: List[str] = field(default_factory=list)
    returncode: int = 0

class Runtime(ABC):
    """Runtime interface for LLM execution"""

    runtime_id: str
    name: str

    @abstractmethod
    async def execute(self,
                     prompt: str,
                     **kwargs) -> RuntimeResult:
        """Execute a prompt on the runtime"""
        pass

    @abstractmethod
    async def run_command(self,
                         command: List[str],
                         cwd: Optional[str] = None) -> subprocess.CompletedProcess:
        """Run a shell command"""
        pass

    @abstractmethod
    def get_worktree_context(self, worktree_path: str) -> Dict[str, Any]:
        """Get context about files in worktree"""
        pass
```

### 5.2 Runtime Implementations

```python
import asyncio

class ClaudeCodeRuntime(Runtime):
    """Claude Code CLI runtime"""

    runtime_id = "claude-code"
    name = "Claude Code CLI"

    def __init__(self, config: Dict[str, Any]):
        self.claude_path = config.get("claude_path", "claude")
        self.timeout = config.get("timeout", 1800)

    async def execute(self, prompt, **kwargs):
        worktree_path = kwargs.get("worktree_path", ".")

        # Run claude CLI with prompt
        proc = await asyncio.create_subprocess_exec(
            self.claude_path,
            "--print",
            cwd=worktree_path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=prompt.encode()),
                timeout=self.timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            return RuntimeResult(
                success=False,
                output="",
                error="Timeout exceeded",
                returncode=-1
            )

        # Get modified files
        files = await self._get_modified_files(worktree_path)

        return RuntimeResult(
            success=proc.returncode == 0,
            output=stdout.decode(),
            error=stderr.decode() if proc.returncode != 0 else None,
            files_modified=files,
            returncode=proc.returncode
        )

    async def run_command(self, command, cwd=None):
        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()

        return subprocess.CompletedProcess(
            args=command,
            returncode=proc.returncode,
            stdout=stdout.decode(),
            stderr=stderr.decode()
        )

    async def _get_modified_files(self, worktree_path: str) -> List[str]:
        proc = await asyncio.create_subprocess_exec(
            "git", "status", "--porcelain",
            cwd=worktree_path,
            stdout=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()

        modified = []
        for line in stdout.decode().split("\n"):
            if line.strip():
                # Git status: XY filename
                if len(line) > 3:
                    modified.append(line[3:])
        return modified

    def get_worktree_context(self, worktree_path):
        # Implementation to gather file context
        pass


class GeminiRuntime(Runtime):
    """Google Gemini API runtime"""

    runtime_id = "gemini"
    name = "Google Gemini"

    def __init__(self, config: Dict[str, Any]):
        import google.generativeai as genai
        genai.configure(api_key=config["api_key"])
        self.model = genai.GenerativeModel(config.get("model", "gemini-pro"))

    async def execute(self, prompt, **kwargs):
        # Gemini doesn't have file access, so we provide context
        context = kwargs.get("context", {})
        full_prompt = self._build_prompt(prompt, context)

        response = await self.model.generate_content_async(full_prompt)

        return RuntimeResult(
            success=True,
            output=response.text,
            files_modified=[]  # Gemini can't modify files directly
        )

    async def run_command(self, command, cwd=None):
        # Gemini can't run commands
        raise NotImplementedError("Gemini runtime cannot run shell commands")

    def _build_prompt(self, prompt, context):
        """Add file context to prompt"""
        if context.get("files"):
            file_contents = "\n\n".join(
                f"File: {path}\n```\n{content}\n```"
                for path, content in context["files"].items()
            )
            return f"{file_contents}\n\n{prompt}"
        return prompt

    def get_worktree_context(self, worktree_path):
        pass


class LocalRuntime(Runtime):
    """Local command execution (for linting, formatting, etc.)"""

    runtime_id = "local"
    name = "Local Execution"

    def __init__(self, config: Dict[str, Any]):
        self.shell = config.get("shell", "/bin/bash")

    async def execute(self, prompt, **kwargs):
        # For local runtime, prompt might be a command
        command = kwargs.get("command", prompt.split())

        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await proc.communicate()

        return RuntimeResult(
            success=proc.returncode == 0,
            output=stdout.decode(),
            error=stderr.decode() if proc.returncode != 0 else None,
            returncode=proc.returncode
        )

    async def run_command(self, command, cwd=None):
        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()

        return subprocess.CompletedProcess(
            args=command,
            returncode=proc.returncode,
            stdout=stdout.decode(),
            stderr=stderr.decode()
        )

    def get_worktree_context(self, worktree_path):
        pass
```

### 5.3 Runtime Manager

```python
class RuntimeManager:
    """Manages runtime selection and initialization"""

    def __init__(self, config: Dict[str, Any]):
        self.runtimes: Dict[str, Runtime] = {}
        self._load_runtimes(config)

    def _load_runtimes(self, config):
        """Load runtimes from configuration"""
        runtime_configs = config.get("runtimes", {})

        for runtime_id, runtime_config in runtime_configs.items():
            runtime_type = runtime_config["type"]

            if runtime_type == "claude-code":
                self.runtimes[runtime_id] = ClaudeCodeRuntime(runtime_config)
            elif runtime_type == "gemini":
                self.runtimes[runtime_id] = GeminiRuntime(runtime_config)
            elif runtime_type == "local":
                self.runtimes[runtime_id] = LocalRuntime(runtime_config)
            # Add custom runtimes...

    def get_runtime(self, runtime_id: str) -> Runtime:
        """Get runtime by ID"""
        return self.runtimes.get(runtime_id)

    async def execute_on_runtime(self,
                                 runtime_id: str,
                                 prompt: str,
                                 **kwargs) -> RuntimeResult:
        """Execute prompt on specified runtime"""
        runtime = self.get_runtime(runtime_id)
        return await runtime.execute(prompt, **kwargs)
```

---

## 6. Dagu Workflow Generation

This is the core transformation layer. It converts the logical `DAGSpec` into a physical `dagu.yaml`.

### 6.1 Translation Logic

1.  **Phases to Groups**: Dagu doesn't strictly have "Phases", but we prefix step names and manage dependencies such that Phase 2 steps depend on Phase 1 completion.
2.  **Tasks to Steps**: Each `Task` in the spec becomes a series of Dagu `steps`.
3.  **Dependencies**:
    *   `Task -> Task`: Dagu `depends` list.
    *   `Phase -> Phase`: The first step of a task in Phase N depends on *all* terminal steps of Phase N-1.

### 6.2 Generator Implementation

```python
from typing import Dict, List, Any

class DaguGenerator:
    def generate(self, spec: DAGSpec) -> Dict[str, Any]:
        dagu_dag = {
            "name": spec.name.replace(" ", "_").lower(),
            "description": spec.description,
            "env": {
                "DAG_PROJECT_ROOT": spec.repo_root,
                "DAG_LOG_LEVEL": spec.log_level
            },
            "params": "EXECUTION_ID",
            "steps": []
        }

        # 1. Generate Steps for each Task
        for task_id, task in spec.tasks.items():
            prev_step_name = None

            # Resolve Dependencies (Task-level)
            task_deps = self._resolve_dagu_dependencies(task, spec)

            for step in task.steps:
                step_name = f"{task_id}_{step.name}"

                dagu_step = {
                    "name": step_name,
                    "command": self._build_command(task, step),
                    "depends": [],
                    "dir": spec.repo_root
                }

                # Add error handling based on on_failure
                if step.on_failure == "skip":
                    dagu_step["continueOn"] = {"failure": True}
                elif step.on_failure == "retry":
                    dagu_step["retryPolicy"] = {
                        "limit": step.max_retries,
                        "intervalSec": 30
                    }

                # Add timeout
                if step.timeout_seconds:
                    dagu_step["signalOnStop"] = "SIGTERM"

                # First step inherits task dependencies
                if prev_step_name is None:
                    dagu_step["depends"] = task_deps
                else:
                    # Subsequent steps depend on previous step of same task
                    dagu_step["depends"] = [prev_step_name]

                # Add output capture for artifact passing
                dagu_step["output"] = f"RESULT_{step_name}"

                dagu_dag["steps"].append(dagu_step)
                prev_step_name = step_name

        # 2. Add notification handlers
        dagu_dag["handlerOn"] = {
            "success": {
                "command": "dagctl notify --event success --dag $DAG_NAME"
            },
            "failure": {
                "command": "dagctl notify --event failure --dag $DAG_NAME"
            },
            "cancel": {
                "command": "dagctl notify --event cancel --dag $DAG_NAME"
            }
        }

        return dagu_dag

    def _resolve_dagu_dependencies(self, task: Task, spec: DAGSpec) -> List[str]:
        dagu_deps = []

        for dep in task.get_dependencies():
            if dep.type == DependencyType.TASK_ID:
                # Depend on the LAST step of the target task
                target_task = spec.tasks[dep.value]
                last_step = target_task.steps[-1]
                dagu_deps.append(f"{target_task.id}_{last_step.name}")

            elif dep.type == DependencyType.PHASE:
                # Depend on all tasks in that phase
                phase_name = dep.value.replace("phase:", "")
                phase = next(p for p in spec.phases if p.id == phase_name)
                for t_id in phase.tasks:
                    t = spec.tasks[t_id]
                    dagu_deps.append(f"{t.id}_{t.steps[-1].name}")

            elif dep.type == DependencyType.SUBTREE:
                # Depend on all tasks in subtree
                subtree_tasks = self._get_tasks_in_subtree(dep.value, spec)
                for t in subtree_tasks:
                    dagu_deps.append(f"{t.id}_{t.steps[-1].name}")

            elif dep.type == DependencyType.CHECKPOINT:
                # Find tasks that set this checkpoint
                checkpoint_name = dep.value.replace("checkpoint:", "")
                for phase in spec.phases:
                    if phase.checkpoint == checkpoint_name:
                        for t_id in phase.tasks:
                            t = spec.tasks[t_id]
                            dagu_deps.append(f"{t.id}_{t.steps[-1].name}")

            elif dep.type == DependencyType.ANY_OF:
                # Dagu doesn't support any_of natively
                # We create a precondition step that checks any
                # For now, just depend on all (stricter)
                for val in dep.value:
                    if val in spec.tasks:
                        t = spec.tasks[val]
                        dagu_deps.append(f"{t.id}_{t.steps[-1].name}")

            elif dep.type == DependencyType.ALL_OF:
                for val in dep.value:
                    if val in spec.tasks:
                        t = spec.tasks[val]
                        dagu_deps.append(f"{t.id}_{t.steps[-1].name}")

        return dagu_deps

    def _get_tasks_in_subtree(self, subtree: str, spec: DAGSpec) -> List[Task]:
        """Get all tasks in a subtree path like 'phase3/validator_tests'"""
        tasks = []
        subtree_clean = subtree.replace("subtree:", "")
        for task in spec.tasks.values():
            task_subtree = f"{task.phase}/{task.subtree}" if task.subtree else task.phase
            if task_subtree and task_subtree.startswith(subtree_clean):
                tasks.append(task)
        return tasks

    def _build_command(self, task: Task, step: TaskStep) -> str:
        return (
            f"dagctl run-agent "
            f"--task {task.id} "
            f"--step {step.name} "
            f"--agent {step.agent} "
            f"--runtime {step.runtime} "
            f"--execution-id $EXECUTION_ID"
        )
```

### 6.3 Example Output (`dagu.yaml`)

```yaml
name: calculator_project
description: "Build a simple calculator"
env:
  DAG_PROJECT_ROOT: "."
  DAG_LOG_LEVEL: "INFO"
params: "EXECUTION_ID"

steps:
  # --- Phase 1: T001 ---
  - name: T001_implement
    command: "dagctl run-agent --task T001 --step implement --agent builder --runtime claude-code --execution-id $EXECUTION_ID"
    dir: "."
    depends: []
    output: RESULT_T001_implement

  # --- Phase 1: T002 ---
  - name: T002_implement
    command: "dagctl run-agent --task T002 --step implement --agent builder --runtime claude-code --execution-id $EXECUTION_ID"
    dir: "."
    depends: ["T001_implement"]
    output: RESULT_T002_implement

  # --- Phase 2: T009 ---
  - name: T009_implement
    command: "dagctl run-agent --task T009 --step implement --agent builder --runtime claude-code --execution-id $EXECUTION_ID"
    dir: "."
    depends:
      - "T001_implement"
      - "T002_implement"
    output: RESULT_T009_implement

  - name: T009_review
    command: "dagctl run-agent --task T009 --step review --agent reviewer --runtime claude-code --execution-id $EXECUTION_ID"
    dir: "."
    depends: ["T009_implement"]
    output: RESULT_T009_review

  # --- Task with retry policy ---
  - name: T112_implement
    command: "dagctl run-agent --task T112 --step implement ..."
    depends: ["..."]
    retryPolicy:
      limit: 3
      intervalSec: 30

  # --- Task with skip on failure ---
  - name: T112_security_check
    command: "dagctl run-agent --task T112 --step security_check --agent sherlock ..."
    depends: ["T112_review"]
    continueOn:
      failure: true

handlerOn:
  success:
    command: "dagctl notify --event success --dag calculator_project"
  failure:
    command: "dagctl notify --event failure --dag calculator_project"
  cancel:
    command: "dagctl notify --event cancel --dag calculator_project"
```

### 6.4 Artifact Passing Between Steps

Dagu supports output variables that can be passed between steps:

```python
def _build_command_with_artifacts(self, task: Task, step: TaskStep, prev_step: Optional[str]) -> str:
    cmd = (
        f"dagctl run-agent "
        f"--task {task.id} "
        f"--step {step.name} "
        f"--agent {step.agent} "
        f"--runtime {step.runtime}"
    )

    # Pass previous step's output as context
    if prev_step:
        cmd += f" --prev-result $RESULT_{prev_step}"

    return cmd
```

---

## 7. CLI Interface

### 7.1 Commands

```bash
# Initialize new DAG project
dagctl init my-project --template calculator

# Generate Dagu configuration
dagctl generate dag.yaml --output ~/.dagu/dags/my_project.yaml

# Validate DAG specification
dagctl validate dag.yaml

# Execute entire DAG
dagctl execute dag.yaml

# Execute specific phase
dagctl execute dag.yaml --phase phase2

# Execute specific task
dagctl execute dag.yaml --task T001

# Execute with dry-run (show what would happen)
dagctl execute dag.yaml --dry-run

# Monitor execution
dagctl monitor dag.yaml

# Query state
dagctl state dag.yaml

# Visualize DAG
dagctl visualize dag.yaml --format mermaid

# Add task to DAG
dagctl add dag.yaml --task my-task --description "..." --phase phase1

# Generate documentation
dagctl docs dag.yaml --output README.md

# Run a single agent step (used by Dagu)
dagctl run-agent --task T001 --step implement --agent builder --runtime claude-code

# Send notifications (used by Dagu handlers)
dagctl notify --event success --dag my_project
```

### 7.2 CLI Implementation

```python
import click
from pathlib import Path
import yaml
import json

@click.group()
@click.version_option(version="1.0.0")
def cli():
    """DAG-to-Dagu workflow generator"""
    pass

@cli.command()
@click.argument("name")
@click.option("--template", default="basic", help="Project template")
def init(name, template):
    """Initialize a new DAG project"""
    # Create project structure
    project_dir = Path(name)
    project_dir.mkdir(parents=True, exist_ok=True)

    # Copy template files
    template_dir = Path(__file__).parent / "templates" / template
    copy_tree(template_dir, project_dir)

    click.echo(f"✓ Created {name}")
    click.echo(f"✓ Template: {template}")

@cli.command()
@click.argument("dag_file", type=click.Path(exists=True))
@click.option("--output", default=None, help="Output file path")
def generate(dag_file, output):
    """Generate Dagu YAML from DAG spec"""
    # Load DAG spec
    dag_spec = load_dag_spec(dag_file)

    # Validate
    errors = dag_spec.validate()
    if errors:
        click.echo("❌ Validation errors:", err=True)
        for error in errors:
            click.echo(f"  - {error}", err=True)
        raise SystemExit(1)

    # Generate Dagu YAML
    generator = DaguGenerator()
    dagu_yaml = generator.generate(dag_spec)

    # Determine output path
    if output is None:
        output = Path.home() / ".dagu" / "dags" / f"{dag_spec.name.replace(' ', '_').lower()}.yaml"

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write YAML
    with open(output_path, "w") as f:
        yaml.dump(dagu_yaml, f, default_flow_style=False, sort_keys=False)

    click.echo(f"✓ Generated Dagu workflow")
    click.echo(f"✓ Output: {output_path}")

@cli.command()
@click.argument("dag_file", type=click.Path(exists=True))
def validate(dag_file):
    """Validate DAG specification"""
    dag_spec = load_dag_spec(dag_file)
    errors = dag_spec.validate()

    if errors:
        click.echo("❌ Validation failed:", err=True)
        for error in errors:
            click.echo(f"  ✗ {error}", err=True)
        raise SystemExit(1)
    else:
        click.echo("✓ DAG specification is valid")
        click.echo(f"  Tasks: {len(dag_spec.tasks)}")
        click.echo(f"  Phases: {len(dag_spec.phases)}")

@cli.command()
@click.argument("dag_file", type=click.Path(exists=True))
@click.option("--phase", help="Execute specific phase")
@click.option("--task", help="Execute specific task")
@click.option("--dry-run", is_flag=True, help="Show what would execute")
def execute(dag_file, phase, task, dry_run):
    """Execute DAG via Dagu"""
    dag_spec = load_dag_spec(dag_file)
    config = load_config()

    if dry_run:
        # Show execution plan
        show_execution_plan(dag_spec, phase, task)
        return

    # Generate/update Dagu YAML
    generator = DaguGenerator()
    dagu_yaml = generator.generate(dag_spec)

    dag_name = dag_spec.name.replace(" ", "_").lower()
    dagu_path = Path(config["engine"]["dags_dir"]).expanduser() / f"{dag_name}.yaml"

    with open(dagu_path, "w") as f:
        yaml.dump(dagu_yaml, f, default_flow_style=False)

    # Trigger Dagu execution
    import requests

    dagu_host = config["engine"]["dagu_host"]
    execution_id = str(uuid.uuid4())

    response = requests.post(
        f"{dagu_host}/api/v1/dags/{dag_name}/start",
        json={"params": f"EXECUTION_ID={execution_id}"}
    )

    if response.status_code == 200:
        click.echo(f"✓ Started execution: {execution_id}")
        click.echo(f"✓ Monitor at: {dagu_host}")
    else:
        click.echo(f"❌ Failed to start: {response.text}", err=True)
        raise SystemExit(1)

@cli.command()
@click.argument("dag_file", type=click.Path(exists=True))
@click.option("--port", default=8501, help="Dashboard port")
def monitor(dag_file, port):
    """Launch monitoring dashboard"""
    dag_spec = load_dag_spec(dag_file)

    # Start dashboard
    dashboard = Dashboard(dag_spec, port)
    dashboard.run()

@cli.command()
@click.argument("dag_file", type=click.Path(exists=True))
@click.option("--format", "fmt", default="mermaid", type=click.Choice(["mermaid", "dot", "json"]))
def visualize(dag_file, fmt):
    """Visualize DAG structure"""
    dag_spec = load_dag_spec(dag_file)

    if fmt == "mermaid":
        output = generate_mermaid(dag_spec)
    elif fmt == "dot":
        output = generate_dot(dag_spec)
    elif fmt == "json":
        output = json.dumps(asdict(dag_spec), indent=2, default=str)

    click.echo(output)

@cli.command()
@click.argument("dag_file", type=click.Path(exists=True))
def state(dag_file):
    """Query current execution state"""
    dag_spec = load_dag_spec(dag_file)
    config = load_config()

    dag_name = dag_spec.name.replace(" ", "_").lower()
    fetcher = DaguStatusFetcher(config["engine"]["dagu_host"])

    state = fetcher.get_project_state(dag_name)

    click.echo(f"DAG: {dag_spec.name}")
    click.echo(f"Progress: {state['progress_percent']:.1f}%")
    click.echo(f"Completed: {len(state['completed_tasks'])}/{len(dag_spec.tasks)}")
    click.echo(f"In Progress: {len(state['in_progress'])}")
    click.echo(f"Failed: {len(state['failed'])}")

@cli.command("run-agent")
@click.option("--task", required=True, help="Task ID")
@click.option("--step", required=True, help="Step name")
@click.option("--agent", required=True, help="Agent name")
@click.option("--runtime", required=True, help="Runtime name")
@click.option("--execution-id", default=None, help="Execution ID")
@click.option("--prev-result", default=None, help="Previous step result")
def run_agent(task, step, agent, runtime, execution_id, prev_result):
    """Run a single agent step (called by Dagu)"""
    wrapper = AgentCLIWrapper()
    wrapper.run(task, step, agent, runtime, execution_id, prev_result)

@cli.command()
@click.option("--event", required=True, type=click.Choice(["success", "failure", "cancel"]))
@click.option("--dag", required=True, help="DAG name")
def notify(event, dag):
    """Send notification (called by Dagu handlers)"""
    config = load_config()
    notifier = Notifier(config)
    notifier.send(event, dag)
```

---

## 8. Monitoring Dashboard

We adopt a hybrid monitoring approach.

### 8.1 Level 1: Low-Level (Dagu UI)

Users can visit `http://localhost:8080` to see the standard Dagu interface.

*   **Pros**: Native real-time graph, logs, manual retry, stop/start.
*   **Cons**: Shows "Steps" not "Tasks", graph can get very large for complex projects.

### 8.2 Level 2: High-Level (Dagctl Dashboard)

The custom dashboard pulls status from Dagu API and maps to logical tasks.

```python
from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
import uvicorn
import requests

class DaguStatusFetcher:
    """Fetches and maps Dagu status to logical model"""

    def __init__(self, dagu_host: str):
        self.dagu_host = dagu_host

    def get_project_state(self, dag_name: str) -> Dict[str, Any]:
        # Call Dagu API
        resp = requests.get(f"{self.dagu_host}/api/v1/dags/{dag_name}/status")
        dagu_state = resp.json()

        # Map back to logical model
        logical_state = {
            "completed_tasks": [],
            "in_progress": [],
            "failed": [],
            "pending": [],
            "progress_percent": 0.0
        }

        task_status = {}  # task_id -> {steps: {step_name: status}}

        for node in dagu_state.get("nodes", []):
            step_name = node["name"]
            status = node["status"]

            # Extract "T001" from "T001_implement"
            task_id = step_name.split("_")[0]

            if task_id not in task_status:
                task_status[task_id] = {"steps": {}, "overall": "pending"}

            task_status[task_id]["steps"][step_name] = status

        # Aggregate step statuses into task status
        for task_id, data in task_status.items():
            steps = data["steps"].values()

            if any(s == "failed" for s in steps):
                logical_state["failed"].append(task_id)
            elif any(s == "running" for s in steps):
                logical_state["in_progress"].append(task_id)
            elif all(s == "success" for s in steps):
                logical_state["completed_tasks"].append(task_id)
            else:
                logical_state["pending"].append(task_id)

        total = len(task_status)
        if total > 0:
            logical_state["progress_percent"] = len(logical_state["completed_tasks"]) / total * 100

        return logical_state


class Dashboard:
    """Real-time monitoring dashboard"""

    def __init__(self, dag_spec: DAGSpec, port: int = 8501):
        self.dag = dag_spec
        self.port = port
        self.app = FastAPI(title=f"{dag_spec.name} Dashboard")
        self.websocket_connections: List[WebSocket] = []
        self.status_fetcher = DaguStatusFetcher(load_config()["engine"]["dagu_host"])

        self._setup_routes()
        self._setup_websocket()

    def _setup_routes(self):
        """Setup HTTP routes"""

        @self.app.get("/")
        async def index():
            """Serve dashboard UI"""
            return FileResponse("dashboard/index.html")

        @self.app.get("/api/state")
        async def get_state():
            """Get current execution state"""
            dag_name = self.dag.name.replace(" ", "_").lower()
            state = self.status_fetcher.get_project_state(dag_name)
            return state

        @self.app.get("/api/tasks/{task_id}")
        async def get_task(task_id: str):
            """Get task details"""
            task = self.dag.tasks.get(task_id)
            if task:
                return asdict(task)
            return {"error": "Task not found"}

        @self.app.get("/api/dag")
        async def get_dag():
            """Get DAG structure for visualization"""
            return {
                "tasks": {tid: asdict(t) for tid, t in self.dag.tasks.items()},
                "phases": [asdict(p) for p in self.dag.phases],
                "dependencies": self._build_dependency_graph()
            }

        @self.app.post("/api/execute")
        async def start_execution():
            """Start DAG execution"""
            config = load_config()
            dag_name = self.dag.name.replace(" ", "_").lower()
            execution_id = str(uuid.uuid4())

            # Trigger Dagu
            response = requests.post(
                f"{config['engine']['dagu_host']}/api/v1/dags/{dag_name}/start",
                json={"params": f"EXECUTION_ID={execution_id}"}
            )

            return {"execution_id": execution_id, "status": response.status_code}

    def _setup_websocket(self):
        """Setup WebSocket for real-time updates"""

        @self.app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await websocket.accept()
            self.websocket_connections.append(websocket)

            try:
                while True:
                    # Poll Dagu status and push updates
                    await asyncio.sleep(2)
                    dag_name = self.dag.name.replace(" ", "_").lower()
                    state = self.status_fetcher.get_project_state(dag_name)
                    await websocket.send_json({"type": "state_update", "data": state})
            except:
                self.websocket_connections.remove(websocket)

    def _build_dependency_graph(self):
        """Build dependency graph for visualization"""
        edges = []
        for task_id, task in self.dag.tasks.items():
            for dep in task.get_dependencies():
                if dep.type == DependencyType.TASK_ID:
                    edges.append({"from": dep.value, "to": task_id})
        return edges

    def run(self):
        """Start dashboard server"""
        uvicorn.run(
            self.app,
            host="0.0.0.0",
            port=self.port,
            log_level="info"
        )
```

### 8.3 Dashboard UI

```html
<!-- dashboard/index.html -->
<!DOCTYPE html>
<html>
<head>
    <title>DAG Monitor</title>
    <script src="https://cdn.jsdelivr.net/npm/vis-network/standalone/umd/vis-network.min.js"></script>
    <style>
        body { font-family: Arial, sans-serif; margin: 0; padding: 20px; }

        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }

        .stats {
            display: flex;
            gap: 20px;
            margin-bottom: 20px;
        }

        .stat-card {
            background: #f5f5f5;
            padding: 15px;
            border-radius: 8px;
            min-width: 150px;
        }

        .stat-value {
            font-size: 32px;
            font-weight: bold;
        }

        .stat-label {
            color: #666;
            font-size: 14px;
        }

        #dag-container {
            height: 500px;
            border: 1px solid #ddd;
            border-radius: 8px;
            margin-bottom: 20px;
        }

        .task-list {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 15px;
        }

        .task-card {
            border: 1px solid #ddd;
            border-radius: 8px;
            padding: 15px;
        }

        .task-card.completed {
            border-color: #4caf50;
            background: #f1f8f4;
        }

        .task-card.in-progress {
            border-color: #ff9800;
            background: #fff8f1;
        }

        .task-card.failed {
            border-color: #f44336;
            background: #fef1f1;
        }

        .status-badge {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: bold;
        }

        .status-badge.completed { background: #4caf50; color: white; }
        .status-badge.in-progress { background: #ff9800; color: white; }
        .status-badge.pending { background: #9e9e9e; color: white; }
        .status-badge.failed { background: #f44336; color: white; }

        button {
            background: #2196f3;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 4px;
            cursor: pointer;
        }

        button:hover {
            background: #1976d2;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1 id="dag-name">DAG Monitor</h1>
        <button onclick="startExecution()">Start Execution</button>
    </div>

    <div class="stats">
        <div class="stat-card">
            <div class="stat-value" id="stat-progress">0%</div>
            <div class="stat-label">Progress</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" id="stat-completed">0</div>
            <div class="stat-label">Completed</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" id="stat-in-progress">0</div>
            <div class="stat-label">In Progress</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" id="stat-failed">0</div>
            <div class="stat-label">Failed</div>
        </div>
    </div>

    <div id="dag-container"></div>

    <h2>Tasks</h2>
    <div class="task-list" id="task-list"></div>

    <script>
        let dagData = null;
        let taskStatus = {};
        let ws = null;
        let network = null;

        // Load DAG data
        async function loadDAG() {
            const resp = await fetch("/api/dag");
            dagData = await resp.json();
            initDAG();
            renderTasks();
        }

        // Initialize DAG visualization
        function initDAG() {
            const nodes = [];
            const edges = [];

            // Create nodes from tasks
            for (const [id, task] of Object.entries(dagData.tasks)) {
                nodes.push({
                    id: id,
                    label: `${id}\n${task.title.substring(0, 20)}...`,
                    color: getTaskColor(id),
                    shape: "box"
                });
            }

            // Create edges from dependencies
            for (const edge of dagData.dependencies) {
                edges.push({
                    from: edge.from,
                    to: edge.to,
                    arrows: "to"
                });
            }

            const container = document.getElementById("dag-container");
            const data = { nodes: new vis.DataSet(nodes), edges: new vis.DataSet(edges) };
            const options = {
                layout: {
                    hierarchical: {
                        direction: "UD",
                        sortMethod: "directed"
                    }
                }
            };

            network = new vis.Network(container, data, options);
        }

        function getTaskColor(taskId) {
            const status = taskStatus[taskId] || "pending";
            if (status === "completed") return "#4caf50";
            if (status === "in-progress") return "#ff9800";
            if (status === "failed") return "#f44336";
            return "#e0e0e0";
        }

        function renderTasks() {
            const container = document.getElementById("task-list");
            container.innerHTML = "";

            for (const [id, task] of Object.entries(dagData.tasks)) {
                const status = taskStatus[id] || "pending";
                const card = document.createElement("div");
                card.className = `task-card ${status}`;
                card.innerHTML = `
                    <h3>${id}: ${task.title}</h3>
                    <p>${task.description.substring(0, 100)}...</p>
                    <span class="status-badge ${status}">
                        ${status.charAt(0).toUpperCase() + status.slice(1)}
                    </span>
                `;
                container.appendChild(card);
            }
        }

        function updateStats(state) {
            document.getElementById("stat-completed").textContent = state.completed_tasks.length;
            document.getElementById("stat-in-progress").textContent = state.in_progress.length;
            document.getElementById("stat-failed").textContent = state.failed.length;
            document.getElementById("stat-progress").textContent =
                state.progress_percent.toFixed(0) + "%";
        }

        function updateTaskStatus(state) {
            taskStatus = {};
            for (const id of state.completed_tasks) taskStatus[id] = "completed";
            for (const id of state.in_progress) taskStatus[id] = "in-progress";
            for (const id of state.failed) taskStatus[id] = "failed";

            renderTasks();

            // Update node colors
            if (network && dagData) {
                for (const id of Object.keys(dagData.tasks)) {
                    network.body.data.nodes.update({
                        id: id,
                        color: getTaskColor(id)
                    });
                }
            }
        }

        function connectWebSocket() {
            ws = new WebSocket(`ws://${window.location.host}/ws`);

            ws.onmessage = (event) => {
                const msg = JSON.parse(event.data);
                if (msg.type === "state_update") {
                    updateStats(msg.data);
                    updateTaskStatus(msg.data);
                }
            };

            ws.onclose = () => {
                setTimeout(connectWebSocket, 3000);
            };
        }

        async function startExecution() {
            const response = await fetch("/api/execute", {
                method: "POST",
                headers: {"Content-Type": "application/json"}
            });

            const data = await response.json();
            console.log("Execution started:", data.execution_id);
            alert("Execution started: " + data.execution_id);
        }

        // Initialize
        loadDAG();
        connectWebSocket();
    </script>
</body>
</html>
```

---

## 9. Configuration System

### 9.1 Full Configuration (`dagctl.yaml`)

```yaml
# dagctl.yaml
project:
  name: "My Project"
  version: "1.0.0"

# Repository settings
repository:
  root: .
  main_branch: main
  worktree_dir: .worktrees

# Dagu engine settings
engine:
  type: dagu
  dagu_host: "http://localhost:8080"
  dags_dir: "~/.dagu/dags"

# Runtimes
runtimes:
  claude-code:
    type: claude-code
    config:
      claude_path: claude
      timeout: 1800

  gemini:
    type: gemini
    config:
      api_key: ${GEMINI_API_KEY}
      model: gemini-pro

  local:
    type: local
    config:
      shell: /bin/bash

# Agents
agents:
  builder:
    class: BuilderAgent
    default_runtime: claude-code
    config:
      temperature: 0.3
      max_tokens: 4000

  reviewer:
    class: ReviewerAgent
    default_runtime: claude-code
    config:
      temperature: 0.1
      max_tokens: 2000

  sherlock:
    class: SherlockAgent
    default_runtime: claude-code
    enabled: true
    config:
      severity_threshold: medium

  tester:
    class: TesterAgent
    default_runtime: claude-code
    config:
      test_framework: pytest

  linter:
    class: LinterAgent
    default_runtime: local
    config:
      tool: flake8
      max_line_length: 88

  formatter:
    class: FormatterAgent
    default_runtime: local
    config:
      tool: black
      line_length: 88

# Dashboard
dashboard:
  enabled: true
  port: 8501
  refresh_interval: 2  # seconds

# Logging
logging:
  level: INFO
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  file: dagctl.log

# Execution settings
execution:
  auto_commit: true
  auto_merge: false
  keep_worktrees: false
  max_parallel_tasks: 10
  retry_on_failure: true
  max_retries: 3

# Quality gates
quality_gates:
  require_review_pass: true
  require_tests_pass: true
  require_lint_pass: false
  coverage_threshold: 80

# Notifications
notifications:
  slack:
    enabled: false
    webhook_url: ${SLACK_WEBHOOK}
    events: ["failure", "completion"]

  email:
    enabled: false
    smtp_host: smtp.example.com
    smtp_port: 587
    from_address: dagctl@example.com
    to_addresses: ["team@example.com"]
    events: ["failure"]
```

### 9.2 Notifier Implementation

```python
class Notifier:
    """Sends notifications based on configuration"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config.get("notifications", {})

    def send(self, event: str, dag_name: str):
        """Send notification for an event"""
        # Slack notification
        if self.config.get("slack", {}).get("enabled"):
            self._send_slack(event, dag_name)

        # Email notification
        if self.config.get("email", {}).get("enabled"):
            self._send_email(event, dag_name)

    def _send_slack(self, event: str, dag_name: str):
        slack_config = self.config["slack"]

        if event not in slack_config.get("events", []):
            return

        color = {"success": "good", "failure": "danger", "cancel": "warning"}.get(event, "#439FE0")

        payload = {
            "attachments": [{
                "color": color,
                "title": f"DAG {event.upper()}: {dag_name}",
                "text": f"The DAG '{dag_name}' has {event}.",
                "ts": int(datetime.now().timestamp())
            }]
        }

        requests.post(slack_config["webhook_url"], json=payload)

    def _send_email(self, event: str, dag_name: str):
        email_config = self.config["email"]

        if event not in email_config.get("events", []):
            return

        import smtplib
        from email.mime.text import MIMEText

        msg = MIMEText(f"The DAG '{dag_name}' has {event}.")
        msg["Subject"] = f"DAG {event.upper()}: {dag_name}"
        msg["From"] = email_config["from_address"]
        msg["To"] = ", ".join(email_config["to_addresses"])

        with smtplib.SMTP(email_config["smtp_host"], email_config["smtp_port"]) as server:
            server.send_message(msg)
```

---

## 10. Extension Points

### 10.1 Custom Agents

```python
# my_agents.py
from dagctl.agents import Agent

class DomainExpertAgent(Agent):
    """Custom agent for domain-specific review"""

    agent_id = "domain_expert"
    name = "Domain Expert"
    description = "Reviews code for domain-specific requirements"

    def __init__(self, config):
        self.domain = config.get("domain", "general")
        self.guidelines_file = config.get("guidelines")

    async def execute(self, task, context, runtime):
        # Load domain guidelines
        guidelines = Path(self.guidelines_file).read_text()

        # Build domain-specific prompt
        prompt = f"""Review this code for {self.domain} compliance:

Guidelines:
{guidelines}

Code changes:
{context['git_diff']}

Check for:
1. {self.domain} best practices
2. Compliance with guidelines
3. Common pitfalls

Respond with JSON:
{{
  "passed": true/false,
  "issues": [...],
  "suggestions": [...]
}}
"""

        result = await runtime.execute(prompt)
        review_data = parse_json_response(result.output)

        return {
            "success": True,
            "artifacts": review_data
        }

    def validate_config(self, config):
        errors = []
        if not config.get("guidelines"):
            errors.append("guidelines file path required")
        return errors

# Register in dagctl.yaml:
# custom_agents:
#   domain_expert:
#     class: DomainExpertAgent
#     module: ./my_agents.py
#     config:
#       domain: finance
#       guidelines: ./finance_guidelines.md
```

### 10.2 Custom Runtimes

```python
# my_runtimes.py
from dagctl.runtimes import Runtime, RuntimeResult
import aiohttp

class CustomLLMRuntime(Runtime):
    """Integration with custom LLM API"""

    runtime_id = "custom-llm"
    name = "Custom LLM"

    def __init__(self, config: Dict[str, Any]):
        self.api_key = config["api_key"]
        self.base_url = config["base_url"]

    async def execute(self, prompt, **kwargs):
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/generate",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"prompt": prompt}
            ) as response:
                data = await response.json()

                return RuntimeResult(
                    success=data.get("success", True),
                    output=data.get("text", ""),
                    error=data.get("error")
                )

    async def run_command(self, command, cwd=None):
        raise NotImplementedError("Custom LLM cannot run commands")

    def get_worktree_context(self, worktree_path):
        pass

# Register in dagctl.yaml:
# runtimes:
#   custom-llm:
#     type: custom
#     class: CustomLLMRuntime
#     module: ./my_runtimes.py
#     config:
#       api_key: ${CUSTOM_API_KEY}
#       base_url: https://api.example.com
```

### 10.3 Custom Dagu Templates

Users can provide a Jinja2 template for the `dagu.yaml` generation:

```yaml
# dagctl.yaml
engine:
  type: dagu
  template: ./custom_dagu_template.yaml.j2
```

```jinja2
{# custom_dagu_template.yaml.j2 #}
name: {{ spec.name | replace(" ", "_") | lower }}
description: {{ spec.description }}

env:
  DAG_PROJECT_ROOT: {{ spec.repo_root }}
  DAG_LOG_LEVEL: {{ spec.log_level }}
  CUSTOM_VAR: "my_value"

params: "EXECUTION_ID"

{% for task_id, task in spec.tasks.items() %}
{% for step in task.steps %}
  - name: {{ task_id }}_{{ step.name }}
    command: "dagctl run-agent --task {{ task_id }} --step {{ step.name }} --agent {{ step.agent }} --runtime {{ step.runtime }} --execution-id $EXECUTION_ID"
    dir: {{ spec.repo_root }}
    depends: {{ depends_list | tojson }}
    {% if step.on_failure == "skip" %}
    continueOn:
      failure: true
    {% endif %}
    {% if step.on_failure == "retry" %}
    retryPolicy:
      limit: {{ step.max_retries }}
      intervalSec: 30
    {% endif %}
    output: RESULT_{{ task_id }}_{{ step.name }}
{% endfor %}
{% endfor %}

# Custom notification with more detail
handlerOn:
  success:
    command: |
      curl -X POST $SLACK_WEBHOOK -d '{"text": "DAG {{ spec.name }} completed successfully!"}'
  failure:
    command: |
      curl -X POST $SLACK_WEBHOOK -d '{"text": "DAG {{ spec.name }} FAILED! Check logs."}'
```

---

## 11. Implementation Roadmap

### Phase 1: Core (MVP)
- [ ] DAG parser (YAML/JSON)
- [ ] Validation engine
- [ ] Basic Dagu YAML generator
- [ ] CLI with init/generate/validate commands
- [ ] Basic agent wrapper (builder only)

### Phase 2: Multi-Agent
- [ ] Agent system architecture
- [ ] Built-in agents (builder, reviewer, tester)
- [ ] Multi-step task execution
- [ ] Agent configuration
- [ ] Artifact passing between steps

### Phase 3: Multi-Runtime
- [ ] Runtime abstraction layer
- [ ] Claude Code runtime
- [ ] Gemini runtime
- [ ] Local runtime
- [ ] Runtime manager

### Phase 4: Advanced Dependencies
- [ ] All dependency types (phase, subtree, checkpoint, expression)
- [ ] Dependency resolution engine
- [ ] Any-of / all-of logic
- [ ] Expression parser

### Phase 5: Monitoring & Dashboard
- [ ] Dagu status fetcher
- [ ] Logical state mapping
- [ ] FastAPI dashboard
- [ ] WebSocket real-time updates
- [ ] DAG visualization

### Phase 6: Polish
- [ ] Error handling & retry (Dagu continueOn, retryPolicy)
- [ ] Quality gates
- [ ] Notifications (Slack, email)
- [ ] Custom templates (Jinja2)
- [ ] Documentation generation

---

## 12. Appendix

### A. Dependency Expression Grammar

```
expression ::= or_expr
or_expr ::= and_expr ('|' and_expr)*
and_expr ::= primary ('&' primary)*
primary ::= task_id | phase_ref | subtree_ref | checkpoint_ref | '(' expression ')'
task_id ::= 'T' [0-9]+
phase_ref ::= 'phase:' [a-z0-9_]+
subtree_ref ::= 'subtree:' [a-z0-9_/]+
checkpoint_ref ::= 'checkpoint:' [a-z0-9_]+
```

### B. File Structure

```
dagctl/
├── __init__.py
├── cli.py                  # CLI commands
├── parser.py               # DAG parser
├── validator.py            # DAG validator
├── generator.py            # Dagu YAML generator
├── agents/
│   ├── __init__.py
│   ├── base.py             # Base agent interface
│   ├── builder.py          # Builder agent
│   ├── reviewer.py         # Reviewer agent
│   ├── sherlock.py         # Security agent
│   ├── tester.py           # Tester agent
│   ├── linter.py           # Linter agent
│   └── formatter.py        # Formatter agent
├── runtimes/
│   ├── __init__.py
│   ├── base.py             # Runtime interface
│   ├── claude_code.py      # Claude Code runtime
│   ├── gemini.py           # Gemini runtime
│   └── local.py            # Local runtime
├── dashboard/
│   ├── __init__.py
│   ├── app.py              # FastAPI app
│   ├── status_fetcher.py   # Dagu status fetcher
│   └── static/
│       └── index.html      # Dashboard UI
├── notifications/
│   ├── __init__.py
│   ├── slack.py            # Slack notifier
│   └── email.py            # Email notifier
├── config.py               # Configuration management
├── state.py                # Execution state
├── models.py               # Data models
└── utils.py                # Utilities

templates/
├── basic/                  # Basic project template
├── calculator/             # Calculator project template
└── microservice/           # Microservice template
```

### C. Dagu Feature Mapping

| Feature | Dagu Support | Implementation |
|---------|--------------|----------------|
| Dependencies | `depends: [...]` | Direct mapping |
| Retry | `retryPolicy` | Map from `on_failure: retry` |
| Skip on failure | `continueOn.failure` | Map from `on_failure: skip` |
| Timeout | `signalOnStop` | Map from `timeout_seconds` |
| Artifacts | `output` variables | Map to `$RESULT_*` vars |
| Notifications | `handlerOn` | Map from config |
| Parallelism | Native | Dagu handles via deps |
| Visualization | Dagu Web UI | Built-in |

### D. Examples

See `/examples/` for example DAG specifications:
- `calculator.yaml` - Calculator project (130 tasks)
- `microservice.yaml` - Microservice setup (25 tasks)
- `documentation.yaml` - Docs generation (10 tasks)

---

**End of Specification**
