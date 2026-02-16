# Complete Redo: Git-Elegant Architecture — Task Plan

**Branch**: `feature/complete-redo-phase1`
**Strategy**: Start fresh on a new branch. Gut the existing `src/agent_arborist/` and rebuild from scratch using Git-native primitives. Keep `docs/` and `tests/fixtures/` for reference. All existing Dagu, worktree, and sequential-git code is discarded.

**⚠️ ARCHITECTURAL UPDATE (Phase 1 Complete)**:
**jj (Jujutsu) has been removed entirely.** The implementation is now 100% Git-native:
- All `jj/` modules replaced with `git/` modules using subprocess wrappers
- Git branches instead of jj bookmarks for task tracking
- `git log --grep` and trailer parsing instead of jj revsets
- Simplified dependency chain (no jj installation required)
- Direct GitHub/GitLab compatibility

---

## Phase Overview

| Phase | Scope | Status |
|:------|:------|:-------|
| **Phase 1** | Git-native single-worker, tree builder, protocol commits | **Complete** ✅ |
| **Phase 2.0** | First-class test commands, per-node tests, output parsing, phase gating | **Complete** ✅ |
| **Phase 2.1** | Devcontainer support (detection, CLI wrapper, runtime wiring) | **Complete** ✅ |
| **Phase 2.2–2.3** | Hooks system, custom protocol steps | Future |
| **Phase 3** | Parallel workers, locking, distributed coordination | Future |

---

## Phase 1: Git-Native Single Worker ✅ (COMPLETE)

**The goal was a minimal, working system where:**
- A **spec directory** (markdown) is parsed into a hierarchical task tree
- The tree is materialized as **Git branches** (per phase) in a target repo
- A **single worker loop** pops the next ready task, runs implement → test → review, and merges completed leaves upward
- All state lives in Git commits/trailers — no sidecar DB, no YAML DAGs, no Dagu, no jj

**✅ IMPLEMENTED AS:**
- Phase branches (`feature/{spec-id}/{phase}`) instead of per-task bookmarks
- Git trailers in commit messages track task state through protocol steps
- Single-worker gardener loop sequentially processes ready tasks
- State recovery via `git log --grep` and trailer parsing

### Testing Strategy: RED → GREEN

Every module follows strict RED/GREEN TDD:

1. **RED**: Write failing tests *first* — before any implementation. Tests define the contract.
2. **GREEN**: Write the minimum implementation to make tests pass.
3. Tests live in `tests/` mirroring `src/` structure (e.g., `tests/tree/test_spec_parser.py`).

**Existing Test Fixtures** (preserved from current codebase, used extensively):

| Fixture File | What It Tests | Used By |
|:-------------|:--------------|:--------|
| `tests/fixtures/tasks-hello-world.md` | Simple 3-phase, 6-task linear spec (FastAPI hello world) | Spec parser, tree model, materializer, controller e2e |
| `tests/fixtures/tasks-calculator.md` | Complex 4-phase, 12-task spec with `[P]` parallel markers and branching deps | Spec parser (parallel flags), dependency resolution |
| `tests/fixtures/tasks-todo-app.md` | Mid-complexity spec | Spec parser variety |
| `tests/fixtures/tasks-url-shortener.md` | Mid-complexity spec | Spec parser variety |
| `tests/fixtures/tasks-markdown-blog.md` | Mid-complexity spec | Spec parser variety |
| `tests/fixtures/tasks-weather-cli.md` | Mid-complexity spec | Spec parser variety |
| `tests/fixtures/dag-simple.json` | Expected tree structure (3 tasks, parent-child) | Tree model golden-file validation |
| `tests/fixtures/dag-parallel.json` | Expected tree with parallel branches | Tree model golden-file validation |

**New Fixtures to Create**:
- `tests/fixtures/expected-hello-world-tree.json` — golden-file: expected `TaskTree` from parsing `tasks-hello-world.md`
- `tests/fixtures/expected-calculator-tree.json` — golden-file: expected `TaskTree` from parsing `tasks-calculator.md`
- `tests/fixtures/mock-runner-responses.json` — canned implement/test/review responses for mock runner

**Git Test Helper** (`tests/conftest.py`):

> **CRITICAL: Test Repo Isolation**
>
> Tests MUST NEVER run against the agent-arborist project repo. Every test that
> touches git creates a **completely separate, disposable repository** under
> `/tmp` via pytest's `tmp_path`. No test should `os.chdir()` into or operate on
> the working tree at `/Users/.../agent-arborist`. The `git_repo` fixture enforces
> this — all git wrapper calls receive an explicit `cwd=tmp_path` argument.
> Any function that defaults `cwd` to the current directory is a bug.

```python
import os
import subprocess
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

# Safety guard: abort if any test accidentally runs in the project repo
PROJECT_ROOT = Path(__file__).parent.parent

@pytest.fixture(autouse=True)
def _guard_project_repo(tmp_path, monkeypatch):
    """Prevent tests from accidentally modifying the project repo.

    Sets CWD to tmp_path for every test. Any git operation that omits
    the cwd argument will hit the temp dir, not the project.
    """
    monkeypatch.chdir(tmp_path)

@pytest.fixture
def git_repo(tmp_path):
    """Create a fresh git repo in an isolated temp directory.

    - Lives under /tmp (pytest tmp_path) — completely separate from project repo
    - Initializes git only (no jj dependency)
    - Sets dummy git identity for commits
    - All downstream code MUST pass cwd=git_repo to every git call
    """
    repo_dir = tmp_path / "test-repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init", str(repo_dir)], check=True,
                   capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"],
                   cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"],
                   cwd=repo_dir, check=True, capture_output=True)
    # Sanity: confirm this is NOT the project repo
    assert str(repo_dir) != str(PROJECT_ROOT)
    assert not (repo_dir / "pyproject.toml").exists()
    return repo_dir

@pytest.fixture
def mock_runner_all_pass():
    """Runner that always returns success for implement/review."""
    return MockRunner(implement_ok=True, review_ok=True)

@pytest.fixture
def mock_runner_reject_then_pass():
    """Runner that rejects first review, approves second."""
    return MockRunner(implement_ok=True, review_sequence=[False, True])

@pytest.fixture
def mock_runner_always_reject():
    """Runner that always rejects review."""
    return MockRunner(implement_ok=True, review_ok=False)
```

