# CLI Reference

## Global Options

```
arborist [--log-level DEBUG|INFO|WARNING|ERROR] <command>
```

| Option | Default | Description |
|--------|---------|-------------|
| `--log-level` | `WARNING` | Set logging verbosity |

## Commands

### `arborist init`

Initialize `.arborist/` directory with config and logs.

```bash
arborist init
```

Creates:
- `.arborist/config.json` — project configuration (prompts for runner/model)
- `.arborist/logs/` — log directory
- Adds `.arborist/logs/` to `.gitignore`

---

### `arborist build`

Build a task tree from a spec directory.

```bash
arborist build [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--spec-dir` | `spec` | Directory containing task spec markdown files |
| `--output`, `-o` | `task-tree.json` | Output path for the task tree JSON file |
| `--no-ai` | off | Use deterministic markdown parser instead of AI planning |
| `--runner` | from config | Runner for AI planning |
| `--model` | from config | Model for AI planning |

**Examples:**

```bash
# Default: AI planning
arborist build

# Custom spec directory and output
arborist build --spec-dir my-specs/ -o trees/feature.json

# Use Gemini for planning
arborist build --runner gemini --model gemini-2.5-pro

# Deterministic parser (no API calls)
arborist build --no-ai
```

---

### `arborist garden`

Execute a single task through the implement → test → review pipeline.

```bash
arborist garden [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--tree` | *(required)* | Path to `task-tree.json` |
| `--runner-type` | from config | Runner type for implementation |
| `--model` | from config | Model name |
| `--max-retries` | from config (5) | Max retries per task |
| `--target-repo` | git root of cwd | Repository to work in |
| `--base-branch` | current branch | Branch name for spec path resolution |
| `--report-dir` | next to task tree | Directory for JSON report files |
| `--log-dir` | `.arborist/logs` | Directory for runner log files |

**Examples:**

```bash
# Execute the next ready task
arborist garden --tree task-tree.json

# Use a specific runner/model
arborist garden --tree task-tree.json --runner-type gemini --model gemini-2.5-pro
```

---

### `arborist gardener`

Execute all tasks in dependency order (loops until done or failure).

```bash
arborist gardener [OPTIONS]
```

Takes the same options as `garden`.

**Examples:**

```bash
# Run everything
arborist gardener --tree task-tree.json

# With custom retries and log directory
arborist gardener --tree task-tree.json --max-retries 10 --log-dir ./logs
```

---

### `arborist status`

Show the current status of all tasks in the tree.

```bash
arborist status [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--tree` | *(required)* | Path to `task-tree.json` |
| `--target-repo` | git root of cwd | Repository to check |

**Output:**

```
my-project
├── phase1 Database Layer
│   ├── OK T001 Create schema (complete)
│   └── OK T002 Add migrations (complete)
└── phase2 API Layer
    ├── ... T003 Build endpoints (implementing)
    └── -- T004 Add tests (pending)
```

Status icons:
- `OK` — complete
- `...` — in progress (implementing, testing, or reviewing)
- `--` — pending
- `FAIL` — failed after max retries

---

### `arborist inspect`

Deep-dive into a single task: metadata, commit history, trailers, and current state.

```bash
arborist inspect [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--tree` | *(required)* | Path to `task-tree.json` |
| `--task-id` | *(required)* | Task ID to inspect (e.g. `T003`) |
| `--target-repo` | git root of cwd | Repository to check |

**Output:**

Shows task metadata (name, description, dependencies), current state from git trailers, and full commit history for the task.

**Examples:**

```bash
# Inspect a specific task
arborist inspect --tree task-tree.json --task-id T003

# Inspect in a different repo
arborist inspect --tree task-tree.json --task-id T001 --target-repo /path/to/repo
```
