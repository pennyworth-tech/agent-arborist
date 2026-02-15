# Agent Arborist

Git-native task tree orchestration. Break complex projects into hierarchical tasks, then let AI execute them — one branch, one commit at a time.

## Quick Start

### 1. Install

```bash
pip install -e .
```

### 2. Initialize a Project

```bash
cd your-project
arborist init
```

This creates `.arborist/config.json` with your preferred runner (Claude, Gemini, or OpenCode) and model.

### 3. Write a Task Spec

Create a `spec/` directory with markdown files describing your tasks:

```markdown
## Phase 1: Setup
- [ ] T001 Create database schema
- [ ] T002 Add migration scripts

## Phase 2: API
- [ ] T003 Implement user endpoints (depends on T001)
- [ ] T004 Add authentication middleware (depends on T003)

## Dependencies
T003 -> T001
T004 -> T003
```

### 4. Build the Task Tree

```bash
arborist build --spec-dir spec/
```

This sends your spec to an AI planner (Claude Opus by default) which produces a `task-tree.json` with the full hierarchy and execution order.

### 5. Run All Tasks

```bash
arborist gardener --tree task-tree.json
```

Arborist works through each task in dependency order. For each task it:
1. Creates a git branch
2. Sends the task to an AI runner to implement
3. Runs your test command
4. Sends the diff for AI code review
5. On approval, commits and merges back

### 6. Check Status

```bash
arborist status --tree task-tree.json
```

## How It Works

Arborist stores all state in git — branches for isolation, commit trailers for tracking. No external database, no daemon. If a process crashes, pick up where you left off by running `gardener` again.

```
spec/*.md  ──►  arborist build  ──►  task-tree.json
                                          │
                                    arborist gardener
                                          │
                              ┌───────────┼───────────┐
                              ▼           ▼           ▼
                          branch/T001  branch/T002  branch/T003
                          implement    implement    implement
                          test         test         test
                          review       review       review
                          merge ◄──────merge ◄──────merge
```

## Configuration

Arborist uses a layered config system (highest precedence first):

1. CLI flags
2. Environment variables (`ARBORIST_RUNNER`, `ARBORIST_MODEL`, etc.)
3. Project config (`.arborist/config.json`)
4. Global config (`~/.arborist_config.json`)
5. Built-in defaults

### Per-Step Runner Overrides

Use a powerful model for implementation and a fast one for review:

```json
{
  "defaults": { "runner": "claude", "model": "sonnet" },
  "steps": {
    "implement": { "runner": "claude", "model": "opus" },
    "review": { "runner": "claude", "model": "haiku" }
  }
}
```

## Supported Runners

| Runner | CLI Tool | Example Models |
|--------|----------|----------------|
| Claude | `claude` | `opus`, `sonnet`, `haiku` |
| Gemini | `gemini` | `gemini-2.5-flash`, `gemini-2.5-pro` |
| OpenCode | `opencode` | `cerebras/zai-glm-4.7` |

## Documentation

See [docs/manual/](docs/manual/) for the full user manual.

## Testing

```bash
# Unit tests
pytest tests/

# Provider-specific (requires API keys)
pytest tests/ -m claude
pytest tests/ -m gemini
pytest tests/ -m opencode
```

See `.env.example` for required API keys.
