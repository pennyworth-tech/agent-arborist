# Arborist Trailers Reference

**Generated:** 2025-02-16
**Purpose:** Complete documentation of all Git commit trailers used by Arborist for task state tracking

---

## Overview

Arborist is **git-native** — all task state lives in the repository itself. No database, no state files, no daemon. Everything is recoverable from git history.

Trailers are structured key-value metadata appended to commit messages in the standard Git trailer format (e.g., `Arborist-Step: implement`).

**Key Architectural Principle:** All state lives in Git — everything is recoverable from git history.

---

## All Trailer Definitions

### Trailers

| Trailer Key | Values | Description | Used in Steps |
|-------------|--------|-------------|----------------|
| `Arborist-Step` | `implement`, `test`, `review`, `complete` | Which pipeline phase this commit represents | All steps |
| `Arborist-Result` | `pass`, `fail` | Whether the step succeeded | Implement, Complete |
| `Arborist-Test` | `pass`, `fail` | Test command result | Test |
| `Arborist-Review` | `approved`, `rejected` | Code review result | Review |
| `Arborist-Retry` | `0`, `1`, `2`, ... | Which attempt number (0-indexed) | Implement, Test, Review |
| `Arborist-Report` | `<path>` | Path to the JSON report file | Complete (success) |
| `Arborist-Test-Log` | `<path>` | Path to test output log | Test (on failure) |
| `Arborist-Review-Log` | `<path>` | Path to review output log | Review |
| `Arborist-Test-Type` | `unit`, `integration`, `e2e` | Type of test run | Test |
| `Arborist-Test-Passed` | `<count>` | Number of passed tests | Test |
| `Arborist-Test-Failed` | `<count>` | Number of failed tests | Test |
| `Arborist-Test-Skipped` | `<count>` | Number of skipped tests | Test |
| `Arborist-Test-Runtime` | `<seconds>` | Test execution time | Test |

---

## Pipeline Steps and Their Trailers

Arborist executes tasks through a **three-phase pipeline**: implement → test → review

### 1. Implement Step

**Purpose:** The AI agent implements the task requirements

**Trailers Created:**
- `Arborist-Step: implement`
- `Arborist-Result: pass` or `fail`
- `Arborist-Retry: <attempt>`

**Example Commit Message:**

**Success:**
```
task(T001): implement "Create database schema"

Runner output (truncated to 2000 chars):
Created schema.sql with users, posts, and comments tables.

Arborist-Step: implement
Arborist-Result: pass
Arborist-Retry: 0
```

**Failure:**
```
task(T001): implement "Create database schema" (failed, attempt 1/5)

Runner output truncated...

Arborist-Step: implement
Arborist-Result: fail
Arborist-Retry: 1
```

**Retry Behavior:**
- On failure, Arborist reads the failed commit body to provide "lessons learned" to the next AI implementation pass
- The `Arborist-Retry` trailer increments with each attempt (0-indexed)

---

### 2. Test Step

**Purpose:** Run automated tests to verify the implementation

**Trailers Created:**
- `Arborist-Step: test`
- `Arborist-Test: pass` or `fail`
- `Arborist-Retry: <attempt>`
- `Arborist-Test-Type: unit` or `integration` or `e2e`
- `Arborist-Test-Passed: <count>` (if parsing succeeds)
- `Arborist-Test-Failed: <count>` (if parsing succeeds)
- `Arborist-Test-Skipped: <count>` (if parsing succeeds)
- `Arborist-Test-Runtime: <seconds>`
- `Arborist-Test-Log: <path>` (on failure only)

**Example Commit Message:**

**Success:**
```
task(T001): tests pass for "Create database schema"

Test (unit) stdout (last 1000 chars):
Ran 15 tests in 3.2s
OK

Arborist-Step: test
Arborist-Test: pass
Arborist-Retry: 0
Arborist-Test-Type: unit
Arborist-Test-Passed: 15
Arborist-Test-Failed: 0
Arborist-Test-Skipped: 0
Arborist-Test-Runtime: 3.2
```

