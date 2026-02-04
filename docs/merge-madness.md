# Merge Madness: Post-Merge Worktree Investigation

## Executive Summary

Post-merge steps in arborist DAG runs are failing silently because:
1. Temp worktrees are created at `/tmp/` which isn't accessible from devcontainers
2. Parallel merges to the same parent branch can execute concurrently (no serialization)

This doc proposes a container-safe, git-friendly merge strategy:
- Always operate on worktrees inside `.arborist/` (mounted into devcontainers)
- Serialize merges per `(spec_id, parent_branch)` via a simple filesystem lock
- Use DAGU-native step retries (60s delay, 60 attempts) instead of custom retry loops

This document captures the investigation and proposed fix.

---

## Investigation Timeline

### Initial Symptom

GitHub Actions workflow runs complete successfully, but no commits appear on the `_a` branch:
- https://github.com/pennyworth-tech/backlit-core/actions/runs/21652107261
- https://github.com/pennyworth-tech/backlit-core/actions/runs/21678973280

Push step shows:
```
Switched to branch '003-terraform-hello-world_a'
Everything up-to-date
```

### First Fix Attempt (Failed)

Changed workflow from:
```yaml
git checkout -B "$BRANCH_A"  # -B resets branch to HEAD!
git push --force origin "$BRANCH_A"
```

To:
```yaml
git checkout "$BRANCH_A"
git push origin "$BRANCH_A"
```

This was necessary but not sufficient - the `_a` branch still had no new commits.

### Root Cause Discovery

Examining the workflow logs revealed the real issue:

**T1 Commit Result:**
```json
{
  "commit_sha": "0a8572329b944665763536315611e9b3062f2457",
  "message": "task(T1): create infrastructure directory structure"
}
```

**T1 Post-Merge Result:**
```json
{
  "commit_sha": "7632f5ac5a3a39748ddd51f078318dfccd0ee49f",  // SAME AS ORIGINAL!
  "merged_into": "003-terraform-hello-world_a"
}
```

The task commit exists (`0a8572...`) but after post-merge, the `_a` branch still has the original SHA (`7632f5...`). The merge isn't happening!

### The Container Path Problem

Looking at the post-merge code in `cli.py`:

```python
# Creates temp worktree at /tmp/ on HOST
temp_worktree_dir = tempfile.mkdtemp(prefix="arborist_merge_")
merge_worktree = Path(temp_worktree_dir) / "parent"
```

Then the AI is told:
```
FIRST: Change to the merge worktree directory:
cd /tmp/arborist_merge_xxx/parent
```

But the AI runs in the git-root container via `devcontainer exec`. The container's `/tmp` is isolated from the host's `/tmp`. The path doesn't exist inside the container!

The AI silently fails to `cd` to the worktree, and the merge never happens.

---

## Architecture Analysis

### Current Worktree Flow

1. **branches-setup**: Creates BRANCHES (not worktrees)
   - `_a` (base branch)
   - `_a_T1`, `_a_T2`, etc. (task branches)

2. **pre-sync** (per task): Creates WORKTREE for task's branch
   - `.arborist/worktrees/<spec>/T1/` on branch `_a_T1`
   - `.arborist/worktrees/<spec>/T2/` on branch `_a_T2`

3. **post-merge** (per task): Merges task branch into parent
   - T1 → _a (base branch has NO worktree)
   - T4 → T1 (parent T1 HAS a worktree)

### Parallel Execution Model

```
Root DAG:
  branches-setup
       ↓
  merge-container-up
       ↓
    c-T1 → c-T2 → c-T3  (root tasks run SEQUENTIALLY)

Parent Task Subdag (T1):
  pre-sync
     ↓
  c-T4, c-T5, c-T6  (children run IN PARALLEL)
     ↓
  complete (run-test, post-merge, cleanup)
```

When T4, T5, T6 all finish, they all try to merge to T1's branch simultaneously.

### Git Constraints

**Key constraint**: Git only allows ONE worktree per branch.

```bash
$ git worktree add /path/one branch-x
$ git worktree add /path/two branch-x
fatal: 'branch-x' is already checked out at '/path/one'
```

This constraint helps prevent multiple worktrees for the same branch, but it is
NOT sufficient to serialize merges in Arborist:

- For child → running parent merges (e.g. T4 → T1), the parent branch is
  intentionally checked out in the parent's long-lived worktree for the entire
  child subdag.
- Attempting to create another worktree for that parent branch will *always*
  fail, which would deadlock if used as the only serialization mechanism.

---

## Proposed Solution

### Design Goals

1. **Container-safe paths**: Merge operations must reference paths that exist inside the devcontainer.
2. **Predictable serialization**: At most one merge into a given `parent_branch` at a time.
3. **Simple, cross-platform locking**: Avoid Unix-only primitives (`fcntl`) and avoid parsing git stderr as a coordination mechanism.
4. **DAGU-native retries**: Prefer DAGU step retries (delay=60s, count=60) over bespoke retry loops in Python.

### Architecture

