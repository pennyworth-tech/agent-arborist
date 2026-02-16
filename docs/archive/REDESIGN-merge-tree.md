# JJ Tree Redesign: Pure Merge-Based Rollup

## Executive Summary

Replace squash-based rollup with merge-based rollup. Every task produces exactly one commit. Parent tasks create merge commits that combine children's work with their own. A special ROOT task handles final bookmark and git export.

**Key Principles:**
1. **One commit per task** - leaf = simple commit, parent = merge commit
2. **Pure recursion** - same pattern at every level
3. **Parents do work too** - after children complete, in the merge commit
4. **ROOT finalizes** - bookmarks and exports to git

---

## The Problem with Current Design

The current implementation uses **squash**, which **destroys child commits**:

```
T2 squashes into T1 → T2 disappears, T1 absorbs work
```

This gives ONE commit total, not one per task. The TIP pattern tries to accumulate everything, but it's still one blob.

---

## The Clean Model: Merge-Based Tree Rollup

### Core Principle

**Every task produces exactly one commit:**

| Task Type | Commit Type |
|-----------|-------------|
| **Leaf** | Simple change (task's work) |
| **Parent** | Merge commit (children + parent's own work) |
| **ROOT** | Final merge commit (all root tasks + finalize) |

### Example Tree

```
ROOT
└── T1 (parent)
    ├── T2 (leaf)
    └── T3 (parent)
        ├── T4 (leaf)
        └── T5 (leaf)
```

### Final Commit Graph

```
source_rev
├── T4 ────────────┐
├── T5 ────────────┴── T3 (merge + T3's work)
├── T2 ────────────────────────┐
└──────────────────────────────┴── T1 (merge of T2, T3 + T1's work)
                                   └── ROOT (final merge + finalize)
```

**6 tasks = 6 commits.** Each task has exactly one.

---

## Task Lifecycle

### Leaf Task

```
1. pre-sync   → Create workspace, branch from parent's merge (or source_rev)
2. run        → AI does the task's work
3. run-test   → Run tests (optional)
4. complete   → Mark [DONE], no squash
5. cleanup    → Remove workspace
```

### Parent Task

```
1. (children run in parallel)
2. (wait for all children to complete)
3. create-merge → jj new <child1> <child2> ... -m "spec:T1"
4. run          → Parent does ITS OWN work in the merge commit
5. run-test     → Integration tests
6. complete     → Mark [DONE]
7. cleanup      → Remove workspace
```

### ROOT Task (Special)

```
1. (all root-level tasks run)
2. (wait for all to complete)
3. create-merge → jj new <root1> <root2> ... -m "spec:ROOT"
4. run          → Final integration, validation
5. run-test     → Full test suite
6. finalize     → Move bookmark to ROOT merge, jj git export
7. complete     → Mark [DONE]
```

---

## DAG Generation Rules

The DAG structure emerges automatically from the task tree. No explicit "phase" tasks needed.

### Rule 1: Leaf Task Subdag

```yaml
name: T2
env:
  - ARBORIST_TASK_PATH=T1:T2
steps:
  - name: pre-sync
    command: arborist task pre-sync T2

  - name: run
    command: arborist task run T2
    depends: [pre-sync]

  - name: run-test
    command: arborist task run-test T2
    depends: [run]
    continueOn: { failure: true }  # Optional: continue even if tests fail

  - name: complete
    command: arborist task complete T2
    depends: [run-test]

  - name: cleanup
    command: arborist task cleanup T2
    depends: [complete]
```

### Rule 2: Parent Task Subdag

```yaml
name: T1
env:
  - ARBORIST_TASK_PATH=T1
steps:
  # Children run first (parallel - no depends between them)
  - name: c-T2
    call: T2

  - name: c-T3
    call: T3

  # After ALL children complete, create merge
  - name: create-merge
    command: arborist task create-merge T1
    depends: [c-T2, c-T3]

  # Parent's OWN work happens in the merge commit
  - name: run
    command: arborist task run T1
    depends: [create-merge]

  - name: run-test
    command: arborist task run-test T1
    depends: [run]

  - name: complete
    command: arborist task complete T1
    depends: [run-test]

  - name: cleanup
    command: arborist task cleanup T1
    depends: [complete]
```

### Rule 3: ROOT Subdag

```yaml
name: ROOT
steps:
  # All root-level tasks
  - name: c-T1
    call: T1

  - name: c-T5
    call: T5
    depends: [c-T1]  # Sequential root tasks (or parallel if independent)

  # Create final merge
  - name: create-merge
    command: arborist task create-merge ROOT
    depends: [c-T1, c-T5]

  # Final integration work
  - name: run
    command: arborist task run ROOT
    depends: [create-merge]

  # Full test suite
  - name: run-test
    command: arborist task run-test ROOT
    depends: [run]

  # Finalize: bookmark + git export
  - name: finalize
    command: arborist spec finalize
    depends: [run-test]

  - name: complete
    command: arborist task complete ROOT
    depends: [finalize]
```

---

## DAG Generator Algorithm

```python
def generate_dag(spec: Spec) -> str:
    """Generate complete DAGU YAML from spec."""

    task_tree = build_task_tree(spec)
    documents = []

    # Generate ROOT subdag (entry point)
    root_dag = generate_root_dag(spec.id, task_tree)
    documents.append(root_dag)

    # Generate subdags for all tasks (recursive)
    for task_id in topological_order(task_tree):
        task = task_tree.get_task(task_id)
        subdag = generate_task_subdag(task, task_tree, spec.id)
        documents.append(subdag)

    return yaml_multi_document(documents)


def generate_task_subdag(task: TaskNode, tree: TaskTree, spec_id: str) -> dict:
    """Generate subdag for a single task."""

    steps = []

    if task.is_leaf:
        # Leaf: pre-sync → run → run-test → complete → cleanup
        steps = [
            step("pre-sync", f"arborist task pre-sync {task.id}"),
            step("run", f"arborist task run {task.id}", depends=["pre-sync"]),
            step("run-test", f"arborist task run-test {task.id}", depends=["run"]),
            step("complete", f"arborist task complete {task.id}", depends=["run-test"]),
            step("cleanup", f"arborist task cleanup {task.id}", depends=["complete"]),
        ]
    else:
        # Parent: children → create-merge → run → run-test → complete → cleanup

        # Child calls (parallel)
        child_calls = [
            call_step(f"c-{child_id}", child_id)
            for child_id in task.children
        ]

        child_names = [f"c-{c}" for c in task.children]

        steps = child_calls + [
            step("create-merge", f"arborist task create-merge {task.id}", depends=child_names),
            step("run", f"arborist task run {task.id}", depends=["create-merge"]),
            step("run-test", f"arborist task run-test {task.id}", depends=["run"]),
            step("complete", f"arborist task complete {task.id}", depends=["run-test"]),
            step("cleanup", f"arborist task cleanup {task.id}", depends=["complete"]),
        ]

    return {
        "name": task.id,
        "env": [f"ARBORIST_TASK_PATH={task.path}"],
        "steps": steps,
    }


def generate_root_dag(spec_id: str, tree: TaskTree) -> dict:
    """Generate the ROOT entry point DAG."""

    root_tasks = tree.root_tasks  # Tasks with no parent

    steps = [
        step("setup-changes", "arborist task setup-spec"),
    ]

    # Call each root task (sequential by default, can be parallel)
    prev_dep = ["setup-changes"]
    for i, root_id in enumerate(root_tasks):
        steps.append(
            call_step(f"c-{root_id}", root_id, depends=prev_dep)
        )
        prev_dep = [f"c-{root_id}"]  # Sequential root tasks

    root_names = [f"c-{r}" for r in root_tasks]

    # ROOT merge and finalize
    steps += [
        step("create-merge", "arborist task create-merge ROOT", depends=root_names),
        step("run", "arborist task run ROOT", depends=["create-merge"]),
        step("run-test", "arborist task run-test ROOT", depends=["run"]),
        step("finalize", "arborist spec finalize", depends=["run-test"]),
        step("complete", "arborist task complete ROOT", depends=["finalize"]),
    ]

    return {
        "name": spec_id,
        "env": [
            f"ARBORIST_SPEC_ID={spec_id}",
            "ARBORIST_TASK_PATH=ROOT",
        ],
        "steps": steps,
    }
```

---

## JJ Operations

### Setup: Create Leaf Changes

All leaves created as children of `source_rev`:

```bash
# For each leaf task
jj new source_rev -m "spec:T1:T2"
jj new source_rev -m "spec:T1:T3:T4"
jj new source_rev -m "spec:T1:T3:T5"
```

Parent tasks (T1, T3, ROOT) do NOT create changes at setup. They create merge commits at completion.

### Pre-sync: Rebase Onto Parent's Merge

When a leaf starts, it rebases onto its parent's merge (if parent has completed):

```bash
# T4 starting (T3 is its parent, but T3 hasn't completed yet)
# T4 rebases onto T3's parent's merge, or source_rev
parent_base=$(arborist task find-parent-base T4)
jj rebase -r T4_change -d $parent_base
```

### Create Merge: Parent Combines Children

```bash
# T3 creates merge after T4, T5 complete
jj new T4_change T5_change -m "spec:T1:T3"

# Now in T3's merge commit working copy
# T3's "run" step does work here
```

### Parent's Own Work

After `create-merge`, the working copy is the merge commit. Parent's `run` step executes here:

```bash
# Working copy is T3's merge commit
# Contains T4's files + T5's files (merged)
# T3's AI task can now:
#   - Add integration glue
#   - Fix any merge conflicts
#   - Run integration tests
#   - Add documentation
```

### Complete: Mark Done

```bash
jj status  # Snapshot working copy
# Update description to mark [DONE]
jj describe -m "spec:T1:T3 [DONE]"
```

### ROOT Finalize

```bash
# ROOT's merge contains all work
# Move bookmark to ROOT's merge
jj bookmark set $SOURCE_REV -r ROOT_change

# Export to git
jj git export
```

---

## Changes from Current Implementation

### REMOVE

| Item | Reason |
|------|--------|
| TIP pattern | Replaced by ROOT merge |
| `squash_into_parent()` | Replaced by merge commits |
| `sync_parent()` rebasing | Not needed - children are independent |
| Complex parent change tracking | Parents don't have changes until completion |

### ADD

| Item | Purpose |
|------|---------|
| `create_merge_commit()` | Create merge from children |
| `find_completed_children()` | Find children's changes for merge |
| `task create-merge` CLI | New command for parent tasks |
| ROOT task handling | Special finalization logic |

### MODIFY

| Item | Change |
|------|--------|
| `_create_changes_from_tree()` | Only create changes for LEAF tasks |
| `task complete` | No squash, just mark done |
| `spec finalize` | Find ROOT merge instead of TIP |
| DAG generator | New parent/leaf/ROOT patterns |

---

## Example: 3 Phases, 2 Tasks Each

### Task Tree

```
ROOT
├── Phase1 (parent)
│   ├── T1 (leaf)
│   └── T2 (leaf)
├── Phase2 (parent, sequential after Phase1)
│   ├── T3 (leaf)
│   └── T4 (leaf)
└── Phase3 (parent, sequential after Phase2)
    ├── T5 (leaf)
    └── T6 (leaf)
```

### Execution Timeline

```
1. Setup: Create T1, T2, T3, T4, T5, T6 as leaves (all from source_rev)

2. Phase1: T1, T2 run in parallel
   → T1, T2 complete
   → Phase1 creates merge of T1, T2
   → Phase1 does its work
   → Phase1 complete

3. Phase2: T3, T4 rebase onto Phase1's merge, run in parallel
   → T3, T4 complete
   → Phase2 creates merge of T3, T4
   → Phase2 does its work
   → Phase2 complete

4. Phase3: T5, T6 rebase onto Phase2's merge, run in parallel
   → T5, T6 complete
   → Phase3 creates merge of T5, T6
   → Phase3 does its work
   → Phase3 complete

5. ROOT: Creates merge of Phase1, Phase2, Phase3
   → ROOT does final integration
   → ROOT runs full test suite
   → Finalize: bookmark + git export
   → ROOT complete
```

### Final Graph

```
source_rev
├── T1 ──────┐
├── T2 ──────┴── Phase1 ──────────────────────────────┐
├── T3 ──────┐                                        │
├── T4 ──────┴── Phase2 ──────────────────────────────┤
├── T5 ──────┐                                        │
├── T6 ──────┴── Phase3 ──────────────────────────────┴── ROOT
```

**10 commits:** T1, T2, Phase1, T3, T4, Phase2, T5, T6, Phase3, ROOT

---

## Code Changes Required

### 1. tasks.py - New Functions

```python
def create_merge_commit(
    parent_changes: list[str],
    description: str,
    cwd: Path | None = None,
) -> str:
    """Create a merge commit with multiple parents."""
    if not parent_changes:
        raise ValueError("Need at least one parent change")

    args = ["new"] + parent_changes + ["-m", description]
    run_jj(*args, cwd=cwd)
    return get_change_id(cwd=cwd)


def find_completed_children(
    spec_id: str,
    task_path: list[str],
    cwd: Path | None = None,
) -> list[str]:
    """Find all completed child changes for a parent task."""
    parent_desc = build_task_description(spec_id, task_path)

    # Direct children that are done
    revset = (
        f'description(glob:"{parent_desc}:*") & '
        f'~description(glob:"{parent_desc}:*:*") & '
        f'description("[DONE]") & '
        f'mutable()'
    )

    result = run_jj(
        "log", "-r", revset,
        "--no-graph", "-T", 'change_id ++ "\\n"',
        cwd=cwd, check=False,
    )

    if result.returncode != 0:
        return []

    return [c.strip() for c in result.stdout.strip().split("\\n") if c.strip()]


def find_parent_base(
    spec_id: str,
    task_path: list[str],
    source_rev: str,
    cwd: Path | None = None,
) -> str:
    """Find the base to rebase onto before running a task."""
    # Walk up the tree looking for completed ancestors
    path = task_path.copy()

    while len(path) > 1:
        path = path[:-1]  # Parent's path
        parent_change = find_change_by_description(spec_id, path, cwd)
        if parent_change:
            # Check if parent is complete (has merge)
            desc = get_description(parent_change, cwd)
            if "[DONE]" in desc:
                return parent_change

    # No completed ancestor, use source_rev
    return source_rev
```

### 2. task_cli.py - New Command

```python
@task.command("create-merge")
@click.argument("task_id")
@click.pass_context
def task_create_merge(ctx: click.Context, task_id: str) -> None:
    """Create merge commit for a parent task."""
    spec_id = _get_spec_id(ctx)
    task_path = _get_task_path()

    if not spec_id or not task_path:
        raise SystemExit(1)

    # Find all completed children
    child_changes = find_completed_children(spec_id, task_path)

    if not child_changes:
        console.print(f"[red]Error:[/red] No completed children found for {task_id}")
        raise SystemExit(1)

    console.print(f"[cyan]Creating merge for:[/cyan] {task_id}")
    console.print(f"[dim]Merging {len(child_changes)} children[/dim]")

    # Create merge commit
    desc = build_task_description(spec_id, task_path)
    workspace_path = get_workspace_path(spec_id, task_id)

    # Create workspace for the merge
    if not workspace_path.exists():
        create_workspace(workspace_path, f"ws-{task_id}")

    merge_change = create_merge_commit(child_changes, desc, cwd=workspace_path)

    console.print(f"[green]Merge created:[/green] {merge_change}")
```

### 3. dag_builder.py - New Generation Logic

See DAG Generator Algorithm section above.

### 4. cli.py - Update Finalize

```python
@spec.command("finalize")
def spec_finalize(ctx):
    # Find ROOT's merge (not TIP)
    root_change = find_change_by_description(spec_id, ["ROOT"])

    if not root_change:
        console.print("[red]Error:[/red] ROOT merge not found")
        raise SystemExit(1)

    # Move bookmark to ROOT
    run_jj("bookmark", "set", source_rev, "-r", root_change)

    # Export to git
    run_jj("git", "export")
```

---

## Migration Path

1. **Add new functions** to tasks.py (non-breaking)
2. **Add `task create-merge`** command
3. **Update DAG generator** with new patterns
4. **Update `spec finalize`** to use ROOT
5. **Add tests** for new flow
6. **Remove old code** (TIP, squash) after validation

---

## Test Cases

### Test 1: Single Leaf Task

```
ROOT
└── T1 (leaf)
```

Expected: 2 commits (T1, ROOT)

### Test 2: Parent with Two Children

```
ROOT
└── T1 (parent)
    ├── T2 (leaf)
    └── T3 (leaf)
```

Expected: 4 commits (T2, T3, T1, ROOT)

### Test 3: Three-Level Nesting

```
ROOT
└── T1 (parent)
    ├── T2 (leaf)
    └── T3 (parent)
        ├── T4 (leaf)
        └── T5 (leaf)
```

Expected: 6 commits (T4, T5, T3, T2, T1, ROOT)

### Test 4: Sequential Phases

```
ROOT
├── Phase1 (parent)
│   ├── T1 (leaf)
│   └── T2 (leaf)
└── Phase2 (parent, depends on Phase1)
    ├── T3 (leaf)
    └── T4 (leaf)
```

Expected: 7 commits (T1, T2, Phase1, T3, T4, Phase2, ROOT)
T3, T4 should have Phase1's work (rebased onto Phase1's merge)

### Test 5: Parent Does Own Work

Verify that parent's `run` step executes in the merge commit and the work appears in the final commit.