**Failure:**
```
task(T001): tests fail for "Create database schema" (attempt 1/5)

Test (unit) stderr (last 1000 chars):
FAILED test_create_user - AssertionError: Expected user table to have email column
test_create_user: line 42

Test (unit) stdout (last 1000 chars):
Ran 15 tests in 3.2s
FAILED (failures=1)

Arborist-Step: test
Arborist-Test: fail
Arborist-Retry: 1
Arborist-Test-Type: unit
Arborist-Test-Passed: 14
Arborist-Test-Failed: 1
Arborist-Test-Skipped: 0
Arborist-Test-Runtime: 3.2
Arborist-Test-Log: spec/logs/T001_test_20250216T143022.log
```

**Log File Details:**
- Test log files are created on failure only
- Stored in `spec/logs/<task-id>_test_<timestamp>.log` (or configured log directory)
- Contains full stdout and stderr from all test runs
- Multiple test type results are concatenated in order

---

### 3. Review Step

**Purpose:** An AI reviewer approves or rejects the code changes

**Trailers Created:**
- `Arborist-Step: review`
- `Arborist-Review: approved` or `rejected`
- `Arborist-Retry: <attempt>`
- `Arborist-Review-Log: <path>`

**Example Commit Message:**

**Approved:**
```
task(T001): review approved for "Create database schema"

Review:
The implementation correctly creates the required tables with appropriate
constraints. The schema follows best practices. APPROVED.

Arborist-Step: review
Arborist-Review: approved
Arborist-Retry: 0
```

**Rejected:**
```
task(T001): review rejected for "Create database schema" (attempt 1/5)

Review:
The implementation is missing foreign key constraints. The users table
should have a foreign key reference to the posts table. REJECTED.

Arborist-Step: review
Arborist-Review: rejected
Arborist-Retry: 1
Arborist-Review-Log: spec/logs/T001_review_20250216T143125.log
```

**Review Prompt Context:**
The review prompt includes:
- Task ID and name
- Git diff (truncated to 8000 chars)
- Instruction to reply APPROVED or REJECTED

---

### 4. Complete Step

#### Success Case

**Purpose:** Mark task as successfully completed with a report

**Trailers Created:**
- `Arborist-Step: complete`
- `Arborist-Result: pass`
- `Arborist-Report: <path>`

**Example Commit Message:**

```
task(T001): complete "Create database schema"

Completed after 3 attempt(s). Report: spec/reports/T001_run_20250216T143130.json

Arborist-Step: complete
Arborist-Result: pass
Arborist-Report: spec/reports/T001_run_20250216T143130.json
```

**Report File Details:**
- JSON format with task metadata
- Contains: `task_id`, `result: pass`, `retries: <number>`
- Stored in `spec/reports/<task-id>_run_<timestamp>.json` (or configured report directory)

#### Failure Case

**Purpose:** Mark task as failed after exhausting all retries

**Trailers Created:**
- `Arborist-Step: complete`
- `Arborist-Result: fail`

**Example Commit Message:**

```
task(T001): failed "Create database schema" after 5 retries

Arborist-Step: complete
Arborist-Result: fail
```

---

## State Recovery from Trailers

Arborist determines task state by reading trailers from git history:

```python
def task_state_from_trailers(trailers: dict[str, str]) -> TaskState:
    """Determine task state from its trailers."""
    step = trailers.get(TRAILER_STEP, "pending")
    
    if step == "complete":
        result = trailers.get(TRAILER_RESULT, "pass")
        return TaskState.FAILED if result == "fail" else TaskState.COMPLETE
    if step == "review":
        return TaskState.REVIEWING
    if step == "test":
        return TaskState.TESTING
    if step == "implement":
        return TaskState.IMPLEMENTING
    return TaskState.PENDING
```

**Task States:**
- **pending** — no commits found for this task
- **implementing** — last commit was an implement step
- **testing** — last commit was a test step
- **reviewing** — last commit was a review step
- **complete** — `Arborist-Step: complete` with `Arborist-Result: pass`
- **failed** — `Arborist-Step: complete` with `Arborist-Result: fail`

**State Recovery Flowchart:**

```
Read commits on phase branch matching task(ID):
         │
         ▼
Found Arborist-Step: complete?
    Yes ├── Arborist-Result: pass → COMPLETE
    No  └── Arborist-Result: fail → FAILED
         │
         ▼
    Last Arborist-Step?
         │
     ┌────┴────────┐
     │             │
implement   test      review    none
     │             │         │        │
IMPLEMENTING  TESTING  REVIEWING  PENDING
```

---

## Append-Only State Model

