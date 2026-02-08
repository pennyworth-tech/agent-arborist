# Quick Start

Build a Hello World Calculator in 5 minutes with Agent Arborist.

## What You'll Build

A simple command-line calculator with four operations:
- `add()` - Add two numbers
- `subtract()` - Subtract two numbers
- `multiply()` - Multiply two numbers
- `divide()` - Divide two numbers (with zero-check)

All code will be written by AI agents, isolated in Git worktrees, and orchestrated through a DAG workflow.

## Prerequisites

Required tools:
```bash
# Check Python version (3.11 or higher)
python --version

# Check Git
git --version

# Install AI runners (choose one or more)
# Claude (requires Claude Pro/Max subscription)
# See: https://claude.ai/claude-code

# OpenCode (requires account)
# See: https://opencode.ai

# Gemini (requires Google Cloud project)
# Get key: https://console.cloud.google.com/apis/credentials
```

Install Dagu (workflow executor):
```bash
# macOS
brew install dagu

# Linux
curl -L https://raw.githubusercontent.com/yohamta/dagu/main/scripts/install.sh | bash

# Verify installation
dagu version
# Expected output: 1.30.3 or higher
```

## Step 1: Install Agent Arborist

```bash
# Install from PyPI (recommended)
pip install agent-arborist

# Or install from source for development
git clone https://github.com/your-org/agent-arborist.git
cd agent-arborist
pip install -e .
```

Verify installation:
```bash
arborist version
# Expected output: Agent Arborist - Version 0.1.0
```

## Step 2: Initialize Your Project

```bash
# Create a new directory
mkdir my-calculator
cd my-calculator

# Initialize Git repository
git init
git config user.name "Your Name"
git config user.email "you@example.com"

# Make an initial commit
echo "# My Calculator" > README.md
git add README.md
git commit -m "Initial commit"
```

Initialize Arborist:
```bash
arborist init
```

**What this does:**
- Creates `.arborist/` directory
- Sets up Dagu configuration
- Adds `.arborist/` to `.gitignore`

**Expected output:**
```
Initialized arborist at /path/to/my-calculator/.arborist
```

Verify the setup:
```bash
arborist doctor
```

**Expected output:**
```
                               Dependency Status                                
┏━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┓
┃ Dependency ┃ Status ┃ Version            ┃ Path              ┃ Notes         ┃
┡━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━┩
│ dagu       │ OK     │ 1.30.3             │ /usr/local/bin/dagu│ (min: 1.30.3) │
│ claude     │ OK     │ 2.0.76 (Claude     │ /Users/.../claude  │ (optional)    │
│            │        │ Code)              │                   │               │
└────────────┴────────┴────────────────────┴───────────────────┴───────────────┘

All dependencies OK
```

## Step 3: Configure AI Runner

Create a configuration file to tell Arborist which AI to use:

```json
cat > .arborist/config.json << 'EOF'
{
  "version": "1",
  "defaults": {
    "runner": "claude",
    "model": "sonnet",
    "container_mode": "disabled"
  }
}
EOF
```

**What this does:**
- Tells Arborist to use Claude as the default AI runner
- Uses the "sonnet" model (balanced speed and quality)
- Disables container mode for this simple project

**Why JSON here?** The `.arborist/config.json` file uses JSON format because it's stored within your project and managed by Arborist. See [Configuration System](../03-configuration/01-configuration-system.md) for details on when to use JSON vs YAML.

## Step 4: Create Your Task Specification

Create a markdown file that describes what needs to be built:

```bash
mkdir -p .arborist/specs/001-calculator

cat > .arborist/specs/001-calculator/tasks.md << 'EOF'
# Tasks: Hello World Calculator

**Project**: Simple calculator with four operations
**Total Tasks**: 5

## Phase 1: Setup

- [ ] T001 Create project directory structure: `src/`, `tests/`
- [ ] T002 Create `src/__init__.py` and `tests/__init__.py`

## Phase 2: Implementation

- [ ] T003 [P] Create `src/calculator.py` with add() and subtract() functions
- [ ] T004 [P] Add multiply() and divide() functions to calculator.py (with zero check)

## Phase 3: Polish

- [ ] T005 Create `README.md` with usage examples

## Dependencies

T001 → T002
T002 → T003, T004 → T005
EOF
```

**What this describes:**
- **Tasks 001-002**: Create directory structure
- **Tasks 003-004**: Implement calculator functions (parallel - both run simultaneously)
- **Task 005**: Write documentation (must wait for 003 and 004)

## Step 5: Generate the Workflow DAG

Convert your markdown spec into an executable workflow:

```bash
arborist spec dag-build .arborist/specs/001-calculator --timeout 120
```

**What this does:**
1. **Parses** your markdown spec
2. **Uses AI** (Claude) to generate Dagu YAML configuration
3. **Creates** branch manifest mapping tasks to Git branches
4. **Validates** the generated DAG with Dagu