**Isolation guarantees:**
1. `tmp_path` → pytest creates a unique `/tmp/pytest-XXXX/` dir per test, auto-cleaned
2. `jj_repo` creates `test-repo/` *inside* `tmp_path` — double-nested, no ambiguity
3. `_guard_project_repo` (autouse) → `monkeypatch.chdir(tmp_path)` so even code that
   forgets `cwd=` hits the temp dir, not the project
4. Assertion in `jj_repo` explicitly verifies the path is not the project root
5. All `jj/repo.py` wrapper functions take a **required** `cwd` parameter (not optional)

---

### 1.0 — Project Skeleton & Git Primitives ✅

#### T1.0.1 — Scaffold new package structure ✅
Strip `src/agent_arborist/` to a clean skeleton:
```
src/agent_arborist/
├── __init__.py
├── cli.py            # Click CLI (build, garden, gardener, status, init)
├── config.py         # Simplified config (runner, model, timeouts)
├── runner.py         # Keep runner abstraction (Claude, OpenCode, Gemini)
├── git/
│   ├── __init__.py
│   ├── repo.py       # Git repo wrapper (init, log, branch ops)
│   └── state.py      # Read task state from git log/trailers
├── tree/
│   ├── __init__.py
│   ├── spec_parser.py  # Parse spec/ markdown → TaskTree
│   ├── model.py        # TaskTree, TaskNode dataclasses
│   └── ai_planner.py   # AI-assisted task tree generation
├── worker/
│   ├── __init__.py
│   ├── garden.py       # Single task executor (implement → test → review)
│   └── gardener.py     # The "Gardener" control loop
└── constants.py
```

✅ **COMPLETED**: All modules implemented. `arborist --help` shows `init`, `build`, `garden`, `gardener`, `status` commands.

#### T1.0.2 — Git repo wrapper (`git/repo.py`) ✅
Thin subprocess wrapper around Git CLI:
- `git_init(path)` — init a git repo
- `git_log(branch, fmt, cwd)` — query log with grep
- `git_checkout(branch, cwd, create)` — checkout/create branch
- `git_current_branch(cwd)` — get current branch name
- `git_commit(message, cwd)` — commit with message
- `git_merge(branch, cwd)` — merge branch
- `git_diff(ref1, ref2, cwd)` — show diff
- `git_branch_exists(branch, cwd)` — check if branch exists
- `git_toplevel(cwd)` — get repo root

All functions take a **required** `cwd` parameter — never default to the current directory. This prevents accidental operations against the project repo during tests.

✅ **COMPLETED**: `git/repo.py` implemented with all necessary Git primitives. Tests in `tests/git/test_repo.py` pass.

#### T1.0.3 — Git state reader (`git/state.py`) ✅
Parse Git commit trailers to extract protocol state:
- `get_task_trailers(branch, task_id, cwd)` → dict of all `Arborist-*` trailers from git log
- `task_state_from_trailers(trailers)` → `TaskState` enum (`pending | implementing | testing | reviewing | complete | failed`)
- `is_task_complete(branch, task_id, cwd)` → bool
- `scan_completed_tasks(tree, cwd)` → set of completed task IDs

Uses `git log --grep` with trailer parsing to extract state efficiently.

✅ **COMPLETED**: `git/state.py` implements all state reading functions. Tests in `tests/git/test_state.py` pass.

---

### 1.1 — Tree Builder (spec → task-tree.json) ✅

#### T1.1.1 — Spec parser (`tree/spec_parser.py`) ✅
Parse the spec directory markdown into a `TaskTree`:
- Read all `.md` files from `spec/` directory
- Extract hierarchical task structure (phases → tasks)
- Support existing format: `## Phase N: Name` headers, `- [ ] TXXX Description` items
- Detect dependencies from `## Dependencies` section
- Output: `TaskTree` with parent/child relationships

Reuse logic from existing `task_spec.py` but simplify — no AI generation, pure deterministic parsing.

**RED** (`tests/tree/test_spec_parser.py` — uses existing fixtures):
```python
FIXTURES = Path(__file__).parent.parent / "fixtures"

def test_parse_hello_world_phases():
    tree = parse_spec(FIXTURES / "tasks-hello-world.md", spec_id="hello-world")
    assert len(tree.root_ids) == 3  # Phase 1, 2, 3
    assert tree.nodes["phase1"].name == "Setup"
    assert tree.nodes["phase2"].name == "Implementation"

def test_parse_hello_world_tasks():
    tree = parse_spec(FIXTURES / "tasks-hello-world.md", spec_id="hello-world")
    assert "T001" in tree.nodes
    assert tree.nodes["T001"].description == "Create project directory with `src/`"
    assert tree.nodes["T001"].parent == "phase1"

def test_parse_hello_world_dependencies():
    tree = parse_spec(FIXTURES / "tasks-hello-world.md", spec_id="hello-world")
    assert "T001" in tree.nodes["T002"].depends_on
    assert "T003" in tree.nodes["T004"].depends_on
    assert "T003" in tree.nodes["T005"].depends_on

def test_parse_hello_world_leaves():
    tree = parse_spec(FIXTURES / "tasks-hello-world.md", spec_id="hello-world")
    leaf_ids = {n.id for n in tree.leaves()}
    assert leaf_ids == {"T001", "T002", "T003", "T004", "T005", "T006"}

def test_parse_calculator_parallel_markers():
    tree = parse_spec(FIXTURES / "tasks-calculator.md", spec_id="calculator")
    assert len(tree.root_ids) == 4  # 4 phases
    # T003 and T004 are parallel (both depend on T002, no dep on each other)
    assert "T003" not in tree.nodes["T004"].depends_on
    assert "T004" not in tree.nodes["T003"].depends_on

def test_parse_calculator_branching_deps():
    """Calculator has branching: T006 → T007, T008 (both depend on T006)"""
    tree = parse_spec(FIXTURES / "tasks-calculator.md", spec_id="calculator")
    assert "T006" in tree.nodes["T007"].depends_on
    assert "T006" in tree.nodes["T008"].depends_on

def test_parse_all_fixtures_no_crash():
    """Smoke test: every fixture file parses without error."""
    for f in FIXTURES.glob("tasks-*.md"):
        tree = parse_spec(f, spec_id=f.stem)
        assert len(tree.nodes) > 0
```
✅ **COMPLETED**: `tree/spec_parser.py` implements all parsing logic. Tests in `tests/tree/test_spec_parser.py` pass.

