# Quick Start

Get Agent Arborist up and running in minutes with this step-by-step guide.

## Prerequisites

Before installing, ensure you have:

### Required
- **Python 3.10+** - Agent Arborist is written in Python
- **Git** - Required for worktree management
- **Dagu** - Workflow execution engine

```bash
# Check versions
python --version  # Should be 3.10+
git --version
dagu version
```

### Optional (for AI execution)
- **Claude CLI** - For Claude Code runner
- **OpenCode CLI** - For OpenCode runner
- **Gemini API key** - For Gemini runner

### Optional (for container support)
- **Docker** - Required for devcontainer support
- **Devcontainer CLI** - For running in containers

## Installation

### Step 1: Install Agent Arborist

```bash
# Clone the repository
git clone https://github.com/your-org/agent-arborist.git
cd agent-arborist

# Install in development mode
pip install -e .
```

### Step 2: Install Dagu

```bash
# On macOS
brew install dagu

# On Linux
curl -L https://raw.githubusercontent.com/yohamta/dagu/main/scripts/install.sh | bash

# Verify installation
dagu version
```

### Step 3: Initialize Arborist

```bash
# In your project directory
cd /path/to/your/project
arborist init
```

This creates a `.arborist/` directory with project-specific configuration.

## Your First Spec

### Step 1: Create a Spec Directory

```bash
mkdir -p specs/001-hello-world
```

### Step 2: Write the Spec

Create `specs/001-hello-world/tasks.md`:

```markdown
# Tasks: Hello World

**Project**: Simple hello world program
**Total Tasks**: 2

## Phase 1: Setup

- [ ] T001 Create project directory structure: `src/`, `tests/`
- [ ] T002 Create `src/main.py` with hello world function

## Dependencies

T001 → T002
```

### Step 3: Initialize Git

```bash
# Initialize git if not already done
cd /path/to/your/project
git init
git config user.name "Your Name"
git config user.email "your@email.com"

# Commit initial state
git add .
git commit -m "Initial commit"
```

## Running Your Spec

### Step 1: Generate the DAG

```bash
# Build DAG from spec
arborist spec dag-build specs/001-hello-world
```

This generates a Dagu YAML file in `.arborist/dagu/`.

### Step 2: Create Branches

```bash
# Create all branches for tasks
arborist spec branch-create-all specs/001-hello-world
```

This creates Git branches for each task.

### Step 3: Run the DAG

```bash
# Execute the DAG
arborist dag run specs/001-hello-world
```

This will:
1. Create a worktree for T001
2. Run the AI to complete T001
3. Create a worktree for T002
4. Run the AI to complete T002
5. Merge changes back to main branch

## Monitoring Execution

### Using Dagu Web UI

```bash
# Start Dagu server (in a separate terminal)
dagu server

# Open browser
# Navigate to http://localhost:8080
```

You'll see:
- Live execution status
- Task dependencies
- Logs and outputs
- Success/failure indicators

### Using Arborist Dashboard

```bash
# Launch Arborist dashboard
arborist dashboard
```

The dashboard provides:
- Tree visualization of tasks
- Execution metrics
- Hook outputs (if configured)
- Dependency graph

## Checking Results

### View Task Status

```bash
# Check status of all tasks
arborist task status --spec 001-hello-world

# Check specific task
arborist task status T001 --spec 001-hello-world
```

### View Generated Files

```bash
# Show tree visualization
arborist viz tree specs/001-hello-world --format ascii
```

### Inspect Changes

```bash
# Check main branch
git log --oneline --graph

# View completed worktrees
ls .arborist/worktrees/
```

## Configuration (Optional)

### Set Default Runner

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

### Configure AI Runners

#### Claude Code

```json
{
  "runners": {
    "claude": {
      "default_model": "sonnet",
      "models": {
        "sonnet": "claude-3-5-sonnet-20241022",
        "opus": "claude-3-opus-20240229"
      }
    }
  }
}
```

#### OpenCode

