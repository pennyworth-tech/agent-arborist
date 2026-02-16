# Parallelism Notes for Dagu

This document outlines concurrency considerations discovered when evaluating Dagu queues with nested subDAG structures.

## Background

Arborist generates DAGs with nested subDAGs for task execution. Each task (e.g., T001, T002) becomes a subDAG containing steps like `pre-sync`, `run`, `commit`, `run-test`, and `post-merge`. The main DAG calls these subDAGs sequentially or in parallel depending on task dependencies.

## Key Finding: Queue is DAG-Level Only

**The `queue` field in Dagu is a DAG-level property, NOT a step-level property.**

From the Dagu JSON schema, valid step fields are:
- `name`, `description`, `dir`, `command`, `script`, `stdout`, `output`, `depends`, `continueOn`, `retryPolicy`, `repeatPolicy`, `signalOnStop`, `env`, `executor`, `call`, `run`, `params`, `preconditions`, `mailOnError`

The `queue` field is **not** in this list. Queue configuration belongs at the DAG level:

```yaml
name: my-dag
queue: my-queue  # DAG-level only
maxConcurrency: 2
steps:
  - name: step1
    command: echo "hello"
    # queue: NOT VALID HERE
```

## Deadlock Risk with Nested SubDAGs

When all subDAGs are placed in a single queue with limited concurrency, deadlocks can occur:

### Example Scenario

```yaml
# Main DAG
queue: shared-queue
maxConcurrency: 2
steps:
  - name: c-T001
    call: T001
  - name: c-T002
    call: T002
    depends: [c-T001]

---
# SubDAG T001
queue: shared-queue  # Same queue as parent
steps:
  - name: run
    command: some-task
```

### Deadlock Sequence

1. Main DAG starts, acquires **slot 1** from queue
2. Main DAG calls subDAG T001
3. SubDAG T001 tries to acquire a slot from the same queue
4. SubDAG T001 acquires **slot 2**
5. SubDAG T001 completes, releases slot 2
6. Main DAG proceeds to call T002
7. SubDAG T002 tries to acquire a slot
8. **DEADLOCK**: If another instance of Main DAG started and acquired slot 2, both main DAGs are now waiting for their children, but children can never acquire slots

### Slot Inflation Problem

With hierarchical nesting, a single logical operation can consume multiple queue slots:

```
Main DAG (holds slot 1)
└── SubDAG T001 (needs slot 2)
    └── Nested SubDAG (would need slot 3)
```

For a tree of depth N with branching factor B:
- Worst case slots needed: O(B^N)
- A depth-3 tree with 3 branches could need 27 slots for what's logically 1 operation

## Current Approach

**Concurrency limiting via Dagu queues has been removed from Arborist.**

Given the complexity and deadlock risks, we opted not to implement queue-based concurrency control. The current approach:

1. **No queue assignments** - DAGs and subDAGs run without queue constraints
2. **Natural parallelism** - Tasks run in parallel as dependencies allow
3. **External rate limiting** - If needed, implement rate limiting at the AI client level

## Future Considerations

If concurrency control becomes necessary:

### Option 1: Flat DAG Structure
Generate a flat DAG where all steps are at the top level, avoiding nested subDAG calls entirely.

### Option 2: maxActiveSteps
Use `maxActiveSteps` on individual subDAGs to limit parallelism within each task.

### Option 3: External Semaphore
Implement rate limiting in the runner/AI client rather than at the DAG scheduler level.

### Option 4: Separate Queues
Use different queues for main DAGs vs subDAGs to prevent parent-child deadlock.

## References

- [Dagu Documentation](https://dagu.readthedocs.io/)
- [Dagu JSON Schema](https://github.com/dagu-dev/dagu/blob/main/schemas/dag.schema.json)