#### T1.1.2 — Task tree model (`tree/model.py`) ✅
Dataclasses for the task hierarchy:
```python
@dataclass
class TaskNode:
    id: str                    # e.g. "T001"
    name: str                  # human-readable
    description: str
    parent: Optional[str]      # parent node id
    children: list[str]        # child node ids
    depends_on: list[str]      # explicit dependencies
    is_leaf: bool              # only leaves get worked on

@dataclass
class TaskTree:
    spec_id: str               # e.g. "001-auth"
    namespace: str             # e.g. "feature"
    nodes: dict[str, TaskNode]
    root_ids: list[str]        # top-level phase nodes

    def leaves() -> list[TaskNode]
    def ready_leaves(completed: set[str]) -> list[TaskNode]
    def bookmark_name(node_id: str) -> str  # → "feature/001-auth/phase1/T001"
```

**RED** (`tests/tree/test_model.py`):
```python
def test_leaves_returns_only_leaf_nodes():
    tree = make_tree()  # helper: phase1 → T001, T002
    leaves = tree.leaves()
    assert {l.id for l in leaves} == {"T001", "T002"}

def test_ready_leaves_respects_dependencies():
    tree = make_tree()  # T001 → T002 (T002 depends on T001)
    ready = tree.ready_leaves(completed=set())
    assert [r.id for r in ready] == ["T001"]

def test_ready_leaves_after_completion():
    tree = make_tree()
    ready = tree.ready_leaves(completed={"T001"})
    assert "T002" in [r.id for r in ready]

def test_bookmark_name_hierarchy():
    tree = make_tree(namespace="feature", spec_id="001-auth")
    assert tree.bookmark_name("T001") == "feature/001-auth/phase1/T001"
    assert tree.bookmark_name("phase1") == "feature/001-auth/phase1"
```
✅ **COMPLETED**: `tree/model.py` implements all dataclasses and methods. Tests in `tests/tree/test_model.py` pass.

#### T1.1.3 — AI-assisted tree generation (`tree/ai_planner.py`) ✅
Use an LLM (via runner) to generate a TaskTree from a spec directory:
- Read all markdown files from spec/
- Prompt the LLM to produce a structured JSON task hierarchy
- Parse JSON into `TaskTree`
- Validate: no cycles, all dependencies exist, IDs unique

This is the "smart" path — T1.1.1 is the deterministic fallback for pre-structured specs.

✅ **COMPLETED**: `tree/ai_planner.py` implements LLM-based tree generation. Tests in `tests/tree/test_ai_planner.py` pass.

#### T1.1.4 — ~~Tree materializer~~ **[REMOVED - Not Needed]**
The original spec called for materializing a TaskTree into jj/bookmarks per task. The actual implementation uses:

- **Phase branches** instead of per-task bookmarks (`feature/{spec-id}/{phase}`)
- Task state tracked via **Git trailers** in commit history
- Lazy branch creation when tasks execute (not upfront materialization)

This simplifies the workflow and reduces branch proliferation.

#### T1.1.5 — `arborist build` CLI command ✅
Wire it all together:
```
arborist build [--spec-dir ./spec] [--namespace feature] [--no-ai] [--runner claude] [--model opus]
```
1. Parse spec dir → TaskTree (deterministic or AI-assisted without `--no-ai`)
2. Write `task-tree.json` to disk
3. Print summary: N nodes, M leaves, execution order

✅ **COMPLETED**: `build` command in `cli.py` implements spec parsing and tree JSON export. Integration tests pass.

---

### 1.2 — Protocol Commit State Machine ✅

#### T1.2.1 — Protocol definition ~~(`worker/protocol.py`)~~ **[IMPLICIT in garden.py]**
Define the task lifecycle as a state machine:
```
States: pending → implementing → testing → reviewing → complete
                      ↑                         |
                      └─────── (review fail) ───┘
```

- Implicit state transitions in `garden()` via commit trailers
- `git/state.py` provides `task_state_from_trailers()` function
- Retry loop handles test failure → re-implement, review rejection → re-implement

Each transition produces a commit with `Arborist-Step: <step>` and `Arborist-Result/Review/Test` trailers.

✅ **COMPLETED**: Protocol state machine implemented implicitly in `worker/garden.py`. No separate `protocol.py` module needed.

#### T1.2.2 — Step executors ~~(`worker/steps.py`)~~ **[INTEGRATED in garden.py]** ✅
Execute each protocol step (integrated into `garden()`):

**implement(task, cwd, implement_runner, log_dir)**:
- Build prompt from task description + current repo state
- Invoke runner (Claude/OpenCode/Gemini)
- Git commit with `Arborist-Step: implement` + `Arborist-Result` trailers
- Write log file if log_dir provided
- Return success/failure

**test(task, cwd, test_command, log_dir)**:
- Run configured test command (subprocess)
- Create git commit with `Arborist-Step: test` + `Arborist-Test` trailers
- Write log file with test output on failure
- Return test pass/fail

**review(task, cwd, review_runner, log_dir)**:
- Build review prompt with git diff
- Invoke runner for code review
- Create git commit with `Arborist-Step: review` + `Arborist-Review` trailers
- Write log file with review feedback
- Return approval/rejection

✅ **COMPLETED**: All step executors integrated in `worker/garden.py`. Tests in `tests/worker/test_garden.py` and integration tests verify correctness.

---

### 1.3 — The Gardener Controller (Single Worker) ✅

#### T1.3.1 — Task discovery & prioritization (`worker/garden.py`) ✅
The control loop's "eyes":
- `scan_completed_tasks(tree, cwd)` → set of completed task IDs (from git trailers)
- `find_next_task(tree, cwd)` → next ready task in execution order with satisfied deps
- Task selection respects dependency graph and execution order (computed by `TaskTree.compute_execution_order()`)

✅ **COMPLETED**: Discovery and prioritization logic in `worker/garden.py`. Tests in `tests/worker/test_garden.py` verify correct task selection.

#### T1.3.2 — Merge-up logic (`worker/garden.py`) ✅
When a leaf task reaches `complete`:
1. `_merge_phase_if_complete()` checks if all leaves under the same root phase are complete
2. If yes: git merge the phase branch into the base branch
3. Return to base branch after merge
4. No recursive parent merging needed (phases merge directly to base)

Uses `git merge --no-ff` to fold completed phase work into base branch.