Arborist is **strictly append-only**:
- **No Rewrites:** Failed implementation attempts and rejected reviews stay in Git history
- **Latest Wins:** The current status of a task is always derived from the *most recent* commit matching `task(ID):`
- **Failures as Context:** When a task retries, Arborist reads the immutable body of previous failure commits to provide "lessons learned" to the next AI implementation pass

**Contrast with Other Tools:**
- Unlike tools that use `git commit --amend` or force-pushes to "clean up" work, Arborist preserves all attempts
- This creates a complete audit trail of task execution
- Enables effective AI learning from previous failures

---

## Commit Message Format

Every commit Arborist creates follows this format:

```
task(<task-id>): <subject>

<optional body with runner output or test results>

Arborist-Step: <step>
[Arborist-Result: <result>]
[Arborist-Test: <test>]
[Arborist-Review: <review>]
[Arborist-Retry: <attempt>]
[Arborist-Report: <path>]
[Arborist-Test-Log: <path>]
[Arborist-Review-Log: <path>]
[Arborist-Test-Type: <type>]
[Arborist-Test-Passed: <count>]
[Arborist-Test-Failed: <count>]
[Arborist-Test-Skipped: <count>]
[Arborist-Test-Runtime: <seconds>]
```

The `task(<id>):` prefix allows Arborist to find commits for a specific task using `git log --grep`.

---

## Example Full Task Lifecycle

Here's a complete example showing all commits from start to finish for a task that eventually passes on the second implement attempt:

**Attempt 1:**
```
task(T123): implement "Add user authentication"

Runner output (truncated to 2000 chars):
Created auth.py with login function but missing password hashing.

Arborist-Step: implement
Arborist-Result: fail
Arborist-Retry: 0
```

**Test fail:**
```
task(T123): tests fail for "Add user authentication"

Test (unit) stderr (last 1000 chars):
FAILED test_password_hashing - Password should be hashed before storage

Arborist-Step: test
Arborist-Test: fail
Arborist-Retry: 0
Arborist-Test-Type: unit
Arborist-Test-Passed: 8
Arborist-Test-Failed: 1
Arborist-Test-Skipped: 0
Arborist-Test-Runtime: 2.1
Arborist-Test-Log: spec/logs/T123_test_20250216T143000.log
```

**Attempt 2:**
```
task(T123): implement "Add user authentication"

Runner output (truncated to 2000 chars):
Updated auth.py with bcrypt password hashing. All tests pass.

Arborist-Step: implement
Arborist-Result: pass
Arborist-Retry: 1
```

**Test pass:**
```
task(T123): tests pass for "Add user authentication"

Test (unit) stdout (last 1000 chars):
Ran 10 tests in 2.5s
OK

Arborist-Step: test
Arborist-Test: pass
Arborist-Retry: 1
Arborist-Test-Type: unit
Arborist-Test-Passed: 10
Arborist-Test-Failed: 0
Arborist-Test-Skipped: 0
Arborist-Test-Runtime: 2.5
```

**Review approved:**
```
task(T123): review approved for "Add user authentication"

Review:
Password hashing is correctly implemented using bcrypt.
Authentication logic follows best practices. APPROVED.

Arborist-Step: review
Arborist-Review: approved
Arborist-Retry: 1
```

**Complete:**
```
task(T123): complete "Add user authentication"

Completed after 2 attempt(s). Report: spec/reports/T123_run_20250216T143130.json

Arborist-Step: complete
Arborist-Result: pass
Arborist-Report: spec/reports/T123_run_20250216T143130.json
```

---

## Location in Codebase

- **Trailer Constants:** `/Users/ngoodman/dev/pw/agent-arborist/src/agent_arborist/constants.py` (lines 3-16)
- **State Parsing:** `/Users/ngoodman/dev/pw/agent-arborist/src/agent_arborist/git/state.py` (lines 31-93)
- **Trailer Creation:** `/Users/ngoodman/dev/pw/agent-arborist/src/agent_arborist/worker/garden.py` (lines 384-530)
- **Documentation:** `/Users/ngoodman/dev/pw/agent-arborist/docs/manual/06-git-integration.md`

---

## Additional Resources

- See `docs/manual/06-git-integration.md` for more on Git integration and crash recovery
- See `docs/manual/05-execution.md` for how the gardener orchestrates these steps
- See `docs/manual/08-runners.md` for how implement, test, and review runners work