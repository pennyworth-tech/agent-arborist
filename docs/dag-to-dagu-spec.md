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
8. [Monitoring](#8-monitoring)
9. [Configuration System](#9-configuration-system)

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
2.  **Dagu-Native**: compilation targets standard Dagu YAML files, allowing use of standard Dagu tooling and UI.
3.  **Agent-as-CLI**: Agents are packaged as CLI commands that Dagu steps execute.
4.  **Git-Native**: Every task operates in its own branch/worktree context.
5.  **Observable**: Leverages Dagu's built-in UI for operational monitoring, augmented by `dagctl` for logical project tracking.

---

## 2. Data Models

### 2.1 DAG Specification

The input specification remains the same as the original design. It defines the *logical* structure of the project (Phases, Tasks, Checkpoints).

*(See original spec for full Python dataclasses for `Dependency`, `TaskStep`, `Task`, `Phase`, and `DAGSpec`)*

### 2.2 Execution State in Dagu

Dagu maintains its own state. We map our logical state to Dagu's physical state:

*   **DAG File**: Maps to a generic project spec.
*   **Dagu Step**: Maps to a specific `TaskStep` (e.g., `T001_implement`, `T001_review`).
*   **Execution ID**: Maps to a Dagu run ID.

---

## 3. DAG Specification Format

The YAML format for defining the project remains the same. This allows users to define "What needs to be done" without worrying about "How Dagu runs it".

*(See original spec for `dag.yaml` example)*

---

## 4. Agent System

### 4.1 Agent Interface via CLI

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

### 4.2 Agent Wrapper Implementation

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
```

---

## 5. Runtime Abstraction

Runtimes (Claude, Gemini, etc.) are libraries used by the Agent Python code. They are unchanged from the original spec.

---

## 6. Dagu Workflow Generation

This is the core transformation layer. It converts the logical `DAGSpec` into a physical `dagu.yaml`.

### 6.1 Translation Logic

1.  **Phases to Groups**: Dagu doesn't strictly have "Phases", but we can prefix step names or use Dagu Groups (if supported in the target version) or simply manage dependencies such that Phase 2 steps depend on Phase 1 completion.
2.  **Tasks to Steps**: Each `Task` in the spec becomes a series of Dagu `steps`.
3.  **Dependencies**:
    *   `Task -> Task`: Dagu `depends` list.
    *   `Phase -> Phase`: The first step of a task in Phase N depends on *all* terminal steps of Phase N-1.

### 6.2 Generator Implementation

```python
class DaguGenerator:
    def generate(self, spec: DAGSpec) -> Dict[str, Any]:
        dagu_dag = {
            "description": spec.description,
            "env": {
                "DAG_PROJECT_ROOT": spec.repo_root,
                "DAG_LOG_LEVEL": spec.log_level
            },
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
                    "depends": []
                }

                # First step inherits task dependencies
                if prev_step_name is None:
                    dagu_step["depends"] = task_deps
                else:
                    # Subsequent steps depend on previous step of same task
                    dagu_step["depends"] = [prev_step_name]

                dagu_dag["steps"].append(dagu_step)
                prev_step_name = step_name

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
                phase = next(p for p in spec.phases if p.id == dep.value)
                for t_id in phase.tasks:
                    t = spec.tasks[t_id]
                    dagu_deps.append(f"{t.id}_{t.steps[-1].name}")
                    
        return dagu_deps

    def _build_command(self, task: Task, step: TaskStep) -> str:
        return (
            f"dagctl run-agent "
            f"--task {task.id} "
            f"--step {step.name} "
            f"--agent {step.agent} "
            f"--runtime {step.runtime}"
        )
```

### 6.3 Example Output (`dagu.yaml`)

```yaml
name: calculator_project
description: "Build a simple calculator"
steps:
  # --- Phase 1: T001 ---
  - name: T001_implement
    command: "dagctl run-agent --task T001 --step implement ..."
    depends: []

  # --- Phase 1: T002 ---
  - name: T002_implement
    command: "dagctl run-agent --task T002 --step implement ..."
    depends: ["T001_implement"]

  # --- Phase 2: T009 ---
  - name: T009_implement
    command: "dagctl run-agent --task T009 --step implement ..."
    depends: 
      - "T001_implement" # Dependency on Phase 1 tasks
      - "T002_implement"

  - name: T009_review
    command: "dagctl run-agent --task T009 --step review ..."
    depends: ["T009_implement"]
```

---

## 7. CLI Interface

The CLI is updated to support Dagu.

```bash
# Generate Dagu configuration
dagctl generate dag.yaml --target dagu --output ~/.dagu/dags/my_project.yaml

# Start Dagu (if not running)
dagu start-all

# Trigger execution via Dagu API
dagctl execute dag.yaml --engine dagu
```

### 7.1 Execute Command Logic

When `dagctl execute` is run with Dagu engine:
1.  Generates/Updates the YAML in the Dagu DAGs directory.
2.  Calls Dagu API: `POST /api/v2/dags/my_project.yaml/start`.
3.  Optionally tails the logs or status.

---

## 8. Monitoring

We adopt a hybrid monitoring approach.

### 8.1 Level 1: Low-Level (Dagu UI)
Users can visit `http://localhost:8080` to see the standard Dagu interface.
*   **Pros**: Native real-time graph, logs, manual retry, stop/start.
*   **Cons**: Shows "Steps" not "Tasks", graph can get very large for complex projects.

### 8.2 Level 2: High-Level (Dagctl Dashboard)
The custom dashboard (from original spec) is updated to pull status from Dagu API instead of Inngest.

**API Mapping**:
*   `GET /api/v2/dags/{dag}/status` -> Maps running steps back to Logical Tasks.
*   **Aggregation**: If `T001_implement` is Done and `T001_review` is Running, the Dashboard shows Task T001 as "In Progress (Reviewing)".

```python
class DaguStatusFetcher:
    def get_project_state(self, dag_name):
        # Call Dagu API
        resp = requests.get(f"{DAGU_HOST}/api/v2/dags/{dag_name}")
        dagu_state = resp.json()
        
        # Map back to logical model
        logical_state = {
            "completed_tasks": [],
            "in_progress": [],
            "failed": []
        }
        
        for step_name, step_status in dagu_state["steps"].items():
            task_id = parse_task_id(step_name) # Extract "T001" from "T001_implement"
            if step_status == "failed":
                logical_state["failed"].append(task_id)
            # ... logic to aggregate steps into task status
            
        return logical_state
```

---

## 9. Configuration System

Updated `dagctl.yaml` to include Dagu specific settings.

```yaml
project:
  name: "My Project"

engine:
  type: dagu
  dagu_host: "http://localhost:8080"
  dags_dir: "~/.dagu/dags"

# Agents & Runtimes configuration remains identical
agents:
  builder:
    class: BuilderAgent
    # ...
```

---

## 10. Extension Points

### 10.1 Custom Dagu Templates
Users can provide a Jinja2 template for the `dagu.yaml` generation if they want to inject custom Dagu hooks (e.g., `handlerOn` for Slack notifications).

### 10.2 Hybrid Execution
Possibility to mix "Local Exec" tasks (simple scripts) directly in Dagu YAML vs "Agent Exec" tasks (LLM based) via `dagctl` wrapper.

```