✅ **COMPLETED**: Phase merge logic in `worker/garden.py`. Integration tests verify correct merge behavior.

#### T1.3.3 — The main loop (`worker/gardener.py`) ✅
The "Gardener" single-worker loop:
```python
def gardener(tree, cwd, implement_runner, review_runner, ...):
    while True:
        completed = scan_completed_tasks(tree, cwd)
        # All done?
        if all_leaves <= completed:
            return GardenerResult(success=True)
        # Any ready task?
        next_task = find_next_task(tree, cwd)
        if next_task is None:
            return GardenerResult(success=False, error="stalled")
        # Run one task
        garden_result = garden(tree, cwd, ...)
        if garden_result.success:
            result.tasks_completed += 1
            result.order.append(garden_result.task_id)
        else:
            return GardenerResult(success=False, error=...)
```

Key behaviors:
- Single-threaded, no concurrency (Phase 1)
- On review/test failure: retry loop (max_retries configurable)
- On stall: report "no ready tasks" error
- Returns summary with tasks_completed and order

✅ **COMPLETED**: Main gardener loop in `worker/gardener.py`. Integration tests (test_integration.py, test_e2e_steps.py) verify full workflow.

#### T1.3.4 — `arborist gardener` CLI command ✅
```
arborist gardener --tree task-tree.json [--runner claude] [--model sonnet] [--max-retries 3] [--target-repo .]
```
1. Load task tree from JSON (generated by `arborist build`)
2. Start the Gardener loop
3. Print progress as tasks complete
4. Exit 0 on success, 1 on stall/failure

✅ **COMPLETED**: `gardener` command in `cli.py`. Integration tests verify end-to-end task execution.

---

### 1.4 — Status & Observability ✅

#### T1.4.1 — `arborist status` CLI command ✅
```
arborist status --tree task-tree.json [--target-repo .]
```
Read the git commit trailers to determine task state and display:
```
feature/hello-world
├── phase1 [cyan]Phase 1[/cyan]
│   └── T001 [dim]Create project directory[/dim] [green]OK[/green]
│   └── T002 [dim]Write hello world function[/dim] [green]OK[/green]
└── phase2 [cyan]Phase 2[/cyan]
    │   └── T003 [dim]Add tests[/dim] [yellow]...[/yellow]
    └── T004 ○ [dim]Write API[/dim] [dim]--[/dim]
```

All data read from git log + trailers. Zero sidecar state.

✅ **COMPLETED**: `status` command in `cli.py` reads task state from git trailers and displays rich output. Tests verify correct state detection.

#### T1.4.2 — `arborist inspect` CLI command ✅
Deep-dive into a single task:
```
arborist inspect --tree task-tree.json --task-id T003
```
Shows: task metadata, git state, full commit history with trailers, test commands, and test result metadata.

✅ **COMPLETED**: `inspect` command in `cli.py` shows full task details including test commands and result metadata.

---

### 1.5 — Configuration & Runner ✅

#### T1.5.1 — Simplified config ✅
Strip config to essentials for Phase 1:
```json
{
  "version": "1",
  "defaults": {
    "runner": "claude",
    "model": "sonnet",
    "max_retries": 5
  },
  "steps": {
    "run": {"runner": null, "model": null},
    "implement": {"runner": null, "model": null},
    "review": {"runner": null, "model": null},
    "post-merge": {"runner": null, "model": null}
  },
  "test": {
    "command": null,
    "timeout": null
  },
  "timeouts": {
    "task_run": 1800,
    "task_post_merge": 300,
    "runner_timeout": 600
  }
}
```

Source: CLI flags > env vars > `.arborist/config.json` > ~/.arborist_config.json > defaults.

✅ **COMPLETED**: `config.py` implements hierarchical config system with precedence chain. Tests verify correct merging.

#### T1.5.2 — Preserve runner abstraction ✅
Keep `runner.py` (Claude, OpenCode, Gemini runners) with minimal interface updates:
- `Runner.run(prompt: str, cwd: Path, timeout: int | None)` → `RunnerResult`
- `_extract_commit_summary()` extracts meaningful commit message from AI output
- `get_runner()` factory function instantiates correct runner type

✅ **COMPLETED**: `runner.py` preserves abstraction with simplified interface. All runners work with the new garden workflow.

---

### Phase 1 Integration Tests ✅

#### IT-1 — Hello World end-to-end ✅
1. Create temp dir with `spec/tasks.md` (simple 3-task linear spec)
2. `arborist build --spec-dir spec/`
3. Verify `task-tree.json` created
4. `arborist gardener --tree task-tree.json` with mock runner
5. Verify all tasks complete, commits trailered correctly
6. `arborist status --tree task-tree.json` shows all green

✅ **VERIFIED**: `test_integration.py::TestBuildFromSpec` and `TestGardenerFullLoop` pass.

#### IT-2 — Review failure & retry ✅
1. Build a 1-task spec
2. Mock runner returns: implement ok → test pass → review REJECT → implement ok → test pass → review APPROVE
3. Verify the protocol loops correctly and task completes after retry

✅ **VERIFIED**: Tests in `test_e2e_steps.py` verify retry behavior.

#### IT-3 — Dependency ordering ✅
1. Build a spec with explicit dependencies (T001 → T002 → T003)
2. Verify worker processes in correct order
3. Verify T003 not started until T002 completes

✅ **VERIFIED**: `test_integration.py::TestGardenerFullLoop` verifies dependency respect.

#### IT-4 — Status recovery ✅
1. Build and partially run a spec (kill mid-run)
2. `arborist status` correctly shows partial state from git trailers
3. `arborist gardener` resumes from where it left off (no duplicate work)

✅ **VERIFIED**: `test_integration.py::TestGardenerRepeatedEquivalence` verifies resume behavior.

---

## Phase 2: First-Class Test Commands & Beyond

### 2.0 — First-Class Test Commands ✅

**Branch**: `feature/complete-redo-phase2`

Currently, `test_command` is a single global string passed via CLI/config. This upgrade makes tests a real system: per-node test commands in the task tree JSON, framework-aware output parsing, enhanced trailers, and phase-level test gating.

**Design decisions:**
- Phase tests (integration/e2e) block merge: parent node tests must pass before phase branch merges to base
- AI generates test commands: the planner infers test commands from task context
- Backward compatible: trees without `test_commands` fall back to global `test_command`

