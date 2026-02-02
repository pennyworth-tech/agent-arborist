# Task Commands

Execute individual task operations.

## Run Task

```bash
arborist task run T001
arborist task run T001 --runner claude --model sonnet
arborist task run T001 --timeout 1800
```

Steps: pre-sync, run AI, commit, test, post-merge, cleanup

## Task Status

```bash
arborist task status
arborist task status --spec 001-feature
arborist task status --as-json
```

## Pre-sync

```bash
arborist task pre-sync T001
```

Sync worktree from parent branch.

## Commit

```bash
arborist task commit T001
```

Commit changes to task branch.

## Test

```bash
arborist task run-test T001
arborist task run-test T001 --cmd pytest
```

## Post-merge  

```bash
arborist task post-merge T001
arborist task post-merge T001 --continue-on-error
```

Merge task branch to parent.

## Cleanup

```bash
arborist task post-cleanup T001
arborist task post-cleanup T001 --keep-branch
```

Remove worktree and optionally keep branch.

See: [`src/agent_arborist/cli.py`](../../src/agent_arborist/cli.py#task_*)