**Expected output:**
```
Using task spec: .arborist/specs/001-calculator/tasks.md
Generating DAG using claude (sonnet)...
OK: DAG generated successfully
Generating branch manifest...
Manifest written to:
  /path/to/my-calculator/.arborist/dagu/dags/001-calculator.json
  Source branch: main
  Base branch: main_a
  Tasks: 5
DAG written to:
  /path/to/my-calculator/.arborist/dagu/dags/001-calculator.yaml

Validating DAG with dagu...
OK: DAG validation passed
```

Check what was created:
```bash
ls -la .arborist/dagu/dags/
```

**Expected output:**
```
001-calculator.json   # Branch manifest (maps tasks to branches)
001-calculator.yaml   # Dagu workflow configuration
```

View the generated DAG:
```bash
cat .arborist/dagu/dags/001-calculator.yaml | head -40
```

**What is Dagu?** Dagu is the workflow orchestrator that Arborist uses. It:
- Executes tasks in dependency order
- Provides a web UI for monitoring
- Handles retries, timeouts, and failures
- Persists execution history

See [DAGs and Dagu](../02-core-concepts/02-dags-and-dagu.md) for more information.

## Step 6: Create Git Branches

```bash
arborist spec branch-create-all 001-calculator
```

**What this does:**
- Creates a Git branch for each task
- Sets up parent/child branch relationships
- Creates Git worktrees for isolated execution

**Expected output:**
```
创建分支 'main_a'
创建分支 'main_a_T001'
创建分支 'main_a_T002'
创建分支 'main_a_T003'
创建分支 'main_a_T004'
创建分支 'main_a_T005'
```

**What is a Git worktree?** Git worktrees allow you to have multiple working directories for the same repository. Arborist uses worktrees so each task executes in its own isolated environment without conflicts.

See [Git and Worktrees](../02-core-concepts/03-git-and-worktrees.md) for more information.

View the branches:
```bash
git branch -a
```

**Expected output:**
```
  main
* main_a
  main_a_T001
  main_a_T002
  main_a_T003
  main_a_T004
  main_a_T005
```

## Step 7: Run the Workflow

```bash
arborist dag run 001-calculator
```

**What this does:**
1. **Starts Dagu** workflow orchestration
2. **Creates** worktree for T001
3. **Runs AI** (Claude) to execute T001
4. **Commits** T001 changes
5. **Moves** to T002 (depends on T001)
6. **Repeats** for all tasks in order

**Expected output:**
```
Starting DAG: 001-calculator
Step 1: branches-setup
  Creating git branches...
  OK

Step 2: c-T001
  Creating worktree...
  Running AI task (T001)...
  Committing changes...
  OK

Step 3: c-T002
  Creating worktree...
  Running AI task (T002)...
  Committing changes...
  OK

Step 4: c-T003 (parallel with T004)
  Creating worktree...
  Running AI task (T003)...
  OK

Step 5: c-T004 (parallel with T003)
  Creating worktree...
  Running AI task (T004)...
  OK

Step 6: c-T005
  Creating worktree...
  Running AI task (T005)...
  OK

All tasks complete!
```

**This will take 2-5 minutes depending on:**
- Internet connection
- AI model response time
- Complexity of tasks

## Step 8: Verify the Results

Check the generated code:

```bash
# Check directory structure
ls -la src/ tests/

# View the calculator code
cat src/calculator.py
```

**Expected output (src/calculator.py):**
```python
def add(a: float, b: float) -> float:
    """Add two numbers."""
    return a + b

def subtract(a: float, b: float) -> float:
    """Subtract two numbers."""
    return a - b

def multiply(a: float, b: float) -> float:
    """Multiply two numbers."""
    return a * b

def divide(a: float, b: float) -> float:
    """Divide two numbers with zero check."""
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
```

Check the README:
```bash
cat README.md
```

View the Git history:
```bash
git log --oneline --graph --all
```

**Expected output:**
```
* main_a_T005 (HEAD) Add README.md with usage examples
* main_a_T004 Add multiply() and divide() functions
* main_a_T003 Create src/calculator.py with add() and subtract()
* main_a_T002 Create src/__init__.py and tests/__init__.py
* main_a_T001 Create project directory structure
* main_a  README
* main  Initial commit
```

**Note:** After the DAG completes, you'll be on the `main_a` branch, which contains all the merged changes. To return to `main`, run:

```bash
git checkout main
```

## Step 9: Monitor Progress (Optional)

Start the Dagu web UI to monitor runs:

```bash
# In a new terminal
dagu server
# Open: http://localhost:8080

# Or view status from CLI
arborist dag status 001-calculator
```

## Step 10: Clean Up

When you're done experimenting, clean up branches and worktrees:

**Quick cleanup (removes all Arborist state):**
```bash
# Remove entire .arborist directory
rm -rf .arborist

# Remove feature branches
git checkout main
git branch -D main_a main_a_T001 main_a_T002 main_a_T003 main_a_T004 main_a_T005
```

