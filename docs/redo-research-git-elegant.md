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

## 6. Implementation Strategy: The "Merge-Bot" Runner
Under this architecture, the **Arborist Runner** becomes a stateless loop:
1. **Discover**: Scan `git branch` for all active leaf branches.
2. **Evaluate**: Read the last commit on each branch to determine the next step in the protocol.
3. **Dispatch**: Spin up a `git worktree` and invoke the required Agent (Implementer, Tester, Reviewer).
4. **Merge**: Once a leaf branch contains all required "Success" signatures, merge it into its hierarchical parent.