```
.arborist/
├── worktrees/
│   └── <spec-id>/
│       ├── T1/                         # Task worktree (branch: _a_T1)
│       ├── T2/                         # Task worktree (branch: _a_T2)
│       └── _merge/
│           └── <parent-branch-hash>/   # Temp merge worktree (only when parent has no worktree)
└── locks/
    └── <spec-id>/
        └── merge_<parent-branch-hash>/ # Atomic lock directory (per parent branch)
            └── meta.json               # Debug metadata (pid, branch, acquired_at)
```

Key decision: lock is keyed by `(spec_id, parent_branch)`, not by worktree path.

### Unified Post-Merge Flow

Pseudocode (single flow for all merges):

```python
def post_merge(task_id, task_branch, parent_branch, spec_id):
    git_root = get_git_root()
    arborist_home = get_arborist_home()

    # 1) Serialize merges into the same parent branch
    with branch_merge_lock(arborist_home, spec_id, parent_branch):
        # 2) Choose a worktree to run the merge in
        parent_worktree = find_worktree_for_branch(parent_branch)

        if parent_worktree:
            # Parent branch already has a worktree (common for child -> running parent)
            merge_worktree = parent_worktree
            cleanup_worktree = False
        else:
            # Parent branch has no worktree; create a temp merge worktree inside .arborist/
            merge_worktree = arborist_home / "worktrees" / spec_id / "_merge" / hash(parent_branch)
            cleanup_worktree = True
            git worktree add <merge_worktree> <parent_branch>

        try:
            run_ai_merge(merge_worktree, task_branch, parent_branch)
            verify_merge_effect(task_branch, parent_branch, merge_worktree)
        finally:
            if cleanup_worktree:
                git worktree remove <merge_worktree> --force
```

### Container Mode: Make `cd` Work Reliably

When running the AI inside the git-root devcontainer (`devcontainer exec --workspace-folder <git_root>`), the prompt MUST `cd` using a path that exists inside that container.

Rule:
- In container mode, the merge prompt should `cd` to a repo-relative path (computed via `merge_worktree.relative_to(git_root)`), not `merge_worktree.resolve()`.

Example:
```
cd .arborist/worktrees/<spec-id>/_merge/<hash>
```

This is valid inside the merge container because it mounts the repo root.

### Locking Mechanism (Simple + Cross-Platform)

Use an atomic lock directory:

- Acquire lock by `mkdir .arborist/locks/<spec-id>/merge_<hash>`
  - `mkdir` is atomic on all supported platforms
  - if it already exists, another merge is in progress
- Write `.arborist/locks/<spec-id>/merge_<hash>/meta.json` for debugging
- Release lock by removing `meta.json` then removing the directory

Important behavior for DAGU retries:
- Lock acquisition should be **fail-fast** (no internal sleep loop). If the lock directory already exists, `task_post_merge` exits non-zero with a clear, greppable error like `LOCK_BUSY: <parent_branch>`.
- DAGU step retries will re-run the whole `post-merge` step after the configured delay.

Stale lock handling:
- Each lock writes `meta.json` with `pid` and timestamp for debugging.
- If a run crashes, a lock directory could remain. The retry loop will keep failing until the lock is removed.
- Provide an operator escape hatch (either a small `arborist spec unlock --branch <branch>` command, or document manual deletion of `.arborist/locks/<spec-id>/merge_<hash>/`).

### DAGU-Native Retry Policy (60 minutes)

Configure DAGU step retries:

- `delay_seconds: 60`
- `count: 60`

This yields up to ~1 hour of waiting for contention (lock busy or transient merge-container issues) without custom sleep loops in Python.

Where to apply retries:

1) Leaf task subdag `post-merge` step:

```yaml
- name: post-merge
  command: arborist task post-merge T001
  depends: [run-test]
  retry:
    count: 60
    delay_seconds: 60
```

2) Parent subdag: split `complete` into separate steps so only `post-merge` retries.

Current parent subdag uses a single `complete` command:
```
run-test && post-merge && post-cleanup
```

If `post-merge` is blocked, retrying `complete` would re-run tests 60 times.

Plan: change parent subdag to:

```yaml
- name: run-test
  command: arborist task run-test T001
  depends: [c-T004, c-T005, c-T006]

- name: post-merge
  command: arborist task post-merge T001
  depends: [run-test]
  retry:
    count: 60
    delay_seconds: 60

- name: post-cleanup
  command: arborist task post-cleanup T001
  depends: [post-merge]
```

This keeps the DAG semantics the same, but makes retries cheap and focused.

---

## Implementation Plan

### Files to Modify

1. **`src/agent_arborist/cli.py`** - `task_post_merge` function (~line 2039-2228)
   - Move temp merge worktrees under `.arborist/worktrees/<spec-id>/_merge/<parent-branch-hash>/`
   - Add branch-scoped lock acquisition (per `(spec_id, parent_branch)`)
   - In container mode, use repo-relative `cd` paths in the merge prompt
   - On lock contention, fail fast with a recognizable `LOCK_BUSY` error (to trigger DAGU retry)
   - Add post-merge verification guard: if branches differ pre-merge but parent HEAD is unchanged post-merge, treat as failure

