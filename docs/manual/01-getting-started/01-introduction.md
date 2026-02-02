# Introduction

Agent Arborist orchestrates AI-driven task execution using directed acyclic graphs (DAGs) managed by Dagu.

## What is Agent Arborist?

Agent Arborist is a task tree executor that:
- **Reads markdown task specs** from `.arborist/specs/`
- **Generates DAGU DAGs** for workflow orchestration
- **Executes tasks with AI** using runners: claude, opencode, gemini
- **Isolates changes** in Git worktrees
- **Tracks progress** with task state management

## What Problems Does It Solve?

**Without Agent Arborist:**
- You manually describe tasks to an AI, run them one by one, and manage Git branches yourself
- Parallel task execution becomes complex and error-prone
- Task failures require manual intervention and retry
- History is fragmented across multiple AI conversations
- Reproducibility is difficult

**With Agent Arborist:**
- Define your entire project as a structured markdown spec
- Tasks execute automatically in the correct order based on dependencies
- Parallel tasks run simultaneously for speed
- Failures are tracked and can be retried independently
- All execution is tracked in Git worktrees with full history
- Complete reproducibility - run the same spec and get the same results

## Who Is This For?

**Software Developers:** Build features, refactor code, generate tests with AI orchestration

**DevOps Engineers:** Automate infrastructure-as-code, deployment pipelines, configuration changes

**Data Engineers:** Orchestrate ETL pipelines, data transformations, ML workflows

**Teams:** Enable consistent, reproducible AI-driven development across your organization

**Note:** This tool requires technical knowledge of Git, CLI tools, and your chosen AI runner.

## Key Concepts

### Task Specifications

A **spec** is a markdown file defining tasks. Each task has:
- An ID (e.g., T001, T002)
- A description
- Optional parallel flag `[P]`
- Optional phase grouping

**Example spec:**
```markdown
# Tasks: Calculator Project

**Project**: Simple calculator app
**Total Tasks**: 2

## Phase 1: Core

- [ ] T001 Create add() function
- [ ] T002 Create subtract() function

## Dependencies

T001 → T002
```

### Directory Structure

```
project/
├── .arborist/
│   ├── config.json           # Project configuration
│   ├── manifests/            # Branch manifests (spec_id.json)
│   ├── dagu/                 # Generated DAGU YAML files
│   ├── worktrees/            # Git worktrees (spec_id/task_id/)
│   ├── task-state/           # Task state (spec_id.json)
│   └── prompts/              # Hook prompt files
├── specs/
│   └── 001-calculator/       # = spec_id
│       └── tasks.md
└── src/
```

### AI Runners

Agent Arborist supports three runners:
- **claude** - Anthropic Claude (default)
- **opencode** - OpenCode AI
- **gemini** - Google Gemini

Configure runners in JSON config files.

## CLI Commands

`arborist` provides these command groups:

| Command | Purpose |
|---------|---------|
| `init` | Initialize `.arborist/` directory |
| `version` | Show version info |
| `doctor` | System diagnostics |
| `config` | Configuration management |
| `hooks` | Hook configuration and testing |
| `task` | Task operations (run, commit, test) |
| `spec` | Spec operations (dag-build, branch-create) |
| `dag` | DAG operations (run, status, restart) |

## Architecture

```mermaid
graph TB
    User[User CLI] --> Spec[Spec Parser]
    Spec --> DAGGen[DAG Generator]
    DAGGen --> Dagu[Dagu Engine]

    Dagu --> Worktree[Git Worktrees]
    Dagu --> Runner[AI Runner]

    Runner --> Claude[Claude]
    Runner --> Open[OpenCode]
    Runner --> Gemini[Gemini]

    Config[Config JSON] --> DAGGen
    Config --> Runner

    style User fill:#e1f5ff
    style Dagu fill:#ffe1e1
    style Runner fill:#e1ffe1
```

## Next Steps

- [Quick Start](./02-quick-start.md) - Install and run your first spec
- [Core Concepts](../02-core-concepts/README.md) - Understand specs, DAGs, worktrees