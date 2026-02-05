# Agent Arborist: Jujutsu Migration Plan

## Executive Summary

This document outlines a comprehensive plan to migrate Agent Arborist from Git to [Jujutsu (jj)](https://github.com/jj-vcs/jj), a Git-compatible version control system that fundamentally reimagines how parallel development workflows operate. The migration promises to eliminate significant complexity in our current architecture while enabling more powerful concurrent task execution.

**Key Insight**: Agent Arborist's current architecture fights against Git's design constraints. We use worktrees, filesystem locks, and explicit branch naming to achieve isolation and parallelism that Jujutsu provides natively.

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Detailed Walkthrough: 5-Task Example](#detailed-walkthrough-5-task-example-with-devcontainer-isolation)
   - Current Git + Worktrees + Devcontainers implementation
   - Generated DAGU YAML
   - The Jujutsu Alternative (preview)
3. [Part 1: Current Architecture Analysis](#part-1-current-architecture-analysis)
   - Git branch hierarchy
   - Worktree isolation
   - Problems being solved
4. [Part 2: What Jujutsu Offers](#part-2-what-jujutsu-offers)
   - Working copy as commit
   - Automatic rebasing
   - Conflicts as first-class citizens
   - Operation log & undo
   - Revsets query language
5. [Part 3: The Jujutsu Way](#part-3-the-jujutsu-way)
   - Philosophy: Changes over branches
   - Patterns for parallel task execution
6. [Part 3.5: Advanced DAG Patterns & Execution](#part-35-advanced-dag-patterns--execution)
   - Ragged hierarchies & nested subtrees
   - Peer dependencies
   - Incremental conflict resolution
   - Change propagation mechanism
   - Complete execution flow (10 phases)
   - Workspace isolation with Jujutsu
   - **AI Agent Calls: Git vs Jujutsu comparison**
7. [Part 4: Migration Architecture](#part-4-migration-architecture)
   - New system design
   - Component mapping
   - `jj_tasks.py` module
   - Devcontainer integration
8. [Part 5: Migration Plan](#part-5-migration-plan)
   - Phase 0: Preparation
   - Phase 1: Parallel implementation
   - Phase 2: Feature parity testing
   - Phase 3: Advanced features
   - Phase 4: Deprecation
   - Phase 5: New capabilities
9. [Part 6: Detailed Technical Design](#part-6-detailed-technical-design)
   - Task lifecycle: Git vs Jujutsu
   - DAG structure changes
   - Revset queries for task management
   - Error handling & recovery
10. [Part 7: What Jujutsu Is Really Good At](#part-7-what-jujutsu-is-really-good-at)
    - Key insights (5)
11. [Part 8: The Jujutsu-Native Architecture](#part-8-the-jujutsu-native-architecture)
    - Vision: Changes as universal abstraction
    - New CLI commands
    - Estimated code reduction
12. [Part 9: Risk Assessment](#part-9-risk-assessment)
13. [Part 10: Success Metrics](#part-10-success-metrics)
14. [Sources](#sources)
15. [Appendices](#appendix-a-command-mapping)
    - A: Command mapping (git → jj)
    - B: Revset cheat sheet
    - C: Migration checklist

---

## Detailed Walkthrough: 5-Task Example with Devcontainer Isolation

This section traces through a concrete example with 5 tasks to show exactly how devcontainer isolation works.

### Task Structure

```
T001 (root, sequential)
    └── runs, then T002 starts

T002 (root, parent of parallel children)
    ├── T003 (parallel child)
    ├── T004 (parallel child)
    └── T005 (parallel child)
```

### Current Implementation: Git + Worktrees + Devcontainers

#### Phase 0: Setup (branches-setup step)

```
DAGU ROOT DAG STARTS
│
├── branches-setup
│   │
│   │   # Create all branches from manifest (topological order)
│   │   git branch main_a main                    # base branch
│   │   git branch main_a_T001 main_a             # T001 branch
│   │   git branch main_a_T002 main_a             # T002 branch
│   │   git branch main_a_T002_T003 main_a_T002   # T003 (child of T002)
│   │   git branch main_a_T002_T004 main_a_T002   # T004 (child of T002)
│   │   git branch main_a_T002_T005 main_a_T002   # T005 (child of T002)
│   │
│   └── ✓ All 6 branches created
│
├── merge-container-up  (if container_mode != disabled)
│   │
│   │   # Start a single "merge container" at git root for all post-merge ops
│   │   devcontainer up --workspace-folder /path/to/repo
│   │
│   └── ✓ Merge container running (mounts entire repo)
│
└── CALL T001 subdag ──────────────────────────────────────────────────►
```

#### Phase 1: T001 Execution (Leaf Task Subdag)

```
T001 SUBDAG
│
├── pre-sync (runs on HOST)
│   │
│   │   # Create worktree for T001's branch
│   │   mkdir -p .arborist/worktrees/spec-123/T001
│   │   git worktree add .arborist/worktrees/spec-123/T001 main_a_T001
│   │
│   │   # Sync with parent branch
│   │   cd .arborist/worktrees/spec-123/T001
│   │   git merge main_a --no-edit
│   │
│   │   # Copy credentials
│   │   cp .devcontainer/.env → worktree/.devcontainer/.env
│   │
│   └── ✓ Worktree ready at .arborist/worktrees/spec-123/T001
│
├── container-up (if container_mode enabled)
│   │
│   │   # Start devcontainer for THIS worktree (isolated from others)
│   │   devcontainer up --workspace-folder .arborist/worktrees/spec-123/T001
│   │
│   │   # Container now running with:
│   │   #   - Mount: .arborist/worktrees/spec-123/T001 → /workspace
│   │   #   - .env loaded (API keys, etc)
│   │   #   - Docker-in-Docker available
│   │
│   └── ✓ T001 container running (ISOLATED filesystem)
│
├── run
│   │
│   │   # Execute AI runner INSIDE the container
│   │   devcontainer exec \
│   │     --workspace-folder .arborist/worktrees/spec-123/T001 \
│   │     arborist task run T001
│   │
│   │   # Inside container, arborist invokes the AI runner:
│   │   #   claude --task "implement feature X" --cwd /workspace
│   │
│   │   # AI writes files to /workspace (= T001 worktree on host)
│   │
│   └── ✓ Code written to T001 worktree
│
├── commit
│   │
│   │   # Commit changes in worktree
│   │   cd .arborist/worktrees/spec-123/T001
│   │   git add -A
│   │   git commit -m "T001: implement feature X"
│   │
│   └── ✓ Changes committed to main_a_T001 branch
│
├── run-test
│   │
│   │   # Run tests INSIDE container
│   │   devcontainer exec \
│   │     --workspace-folder .arborist/worktrees/spec-123/T001 \
│   │     pytest
│   │
│   └── ✓ Tests pass
│
├── post-merge
│   │
│   │   # Acquire lock (atomic directory creation)
│   │   mkdir .arborist/locks/spec-123/merge_{hash(main_a)}
│   │   # If exists → LockBusyError → DAGU retries in 60s
│   │
│   │   # Merge T001 into base branch (main_a)
│   │   # Uses merge container (already running at git root)
│   │   devcontainer exec --workspace-folder /path/to/repo \
│   │     bash -c "cd /workspace && git checkout main_a && git merge main_a_T001"
│   │
│   │   # Release lock
│   │   rmdir .arborist/locks/spec-123/merge_{hash}
│   │
│   └── ✓ T001 merged into main_a
│
├── container-down
│   │
│   │   # Stop T001's container (but not the merge container)
│   │   docker stop $(docker ps -q --filter label=devcontainer.local_folder=".arborist/worktrees/spec-123/T001")
│   │
│   └── ✓ T001 container stopped
│
└── (T001 subdag complete) ──────────────────────────────────────────►
```

#### Phase 2: T002 Execution (Parent Task with Children)

```
T002 SUBDAG (depends on T001)
│
├── pre-sync
│   │
│   │   # Create worktree for T002
│   │   git worktree add .arborist/worktrees/spec-123/T002 main_a_T002
│   │   cd .arborist/worktrees/spec-123/T002
│   │   git merge main_a --no-edit   # Gets T001's changes!
│   │
│   │   # T002 worktree stays checked out while children run
│   │   # This is the "long-lived parent worktree" pattern
│   │
│   └── ✓ T002 worktree ready (includes T001 changes)
│
│   ┌────────────────────────────────────────────────────────────────┐
│   │              PARALLEL CHILD EXECUTION                          │
│   │                                                                │
│   │   T003, T004, T005 all depend on pre-sync                      │
│   │   They run IN PARALLEL (no dependencies between them)          │
│   └────────────────────────────────────────────────────────────────┘
│
├── c-T003 ─────────────────┐
├── c-T004 ─────────────────┼─── (PARALLEL - all start simultaneously)
├── c-T005 ─────────────────┘
│
│   Each child subdag:
│
│   T003 SUBDAG                    T004 SUBDAG                    T005 SUBDAG
│   │                              │                              │
│   ├── pre-sync                   ├── pre-sync                   ├── pre-sync
│   │   git worktree add           │   git worktree add           │   git worktree add
│   │   .../T003 main_a_T002_T003  │   .../T004 main_a_T002_T004  │   .../T005 main_a_T002_T005
│   │   git merge main_a_T002      │   git merge main_a_T002      │   git merge main_a_T002
│   │                              │                              │
│   ├── container-up               ├── container-up               ├── container-up
│   │   devcontainer up            │   devcontainer up            │   devcontainer up
│   │   (SEPARATE container)       │   (SEPARATE container)       │   (SEPARATE container)
│   │                              │                              │
│   ├── run                        ├── run                        ├── run
│   │   claude "do T003"           │   claude "do T004"           │   claude "do T005"
│   │   (writes to /workspace)     │   (writes to /workspace)     │   (writes to /workspace)
│   │                              │                              │
│   ├── commit                     ├── commit                     ├── commit
│   │                              │                              │
│   ├── run-test                   ├── run-test                   ├── run-test
│   │                              │                              │
│   ├── post-merge ◄───────────────┼───────────────────────────────┼─── SERIALIZED
│   │   │                          │   │                          │   │  via locks!
│   │   │ Lock: merge_{hash(T002)} │   │ (waits for T003 lock)    │   │
│   │   │ Merge T003 → T002        │   │ Merge T004 → T002        │   │
│   │   │ (uses T002's worktree)   │   │                          │   │
│   │   │                          │   │                          │   │
│   │                              │                              │
│   ├── container-down             ├── container-down             ├── container-down
│   │                              │                              │
│   └── complete                   └── complete                   └── complete
│
│   ┌────────────────────────────────────────────────────────────────┐
│   │              ALL CHILDREN COMPLETE                             │
│   └────────────────────────────────────────────────────────────────┘
│
├── run-test (depends on all c-T00X)
│   │
│   │   # Run integration tests in T002 worktree
│   │   # Now contains: T001 base + T003 + T004 + T005 merged
│   │   cd .arborist/worktrees/spec-123/T002
│   │   pytest
│   │
│   └── ✓ Integration tests pass
│
├── post-merge
│   │
│   │   # Lock main_a
│   │   mkdir .arborist/locks/spec-123/merge_{hash(main_a)}
│   │
│   │   # Merge T002 (with all children's work) into main_a
│   │   git checkout main_a
│   │   git merge main_a_T002
│   │
│   │   # Release lock
│   │
│   └── ✓ All work merged to main_a
│
├── post-cleanup
│   │
│   │   # Now safe to remove T002 worktree
│   │   git worktree remove .arborist/worktrees/spec-123/T002 --force
│   │
│   └── ✓ Cleanup complete
│
└── (T002 subdag complete)
```

#### Filesystem State During Parallel Execution

```
.arborist/
├── worktrees/
│   └── spec-123/
│       ├── T002/                  # LONG-LIVED (parent stays checked out)
│       │   ├── .git (file)        #   Children merge INTO this
│       │   ├── src/
│       │   └── ...
│       │
│       ├── T003/                  # Parallel child 1
│       │   ├── .git (file)        #   Isolated container mounts this
│       │   └── ...
│       │
│       ├── T004/                  # Parallel child 2
│       │   └── ...                #   Isolated container mounts this
│       │
│       └── T005/                  # Parallel child 3
│           └── ...                #   Isolated container mounts this
│
├── locks/
│   └── spec-123/
│       └── merge_{hash}/          # Only ONE merge at a time
│           └── meta.json
│
└── dagu/
    └── dags/
        └── spec-123.yaml
```

#### Container Isolation Visualized

```
┌──────────────────────────────────────────────────────────────────────┐
│                              HOST                                     │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐      │
│  │  T003 Container │  │  T004 Container │  │  T005 Container │      │
│  │                 │  │                 │  │                 │      │
│  │  /workspace ────┼──┼─► worktree/T003 │  │                 │      │
│  │  (isolated)     │  │  /workspace ────┼──┼─► worktree/T004 │      │
│  │                 │  │  (isolated)     │  │  /workspace ────┼──►...│
│  │  claude runs    │  │                 │  │  (isolated)     │      │
│  │  here           │  │  claude runs    │  │                 │      │
│  │                 │  │  here           │  │  claude runs    │      │
│  └─────────────────┘  └─────────────────┘  │  here           │      │
│                                            └─────────────────┘      │
│  Each container:                                                     │
│  - Has its own /workspace (separate worktree)                       │
│  - Has its own pip/npm packages                                     │
│  - Cannot see other containers' filesystems                         │
│  - Can run Docker (docker-in-docker)                                │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    Merge Container                             │   │
│  │                                                                │   │
│  │  /workspace ─────────────────────────────► git root            │   │
│  │  (entire repo mounted)                                         │   │
│  │                                                                │   │
│  │  All post-merge ops happen here:                               │   │
│  │  - git checkout <parent>                                       │   │
│  │  - git merge <child>                                           │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

### Why This Design is Necessary (Git's Limitations)

```
PROBLEM 1: "Branch already checked out"
─────────────────────────────────────────
  T002 worktree has main_a_T002 checked out.
  T003 wants to merge INTO main_a_T002.

  Git error: "fatal: 'main_a_T002' is already checked out"

  SOLUTION: T002 worktree stays long-lived.
            T003 merges into it (branch already checked out = OK)
            OR uses a temporary merge worktree

PROBLEM 2: Parallel merges corrupt state
─────────────────────────────────────────
  T003 and T004 both want to merge into T002 simultaneously.

  Without coordination:
    T003: git checkout main_a_T002
    T004: git checkout main_a_T002  ← RACE!
    T003: git merge T003
    T004: git merge T004           ← Overwrites T003's merge!

  SOLUTION: Filesystem locks serialize merges
            mkdir is atomic across processes

PROBLEM 3: Need isolated execution environments
─────────────────────────────────────────
  T003 AI might install packages that break T004.
  T003's test server might use same port as T004's.

  SOLUTION: Separate devcontainers per worktree
            Each has isolated filesystem, network, processes
```

### Generated DAGU YAML for This Example

```yaml
# Root DAG
name: spec-123
env:
  - ARBORIST_SPEC_ID=spec-123
  - ARBORIST_CONTAINER_MODE=auto
steps:
  - name: branches-setup
    command: arborist spec branch-create-all

  - name: merge-container-up
    command: arborist spec merge-container-up
    depends: [branches-setup]

  - name: c-T001
    call: T001
    depends: [merge-container-up]

  - name: c-T002
    call: T002
    depends: [c-T001]           # T002 waits for T001 to complete

---
# T001 Subdag (leaf)
name: T001
env:
  - ARBORIST_TASK_ID=T001
steps:
  - name: pre-sync
    command: arborist task pre-sync T001

  - name: container-up
    command: arborist task container-up T001
    depends: [pre-sync]

  - name: run
    command: arborist task run T001
    depends: [container-up]

  - name: commit
    command: arborist task commit T001
    depends: [run]

  - name: run-test
    command: arborist task run-test T001
    depends: [commit]

  - name: post-merge
    command: arborist task post-merge T001
    depends: [run-test]
    retryPolicy: {limit: 60, intervalSec: 60}

  - name: container-down
    command: arborist task container-stop T001
    depends: [post-merge]

---
# T002 Subdag (parent)
name: T002
env:
  - ARBORIST_TASK_ID=T002
steps:
  - name: pre-sync
    command: arborist task pre-sync T002

  - name: c-T003
    call: T003
    depends: [pre-sync]         # All children depend on pre-sync

  - name: c-T004
    call: T004
    depends: [pre-sync]         # PARALLEL - same dependency

  - name: c-T005
    call: T005
    depends: [pre-sync]         # PARALLEL - same dependency

  - name: run-test
    command: arborist task run-test T002
    depends: [c-T003, c-T004, c-T005]  # Wait for ALL children

  - name: post-merge
    command: arborist task post-merge T002
    depends: [run-test]
    retryPolicy: {limit: 60, intervalSec: 60}

  - name: post-cleanup
    command: arborist task post-cleanup T002
    depends: [post-merge]

---
# T003 Subdag (leaf, child of T002)
name: T003
env:
  - ARBORIST_TASK_ID=T003
steps:
  - name: pre-sync
    command: arborist task pre-sync T003

  - name: container-up
    command: arborist task container-up T003
    depends: [pre-sync]

  - name: run
    command: arborist task run T003
    depends: [container-up]

  - name: commit
    command: arborist task commit T003
    depends: [run]

  - name: run-test
    command: arborist task run-test T003
    depends: [commit]

  - name: post-merge
    command: arborist task post-merge T003   # Merges to T002, not main_a!
    depends: [run-test]
    retryPolicy: {limit: 60, intervalSec: 60}

  - name: container-down
    command: arborist task container-stop T003
    depends: [post-merge]

# T004 and T005 subdags are identical structure to T003
```

### The Jujutsu Alternative (Preview)

With Jujutsu, this entire complexity collapses:

```bash
# Setup: Create changes (no worktrees needed)
jj new main -m "spec:123:T001"           # T001 change
jj new main -m "spec:123:T002"           # T002 change (parallel to T001 in jj)
jj new T002_change -m "spec:123:T003"    # T003 child of T002
jj new T002_change -m "spec:123:T004"    # T004 child of T002
jj new T002_change -m "spec:123:T005"    # T005 child of T002

# Execute T003 (just switch context, run AI)
jj edit T003_change
# AI runs, files change, automatically tracked
jj describe -m "spec:123:T003 [DONE]"

# "Merge" = squash into parent
jj squash --from T003_change --into T002_change
# Automatic! No locks needed - operation is atomic

# T004 and T005 do the same (can run in parallel)
# When T004 squashes, T002 auto-rebases any conflicts
```

No worktrees. No filesystem locks. No retry loops. No complex branch naming.

The devcontainer isolation remains valuable (for test isolation), but git complexity vanishes.

---

## Part 1: Current Architecture Analysis

### How Agent Arborist Works Today

Agent Arborist orchestrates parallel AI task execution using a sophisticated system built on top of Git:

```
┌─────────────────────────────────────────────────────────────────┐
│                        DAGU Orchestrator                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   ┌─────────┐     ┌─────────┐     ┌─────────┐                  │
│   │  T001   │     │  T002   │     │  T003   │   Root Tasks     │
│   │ worktree│     │ worktree│     │ worktree│   (sequential)   │
│   └────┬────┘     └─────────┘     └─────────┘                  │
│        │                                                        │
│   ┌────┴────────────────┐                                      │
│   │    T001 Children    │                                      │
│   │  ┌─────┐ ┌─────┐   │   Child Tasks (parallel)              │
│   │  │T004 │ │T005 │   │                                       │
│   │  └──┬──┘ └──┬──┘   │                                       │
│   │     │       │      │                                       │
│   │     └───┬───┘      │   Merge back to T001                  │
│   │         ▼          │   (serialized via locks)              │
│   │    [T001 branch]   │                                       │
│   └────────────────────┘                                       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### Git Branch Hierarchy

We use an elaborate naming scheme to encode task relationships:

```
main                           # Source branch
main_a                         # Base integration branch
main_a_T001                    # Root task 1
main_a_T001_T004               # Child of T001
main_a_T001_T005               # Child of T001
main_a_T002                    # Root task 2
```

#### Worktree Isolation

Each task gets its own worktree for isolation:

```
.arborist/
├── worktrees/
│   └── spec-123/
│       ├── T001/              # Task worktree
│       ├── T002/              # Task worktree
│       ├── T004/              # Child worktree
│       └── _merge/            # Temporary merge worktrees
│           └── {branch-hash}/
└── locks/
    └── spec-123/
        └── merge_{hash}/      # Filesystem locks
```

#### The Problems We're Solving Around

| Problem | Current Solution | Complexity Cost |
|---------|------------------|-----------------|
| Branch already checked out | Worktrees | ~200 LOC in git_tasks.py |
| Parallel merges conflict | Filesystem locks + retries | 60 attempts × 60s waits |
| Branch name collisions | Deterministic naming scheme | Branch manifest system |
| Tracking task state | Branch existence + worktree detection | Complex state inference |
| Rollback on failure | Manual git operations | No automatic recovery |

#### Key Files in Current Architecture

- `git_tasks.py` (664 lines): Branch/worktree/merge operations
- `branch_manifest.py` (150 lines): Pre-computed branch naming
- `dag_builder.py` (300 lines): DAGU step generation with retry logic
- `container_runner.py` (150 lines): Devcontainer wrapping

**Total complexity devoted to Git workarounds: ~1,200+ lines**

---

## Part 2: What Jujutsu Offers

### Core Philosophy Shift

> "Git's data model treats commits as immutable snapshots requiring branches for work-in-progress. Jujutsu treats changes as mutable, first-class entities that can evolve until published."

### Key Capabilities

#### 1. Working Copy Is a Commit

```bash
# Git way
vim file.txt
git add file.txt
git commit -m "changes"

# Jujutsu way
vim file.txt
# That's it. The working copy IS a commit, automatically amended.
jj describe -m "changes"  # Add message when ready
```

**Implication**: No staging area complexity. Every filesystem change is tracked.

#### 2. Automatic Rebasing

```bash
# Edit a commit from 3 commits ago
jj edit qpvuntsm

# Make changes...

# Return to tip
jj new

# ALL descendants were automatically rebased onto your changes
```

**Implication**: Fix a bug in a parent task, all child tasks automatically incorporate the fix.

#### 3. Conflicts as First-Class Citizens

```bash
# In Git: conflicts BLOCK all operations
git merge feature  # CONFLICT! Can't commit, can't switch, stuck.

# In Jujutsu: conflicts are recorded IN the commit
jj rebase -d main  # Conflict recorded. Work continues.
jj new             # Create child commit on top of conflicted parent
jj edit qpvuntsm   # Come back later to resolve
```

**Implication**: Parallel tasks can proceed even when conflicts exist. Resolution can be deferred.

#### 4. Operation Log & Undo

```bash
jj op log          # See every operation ever performed
jj undo            # Undo last operation
jj op restore xyz  # Restore to any previous state
```

**Implication**: Safe experimentation. Any mistake is recoverable.

#### 5. Revsets: A Query Language for Commits

```bash
# Select all my work not yet on main
jj log -r 'mine() & mutable()'

# Find all descendants of a change
jj log -r 'qpvuntsm::'

# Select commits touching specific files
jj log -r 'files("src/*.py")'

# Complex queries
jj log -r 'author("agent") & ancestors(@) & description("T001")'
```

**Implication**: Replace branch manifests with dynamic queries.

#### 6. Anonymous Branches

```bash
# Creating parallel work doesn't require naming
jj new main -m "feature A"
# ... work ...
jj new main -m "feature B"
# Two parallel lines of development, no branch names needed

# Name them only when publishing
jj bookmark create feature-a -r qpvuntsm
```

**Implication**: Eliminate branch naming complexity entirely.

#### 7. Multiple Parent Merges

```bash
# Create a commit with multiple parents (mega-merge)
jj new task1 task2 task3 -m "dev workspace"

# All three tasks' code is now active in working copy
# Make changes, then distribute back:
jj squash --into task1  # Move relevant changes to task1
```

**Implication**: Work on all parallel tasks simultaneously in one workspace.

---

## Part 3: The Jujutsu Way

### Philosophy: Changes Over Branches

The fundamental shift is from **branch-centric** to **change-centric** thinking:

| Git Mental Model | Jujutsu Mental Model |
|------------------|---------------------|
| Branch = line of work | Change = unit of work |
| Create branch before work | Work creates changes implicitly |
| Commit when ready | Working copy is always a commit |
| Merge branches | Rebase/squash changes |
| Track via branch names | Track via change IDs + revsets |

### The DAG Is the Truth

In Jujutsu, the commit DAG itself encodes all relationships:

```
○  zzzzzzzz  (empty) - working copy
│
○  rrrrrrrr  "Task T003 implementation"
│
│ ○  qqqqqqqq  "Task T002 implementation"
│ │
○ │  pppppppp  "Task T001 child T005"
│ │
○ │  oooooooo  "Task T001 child T004"
├─╯
○  nnnnnnnn  "Task T001 base"
│
◆  main
```

No branch names needed. The structure tells the story.

### Patterns for Parallel Task Execution

#### Pattern 1: Task as Change

Instead of creating a branch for each task, create a change:

```bash
# Old way (git)
git checkout -b main_a_T001 main
git worktree add .arborist/worktrees/spec/T001 main_a_T001

# Jujutsu way
jj new main -m "spec:T001 - Implement feature X"
# That's it. Change ID is the identifier.
```

#### Pattern 2: Parent Tasks with Children

```bash
# Create parent task change
jj new main -m "spec:T001 - Parent task"
PARENT=$(jj log -r @ --no-graph -T 'change_id')

# Create children (parallel)
jj new $PARENT -m "spec:T001:T004 - Child task 1"
jj new $PARENT -m "spec:T001:T005 - Child task 2"

# Children are now parallel descendants of parent
# No worktrees, no branch names
```

#### Pattern 3: Mega-Merge Development Workspace

For testing all parallel work together:

```bash
# Create merge of all active task changes
jj new T001 T002 T003 -m "dev: integration testing"

# Run tests against combined state
# No conflicts block this - they're recorded if they exist
```

#### Pattern 4: Task Discovery via Revsets

```bash
# Find all tasks for a spec
jj log -r 'description("spec:ABC123")'

# Find incomplete tasks (have no descendants on main)
jj log -r 'description("spec:") & mutable() & ~ancestors(main)'

# Find tasks with conflicts
jj log -r 'description("spec:") & conflicts()'
```

#### Pattern 5: Atomic Operations

```bash
# All jj operations are atomic
# If something fails, operation log lets you recover

jj op log
# xyz  2024-01-15 10:30  rebase 5 commits
# wvu  2024-01-15 10:25  new commit

jj op restore wvu  # Roll back the failed rebase
```

---

## Part 3.5: Advanced DAG Patterns & Execution

This section addresses complex real-world scenarios: ragged hierarchies, peer dependencies, incremental conflict resolution, and how changes propagate through the DAG.

### Ragged Hierarchies & Nested Subtrees

Real task trees aren't flat. Consider this structure:

```
T001 (depth 1)
├── T002 (depth 2)
│   ├── T005 (depth 3)
│   │   └── T008 (depth 4!)
│   └── T006 (depth 3)
├── T003 (depth 2)
│   └── T007 (depth 3)
└── T004 (depth 2)
```

**Git approach**: Complex branch naming encodes depth
```
main_a_T001
main_a_T001_T002
main_a_T001_T002_T005
main_a_T001_T002_T005_T008  # Gets unwieldy
```

**Jujutsu approach**: The DAG IS the hierarchy
```
○ T008
│
○ T005    ○ T006
├─────────╯
○ T002    ○ T007
│         │
│         ○ T003    ○ T004
├─────────┴─────────╯
○ T001
│
◆ main
```

No naming scheme needed. Arbitrary depth supported natively. The change DAG directly represents the task DAG.

#### Creating Deep Hierarchies

```bash
# Create the tree structure with changes
jj new main -m "spec:X:T001"
T001=$(jj log -r @ -T change_id --no-graph)

jj new $T001 -m "spec:X:T002"
T002=$(jj log -r @ -T change_id --no-graph)

jj new $T001 -m "spec:X:T003"
T003=$(jj log -r @ -T change_id --no-graph)

jj new $T001 -m "spec:X:T004"

jj new $T002 -m "spec:X:T005"
T005=$(jj log -r @ -T change_id --no-graph)

jj new $T002 -m "spec:X:T006"

jj new $T003 -m "spec:X:T007"

jj new $T005 -m "spec:X:T008"  # Depth 4!

# Query any level with revsets
jj log -r 'descendants($T001) & description("spec:X:")'
```

### Peer Dependencies

What happens when sibling tasks depend on each other?

```
T002 (parent)
├── T003: "Build the API"
├── T004: "Build the client" ◄── NEEDS T003's API!
└── T005: "Write docs" ◄── NEEDS both!
```

#### The Problem: Static vs Dynamic Snapshots

**Git (static)**: All children branch from parent at time=0
```
Timeline:
  t=0: Create main_a_T002_T003, main_a_T002_T004, main_a_T002_T005
       All three have IDENTICAL code (snapshot of T002)

  t=1: T003 completes, writes API code
       BUT T004's branch still has t=0 snapshot!
       T004 cannot see T003's API.

  t=2: T004 runs, cannot import the API
       Either fails, or writes incompatible code

  t=3: Merge conflicts when T003 and T004 merge to T002
```

**Jujutsu (dynamic)**: Children can rebase to get sibling's work
```
Timeline:
  t=0: Create T003, T004, T005 as children of T002
       All reference T002 (not frozen snapshot)

  t=1: T003 completes → squash into T002
       T002 now contains T003's API code

  t=2: T004 starts:
       jj rebase -d $T002  # Rebase onto UPDATED T002
       T004 now has T003's API code!

  t=3: T004 runs, imports and uses the API
       Clean integration, no conflicts
```

#### DAG Structure for Peer Dependencies

```yaml
# spec.yaml with peer dependencies
tasks:
  - id: T002
    children:
      - id: T003
        description: "Build API"

      - id: T004
        description: "Build client"
        depends_on: [T003]  # ◄── PEER DEPENDENCY

      - id: T005
        description: "Write docs"
        depends_on: [T003, T004]  # ◄── MULTIPLE PEERS
```

#### Generated DAGU DAG with Sync Steps

```yaml
name: T002
env:
  - ARBORIST_SPEC_ID=spec-X
  - T002_CHANGE=${T002_CHANGE_ID}
steps:
  # Setup parent workspace
  - name: pre-sync
    command: arborist jj pre-sync T002

  # T003 has no peer dependencies - can start immediately
  - name: c-T003
    call: T003
    depends: [pre-sync]

  # SYNC STEP: After T003, integrate its work into T002
  - name: sync-after-T003
    command: arborist jj sync-parent T002
    depends: [c-T003]

  # T004 depends on T003 - starts after sync
  - name: c-T004
    call: T004
    depends: [sync-after-T003]  # Gets T003's work via rebase

  # SYNC STEP: After T004, integrate its work
  - name: sync-after-T004
    command: arborist jj sync-parent T002
    depends: [c-T004]

  # T005 depends on both - starts after both synced
  - name: c-T005
    call: T005
    depends: [sync-after-T004]  # Gets T003+T004's work

  # Final sync and tests
  - name: sync-final
    command: arborist jj sync-parent T002
    depends: [c-T005]

  - name: run-test
    command: arborist jj run-test T002
    depends: [sync-final]

  - name: complete
    command: arborist jj complete T002
    depends: [run-test]
```

#### Child Task Pre-Sync with Rebase

```yaml
# T004.yaml - child that depends on T003
name: T004
env:
  - T004_CHANGE=${T004_CHANGE_ID}
  - PARENT_CHANGE=${T002_CHANGE_ID}
steps:
  - name: pre-sync
    command: |
      # Switch to T004's workspace
      cd ${WORKSPACE_T004}

      # CRITICAL: Rebase onto parent to get T003's work
      jj rebase -d ${PARENT_CHANGE}

      # Now T004 has T003's API code available

  - name: container-up
    command: arborist jj container-up T004
    depends: [pre-sync]

  - name: run
    command: arborist jj run T004  # Can now use T003's API
    depends: [container-up]

  # ... rest of steps
```

### Incremental Conflict Resolution

Instead of batching all conflicts to the end, resolve as each child completes.

#### Batch Resolution (Bad)

```
T003 completes ───┐
T004 completes ───┼──► ALL merge at end ──► CONFLICT EXPLOSION
T005 completes ───┘
                       T003 vs T004 vs T005 all at once
                       Hard to understand, hard to fix
```

#### Incremental Resolution (Good)

```
T003 completes ──► squash ──► resolve T003 conflicts (small, focused)
                     │
                     ▼
               T002 clean
                     │
T004 completes ──► squash ──► resolve T004 conflicts (only T004 vs T002+T003)
                     │
                     ▼
               T002 clean
                     │
T005 completes ──► squash ──► resolve T005 conflicts (only T005 vs rest)
                     │
                     ▼
               T002 fully integrated
```

#### The Sync-Parent Command

```bash
#!/bin/bash
# arborist jj sync-parent T002
#
# Called after each child completes to:
# 1. Check for conflicts in parent
# 2. Resolve them immediately
# 3. Rebase remaining children onto clean parent

PARENT_CHANGE=$1
SPEC_ID=$ARBORIST_SPEC_ID

# Check if parent has conflicts after child squashed
CONFLICTS=$(jj log -r "$PARENT_CHANGE & conflicts()" --no-graph -T 'change_id')

if [ -n "$CONFLICTS" ]; then
    echo "Conflicts detected in $PARENT_CHANGE, resolving..."

    # Switch to parent
    jj edit $PARENT_CHANGE

    # Option A: Automatic resolution (AI-assisted)
    if [ "$AUTO_RESOLVE" = "true" ]; then
        arborist ai resolve-conflicts --change $PARENT_CHANGE
    fi

    # Option B: Mark for human review but continue
    if [ "$CONFLICTS_BLOCK" != "true" ]; then
        jj describe -m "$(jj log -r @ -T description) [NEEDS_RESOLUTION]"
        echo "Conflicts marked for later resolution, continuing..."
    else
        echo "Conflicts require resolution before continuing"
        exit 1
    fi
fi

# Rebase any pending children onto the (possibly updated) parent
# This propagates T003's resolved work to T004, T005, etc.
PENDING_CHILDREN=$(jj log -r "children($PARENT_CHANGE) & mutable() & ~description('[DONE]')" --no-graph -T 'change_id ++ "\n"')

for CHILD in $PENDING_CHILDREN; do
    echo "Rebasing $CHILD onto updated parent..."
    jj rebase -r $CHILD -d $PARENT_CHANGE
done

echo "Sync complete"
```

### Change Propagation Mechanism

How do downstream tasks pick up upstream changes?

#### The Rebase Chain

```
BEFORE T003 completes:

○ T005 (based on T002 v1)
│
○ T004 (based on T002 v1)
│
○ T003 (based on T002 v1)
│
○ T002 v1
│
◆ main


AFTER T003 squashes into T002:

○ T005 (based on T002 v1) ◄── STALE!
│
○ T004 (based on T002 v1) ◄── STALE!
│
○ T002 v2 (contains T003's work)
│
◆ main


AFTER sync-parent rebases children:

○ T005 (based on T002 v2) ◄── FRESH!
│
○ T004 (based on T002 v2) ◄── FRESH!
│
○ T002 v2 (contains T003's work)
│
◆ main
```

#### Automatic vs Manual Propagation

**Jujutsu auto-rebase** (when editing ancestors):
```bash
# If you edit T002 directly, descendants auto-rebase
jj edit $T002
# ... make changes ...
jj new  # Return to working on something else

# T004, T005 automatically rebased onto new T002
# This is jj's killer feature
```

**Manual rebase** (when squashing from sibling):
```bash
# Squash doesn't trigger auto-rebase of siblings' descendants
jj squash --from $T003 --into $T002

# Must manually rebase siblings
jj rebase -r $T004 -d $T002
jj rebase -r $T005 -d $T002
```

The sync-parent step handles this manual rebase.

### Complete Execution Flow: 5-Task Example with Dependencies

```
Task Structure:
  T001 (sequential, no deps)
  T002 (parent)
    ├── T003 (no peer deps)
    ├── T004 (depends on T003)
    └── T005 (depends on T003, T004)
```

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           EXECUTION TIMELINE                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  PHASE 1: Setup                                                         │
│  ─────────────────                                                      │
│  │                                                                      │
│  ├── Create all changes (jj new)                                        │
│  │     T001 ← main                                                      │
│  │     T002 ← main                                                      │
│  │     T003 ← T002                                                      │
│  │     T004 ← T002                                                      │
│  │     T005 ← T002                                                      │
│  │                                                                      │
│  ├── Create workspaces for parallel execution                           │
│  │     jj workspace add .arborist/ws/T003                               │
│  │     jj workspace add .arborist/ws/T004                               │
│  │     jj workspace add .arborist/ws/T005                               │
│  │                                                                      │
│  └── Record change IDs in environment                                   │
│                                                                         │
│  PHASE 2: T001 Execution                                                │
│  ────────────────────────                                               │
│  │                                                                      │
│  ├── jj edit $T001                                                      │
│  ├── devcontainer up (main workspace)                                   │
│  ├── AI executes T001 task                                              │
│  ├── jj squash --into main                                              │
│  └── T001 complete ✓                                                    │
│                                                                         │
│  PHASE 3: T002 Pre-sync                                                 │
│  ───────────────────────                                                │
│  │                                                                      │
│  ├── jj edit $T002                                                      │
│  ├── jj rebase -d main  # Get T001's changes                            │
│  └── T002 workspace ready with T001's code                              │
│                                                                         │
│  PHASE 4: T003 Execution (First Child)                                  │
│  ──────────────────────────────────────                                 │
│  │                                                                      │
│  ├── cd .arborist/ws/T003                                               │
│  ├── jj edit $T003                                                      │
│  ├── jj rebase -d $T002  # Sync with parent                             │
│  ├── devcontainer up (T003 workspace)                                   │
│  ├── AI executes T003: "Build the API"                                  │
│  │     └── Creates src/api.py, src/models.py                            │
│  ├── devcontainer down                                                  │
│  ├── jj describe -m "spec:X:T003 [DONE]"                                │
│  └── jj squash --into $T002  # Merge T003 → T002                        │
│                                                                         │
│  PHASE 5: Sync After T003                                               │
│  ────────────────────────                                               │
│  │                                                                      │
│  ├── Check T002 for conflicts: jj log -r "$T002 & conflicts()"          │
│  │     └── None (T003 was first, clean merge)                           │
│  ├── Rebase pending children onto T002:                                 │
│  │     jj rebase -r $T004 -d $T002  # T004 now has T003's API!          │
│  │     jj rebase -r $T005 -d $T002  # T005 now has T003's API!          │
│  └── Sync complete ✓                                                    │
│                                                                         │
│  PHASE 6: T004 Execution (Depends on T003)                              │
│  ──────────────────────────────────────────                             │
│  │                                                                      │
│  ├── cd .arborist/ws/T004                                               │
│  ├── jj edit $T004                                                      │
│  ├── (already rebased in Phase 5 - has T003's API)                      │
│  ├── devcontainer up (T004 workspace)                                   │
│  ├── AI executes T004: "Build the client"                               │
│  │     └── Imports from src/api.py  ◄── T003's code available!          │
│  │     └── Creates src/client.py                                        │
│  ├── devcontainer down                                                  │
│  ├── jj describe -m "spec:X:T004 [DONE]"                                │
│  └── jj squash --into $T002  # Merge T004 → T002                        │
│                                                                         │
│  PHASE 7: Sync After T004                                               │
│  ────────────────────────                                               │
│  │                                                                      │
│  ├── Check T002 for conflicts                                           │
│  │     └── Minor conflict in setup.py (both added deps)                 │
│  ├── Resolve conflict:                                                  │
│  │     jj edit $T002                                                    │
│  │     # Merge both dependency lists                                    │
│  │     jj resolve                                                       │
│  ├── Rebase T005 onto resolved T002:                                    │
│  │     jj rebase -r $T005 -d $T002  # T005 has API + client             │
│  └── Sync complete ✓                                                    │
│                                                                         │
│  PHASE 8: T005 Execution (Depends on T003+T004)                         │
│  ──────────────────────────────────────────────                         │
│  │                                                                      │
│  ├── cd .arborist/ws/T005                                               │
│  ├── jj edit $T005                                                      │
│  ├── (already rebased - has API + client code)                          │
│  ├── devcontainer up (T005 workspace)                                   │
│  ├── AI executes T005: "Write docs"                                     │
│  │     └── Documents api.py and client.py  ◄── Both available!          │
│  │     └── Creates docs/api.md, docs/client.md                          │
│  ├── devcontainer down                                                  │
│  ├── jj describe -m "spec:X:T005 [DONE]"                                │
│  └── jj squash --into $T002                                             │
│                                                                         │
│  PHASE 9: Final Sync & Integration Test                                 │
│  ───────────────────────────────────────                                │
│  │                                                                      │
│  ├── Resolve any final conflicts in T002                                │
│  ├── Run integration tests:                                             │
│  │     jj edit $T002                                                    │
│  │     pytest tests/  # Tests API, client, and docs together            │
│  └── Tests pass ✓                                                       │
│                                                                         │
│  PHASE 10: Complete T002                                                │
│  ───────────────────────                                                │
│  │                                                                      │
│  ├── jj describe -m "spec:X:T002 [DONE]"                                │
│  ├── jj squash --into main                                              │
│  └── All work merged to main ✓                                          │
│                                                                         │
│  FINAL STATE:                                                           │
│  ────────────                                                           │
│  ◆ main (contains T001 + T002 with all children's work)                 │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Workspace Isolation with Jujutsu

Jujutsu workspaces provide the same filesystem isolation as git worktrees:

```
.arborist/
├── ws/                           # Workspaces (like worktrees)
│   ├── T003/                     # T003's isolated filesystem
│   │   ├── .jj/                  # Workspace link (like .git file)
│   │   ├── src/
│   │   │   └── api.py           # T003's work
│   │   └── ...
│   │
│   ├── T004/                     # T004's isolated filesystem
│   │   ├── .jj/
│   │   ├── src/
│   │   │   ├── api.py           # From T003 (via rebase)
│   │   │   └── client.py        # T004's work
│   │   └── ...
│   │
│   └── T005/                     # T005's isolated filesystem
│       ├── .jj/
│       ├── src/
│       │   ├── api.py           # From T003
│       │   └── client.py        # From T004
│       ├── docs/
│       │   └── ...              # T005's work
│       └── ...
│
└── dagu/
    └── dags/
        └── spec-X.yaml
```

Each workspace:
- Has its own filesystem (parallel AI agents don't collide)
- Can be mounted into separate devcontainers
- Shares the same jj repository (changes are visible across workspaces)
- Can independently `jj edit` different changes

### AI Agent Calls: Git vs Jujutsu Comparison

Both systems use AI agents for merge/conflict resolution. Here's how they compare:

#### Current Git System: AI-Based Post-Merge

The `arborist task post-merge` command invokes an AI agent to perform the merge:

```python
# From cli.py - current git-based system
merge_prompt = f"""Perform a squash merge of branch '{task_branch}' into '{parent_branch}'.

STEPS:
1. Verify you're on the correct branch: git branch --show-current
   (should show: {parent_branch})
2. Run: git merge --squash {task_branch}
3. If there are conflicts, resolve them carefully by examining both versions
4. After resolving any conflicts, stage all changes with: git add -A
5. Create a SINGLE commit with this EXACT format:

git commit -m "task({task_id}): <one-line summary of what was merged>

- <detail about changes merged>
- <another detail if needed>

(merged by {runner_type} / {resolved_model} from {task_branch})"

Do NOT push. Just complete the merge and commit locally.
"""

# Execute via runner (claude/opencode/gemini) with optional container wrapping
runner_instance = get_runner(runner_type, model=resolved_model)
result = runner_instance.run(
    merge_prompt,
    timeout=timeout,
    cwd=merge_worktree,
    container_cmd_prefix=container_cmd_prefix,  # devcontainer exec wrapper
)
```

**Key points:**
- AI performs BOTH the merge AND conflict resolution in one call
- Prompt includes instructions for handling conflicts
- Runner executes inside devcontainer when enabled
- Same runner infrastructure (claude/opencode/gemini) used for tasks and merges

#### Jujutsu System: AI-Based Squash with Conflict Resolution

The Jujutsu system needs TWO AI agent calls:

1. **`complete_task`**: AI performs squash (simpler, usually no conflicts)
2. **`sync_parent`**: AI resolves conflicts if detected after squash

```python
# jj_tasks.py - Jujutsu-based system

def build_squash_prompt(
    task_id: str,
    task_change: str,
    parent_change: str,
    runner_type: str,
    model: str,
) -> str:
    """Build prompt for AI to perform jj squash."""
    return f"""Perform a squash of change '{task_change}' into parent change '{parent_change}'.

You are working with Jujutsu (jj), not git. The commands are different.

STEPS:
1. Verify current change: jj log -r @ --no-graph
2. Squash this task's changes into the parent:
   jj squash --from {task_change} --into {parent_change}
3. If the squash reports conflicts, they are now IN the parent change.
   We will resolve them in a separate step.
4. Verify the squash succeeded:
   jj log -r {parent_change} --no-graph

After squashing, describe what was merged:
jj describe -r {parent_change} -m "task({task_id}): <summary of merged work>

- <detail about changes>
- <another detail if needed>

(squashed by {runner_type} / {model} from {task_change})"

IMPORTANT:
- Use 'jj' commands, NOT 'git' commands
- Do NOT run 'jj git push' - just complete the squash locally
- If there are no changes to squash (identical), report that
"""


def build_conflict_resolution_prompt(
    parent_change: str,
    conflicting_files: list[str],
    runner_type: str,
    model: str,
) -> str:
    """Build prompt for AI to resolve conflicts in a change."""
    files_list = "\n".join(f"  - {f}" for f in conflicting_files)
    return f"""Resolve merge conflicts in Jujutsu change '{parent_change}'.

You are working with Jujutsu (jj), not git. Conflict resolution is different.

CONFLICTING FILES:
{files_list}

STEPS:
1. Switch to the conflicted change:
   jj edit {parent_change}

2. List the conflicts:
   jj resolve --list

3. For each conflicting file, resolve it:
   - View the conflict: jj diff <file>
   - Jujutsu conflicts show <<<<<<<, ======= and >>>>>>> markers like git
   - Edit the file to resolve the conflict (remove markers, keep correct code)
   - After editing, the file is automatically tracked (no 'jj add' needed)

4. After resolving all files, verify no conflicts remain:
   jj log -r @ --no-graph
   (should NOT show "conflict" in the output)

5. Update the change description to note resolution:
   jj describe -m "$(jj log -r @ -T description --no-graph)

   Conflicts resolved: {', '.join(conflicting_files)}
   (resolved by {runner_type} / {model})"

IMPORTANT:
- Use 'jj' commands, NOT 'git' commands
- The working copy IS the change - edits are automatically tracked
- No need to stage changes with 'add' - jj tracks automatically
- If you cannot resolve a conflict, describe why in the change description
"""


def complete_task_with_ai(
    task_id: str,
    task_change: str,
    parent_change: str,
    workspace_path: Path,
    runner_type: str = "claude",
    model: str = "opus",
    timeout: int = 300,
    container_cmd_prefix: list[str] | None = None,
) -> dict:
    """Complete a task by squashing into parent, using AI for the operation.

    Returns:
        Dict with success status, output, and whether conflicts were created
    """
    from agent_arborist.runner import get_runner

    # Build the squash prompt
    prompt = build_squash_prompt(
        task_id=task_id,
        task_change=task_change,
        parent_change=parent_change,
        runner_type=runner_type,
        model=model,
    )

    # Get runner and execute
    runner = get_runner(runner_type, model=model)
    result = runner.run(
        prompt,
        timeout=timeout,
        cwd=workspace_path,
        container_cmd_prefix=container_cmd_prefix,
    )

    # Check if parent now has conflicts
    conflicts = run_jj(
        "log", "-r", f"{parent_change} & conflicts()",
        "--no-graph", "-T", "change_id",
        cwd=workspace_path,
        check=False
    )

    return {
        "success": result.success,
        "output": result.output,
        "error": result.error,
        "has_conflicts": bool(conflicts.stdout.strip()),
    }


def resolve_conflicts_with_ai(
    parent_change: str,
    workspace_path: Path,
    runner_type: str = "claude",
    model: str = "opus",
    timeout: int = 300,
    container_cmd_prefix: list[str] | None = None,
) -> dict:
    """Resolve conflicts in a change using AI.

    Returns:
        Dict with success status and whether conflicts were resolved
    """
    from agent_arborist.runner import get_runner

    # Get list of conflicting files
    conflicts_result = run_jj(
        "resolve", "--list",
        cwd=workspace_path,
        check=False
    )
    conflicting_files = [
        line.strip() for line in conflicts_result.stdout.strip().split("\n")
        if line.strip()
    ]

    if not conflicting_files:
        return {
            "success": True,
            "resolved": True,
            "message": "No conflicts to resolve",
        }

    # Build resolution prompt
    prompt = build_conflict_resolution_prompt(
        parent_change=parent_change,
        conflicting_files=conflicting_files,
        runner_type=runner_type,
        model=model,
    )

    # Get runner and execute
    runner = get_runner(runner_type, model=model)
    result = runner.run(
        prompt,
        timeout=timeout,
        cwd=workspace_path,
        container_cmd_prefix=container_cmd_prefix,
    )

    # Check if conflicts were resolved
    remaining = run_jj(
        "log", "-r", f"{parent_change} & conflicts()",
        "--no-graph", "-T", "change_id",
        cwd=workspace_path,
        check=False
    )

    resolved = not bool(remaining.stdout.strip())

    return {
        "success": result.success,
        "resolved": resolved,
        "output": result.output,
        "error": result.error,
        "files_attempted": conflicting_files,
    }


def sync_parent_with_ai(
    parent_change: str,
    spec_id: str,
    workspace_path: Path,
    runner_type: str = "claude",
    model: str = "opus",
    timeout: int = 300,
    container_cmd_prefix: list[str] | None = None,
) -> dict:
    """Sync parent after child completion, using AI for conflict resolution.

    1. Check for conflicts in parent
    2. If conflicts, invoke AI to resolve them
    3. Rebase pending children onto updated parent

    Returns:
        Dict with sync status
    """
    result = {
        "conflicts_found": False,
        "conflicts_resolved": False,
        "ai_invoked": False,
        "children_rebased": [],
    }

    # Check for conflicts
    conflicts = run_jj(
        "log", "-r", f"{parent_change} & conflicts()",
        "--no-graph", "-T", "change_id",
        cwd=workspace_path,
        check=False
    )

    if conflicts.stdout.strip():
        result["conflicts_found"] = True
        result["ai_invoked"] = True

        # Invoke AI to resolve conflicts
        resolution = resolve_conflicts_with_ai(
            parent_change=parent_change,
            workspace_path=workspace_path,
            runner_type=runner_type,
            model=model,
            timeout=timeout,
            container_cmd_prefix=container_cmd_prefix,
        )

        result["conflicts_resolved"] = resolution["resolved"]
        result["resolution_output"] = resolution.get("output", "")

        if not resolution["resolved"]:
            # Mark for human review
            current_desc = run_jj(
                "log", "-r", parent_change,
                "--no-graph", "-T", "description",
                cwd=workspace_path
            ).stdout.strip()

            if "[NEEDS_HUMAN_RESOLUTION]" not in current_desc:
                run_jj(
                    "describe", "-r", parent_change,
                    "-m", f"{current_desc}\n\n[NEEDS_HUMAN_RESOLUTION]",
                    cwd=workspace_path
                )

    # Rebase pending children onto (possibly updated) parent
    pending = run_jj(
        "log",
        "-r", f"children({parent_change}) & mutable() & ~description('[DONE]')",
        "--no-graph", "-T", 'change_id ++ "\\n"',
        cwd=workspace_path,
        check=False
    )

    for child_id in pending.stdout.strip().split("\n"):
        if child_id:
            run_jj("rebase", "-r", child_id, "-d", parent_change,
                   cwd=workspace_path, check=False)
            result["children_rebased"].append(child_id)

    return result
```

#### DAG Steps with AI Invocation

**Git (current)** - Single AI call for merge+resolution:
```yaml
- name: post-merge
  command: arborist task post-merge T003 --runner claude --model opus
  depends: [run-test]
  retryPolicy: {limit: 60, intervalSec: 60}  # Retry on lock contention
```

**Jujutsu (new)** - AI calls for squash AND resolution:
```yaml
# Child task completion - AI performs squash
- name: complete
  command: arborist jj complete T003 --runner claude --model opus
  depends: [run-test]
  # No retry needed - jj operations are atomic

# Parent sync - AI resolves any conflicts
- name: sync-after-T003
  command: arborist jj sync-parent T002 --runner claude --model opus
  depends: [c-T003]  # After child subdag completes
```

#### CLI Commands for Jujutsu AI Operations

```python
# cli.py additions for Jujutsu

@jj.command("complete")
@click.argument("task_id")
@click.option("--runner", "-r", default=None)
@click.option("--model", "-m", default=None)
@click.option("--timeout", "-t", default=300)
@click.pass_context
def jj_complete(ctx, task_id: str, runner: str, model: str, timeout: int):
    """Complete a task by squashing into parent using AI."""
    # Load manifest, get change IDs
    manifest = load_manifest(...)
    task_change = manifest.get_change_id(task_id)
    parent_change = manifest.get_parent_change(task_id)
    workspace = get_workspace_path(task_id)

    # Build container prefix if needed
    container_cmd_prefix = get_container_prefix_if_enabled()

    # AI performs the squash
    result = complete_task_with_ai(
        task_id=task_id,
        task_change=task_change,
        parent_change=parent_change,
        workspace_path=workspace,
        runner_type=runner or get_default_runner(),
        model=model or get_default_model(),
        timeout=timeout,
        container_cmd_prefix=container_cmd_prefix,
    )

    if not result["success"]:
        console.print(f"[red]Error:[/red] {result['error']}")
        raise SystemExit(1)

    if result["has_conflicts"]:
        console.print(f"[yellow]Conflicts created - will be resolved in sync step[/yellow]")

    console.print(f"[green]Task {task_id} completed[/green]")


@jj.command("sync-parent")
@click.argument("parent_task_id")
@click.option("--runner", "-r", default=None)
@click.option("--model", "-m", default=None)
@click.option("--timeout", "-t", default=300)
@click.pass_context
def jj_sync_parent(ctx, parent_task_id: str, runner: str, model: str, timeout: int):
    """Sync parent after child completion, resolving conflicts with AI."""
    manifest = load_manifest(...)
    parent_change = manifest.get_change_id(parent_task_id)
    workspace = get_main_workspace()

    container_cmd_prefix = get_container_prefix_if_enabled()

    result = sync_parent_with_ai(
        parent_change=parent_change,
        spec_id=manifest.spec_id,
        workspace_path=workspace,
        runner_type=runner or get_default_runner(),
        model=model or get_default_model(),
        timeout=timeout,
        container_cmd_prefix=container_cmd_prefix,
    )

    if result["conflicts_found"]:
        if result["conflicts_resolved"]:
            console.print(f"[green]Conflicts resolved by AI[/green]")
        else:
            console.print(f"[yellow]Conflicts require human resolution[/yellow]")
            # Don't fail - continue with other work

    if result["children_rebased"]:
        console.print(f"[dim]Rebased {len(result['children_rebased'])} children[/dim]")

    console.print(f"[green]Sync complete[/green]")
```

#### Complete DAG with AI Invocations

```yaml
name: spec-X
env:
  - ARBORIST_SPEC_ID=spec-X
  - ARBORIST_RUNNER=claude
  - ARBORIST_MODEL=opus
steps:
  - name: setup-changes
    command: arborist jj setup-spec

  - name: c-T001
    call: T001
    depends: [setup-changes]

  - name: c-T002
    call: T002
    depends: [c-T001]

---
# T001 subdag (leaf)
name: T001
steps:
  - name: pre-sync
    command: arborist jj pre-sync T001

  - name: container-up
    command: arborist jj container-up T001
    depends: [pre-sync]

  - name: run
    command: arborist jj run T001 --runner ${ARBORIST_RUNNER} --model ${ARBORIST_MODEL}
    depends: [container-up]

  - name: run-test
    command: arborist jj run-test T001
    depends: [run]

  # AI performs squash into main
  - name: complete
    command: arborist jj complete T001 --runner ${ARBORIST_RUNNER} --model ${ARBORIST_MODEL}
    depends: [run-test]

  - name: container-down
    command: arborist jj container-stop T001
    depends: [complete]

---
# T002 subdag (parent with children)
name: T002
steps:
  - name: pre-sync
    command: arborist jj pre-sync T002

  # Children run (may run in parallel depending on deps)
  - name: c-T003
    call: T003
    depends: [pre-sync]

  # AI resolves conflicts from T003, rebases T004/T005
  - name: sync-after-T003
    command: arborist jj sync-parent T002 --runner ${ARBORIST_RUNNER} --model ${ARBORIST_MODEL}
    depends: [c-T003]

  - name: c-T004
    call: T004
    depends: [sync-after-T003]  # Gets T003's work

  # AI resolves conflicts from T004, rebases T005
  - name: sync-after-T004
    command: arborist jj sync-parent T002 --runner ${ARBORIST_RUNNER} --model ${ARBORIST_MODEL}
    depends: [c-T004]

  - name: c-T005
    call: T005
    depends: [sync-after-T004]  # Gets T003+T004's work

  # Final sync after all children
  - name: sync-final
    command: arborist jj sync-parent T002 --runner ${ARBORIST_RUNNER} --model ${ARBORIST_MODEL}
    depends: [c-T005]

  - name: run-test
    command: arborist jj run-test T002
    depends: [sync-final]

  # AI performs final squash into main
  - name: complete
    command: arborist jj complete T002 --runner ${ARBORIST_RUNNER} --model ${ARBORIST_MODEL}
    depends: [run-test]

  - name: cleanup
    command: arborist jj cleanup T002
    depends: [complete]

---
# T003 subdag (leaf, child of T002)
name: T003
steps:
  - name: pre-sync
    command: arborist jj pre-sync T003  # Rebases onto T002 to get any prior work

  - name: container-up
    command: arborist jj container-up T003
    depends: [pre-sync]

  - name: run
    command: arborist jj run T003 --runner ${ARBORIST_RUNNER} --model ${ARBORIST_MODEL}
    depends: [container-up]

  - name: run-test
    command: arborist jj run-test T003
    depends: [run]

  # AI squashes T003 into T002 (may create conflicts)
  - name: complete
    command: arborist jj complete T003 --runner ${ARBORIST_RUNNER} --model ${ARBORIST_MODEL}
    depends: [run-test]

  - name: container-down
    command: arborist jj container-stop T003
    depends: [complete]
```

#### Summary: AI Agent Call Points

| Phase | Git System | Jujutsu System |
|-------|------------|----------------|
| Task execution | `arborist task run` → AI writes code | `arborist jj run` → AI writes code |
| Task completion | `arborist task post-merge` → AI merges + resolves | `arborist jj complete` → AI squashes |
| Conflict resolution | (included in post-merge) | `arborist jj sync-parent` → AI resolves |
| Change propagation | (manual via retry loops) | `sync-parent` rebases children |

**Key difference**: Jujutsu separates squash (usually clean) from conflict resolution (only when needed), making AI calls more focused and efficient.

### Revised `jj_tasks.py` Module

```python
"""Jujutsu-based task management with full DAG support."""

import subprocess
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class TaskChange:
    """A Jujutsu change representing a task."""
    change_id: str
    task_id: str
    spec_id: str
    parent_change: Optional[str]
    depends_on: list[str] = field(default_factory=list)  # Peer dependencies
    has_conflict: bool = False
    is_complete: bool = False


def run_jj(*args, cwd: Optional[Path] = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run a jj command."""
    cmd = ["jj", *args]
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=check)


def get_change_id(revset: str = "@", cwd: Optional[Path] = None) -> str:
    """Get change ID for a revset."""
    result = run_jj("log", "-r", revset, "--no-graph", "-T", "change_id", cwd=cwd)
    return result.stdout.strip()


def create_task_change(
    spec_id: str,
    task_id: str,
    parent_change: str,
    depends_on: Optional[list[str]] = None,
) -> str:
    """Create a new change for a task.

    Args:
        spec_id: Specification identifier
        task_id: Task identifier (e.g., "T003")
        parent_change: Parent change ID (task or main)
        depends_on: List of peer task IDs this depends on

    Returns:
        The new change ID
    """
    deps_str = f" [deps:{','.join(depends_on)}]" if depends_on else ""
    description = f"spec:{spec_id}:{task_id}{deps_str}"

    run_jj("new", parent_change, "-m", description)
    return get_change_id()


def create_workspace(task_id: str, workspace_path: Path) -> None:
    """Create a workspace for parallel task execution."""
    if workspace_path.exists():
        return  # Already exists

    workspace_path.parent.mkdir(parents=True, exist_ok=True)
    run_jj("workspace", "add", str(workspace_path), "--name", f"ws-{task_id}")


def setup_task_workspace(
    task_id: str,
    change_id: str,
    parent_change: str,
    workspace_path: Path,
) -> None:
    """Setup a workspace for task execution, incorporating parent's current state.

    This is the critical step that propagates sibling changes.
    """
    # Switch workspace to task's change
    run_jj("edit", change_id, cwd=workspace_path)

    # Rebase onto parent to get any sibling work that's been merged
    result = run_jj("rebase", "-d", parent_change, cwd=workspace_path, check=False)

    if result.returncode != 0:
        # Rebase might fail if already up-to-date, that's OK
        if "already" not in result.stderr.lower():
            raise RuntimeError(f"Rebase failed: {result.stderr}")

    # Check for conflicts after rebase
    conflicts = run_jj(
        "log", "-r", f"{change_id} & conflicts()",
        "--no-graph", "-T", "change_id",
        cwd=workspace_path
    )

    if conflicts.stdout.strip():
        print(f"Warning: {task_id} has conflicts after rebase, may need resolution")


def complete_task(
    task_id: str,
    change_id: str,
    parent_change: str,
    workspace_path: Optional[Path] = None,
) -> None:
    """Mark task complete and squash into parent."""
    cwd = workspace_path

    # Mark as done
    run_jj(
        "describe", "-m", f"spec:*:{task_id} [DONE]",
        cwd=cwd
    )

    # Squash into parent (atomic operation)
    run_jj("squash", "--from", change_id, "--into", parent_change, cwd=cwd)


def sync_parent(
    parent_change: str,
    spec_id: str,
    auto_resolve: bool = False,
) -> dict:
    """Sync parent after child completion.

    1. Check for conflicts in parent
    2. Optionally resolve them
    3. Rebase pending children onto updated parent

    Returns:
        Dict with sync status
    """
    result = {
        "conflicts_found": False,
        "conflicts_resolved": False,
        "children_rebased": [],
    }

    # Check for conflicts
    conflicts = run_jj(
        "log", "-r", f"{parent_change} & conflicts()",
        "--no-graph", "-T", "change_id"
    )

    if conflicts.stdout.strip():
        result["conflicts_found"] = True

        if auto_resolve:
            # AI-assisted resolution would go here
            run_jj("edit", parent_change)
            # ... resolve conflicts ...
            result["conflicts_resolved"] = True
        else:
            # Mark for human review
            current_desc = run_jj(
                "log", "-r", parent_change,
                "--no-graph", "-T", "description"
            ).stdout.strip()

            if "[NEEDS_RESOLUTION]" not in current_desc:
                run_jj(
                    "describe", "-r", parent_change,
                    "-m", f"{current_desc} [NEEDS_RESOLUTION]"
                )

    # Find and rebase pending children
    pending = run_jj(
        "log",
        "-r", f"children({parent_change}) & mutable() & ~description('[DONE]')",
        "--no-graph", "-T", 'change_id ++ "\\n"'
    )

    for child_id in pending.stdout.strip().split("\n"):
        if child_id:
            run_jj("rebase", "-r", child_id, "-d", parent_change, check=False)
            result["children_rebased"].append(child_id)

    return result


def find_tasks_by_spec(spec_id: str) -> list[TaskChange]:
    """Find all task changes for a spec using revsets."""
    result = run_jj(
        "log",
        "-r", f'description("spec:{spec_id}:") & mutable()',
        "--no-graph",
        "-T", 'change_id ++ "|" ++ description ++ "\\n"'
    )

    tasks = []
    for line in result.stdout.strip().split("\n"):
        if "|" in line:
            change_id, desc = line.split("|", 1)
            # Parse task ID from description
            # Format: "spec:SPEC:TASK [optional status]"
            parts = desc.split(":")
            if len(parts) >= 3:
                task_id = parts[2].split()[0].split("[")[0]
                tasks.append(TaskChange(
                    change_id=change_id.strip(),
                    task_id=task_id,
                    spec_id=spec_id,
                    parent_change=None,  # Would need additional query
                    is_complete="[DONE]" in desc,
                    has_conflict="[NEEDS_RESOLUTION]" in desc,
                ))

    return tasks


def get_task_status(spec_id: str) -> dict:
    """Get status of all tasks in a spec."""
    tasks = find_tasks_by_spec(spec_id)

    return {
        "total": len(tasks),
        "complete": sum(1 for t in tasks if t.is_complete),
        "with_conflicts": sum(1 for t in tasks if t.has_conflict),
        "pending": sum(1 for t in tasks if not t.is_complete and not t.has_conflict),
        "tasks": tasks,
    }
```

---

## Part 4: Migration Architecture

### New System Design

```
┌─────────────────────────────────────────────────────────────────┐
│                        DAGU Orchestrator                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   ┌───────────────────────────────────────────────────────┐    │
│   │              Jujutsu Change DAG                        │    │
│   │                                                        │    │
│   │    ○  T003 change                                      │    │
│   │    │                                                   │    │
│   │    │ ○  T002 change                                    │    │
│   │    │ │                                                 │    │
│   │    ○ │  T001:T005 change                               │    │
│   │    │ │                                                 │    │
│   │    ○ │  T001:T004 change                               │    │
│   │    ├─╯                                                 │    │
│   │    ○  T001 change                                      │    │
│   │    │                                                   │    │
│   │    ◆  main                                             │    │
│   └───────────────────────────────────────────────────────┘    │
│                                                                 │
│   No worktrees. No branch manifests. No filesystem locks.       │
│   Just changes and their relationships.                         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Component Mapping

| Current Component | Jujutsu Replacement |
|-------------------|---------------------|
| `git_tasks.py` | `jj_tasks.py` (~200 LOC estimated) |
| `branch_manifest.py` | Revset queries (no file needed) |
| Worktree management | `jj edit` / `jj new` |
| Filesystem locks | Atomic operations + `jj op` |
| Branch naming scheme | Change descriptions + tags |
| Merge serialization | Sequential rebase with auto-resolution |

### New Module: `jj_tasks.py`

```python
"""Jujutsu-based task management for Agent Arborist."""

import subprocess
import json
from dataclasses import dataclass
from typing import Optional

@dataclass
class Change:
    """A Jujutsu change representing a task."""
    change_id: str
    description: str
    parent_ids: list[str]
    has_conflict: bool

def create_task_change(spec_id: str, task_id: str, parent_change: Optional[str] = None) -> str:
    """Create a new change for a task."""
    parent = parent_change or "main"
    description = f"spec:{spec_id}:{task_id}"

    result = subprocess.run(
        ["jj", "new", parent, "-m", description],
        capture_output=True, text=True, check=True
    )

    # Get the new change ID
    return get_current_change_id()

def get_current_change_id() -> str:
    """Get the change ID of the current working copy."""
    result = subprocess.run(
        ["jj", "log", "-r", "@", "--no-graph", "-T", "change_id"],
        capture_output=True, text=True, check=True
    )
    return result.stdout.strip()

def find_task_changes(spec_id: str) -> list[Change]:
    """Find all changes for a spec using revsets."""
    result = subprocess.run(
        ["jj", "log", "-r", f'description("spec:{spec_id}")',
         "--no-graph", "-T", 'change_id ++ "\\n"'],
        capture_output=True, text=True, check=True
    )
    # Parse and return changes
    ...

def switch_to_task(change_id: str):
    """Switch working copy to a task's change."""
    subprocess.run(["jj", "edit", change_id], check=True)

def squash_to_parent(child_change: str, parent_change: str):
    """Merge a child task's changes into its parent."""
    subprocess.run(
        ["jj", "squash", "--from", child_change, "--into", parent_change],
        check=True
    )

def check_conflicts(change_id: str) -> bool:
    """Check if a change has conflicts."""
    result = subprocess.run(
        ["jj", "log", "-r", f'{change_id} & conflicts()', "--no-graph"],
        capture_output=True, text=True
    )
    return bool(result.stdout.strip())

def rebase_to_main(change_id: str):
    """Rebase a task change onto main."""
    subprocess.run(["jj", "rebase", "-r", change_id, "-d", "main"], check=True)

def operation_restore(op_id: str):
    """Restore to a previous operation state (rollback)."""
    subprocess.run(["jj", "op", "restore", op_id], check=True)

def get_last_operation() -> str:
    """Get the ID of the last operation for potential rollback."""
    result = subprocess.run(
        ["jj", "op", "log", "--no-graph", "-T", "operation_id", "-l", "1"],
        capture_output=True, text=True, check=True
    )
    return result.stdout.strip()
```

### Devcontainer Integration

The devcontainer pattern remains valuable for execution isolation, but simplifies significantly:

```yaml
# Before: Complex worktree mounting
services:
  task-runner:
    volumes:
      - ${ARBORIST_WORKTREE}:/workspace

# After: Single repo mounting, jj handles context
services:
  task-runner:
    volumes:
      - .:/workspace
    environment:
      - JJ_CHANGE_ID=${TASK_CHANGE_ID}
```

Inside container:
```bash
# Switch to task context
jj edit $JJ_CHANGE_ID
# Run task...
# Changes are in the change, not a worktree
```

---

## Part 5: Migration Plan

### Phase 0: Preparation (Week 1)

1. **Install jj alongside git**
   ```bash
   # macOS
   brew install jj

   # Or from source
   cargo install jj-cli
   ```

2. **Initialize colocated repository**
   ```bash
   cd agent-arborist
   jj git init --colocate
   ```

3. **Verify compatibility**
   ```bash
   jj log  # Should show git history
   jj git fetch  # Should work with remotes
   ```

4. **Team education**
   - Distribute Steve Klabnik's [Jujutsu Tutorial](https://steveklabnik.github.io/jujutsu-tutorial/)
   - Practice basic workflows on test repositories

### Phase 1: Parallel Implementation (Weeks 2-3)

Create new modules without removing old ones:

1. **Create `jj_tasks.py`**
   - Implement change creation, discovery, switching
   - Use revsets for task queries
   - Leverage operation log for rollback

2. **Create `jj_dag_builder.py`**
   - Generate simpler DAG without worktree steps
   - Remove lock/retry complexity
   - Use change IDs instead of branch names

3. **Add CLI flag for jj mode**
   ```bash
   arborist dag build --vcs=jj spec.yaml
   ```

### Phase 2: Feature Parity Testing (Week 4)

1. **Run existing specs with both backends**
   ```bash
   arborist dag build --vcs=git spec.yaml > dag-git.yaml
   arborist dag build --vcs=jj spec.yaml > dag-jj.yaml
   ```

2. **Compare execution characteristics**
   - Execution time
   - Failure recovery
   - Resource usage

3. **Document edge cases**
   - Conflict handling differences
   - Rollback behavior
   - Remote push requirements

### Phase 3: Advanced Features (Weeks 5-6)

Leverage jj capabilities not possible with git:

1. **Conflict-tolerant execution**
   - Tasks can complete even with conflicts
   - Resolution deferred to human review

2. **Automatic fixup propagation**
   - Fixes to parent tasks auto-rebase to children
   - No manual merge conflict resolution

3. **Mega-merge testing**
   - Test all parallel tasks together before individual completion
   - Single `jj new task1 task2 task3` creates test environment

4. **Operation-based rollback**
   - Replace retry loops with atomic operations
   - Use `jj op restore` for clean failure recovery

### Phase 4: Deprecation (Weeks 7-8)

1. **Mark git-based code as deprecated**
2. **Migration guide for existing users**
3. **Remove git-specific code after sunset period**

### Phase 5: New Capabilities (Ongoing)

1. **jj absorb integration**
   - Automatic distribution of fixes to appropriate tasks

2. **Revset-based monitoring**
   - Real-time dashboards using revset queries
   - Conflict detection across all active work

3. **Workspace multiplication**
   - Multiple developers/agents sharing change graph
   - Seamless handoff via change IDs

---

## Part 6: Detailed Technical Design

### Task Lifecycle: Git vs Jujutsu

#### Current (Git) Lifecycle

```
1. pre-sync:
   - Create branch: git checkout -b {branch} {parent}
   - Create worktree: git worktree add {path} {branch}
   - Sync from parent: git merge {parent_branch}
   - Copy .env files

2. run:
   - devcontainer up
   - Execute runner in worktree

3. run-test:
   - Execute tests in worktree

4. post-merge:
   - Acquire filesystem lock (retry 60x)
   - Find/create merge worktree
   - git checkout {parent_branch}
   - git merge {task_branch}
   - Release lock

5. post-cleanup:
   - devcontainer down
   - git worktree remove {path}
   - git branch -d {branch}
```

#### New (Jujutsu) Lifecycle

```
1. setup:
   - Create change: jj new {parent_change} -m "spec:{id}:{task}"
   - Record change ID for tracking

2. run:
   - jj edit {change_id}  # Switch context
   - Execute runner
   - Changes auto-recorded in change

3. run-test:
   - Execute tests
   - Results recorded in change or child

4. complete:
   - jj describe -m "spec:{id}:{task} [DONE]"
   - If merging to parent: jj squash --into {parent_change}
   - Descendants auto-rebase

5. (no cleanup needed)
   - No worktrees to remove
   - No branches to delete
   - Changes persist in history
```

### DAG Structure Changes

#### Current DAGU DAG

```yaml
steps:
  - name: branches-setup
    command: arborist task create-all-branches

  - name: merge-container-up
    command: devcontainer up --workspace-folder .
    depends: [branches-setup]

  - name: T001
    subdag: T001.yaml
    depends: [merge-container-up]

  - name: T002
    subdag: T002.yaml
    depends: [T001]

# T001.yaml
steps:
  - name: container-up
    command: devcontainer up --workspace-folder ${WORKTREE}

  - name: pre-sync
    command: devcontainer exec arborist task pre-sync T001
    depends: [container-up]

  - name: run
    command: devcontainer exec arborist task run T001
    depends: [pre-sync]

  - name: run-test
    command: devcontainer exec arborist task run-test T001
    depends: [run]

  - name: post-merge
    command: devcontainer exec arborist task post-merge T001
    depends: [run-test]
    retry:
      count: 60
      delay_seconds: 60

  - name: container-down
    command: docker stop ...
    depends: [post-merge]

  - name: post-cleanup
    command: arborist task post-cleanup T001
    depends: [container-down]
```

#### New DAGU DAG (Jujutsu)

```yaml
steps:
  - name: setup-changes
    command: arborist jj setup-spec ${SPEC_ID}
    # Creates all task changes in correct hierarchy

  - name: T001
    subdag: T001.yaml
    depends: [setup-changes]

  - name: T002
    subdag: T002.yaml
    depends: [T001]

# T001.yaml (dramatically simplified)
steps:
  - name: run
    command: |
      jj edit ${T001_CHANGE}
      devcontainer exec arborist task run T001
    env:
      T001_CHANGE: ${T001_CHANGE_ID}

  - name: run-test
    command: devcontainer exec arborist task run-test T001
    depends: [run]

  - name: complete
    command: |
      jj describe -m "spec:${SPEC_ID}:T001 [COMPLETE]"
    depends: [run-test]
    # No retries needed - operation is atomic
    # No cleanup needed - no worktrees
```

### Revset Queries for Task Management

```bash
# All active tasks for a spec
ACTIVE='description("spec:ABC") & mutable() & ~description("[COMPLETE]")'

# Tasks with conflicts
CONFLICTED='description("spec:ABC") & conflicts()'

# Tasks ready for review (complete, no conflicts)
READY='description("spec:ABC") & description("[COMPLETE]") & ~conflicts()'

# Child tasks of T001
CHILDREN='description("spec:ABC:T001:") & children(description("spec:ABC:T001") & ~description(":"))'

# Integration test merge
jj new $(jj log -r "$ACTIVE" --no-graph -T 'change_id ++ " "')
```

### Error Handling & Recovery

```python
def execute_task_with_recovery(task_id: str, change_id: str):
    """Execute a task with automatic recovery on failure."""

    # Record operation state before execution
    op_before = get_last_operation()

    try:
        # Switch to task context
        switch_to_task(change_id)

        # Run the task
        run_task(task_id)

        # Run tests
        run_tests(task_id)

        # Mark complete
        mark_complete(change_id)

    except TaskExecutionError as e:
        # Restore to pre-execution state
        operation_restore(op_before)

        # Record failure in change description
        subprocess.run([
            "jj", "describe", "-m",
            f"spec:{spec_id}:{task_id} [FAILED: {e}]"
        ])

        raise
```

---

## Part 7: What Jujutsu Is Really Good At

### Insight 1: The Working Copy Problem Dissolves

Git's fundamental issue is that the working copy is separate from commits. This creates:
- The staging area complexity
- The "detached HEAD" state
- The "branch already checked out" error

Jujutsu eliminates this by making the working copy literally be a commit. Every change to files is immediately part of a change. This is why worktrees become unnecessary.

### Insight 2: Parallelism Without Isolation Theater

Our current architecture creates elaborate isolation:
- Separate worktrees per task
- Separate branches per task
- Filesystem locks for merge coordination

But this isolation is theater. The real isolation comes from:
- Devcontainers (execution isolation)
- The DAG structure (dependency ordering)

Jujutsu lets us drop the git-level isolation while keeping the real isolation.

### Insight 3: Conflicts as Data, Not Errors

In Git, a conflict is an error state. Work stops until resolution.

In Jujutsu, a conflict is data stored in a commit. You can:
- See the conflict exists
- Continue working on other things
- Come back to resolve later
- Have AI attempt resolution
- Track conflict history over time

This transforms how we think about parallel development.

### Insight 4: The Operation Log Is a Time Machine

Every jj operation is recorded. This means:
- No operation is truly destructive
- Experimentation is safe
- Recovery is always possible

For AI agents, this is transformative. An agent can try aggressive changes knowing rollback is trivial.

### Insight 5: Revsets Replace Static Manifests

Our branch manifest is a snapshot of intended state. It's static and can drift from reality.

Revsets are live queries against actual state. They're always accurate.

```bash
# Manifest approach: read JSON, hope it matches reality
manifest = load_manifest("spec_123_manifest.json")
tasks = manifest.tasks

# Revset approach: query actual state
jj log -r 'description("spec:123:") & mutable()'
```

---

## Part 8: The Jujutsu-Native Architecture

### Vision: Changes as the Universal Abstraction

```
┌─────────────────────────────────────────────────────────────────┐
│                     Agent Arborist (Jujutsu)                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Spec File ──▶ Change Tree ──▶ DAGU DAG ──▶ Execution           │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    Jujutsu Change Tree                   │   │
│  │                                                          │   │
│  │  Each task = One change                                  │   │
│  │  Parent/child = Ancestor/descendant in DAG              │   │
│  │  Task state = Change description tags                   │   │
│  │  Discovery = Revset queries                             │   │
│  │  Recovery = Operation restore                           │   │
│  │                                                          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    Devcontainer Layer                    │   │
│  │                                                          │   │
│  │  Execution isolation (unchanged from current)            │   │
│  │  Single repo mount, jj edit for context switching       │   │
│  │                                                          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### New CLI Commands

```bash
# Initialize a spec's change tree
arborist jj init-spec spec.yaml
# Creates all task changes in correct hierarchy

# Run a single task
arborist jj run-task T001 --spec spec.yaml
# Switches to change, executes, marks complete

# Check spec status via revsets
arborist jj status spec.yaml
# Queries change tree for task states

# Integration test all active work
arborist jj test-integration spec.yaml
# Creates mega-merge of all task changes, runs tests

# Complete and publish
arborist jj publish spec.yaml
# Rebases completed changes to main, pushes
```

### Estimated Code Reduction

| Module | Current LOC | Estimated New LOC | Reduction |
|--------|-------------|-------------------|-----------|
| git_tasks.py | 664 | 0 (removed) | -664 |
| jj_tasks.py | 0 | 200 | +200 |
| branch_manifest.py | 150 | 0 (removed) | -150 |
| dag_builder.py | 300 | 150 | -150 |
| container_runner.py | 150 | 100 | -50 |
| **Total** | **1,264** | **450** | **-814 (64% reduction)** |

---

## Part 9: Risk Assessment

### Low Risk
- **Git compatibility**: jj uses git as backend, full interop
- **Learning curve**: Commands map closely to git concepts
- **Rollback**: Can always `jj git export` and return to pure git

### Medium Risk
- **Tooling ecosystem**: IDE support less mature than git
- **CI/CD integration**: May need adapter scripts
- **Team adoption**: Requires training investment

### High Risk (Mitigations)
- **jj stability**: Still pre-1.0
  - *Mitigation*: Colocate mode maintains git fallback
- **Conflict handling differences**: Behavior differs from git
  - *Mitigation*: Explicit conflict checking in DAG
- **Performance at scale**: Less battle-tested
  - *Mitigation*: Profile early, report issues upstream

---

## Part 10: Success Metrics

### Quantitative
- 50%+ reduction in git-related code
- 80%+ reduction in merge retry loops
- 90%+ reduction in worktree-related failures
- Zero "branch already checked out" errors

### Qualitative
- Simpler mental model for task isolation
- Faster failure recovery
- Better conflict visibility
- Cleaner operation history

---

## Sources

### Official Jujutsu Resources
- [Jujutsu GitHub Repository](https://github.com/jj-vcs/jj)
- [Jujutsu Documentation](https://docs.jj-vcs.dev/latest/tutorial/)
- [Revset Language Reference](https://docs.jj-vcs.dev/latest/revsets/)

### Tutorials & Guides
- [Steve Klabnik's Jujutsu Tutorial](https://steveklabnik.github.io/jujutsu-tutorial/)
- [Jujutsu Strategies (Reasonably Polymorphic)](https://reasonablypolymorphic.com/blog/jj-strategy/)
- [A Better Merge Workflow with Jujutsu](https://ofcr.se/jujutsu-merge-workflow)
- [Jujutsu VCS Introduction and Patterns](https://kubamartin.com/posts/introduction-to-the-jujutsu-vcs/)

### Comparisons & Analysis
- [Jujutsu vs Git Worktrees](https://gist.github.com/ruvnet/60e5749c934077c7040ab32b542539d0)
- [Git and Jujutsu: The Next Evolution](https://www.infovision.com/blog/git-and-jujutsu-the-next-evolution-in-version-control-systems/)
- [Tech Notes: The Jujutsu Version Control System](https://neugierig.org/software/blog/2024/12/jujutsu.html)
- [Jujutsu: A Haven for Mercurial Users (Mozilla)](https://ahal.ca/blog/2024/jujutsu-mercurial-haven/)

### Stacked PRs & Advanced Workflows
- [jj-stack: Stacked PRs on GitHub](https://github.com/keanemind/jj-stack)
- [jj-spr: Power Tool for Jujutsu + GitHub](https://github.com/LucioFranco/jj-spr)
- [Jujutsu Megamerges and jj absorb](https://v5.chriskrycho.com/journal/jujutsu-megamerges-and-jj-absorb)

---

## Appendix A: Command Mapping

| Git Command | Jujutsu Equivalent |
|-------------|-------------------|
| `git init` | `jj git init` |
| `git clone` | `jj git clone` |
| `git add` | (automatic) |
| `git commit` | `jj commit` or `jj new` |
| `git commit --amend` | `jj describe` / `jj squash` |
| `git checkout <branch>` | `jj edit <change>` |
| `git checkout -b <branch>` | `jj new` + `jj bookmark create` |
| `git branch` | `jj bookmark list` |
| `git merge` | `jj new <a> <b>` (merge commit) |
| `git rebase` | `jj rebase` |
| `git stash` | `jj new @-` (just create new change) |
| `git log` | `jj log` |
| `git diff` | `jj diff` |
| `git status` | `jj status` |
| `git worktree` | (not needed) |

## Appendix B: Revset Cheat Sheet

```bash
# Symbols
@                    # Working copy
root()               # Repository root
trunk()              # Main branch
mine()               # My commits

# Navigation
x-                   # Parents of x
x+                   # Children of x
::x                  # Ancestors of x (inclusive)
x::                  # Descendants of x (inclusive)
x::y                 # x to y path

# Set Operations
x | y                # Union
x & y                # Intersection
x ~ y                # Difference (x minus y)
~x                   # Complement

# Filtering
description(pat)     # By commit message
author(pat)          # By author
files(pat)           # Touching files
conflicts()          # Has conflicts
empty()              # Empty commits
merges()             # Merge commits
mutable()            # Not immutable
```

## Appendix C: Migration Checklist

- [ ] Install jj on all development machines
- [ ] Initialize colocated repository
- [ ] Create `jj_tasks.py` module
- [ ] Create `jj_dag_builder.py` module
- [ ] Add `--vcs=jj` CLI flag
- [ ] Run parallel tests (git vs jj)
- [ ] Document behavioral differences
- [ ] Train team on jj workflows
- [ ] Migrate one production spec
- [ ] Monitor and iterate
- [ ] Deprecate git-specific code
- [ ] Remove git-specific code
- [ ] Celebrate
