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
| **Phase 2** | First-class test commands, devcontainer support, hooks | **T2.0 Complete** ✅ |
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

### 2.1 — Devcontainer Integration (Future)
- Detect `.devcontainer/` in target repo
- Wrap runner commands with `devcontainer exec`
- Container lifecycle management (build, start, stop)
- Environment variable passthrough

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
