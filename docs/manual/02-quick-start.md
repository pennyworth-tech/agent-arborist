# Quick Start

Get from zero to executing AI-driven tasks in 5 minutes.

## Prerequisites

- Python 3.11+
- Git
- At least one AI runner CLI installed:
  - [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (`claude`)
  - [Gemini CLI](https://github.com/google-gemini/gemini-cli) (`gemini`)
  - [OpenCode](https://github.com/opencode-ai/opencode) (`opencode`)

## 1. Install Arborist

```bash
git clone <repo-url>
cd agent-arborist
pip install -e .
```

Verify:

```bash
arborist --help
```

## 2. Initialize Your Project

```bash
cd /path/to/your-project
arborist init
```

You'll be prompted for a default runner and model. This creates:

```
.arborist/
├── config.json    # Project configuration
└── logs/          # Runner output logs (gitignored)
```

## 3. Write a Task Spec

Create `spec/tasks.md`:

```markdown
## Phase 1: Foundation
- [ ] T001 Create the data models
- [ ] T002 Add unit tests for models

## Phase 2: API Layer
- [ ] T003 Implement REST endpoints
- [ ] T004 Add integration tests

## Dependencies
T002 -> T001
T003 -> T001
T004 -> T003
```

The format is flexible — the AI planner understands headers, lists, numbering, and indentation. See [Task Specs](03-task-specs.md) for details.

## 4. Build the Task Tree

```bash
arborist build --spec-dir spec/
```

This calls an AI planner (Claude Opus by default) which reads your spec and produces `task-tree.json` — a structured hierarchy with dependency edges and execution order.

You'll see output like:

```
Task Tree: your-project
  Output: /path/to/task-tree.json
  Nodes: 6
  Leaves: 4
  Execution order: T001 -> T002 -> T003 -> T004
```

## 5. Execute All Tasks

```bash
arborist gardener --tree task-tree.json
```

Arborist loops through each leaf task in order. For each one:

1. Creates a git branch (`arborist/your-project/phase1`)
2. Sends the task to the AI runner for implementation
3. Runs your test command
4. Sends the diff for AI code review
5. On success: commits with trailers and merges

If a step fails, Arborist retries (up to 5 times by default) with feedback from the failure.

## 6. Check Progress

```bash
arborist status --tree task-tree.json
```

Shows a tree with status icons:

```
arborist/your-project
├── phase1 Foundation
│   ├── OK T001 Create the data models (complete)
│   └── OK T002 Add unit tests for models (complete)
└── phase2 API Layer
    ├── ... T003 Implement REST endpoints (implementing)
    └── -- T004 Add integration tests (pending)
```

## Next Steps

- [Task Specs](03-task-specs.md) — write better specifications
- [Configuration](07-configuration.md) — tune runners, retries, timeouts
- [CLI Reference](09-cli-reference.md) — all commands and options
