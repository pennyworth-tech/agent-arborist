# Redesign Research: The Git-Elegant Architecture

## Executive Summary
This document proposes a transition from a **Procedural Orchestrator** (generating static DAGs) to a **Git-Native State Machine**. By treating the Git repository not just as a destination for code, but as the primary source of truth for orchestration, we can eliminate sidecar databases, simplify state management, and enable robust, recursive task execution.

---

## 1. The Core Philosophy: "GitOps for Agents"
In an elegant design, the "Orchestrator" does not manage a list of commands; it manages a **Graph of Branches**. 
- **The Code is the State**: If a branch exists, work is in progress. If it is merged, it is complete.
- **Zero-Sidecar State**: If you delete the `.arborist` directory, the project status should be entirely rebuildable by scanning the Git tree.

---

## 2. Codifying the Branch Tree
The task hierarchy is codified directly into the Git branch naming convention, providing immediate visibility and scope isolation.

### Namespace Pattern
`{namespace}/{spec-id}/{parent-task}/{child-task}`

**Example:**
`feature/001-auth/api/validate-jwt`

- **Dashboard-by-Default**: `git branch -a` becomes a visual project dashboard.
- **Scoping**: Dependency management is handled by standard Git merges. Merging `validate-jwt` into `api` signifies the completion of a dependency.

---

## 3. Protocol Commits: Managing Sequential Steps
Instead of creating a new branch for every low-level step (Implement, Test, Review), we use a **linear chain of commits** on the leaf branch. Each commit acts as a state transition in the task's lifecycle.

### The Lifecycle Artifact Set
Every task in the tree follows a **Protocol Commit** sequence:

| Step | Commit Message / Trailer | Artifact Created |
| :--- | :--- | :--- |
| **Implement** | `Arborist-Step: implement` | Source Code / Diffs |
| **Test** | `Arborist-Step: test` | `TEST-REPORT.md` (Committed) |
| **Review** | `Arborist-Step: review` | `REVIEW.md` + `Status: Approved` |

### The Elegant Loop (Backtracking)
If a **Review** fails, the Agent simply adds a new `Implement` commit. The Orchestrator observes the sequence:
1. `implement`
2. `test` (Pass)
3. `review` (Fail)
4. `implement` (New fix)
**Action:** The Orchestrator automatically resets the state machine to re-run the `test` step because it detects a content change after a failed validation.

---

## 4. Evidence Artifacts & Attestation
To operate autonomously and reliably, the system uses **Git Trailers** to store "Evidence" without cluttering the codebase.

### Example Commit with Trailers
```text
task(T001): implement login logic

Arborist-Agent: claude-3-7-sonnet
Arborist-Status: completed
Arborist-Test-Result: pass (12/12)
Arborist-Parent-SHA: a1b2c3d4
```

- **Attestation**: The "Signature" (Trailers) allows the orchestrator to "read" the state of the tree using `git log` rather than querying an external database.
- **Context Anchors**: The `Arborist-Parent-SHA` ensures that agents are working against the correct context. If the parent moves, the task is marked "Stale" and requires a rebase.

---

## 5. Architectural Comparison

| Feature | Current "Procedural" Model | Proposed "Git-Elegant" Model |
| :--- | :--- | :--- |
| **Source of Truth** | Dagu YAML + JSON Files | Git Branch/Merge Tree |
| **Task State** | Dagu Database | Git Trailers & Merges |
| **Parallelism** | Forced Sequential (mostly) | Native (Parallel Worktrees) |
| **Artifacts** | Captured in Logs | Committed to Branch |
| **Restart/Resume** | Complex Restart Contexts | Log Traversal (`git log`) |
| **Extensibility** | Regenerate YAML | Update Branch Protocol |

---

## 6. Execution Model: The "Gardener" Controller
In this model, the execution system shifts from a "Task Queue" to a **"State Controller."** Instead of pushing tasks into a queue, you have a controller that constantly reconciles the "Actual State" (the Git tree) with the "Desired State" (the Manifest).

### The Control Loop
1.  **Discovery**: Scan all branches matching the `{namespace}/{spec-id}/**` pattern.
2.  **Inspection**: Read the latest commit message and trailers (`Arborist-Step`, `Arborist-Status`).
3.  **Planning**: Identify "stalled" branches (e.g., last commit was `implement`, but protocol requires `test`).
4.  **Dispatch**: Allocate a Worker to perform the next action.

### The Worker Pool
**Phase 1 (Single Worker)**: Uses sequential branch checkout on the primary worktree.  
**Phase 3 (Multi-Worker)**: Workers will manage dedicated **Git Worktrees**, allowing Worker A to be on `task-1` and Worker B to be on `task-2` simultaneously within the same repository without cross-talk.

---

## 7. Distributed System Coordination
In a distributed environment, the repository acts as the **Sequencer**. We utilize native Git primitives to ensure integrity across multiple workers.

### Atomic Mutexes via `git update-ref`
For low-level resource locking, we use Git's atomic reference updates:
- **Acquire**: `git update-ref refs/locks/T001 <worker-id-sha> <null-sha>`
- **Release**: `git update-ref refs/locks/T001 <null-sha> <worker-id-sha>`
Git's internal locking mechanism ensures that only one worker can successfully "claim" a task reference at a time.

### The "First-to-Push" Strategy
Distributed synchronization is enforced at the push level using `--force-with-lease`. This ensures that a worker's "State Transition" commit is only accepted if the remote branch hasn't moved. If a push is rejected, the worker must re-sync, re-evaluate the protocol, and potentially re-run the step.

### Fencing Tokens
To prevent "Zombie Workers" (slow agents writing to an expired task), every agent action is anchored to a specific **Commit SHA**. The Controller rejects any commit whose parent does not match the anchor SHA, forcing a re-sync/rebase.

---

## 8. ~~Jujutsu (jj): The Distributed State Engine~~ **[REMOVED - Git-Only Architecture]**

**Jujutsu (jj) has been removed from the implementation.**

The architecture is now **100% Git-native**. After Phase 1 implementation, we determined that:

- **Simplified Dependency**: Git is universally available; jj adds a dependency barrier
- **Sufficient Git Primitives**: Git's branch/commit/trailer mechanisms provide all necessary state management
- **Direct GitHub/GitLab Compatibility**: Pure Git workflow integrates seamlessly with remote platforms without translation layers
- **Revset Replacement**: Simple `git log --grep` patterns and trailer parsing provide equivalent query capabilities

**Note on Distributed Coordination**: While jj's conflict handling was elegant, standard Git worktrees with `--force-with-lease` push validation provide sufficient coordination for single-worker Phase 1. Multi-worker parallelism (Phase 3) will use Git worktrees and atomic ref locks instead ofjj's committable conflicts.

---

## 9. Implementation Strategy: The "Merge-Bot" Runner
Under this architecture, the **Arborist Runner** becomes a stateless loop:
1. **Discover**: Scan `git branch` for all active task branches matching `{namespace}/{spec-id}/**` pattern.
2. **Evaluate**: Read the last commit on each branch (using `git log --grep` for trailers) to determine the next step in the protocol.
3. **Dispatch**: Check out the task branch and invoke the required Agent (Implementer, Tester, Reviewer).
4. **Merge**: Once a leaf branch contains all required "Success" signatures, merge it into its hierarchical parent or base branch.