#### T2.0.1 — Data model: `TestCommand` + `TestType` ✅
- Added `TestType` enum (unit, integration, e2e) and `TestCommand` dataclass to `tree/model.py`
- Added `test_commands: list[TestCommand]` field on `TaskNode`
- Updated `to_dict()` / `from_dict()` for serialization; old trees default to `[]`

#### T2.0.2 — New trailer constants ✅
- `TRAILER_TEST_TYPE`, `TRAILER_TEST_PASSED`, `TRAILER_TEST_FAILED`, `TRAILER_TEST_SKIPPED`, `TRAILER_TEST_RUNTIME`

#### T2.0.3 — Test execution refactor in `garden.py` ✅
- Extracted `_run_tests()` with `TestResult` dataclass
- Per-node test commands with fallback to global `test_command`
- `_parse_test_counts()` for pytest, jest/vitest, and go test output
- Config timeout support (no more hardcoded 300s)
- Enhanced trailers with test type, counts, and runtime

#### T2.0.4 — Phase-level test gating ✅
- `_merge_phase_if_complete()` now runs parent node's integration/e2e tests before merging
- Phase test failure blocks merge and fails the garden run

#### T2.0.5 — AI planner test command generation ✅
- Extended `TASK_ANALYSIS_PROMPT` with test command generation instructions and framework templates
- Updated `_build_tree_from_json()` to parse `test_commands` from AI output
- Backward compatible: missing field defaults to empty list

#### T2.0.6 — CLI + inspect updates ✅
- Config test timeout passed through to `garden()` (fixes hardcoded 300s)
- `inspect` shows test commands and test result metadata from trailers

#### T2.0.7 — Docs ✅
- Updated manual docs with `test_commands` schema and test execution flow

### 2.x — Pre-Merge Cleanup / Prune (Future)
- Arborist is always append-only — never rewrites git history
- A `prune` step removes generated artifacts (`.arborist/logs/`, `spec/reports/`, etc.) from the working tree
- Commits the deletion as a final cleanup commit on the phase branch
- Prepares the branch for the user to open a clean squash-merge PR through their normal workflow

### 2.1 — Devcontainer Integration

**Branch**: `feature/complete-redo-phase2`

Arborist can optionally run AI runner and test commands inside the **target project's devcontainer**. Arborist does NOT provide a devcontainer — it detects and uses the target repo's existing `.devcontainer/` configuration.

**Design decisions:**
- **Exec + lazy up**: Use `devcontainer exec` for all in-container commands. If no container is running, `devcontainer up` is called automatically before the first exec. No explicit teardown (container persists for reuse across tasks).
- **Env var strategy**: User's responsibility. API keys (ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.) are configured via `remoteEnv` / `${localEnv:VAR}` in the user's `devcontainer.json`. Arborist does NOT manage env files or passthrough — zero arborist code for env vars.
- **Container mode**: Three modes — `auto` (default: use if `.devcontainer/` present), `enabled` (require it, fail if absent), `disabled` (never use).
- **Health check**: On first container exec, verify `git --version` is available. Fail with clear error if git is missing.
- **Testing**: Real container builds behind `@pytest.mark.container`. Existing fixtures in `tests/fixtures/devcontainers/` are used.

**What runs WHERE:**

| What | Where | Why |
|:-----|:------|:----|
| AI runner CLI (implements code, may commit) | **Container** | Needs project tooling, deps, language runtimes |
| Test commands (pytest, jest, go test) | **Container** | Needs project deps and test frameworks |
| AI review runner (reads diff, returns verdict) | **Container** | Consistent with implement; may need project context |
| Git commits with trailers (`_commit_with_trailers`) | **Host** | Arborist protocol; workspace volume-mounted so host sees AI's file changes |
| Git branch/checkout/merge/diff/log | **Host** | Arborist orchestration; sequential so no conflicts |
| Task discovery, state scanning | **Host** | Pure git log parsing |
| Gardener loop, garden() orchestration | **Host** | Control flow only |
| AI planner (`build` without `--no-ai`) | **Container** | All AI calls go through container when active |

**Key insight**: The workspace is volume-mounted. The AI agent runs inside the container and edits files (may also `git commit`). Those changes are immediately visible on the host via the mount. Arborist then does `git_add_all` + `_commit_with_trailers` on the host to record protocol state. Merges are always conflict-free because execution is sequential (single worker).