2. **`src/agent_arborist/git_tasks.py`** - Add helpers
   - `branch_merge_lock(arborist_home, spec_id, parent_branch)` using atomic lock directory
   - `hash_branch(parent_branch)` utility for stable path names

3. **`src/agent_arborist/dag_builder.py`** - DAGU retries + DAG structure
   - Extend `SubDagStep` with an optional `retry` field (dict with `count`, `delay_seconds`)
   - Update `_step_to_dict()` to emit `retry` when present
   - Add `retry: {count: 60, delay_seconds: 60}` to `post-merge` steps
   - Split parent `complete` into `run-test`, `post-merge`, `post-cleanup` steps so only `post-merge` retries
   - Update any DAG-related tests that assert exact YAML shape

### Code Changes

#### A. Add branch merge lock helper (git_tasks.py)

```python
import os
import json
import time
import hashlib
from contextlib import contextmanager

@contextmanager
def branch_merge_lock(arborist_home: Path, spec_id: str, parent_branch: str):
    """Serialize merges into a parent branch (cross-platform).

    Uses an atomic lock directory under .arborist/locks/<spec-id>/.
    If the lock is busy, raise a LockBusyError so DAGU can retry.
    """
    locks_dir = arborist_home / "locks" / spec_id
    locks_dir.mkdir(parents=True, exist_ok=True)

    branch_hash = hashlib.sha1(parent_branch.encode("utf-8")).hexdigest()[:12]
    lock_dir = locks_dir / f"merge_{branch_hash}"

    try:
        os.mkdir(lock_dir)  # atomic
    except FileExistsError:
        raise LockBusyError(f"LOCK_BUSY: {parent_branch}")

    meta = lock_dir / "meta.json"
    meta.write_text(json.dumps({"parent_branch": parent_branch, "pid": os.getpid(), "acquired_at": time.time()}))

    try:
        yield
    finally:
        try:
            meta.unlink(missing_ok=True)
        finally:
            try:
                os.rmdir(lock_dir)
            except Exception:
                pass
```

#### B. Update task_post_merge (cli.py ~line 2059)

```python
from agent_arborist.git_tasks import branch_merge_lock

arborist_home = get_arborist_home()

with branch_merge_lock(arborist_home, manifest.spec_id, parent_branch):
    parent_worktree = find_worktree_for_branch(parent_branch)

    if parent_worktree:
        merge_worktree = parent_worktree
        cleanup_worktree = False
    else:
        branch_hash = hash_branch(parent_branch)
        merge_worktree = arborist_home / "worktrees" / manifest.spec_id / "_merge" / branch_hash
        cleanup_worktree = True
        _run_git("worktree", "add", str(merge_worktree), parent_branch, cwd=git_root)

    try:
        # In container mode, prompt must use repo-relative paths:
        rel = merge_worktree.relative_to(git_root)
        # AI merge + verification...
        pass
    finally:
        if cleanup_worktree:
            _run_git("worktree", "remove", str(merge_worktree), "--force", cwd=git_root, check=False)
```

#### C. Add DAGU retries + parent-step split (dag_builder.py)

- Add `retry` stanza to leaf `post-merge` steps
- Replace parent `complete` with explicit `run-test`, `post-merge`, `post-cleanup` steps
- Apply `retry` only to the `post-merge` step

---

## Testing Scenarios

1. **Single task merge to _a**
   - Create temp merge worktree under `.arborist/`, merge, cleanup

2. **Parallel root tasks merging to _a**
   - First merge acquires lock; second fails fast with `LOCK_BUSY`; DAGU retries for up to 1 hour

3. **Parallel children merging to parent (T4/T5/T6 → T1)**
   - Parent branch already checked out in T1 worktree
   - Lock serializes; merges run sequentially *in the existing parent worktree*

4. **Deep hierarchy (T8 → T4 → T1 → _a)**
   - Mix of Case A and B at each level

5. **Container mode**
   - All merge paths are repo-relative, so `cd` works inside git-root merge container

6. **Conflict resolution**
   - AI has stable worktree to resolve conflicts

---

## Cleanup

- **Temp merge worktrees**: Removed immediately after merge (in `finally` block)
- **Lock directories**: Removed on successful completion of the merge critical section; stale locks can be inspected via `meta.json`
- **Parent task worktrees**: Not affected, cleaned up by task lifecycle

---

## Benefits

1. **Container-safe**: All paths inside git repo, accessible via mount
2. **Predictable serialization**: One merge at a time per `(spec_id, parent_branch)`
3. **Cross-platform**: Atomic lock directory avoids `fcntl` and avoids git-stderr parsing
4. **Operationally robust**: DAGU retries provide a bounded, observable wait (60 x 60s)
5. **Less wasted work**: Parent subdag retries only re-run `post-merge` (not tests/cleanup)