```bash
# Set environment variable
export ARBORIST_RUNNER=opencode
```

#### Gemini

```json
{
  "runners": {
    "gemini": {
      "default_model": "gemini-2.5-flash",
      "models": {
        "flash": "gemini-2.5-flash",
        "pro": "gemini-2.5-pro"
      }
    }
  }
}
```

## Common Workflows

### Creating a New Spec

```bash
# 1. Create spec directory
mkdir -p specs/002-new-feature

# 2. Write tasks.md
cat > specs/002-new-feature/tasks.md << 'EOF'
# Tasks: New Feature

## Phase 1: Design
- [ ] T001 Design feature specification
- [ ] T002 Create design document

## Phase 2: Implementation
- [ ] T003 Implement core logic
- [ ] T004 Add tests

## Dependencies
T001 → T002 → T003 → T004
EOF

# 3. Generate DAG
arborist spec dag-build specs/002-new-feature

# 4. Create branches
arborist spec branch-create-all specs/002-new-feature

# 5. Run
arborist dag run specs/002-new-feature
```

### Running a Dry Run

```bash
# See what would happen without executing
arborist dag dry specs/002-new-feature
```

### Re-running Failed Tasks

```bash
# Arborist will automatically skip completed tasks
# Just run again
arborist dag run specs/002-new-feature
```

### Cleaning Up

```bash
# Clean up old worktrees (keep recent ones)
arborist task cleanup --older-than 7d

# Remove all worktrees for a spec
rm -rf .arborist/worktrees/
```

## Troubleshooting

### "claude not found in PATH"

Install Claude CLI:
```bash
# With npm (if using Node version)
npm install -g @anthropics/claude-cli

# Or install from source
# See: https://docs.anthropic.com/claude/reference/claude-cli
```

### "dagu not found in PATH"

Reinstall Dagu:
```bash
# macOS
brew reinstall dagu

# Linux
curl -L https://raw.githubusercontent.com/yohamta/dagu/main/scripts/install.sh | bash
```

### "Not in a git repository"

Initialize git:
```bash
git init
git config user.name "Your Name"
git config user.email "your@email.com"
git add .
git commit -m "Initial commit"
```

### "Spec not found at path"

Check spec path:
```bash
# Ensure spec exists
ls specs/001-hello-world/tasks.md

# Use correct path
arborist spec dag-build specs/001-hello-world/tasks.md
```

## Next Steps

- [Architecture Overview](./03-architecture.md) - Understand how Arborist works
- [Configuration System](../03-configuration/01-configuration-system.md) - Fine-tune your setup
- [Specs and Tasks](../02-core-concepts/01-specs-and-tasks.md) - Write better specs

## Example: Complete Workflow

Here's a complete example from start to finish:

```bash
#!/bin/bash

# 1. Setup project
mkdir my-project && cd my-project
git init
git config user.name "Developer"
git config user.email "dev@example.com"
echo "# My Project" > README.md
git add . && git commit -m "Init"

# 2. Initialize Arborist
arborist init

# 3. Create spec
mkdir -p specs/001-calculator
cat > specs/001-calculator/tasks.md << 'EOF'
# Tasks: Simple Calculator

## Phase 1: Core
- [ ] T001 Create add() function
- [ ] T002 Create subtract() function

## Dependencies
T001 → T002
EOF

# 4. Generate and run
arborist spec dag-build specs/001-calculator
arborist spec branch-create-all specs/001-calculator
arborist dag run specs/001-calculator

# 5. Monitor (in another terminal)
dagu server
```

## Code References

- CLI initialization: [`src/agent_arborist/cli.py:init()`](../../src/agent_arborist/cli.py#L538)
- Spec building: [`src/agent_arborist/cli.py:spec_cmd_dag_build()`](../../src/agent_arborist/cli.py#L1800)
- Branch creation: [`src/agent_arborist/git_tasks.py:create_all_branches_from_manifest()`](../../src/agent_arborist/git_tasks.py)