**Detailed cleanup (keep specific artifacts):**
```bash
# View all branches
git branch -a

# View all worktrees
git worktree list

# Remove specific worktrees
git worktree prune  # Remove orphaned worktrees

# Remove specific branches
git branch -D main_a_T005  # Remove specific task branch
```

## Step 11: What to Do When Things Go Wrong

### If a Task Fails

Sometimes the AI might make a mistake or a task might not complete correctly. Here's how to recover:

```bash
# 1. Check the DAG status
arborist dag status 001-calculator

# 2. View task-specific logs
# Logs are in .arborist/dagu/data/dags/001-calculator/
ls .arborist/dagu/data/dags/001-calculator/
cat .arborist/dagu/data/dags/001-calculator/latest/stdout.log

# 3. Inspect what the AI did in the workspace
# Workspaces are in ~/.arborist/workspaces/{repo}/{spec}/{task}/
ls -la ~/.arborist/workspaces/my-project/001-calculator/T003/
cat ~/.arborist/workspaces/my-project/001-calculator/T003/src/calculator.py

# 4. Edit the generated code by hand if needed
# Go to the workspace and fix the code manually
cd ~/.arborist/workspaces/my-project/001-calculator/T003/
# Make changes, commit them with jj
jj describe -m "Fix: Fix bug in calculator"

# 5. Retry the task
arborist dag run 001-calculator  # This will pick up where it left off
```

### Start Fresh

If you want to completely reset and start over:

```bash
# 1. Remove all Arborist artifacts
rm -rf .arborist

# 2. Remove all feature branches
git checkout main
git branch -D main_a main_a_T001 main_a_T002 main_a_T003 main_a_T004 main_a_T005

# 3. Remove workspaces and forget jj workspaces
rm -rf ~/.arborist/workspaces/my-project/001-calculator
jj workspace forget --all

# 4. Verify clean state
git status
git branch -a

# You're now ready to start over
arborist init
```

## Troubleshooting

### Problem: `arborist init` fails

**Fix:** Make sure you're in a Git repository:
```bash
git init
git commit --allow-empty -m "Initial"
```

### Problem: `arborist doctor` shows missing dependencies

**Fix:** Install the missing tool:
```bash
# For Dagu
brew install dagu

# For Claude
# Follow: https://claude.ai/claude-code

# For OpenCode
# Follow: https://opencode.ai
```

### Problem: `arborist spec dag-build` hangs

**Fix:** Check your internet connection and AI credentials:
```bash
# Test claude CLI
claude --version

# Test opencode CLI
opencode --version

# Check env vars for Gemini
echo $GOOGLE_API_KEY
```

### Problem: Git worktree errors

**Fix:** Make clean working directory:
```bash
git status
git stash  # If you have uncommitted changes
```

### Problem: "No such file or directory" when running tasks

**Fix:** Check that branch creation succeeded:
```bash
git branch -a
# Should show: main_a, main_a_T001, main_a_T002, etc.

# If branches are missing, recreate them
arborist spec branch-create-all 001-calculator
```

### Problem: DAG validation passes but execution hangs

**Fix:** Check if the runner is responding:
```bash
# Test runner directly
claude --version  # or opencode --version

# Increase timeout if working over slow connection
arborist dag run 001-calculator --timeout 3600

# Check if there's an error in Dagu logs
ls .arborist/dagu/data/dags/001-calculator/
```

### Problem: Can't find generated code after DAG completes

**Fix:** Check which branch you're on and merge results:
```bash
# View your current branch
git branch

# The completed code is on the main_a branch
git checkout main_a

# Or view code from workspaces
ls ~/.arborist/workspaces/my-project/001-calculator/
cat ~/.arborist/workspaces/my-project/001-calculator/T003/src/calculator.py

# To merge final result to main
# (After all tasks complete successfully)
git checkout main
git merge main_a
```

### Problem: Dagu server won't start

**Fix:** Check port availability:
```bash
# Kill existing Dagu process
pkill dagu

# Or use different port
dagu server --port 8081
```

See [Troubleshooting](../appendices/01-troubleshooting.md) for more help.

## Next Steps

- [Architecture](./03-architecture.md) - How Arborist works internally
- [Configuration](../03-configuration/README.md) - Customize settings
- [Specs and Tasks](../02-core-concepts/01-specs-and-tasks.md) - Write better task specs
- [Hooks System](../05-hooks-system/README.md) - Customize execution

## What You Learned

You just:
1. ✅ Installed Agent Arborist
2. ✅ Initialized a project
3. ✅ Configured an AI runner
4. ✅ Wrote a task specification
5. ✅ Generated a workflow DAG
6. ✅ Created Git branches and worktrees
7. ✅ Executed a complete AI-driven workflow
8. ✅ Viewed AI-generated code

**Congratulations!** You've just run your first end-to-end AI workflow with Agent Arborist.

Now try building something more complex, or dive into the documentation to customize your workflows.