**Container requirements** (user's `.devcontainer/` must provide):
- `git` (AI agents commit inside the container; health check verifies this)
- Runner CLIs (`claude`, `opencode`, or `gemini` depending on config)
- Project language runtime and dependencies
- API key env vars via `remoteEnv` in `devcontainer.json`

**Config precedence for `container_mode`** (same pattern as runner/model):
```
CLI flag --container-mode      (highest)
    ↓
ARBORIST_CONTAINER_MODE env var
    ↓
.arborist/config.json → defaults.container_mode
    ↓
~/.arborist_config.json → defaults.container_mode
    ↓
hardcoded "auto"               (lowest)
```

**Note**: `container_mode` stays in `DefaultsConfig` — already exists in config.py. The `ARBORIST_CONTAINER_MODE` env var and config merge are already wired. Only the CLI flag and runtime resolution are missing.

---

#### T2.1.1 — Devcontainer detection & mode resolution

Add detection and resolution functions to new `src/agent_arborist/devcontainer.py`:
- `has_devcontainer(cwd: Path) -> bool` — checks for `.devcontainer/devcontainer.json`
- `should_use_container(mode: str, cwd: Path) -> bool` — resolves auto/enabled/disabled against detection
- `DevcontainerNotFoundError` — raised when mode is `enabled` but no `.devcontainer/` present
- `DevcontainerError` — base error for container operations

Config system already handles `container_mode` in `DefaultsConfig` (config.py:71), `ARBORIST_CONTAINER_MODE` env var (config.py:38), `apply_env_overrides` (config.py:936), and `merge_configs` (config.py:847). No config changes needed.

**Tests** (`tests/test_devcontainer.py`):
```python
def test_detect_devcontainer_present(tmp_path):
    (tmp_path / ".devcontainer").mkdir()
    (tmp_path / ".devcontainer/devcontainer.json").write_text("{}")
    assert has_devcontainer(tmp_path) is True

def test_detect_devcontainer_absent(tmp_path):
    assert has_devcontainer(tmp_path) is False

def test_mode_auto_with_devcontainer(tmp_path):
    (tmp_path / ".devcontainer").mkdir()
    (tmp_path / ".devcontainer/devcontainer.json").write_text("{}")
    assert should_use_container("auto", tmp_path) is True

def test_mode_auto_without_devcontainer(tmp_path):
    assert should_use_container("auto", tmp_path) is False

def test_mode_enabled_without_devcontainer_raises(tmp_path):
    with pytest.raises(DevcontainerNotFoundError):
        should_use_container("enabled", tmp_path)

def test_mode_disabled_ignores_devcontainer(tmp_path):
    (tmp_path / ".devcontainer").mkdir()
    (tmp_path / ".devcontainer/devcontainer.json").write_text("{}")
    assert should_use_container("disabled", tmp_path) is False
```

#### T2.1.2 — `devcontainer` CLI wrapper (`devcontainer.py`)

Thin wrapper around the `devcontainer` CLI, same module as T2.1.1:

```python
def devcontainer_up(workspace_folder: Path) -> None:
    """Start container for workspace. Idempotent — safe to call if already running."""
    subprocess.run(
        ["devcontainer", "up", "--workspace-folder", str(workspace_folder)],
        check=True, capture_output=True, text=True,
    )

def devcontainer_exec(
    cmd: list[str] | str,
    workspace_folder: Path,
    timeout: int | None = None,
) -> subprocess.CompletedProcess:
    """Run command inside the container.

    Args:
        cmd: Command as list or shell string. If str, wrapped in ["sh", "-c", cmd]
             to support shell syntax (pipes, &&, etc.) needed by test commands.
        workspace_folder: Path to the workspace (must contain .devcontainer/).
        timeout: Optional timeout in seconds.
    """
    if isinstance(cmd, str):
        cmd = ["sh", "-c", cmd]
    args = ["devcontainer", "exec", "--workspace-folder", str(workspace_folder)]
    args += cmd
    kwargs = {"capture_output": True, "text": True}
    if timeout is not None:
        kwargs["timeout"] = timeout
    return subprocess.run(args, **kwargs)

def is_container_running(workspace_folder: Path) -> bool:
    """Check if a devcontainer is running for this workspace."""
    result = subprocess.run(
        ["devcontainer", "up", "--workspace-folder", str(workspace_folder),
         "--expect-existing-container"],
        capture_output=True, text=True,
    )
    return result.returncode == 0

def ensure_container_running(workspace_folder: Path) -> None:
    """Lazy up: start container if not already running. Health check on first start.

    On first successful start, verifies git is available inside the container.
    Raises DevcontainerError if git is not found.
    """
    if not is_container_running(workspace_folder):
        devcontainer_up(workspace_folder)
        # Health check: git must be available for AI agents to commit
        result = devcontainer_exec(["git", "--version"], workspace_folder)
        if result.returncode != 0:
            raise DevcontainerError(
                "git is not available inside the devcontainer. "
                "AI agents need git to commit. Add git to your Dockerfile."
            )
```

**Tests** (mock subprocess):
```python
def test_devcontainer_exec_list_cmd(mock_subprocess):
    devcontainer_exec(["pytest", "tests/"], workspace_folder=Path("/repo"))
    args = mock_subprocess.call_args[0][0]
    assert args == ["devcontainer", "exec", "--workspace-folder", "/repo", "pytest", "tests/"]

def test_devcontainer_exec_string_cmd_wraps_in_shell(mock_subprocess):
    """String commands get wrapped in sh -c for shell syntax support."""
    devcontainer_exec("pytest tests/ && echo done", workspace_folder=Path("/repo"))
    args = mock_subprocess.call_args[0][0]
    assert args == ["devcontainer", "exec", "--workspace-folder", "/repo",
                    "sh", "-c", "pytest tests/ && echo done"]

def test_devcontainer_exec_with_timeout(mock_subprocess):
    devcontainer_exec(["echo", "hi"], workspace_folder=Path("/repo"), timeout=30)
    assert mock_subprocess.call_args.kwargs["timeout"] == 30

def test_ensure_container_running_calls_up_when_not_running(mock_subprocess):
    # First call (is_running check) fails, second (up) succeeds, third (health) succeeds
    mock_subprocess.side_effect = [
        subprocess.CompletedProcess(args=[], returncode=1),  # not running
        subprocess.CompletedProcess(args=[], returncode=0),  # up succeeds
        subprocess.CompletedProcess(args=[], returncode=0, stdout="git version 2.x"),  # health
    ]
    ensure_container_running(Path("/repo"))

def test_ensure_container_health_check_fails_without_git(mock_subprocess):
    mock_subprocess.side_effect = [
        subprocess.CompletedProcess(args=[], returncode=1),  # not running
        subprocess.CompletedProcess(args=[], returncode=0),  # up succeeds
        subprocess.CompletedProcess(args=[], returncode=1),  # git not found
    ]
    with pytest.raises(DevcontainerError, match="git is not available"):
        ensure_container_running(Path("/repo"))

def test_ensure_container_noop_when_already_running(mock_subprocess):
    mock_subprocess.return_value = subprocess.CompletedProcess(args=[], returncode=0)
    ensure_container_running(Path("/repo"))
    # Only one call (the is_running check), no up or health check
    assert mock_subprocess.call_count == 1
```

#### T2.1.3 — Wire devcontainer into `runner.py`

Update `_execute_command()` to use `devcontainer exec` when container mode is active:

- Currently `_execute_command(cmd, timeout, cwd, container_cmd_prefix)` takes an optional prefix
- Replace `container_cmd_prefix` with `container_workspace: Path | None`
- When `container_workspace` is set: call `ensure_container_running()`, then `devcontainer_exec(cmd, workspace_folder, timeout)`
- When not set: existing `subprocess.run(cmd, cwd=cwd)` behavior unchanged
- Update `Runner.run()` signature: replace `container_cmd_prefix` with `container_workspace`
- Update `run_ai_task()`: accept `use_container: bool`, resolve workspace, pass through

**Tests**:
```python
def test_execute_command_host_mode(mock_subprocess):
    """Without container, runs directly with cwd."""
    _execute_command(["echo", "hi"], timeout=30, cwd=Path("/repo"))
    assert mock_subprocess.call_args.kwargs["cwd"] == Path("/repo")

def test_execute_command_container_mode(mock_subprocess, mock_devcontainer):
    """With container workspace, wraps via devcontainer exec."""
    _execute_command(["echo", "hi"], timeout=30, cwd=Path("/repo"),
                     container_workspace=Path("/repo"))
    # Should have called devcontainer_exec, not subprocess directly
    mock_devcontainer.exec.assert_called_once()

def test_runner_run_passes_container_workspace(mock_subprocess, mock_devcontainer):
    runner = ClaudeRunner(model="sonnet")
    runner.run("hello", cwd=Path("/repo"), container_workspace=Path("/repo"))
    mock_devcontainer.ensure_running.assert_called_with(Path("/repo"))
```

#### T2.1.4 — Wire devcontainer into `garden.py` test execution

Update `_run_tests()` and `_merge_phase_if_complete()` to execute test commands inside the container:

- Add `container_workspace: Path | None` parameter to `_run_tests()`
- When set: use `devcontainer_exec(cmd, workspace_folder, timeout)` instead of `subprocess.run(cmd, shell=True, cwd=...)`
- Note: test commands are strings (shell syntax), so `devcontainer_exec` wraps them in `["sh", "-c", cmd]`
- Same change in `_merge_phase_if_complete()` for phase-level integration/e2e tests
- Test output parsing (`_parse_test_counts`) unchanged — works on stdout regardless
- `garden()` receives `container_workspace: Path | None` parameter, passes through to runner calls and test calls

**Updated `garden()` signature:**
```python
def garden(
    tree: TaskTree,
    cwd: Path,
    runner=None,
    *,
    implement_runner=None,
    review_runner=None,
    test_command: str = "true",
    max_retries: int = 3,
    base_branch: str = "main",
    report_dir: Path | None = None,
    log_dir: Path | None = None,
    runner_timeout: int | None = None,
    test_timeout: int | None = None,
    container_workspace: Path | None = None,  # NEW
) -> GardenResult:
```

**What changes inside `garden()`:**
- `implement_runner.run(prompt, cwd=cwd, container_workspace=container_workspace)` (line ~365)
- `review_runner.run(review_prompt, cwd=cwd, container_workspace=container_workspace)` (line ~452)
- `_run_tests(node, cwd, test_command, test_timeout, container_workspace=container_workspace)` (line ~387)
- `_merge_phase_if_complete(..., container_workspace=container_workspace)` (line ~500)

**What does NOT change:**
- ALL git operations remain on host: `git_checkout`, `git_branch_exists`, `git_add_all`, `git_commit`, `git_merge`, `git_diff`, `git_log`
- `_commit_with_trailers()` — host, uses volume-mounted workspace
- `_collect_feedback_from_git()` — host, reads git log
- `_write_log()`, report file writes — host
- `scan_completed_tasks()` — host, git log parsing

#### T2.1.5 — CLI flags + gardener/build passthrough

Add `--container-mode` / `-c` flag to **all three** runtime CLI commands:

**`garden` command:**
```python
@click.option("--container-mode", "-c", "container_mode", default=None,
              type=click.Choice(["auto", "enabled", "disabled"]),
              help="Container mode (default: from config or 'auto')")
def garden(tree_path, runner, model, ..., container_mode):
    cfg = _load_config()
    resolved_container_mode = container_mode or cfg.defaults.container_mode
    use_container = should_use_container(resolved_container_mode, target)
    container_ws = target if use_container else None
    result = garden_fn(..., container_workspace=container_ws)
```

**`gardener` command** — same flag, passes `container_workspace` through to each `garden()` call.

**`build` command** — same flag. When `use_container` is true AND `--no-ai` is NOT set, the AI planner's runner call goes through `devcontainer exec`. Pure markdown parsing (`--no-ai`) never uses container.

**Precedence** (follows existing pattern for runner/model):
```
CLI --container-mode flag    (highest, None if not provided)
    ↓
config.defaults.container_mode  (already merged from: env var > project > global > "auto")
    ↓
resolve: should_use_container(mode, cwd) → bool
```

#### T2.1.6 — Real container integration tests

Tests using the existing fixtures in `tests/fixtures/devcontainers/`. These actually build and exec into containers.

**Marker**: `@pytest.mark.container` — skipped by default, opt-in via `pytest -m container`

**Requires**: Docker daemon running + `devcontainer` CLI installed (`npm install -g @devcontainers/cli`).

```python
FIXTURES = Path(__file__).parent / "fixtures"

@pytest.mark.container
class TestDevcontainerIntegration:
    """Tests that build and run real devcontainers.

    Requires: docker daemon running, devcontainer CLI installed.
    Uses fixtures from tests/fixtures/devcontainers/
    """

    def test_minimal_container_up_and_exec(self, tmp_path):
        """Build minimal-opencode fixture, exec a command inside."""
        fixture = FIXTURES / "devcontainers" / "minimal-opencode"
        shutil.copytree(fixture, tmp_path / "project", dirs_exist_ok=True)
        project = tmp_path / "project"
        subprocess.run(["git", "init", str(project)], check=True, capture_output=True)

        devcontainer_up(project)
        result = devcontainer_exec(["echo", "hello"], workspace_folder=project)
        assert result.returncode == 0
        assert "hello" in result.stdout

    def test_health_check_git_available(self, tmp_path):
        """Health check passes — git is available in minimal-opencode fixture."""
        fixture = FIXTURES / "devcontainers" / "minimal-opencode"
        shutil.copytree(fixture, tmp_path / "project", dirs_exist_ok=True)
        project = tmp_path / "project"
        subprocess.run(["git", "init", str(project)], check=True, capture_output=True)

        # ensure_container_running does lazy-up + health check
        ensure_container_running(project)
        result = devcontainer_exec(["git", "--version"], workspace_folder=project)
        assert result.returncode == 0

    def test_all_runners_fixture_has_runners(self, tmp_path):
        """All-runners fixture has claude, opencode, gemini CLIs."""
        fixture = FIXTURES / "devcontainers" / "all-runners"
        shutil.copytree(fixture, tmp_path / "project", dirs_exist_ok=True)
        project = tmp_path / "project"
        subprocess.run(["git", "init", str(project)], check=True, capture_output=True)

        devcontainer_up(project)
        for runner_cmd in ["claude", "opencode", "gemini"]:
            result = devcontainer_exec(["which", runner_cmd], workspace_folder=project)
            assert result.returncode == 0, f"{runner_cmd} not found in container"

    def test_volume_mount_file_visibility(self, tmp_path):
        """Files created inside container are visible on host via volume mount."""
        fixture = FIXTURES / "devcontainers" / "minimal-opencode"
        shutil.copytree(fixture, tmp_path / "project", dirs_exist_ok=True)
        project = tmp_path / "project"
        subprocess.run(["git", "init", str(project)], check=True, capture_output=True)

        devcontainer_up(project)
        # Create file inside container
        devcontainer_exec(["sh", "-c", "echo 'hello' > /workspace/test-from-container.txt"],
                          workspace_folder=project)
        # Verify visible on host
        assert (project / "test-from-container.txt").read_text().strip() == "hello"

    def test_git_commit_inside_container_visible_on_host(self, tmp_path):
        """AI agent commits inside container → visible to host git."""
        fixture = FIXTURES / "devcontainers" / "minimal-opencode"
        shutil.copytree(fixture, tmp_path / "project", dirs_exist_ok=True)
        project = tmp_path / "project"
        subprocess.run(["git", "init", str(project)], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                        cwd=project, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"],
                        cwd=project, check=True, capture_output=True)
        # Initial commit on host
        (project / "README.md").write_text("init")
        subprocess.run(["git", "add", "."], cwd=project, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=project, check=True, capture_output=True)

        devcontainer_up(project)
        # Commit inside container
        devcontainer_exec(
            "echo 'new file' > newfile.txt && git add . && git commit -m 'from container'",
            workspace_folder=project,
        )
        # Host sees the commit
        result = subprocess.run(["git", "log", "--oneline", "-1"],
                                cwd=project, capture_output=True, text=True)
        assert "from container" in result.stdout

    def test_test_command_runs_inside_container(self, tmp_path):
        """Shell test commands execute inside the container, not on host."""
        fixture = FIXTURES / "devcontainers" / "minimal-opencode"
        shutil.copytree(fixture, tmp_path / "project", dirs_exist_ok=True)
        project = tmp_path / "project"
        subprocess.run(["git", "init", str(project)], check=True, capture_output=True)

        devcontainer_up(project)
        # Run a test command that uses container tooling (node is in container, may not be on host)
        result = devcontainer_exec("node --version", workspace_folder=project)
        assert result.returncode == 0
        assert result.stdout.strip().startswith("v")
```

**pytest config update** (`pyproject.toml`):
```toml
markers = [
    "integration: marks tests that require actual CLI tools",
    "git: marks tests that require git CLI",
    "slow: marks tests that are slow",
    "e2e: end-to-end tests",
    "container: marks tests that build/run real devcontainers (requires docker)",
]
```

#### T2.1.7 — Documentation

User-facing docs covering:
- **Contract**: "Bring your own `.devcontainer/`" — arborist detects and uses, never creates
- **Container requirements**: git, runner CLIs, project deps, API keys via `remoteEnv`
- **`remoteEnv` pattern** for API keys in user's `devcontainer.json`:
  ```json
  {
    "remoteEnv": {
      "ANTHROPIC_API_KEY": "${localEnv:ANTHROPIC_API_KEY}",
      "OPENAI_API_KEY": "${localEnv:OPENAI_API_KEY}",
      "GOOGLE_API_KEY": "${localEnv:GOOGLE_API_KEY}"
    }
  }
  ```
- **Container mode**: `--container-mode auto|enabled|disabled` and `ARBORIST_CONTAINER_MODE` env var
- **Execution model**: what runs in container (AI + tests) vs host (git + orchestration)
- **Troubleshooting**: runner not found, git not found (health check error), container startup fails, API keys not available (remoteEnv misconfigured)

---

**Files to create:**
- `src/agent_arborist/devcontainer.py` — detection, CLI wrapper, health check
- `tests/test_devcontainer.py` — unit tests (mock subprocess)
- `tests/test_devcontainer_integration.py` — real container tests (`@pytest.mark.container`)

**Files to modify:**
- `src/agent_arborist/runner.py` — replace `container_cmd_prefix` with `container_workspace` parameter
- `src/agent_arborist/worker/garden.py` — add `container_workspace` to `garden()`, `_run_tests()`, `_merge_phase_if_complete()`
- `src/agent_arborist/worker/gardener.py` — pass `container_workspace` through to `garden()`
- `src/agent_arborist/cli.py` — add `--container-mode` flag to `garden`, `gardener`, `build`; resolve mode → `container_workspace`
- `pyproject.toml` — add `container` marker

### 2.2 — Hooks System (Future)
- Pre/post hooks for each protocol step (implement, test, review)
- Shell hooks (run arbitrary commands)
- LLM evaluation hooks (quality gates)
- Hook config in `.arborist.json`
- Prompt template loading from `prompts/` directory

### 2.3 — Custom Protocol Steps (Future)
- Allow specs to define custom steps beyond implement/test/review
- Step plugins: lint, security scan, documentation generation
- Configurable step ordering per spec

---

## Phase 3: Parallel Workers & Locking (Future)

### 3.1 — Parallel Worker Pool
- Multiple workers processing independent leaves concurrently
- Each worker operates in a dedicated jj workspace
- Worker heartbeat/health monitoring

### 3.2 — Distributed Coordination
- Atomic task claiming via `jj` operations
- Fencing tokens (commit SHA anchoring)
- Stale task detection and recovery
- Conflict resolution for diverged work

### 3.3 — Remote Synchronization
- Push/pull protocol for distributed workers
- `--force-with-lease` style safety
- Remote bookmark scanning

---

## What Gets Deleted

Everything in `src/agent_arborist/` except:
- `runner.py` — preserved and adapted
- `config.py` — gutted and simplified

Specifically removed:
- `dag_builder.py`, `dag_generator.py` — replaced by tree builder
- `dagu_runs.py` — no more Dagu
- `task_cli.py`, `tasks.py` — replaced by worker/controller
- `task_spec.py`, `task_state.py` — replaced by tree/ modules
- `spec.py` — replaced by jj bookmark discovery
- `home.py` — no more `.arborist/` sidecar directory
- `checks.py` — replaced (check for jj instead of dagu)
- `container_runner.py`, `container_context.py` — deferred to Phase 2
- `hooks/` — deferred to Phase 2
- `viz/` — deferred (may reintroduce later)
- `step_results.py` — replaced by jj trailers
- `constants.py` — rewritten minimal
