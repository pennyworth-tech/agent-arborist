# Quick Start

Install and run your first Agent Arborist spec.

## Prerequisites

### Required
- **Python 3.10+** - Arborist is Python-based
- **Git** - For worktree management
- **Dagu** - Workflow execution engine

```bash
python --version  # 3.10+
git --version
dagu version
```

### Optional (for AI)
- **Claude CLI** - For claude runner
- **OpenCode CLI** - For opencode runner
- **Gemini API key** - For gemini runner

## Installation

```bash
# Clone repository
git clone https://github.com/your-org/agent-arborist.git
cd agent-arborist

# Install in development mode
pip install -e .

# Install Dagu (macOS)
brew install dagu

# Install Dagu (Linux)
curl -L https://raw.githubusercontent.com/yohamta/dagu/main/scripts/install.sh | bash
```

## Initialize

```bash
# In your project directory
arborist init
```

Creates `.arborist/` directory with project config.

## Create First Spec

```bash
mkdir -p .arborist/specs/001-hello-world

cat > .arborist/specs/001-hello-world/tasks.md << 'EOF'
# Tasks: Hello World

**Project**: Simple hello world program
**Total Tasks**: 2

## Phase 1: Setup

- [ ] T001 Create project directory structure: `src/`, `tests/`
- [ ] T002 Create `src/main.py` with hello world function

## Dependencies

T001 → T002
EOF
```

## Generate DAG

```bash
arborist spec dag-build 001-hello-world
```

Generates Dagu YAML in `.arborist/dagu/001-hello-world/`.

## Create Branches

```bash
arborist spec branch-create-all 001-hello-world
```

Creates Git branches for each task.

## Run DAG

```bash
arborist dag run 001-hello-world
```

This executes tasks in order using the configured AI runner.

## Check Status

```bash
# View task status
arborist task status --spec 001-hello-world

# View DAG status
arborist dag status 001-hello-world
```

## Monitor with Dagu

```bash
# Start Dagu server (in separate terminal)
dagu server

# Open http://localhost:8080
```

## Configuration (Optional)

Create `.arborist/config.json`:

```json
{
  "version": "1",
  "defaults": {
    "runner": "claude",
    "model": "sonnet"
  }
}
```

Or global config at `~/.arborist_config.json`.

## Next Steps

- [Architecture](./03-architecture.md) - How Arborist works
- [Configuration](../03-configuration/README.md) - Customize settings