# Complete Redo: Git-Elegant Architecture — Task Plan

**Branch**: `feature/complete-redo-phase1`
**Strategy**: Start fresh on a new branch. Gut the existing `src/agent_arborist/` and rebuild from scratch using jj-native primitives. Keep `docs/` and `tests/fixtures/` for reference. All existing Dagu, worktree, and sequential-git code is discarded.

---

## Phase Overview

| Phase | Scope | Status |
|:------|:------|:-------|
| **Phase 1** | jj-native single-worker, tree builder, protocol commits | **Active** |
| **Phase 2** | Devcontainer support, hooks system | Future |
| **Phase 3** | Parallel workers, locking, distributed coordination | Future |

---

## Phase 1: jj-Native Single Worker

The goal is a minimal, working system where:
- A **spec directory** (markdown) is parsed into a hierarchical task tree
- The tree is materialized as **jj bookmarks** (branches) in a target repo
- A **single worker loop** pops the next ready task, runs implement → test → review, and merges completed leaves upward
- All state lives in jj changes/bookmarks — no sidecar DB, no YAML DAGs, no Dagu

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

**jj Test Helper** (`tests/conftest.py`):

All jj tests run against isolated temp directories. Since jj colocates with git, every
test repo starts with a `git init` + `jj git init --colocate` so the repo is valid for
both jj operations and git-compatible remotes.

```python
import subprocess
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

@pytest.fixture
def jj_repo(tmp_path):
    """Create a fresh git+jj colocated repo in a temp directory.

    Uses tmp_path (pytest built-in) → always under /tmp or platform equivalent.
    Fully isolated — no interaction with the real working tree.
    """
    subprocess.run(["git", "init", str(tmp_path)], check=True,
                   capture_output=True)
    subprocess.run(["jj", "git", "init", "--colocate"], cwd=tmp_path,
                   check=True, capture_output=True)
    # Set git identity for commits (required in CI / clean environments)
    subprocess.run(["git", "config", "user.email", "test@test.com"],
                   cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"],
                   cwd=tmp_path, check=True, capture_output=True)
    return tmp_path

@pytest.fixture
def jj_repo_with_bookmarks(jj_repo):
    """jj repo pre-populated with a hello-world bookmark tree.

    Parses tests/fixtures/tasks-hello-world.md and materializes the full
    bookmark hierarchy so controller/step tests have a realistic starting point.
    """
    tree = parse_spec(FIXTURES / "tasks-hello-world.md", spec_id="hello-world")
    materialize(tree, cwd=jj_repo)
    return jj_repo, tree

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

**Why git init first**: jj's `--colocate` mode requires an existing git repo. This also
ensures that all git operations (trailers, log queries) work identically to production.
Every `jj_repo` fixture is completely disposable — pytest's `tmp_path` handles cleanup.

---

### 1.0 — Project Skeleton & jj Primitives

#### T1.0.1 — Scaffold new package structure
Strip `src/agent_arborist/` to a clean skeleton:
```
src/agent_arborist/
├── __init__.py
├── cli.py            # Click CLI (minimal: build, run, status)
├── config.py         # Simplified config (runner, model, timeouts)
├── runner.py         # Keep runner abstraction (Claude, OpenCode, Gemini)
├── jj/
│   ├── __init__.py
│   ├── repo.py       # jj repo wrapper (init, log, bookmark ops)
│   ├── state.py      # Read task state from jj log/trailers
│   └── changes.py    # Create/describe/new changes
├── tree/
│   ├── __init__.py
│   ├── spec_parser.py  # Parse spec/ markdown → TaskTree
│   ├── model.py        # TaskTree, TaskNode dataclasses
│   └── materializer.py # TaskTree → jj bookmarks
├── worker/
│   ├── __init__.py
│   ├── controller.py   # The "Gardener" control loop
│   ├── protocol.py     # Protocol commit state machine
│   └── steps.py        # implement/test/review step execution
└── constants.py
```

**Test**: Import succeeds, `arborist --help` shows `build`, `run`, `status` commands. (No RED/GREEN — this is scaffolding.)

#### T1.0.2 — jj repo wrapper (`jj/repo.py`)
Thin subprocess wrapper around jj CLI:
- `jj_init(path)` — init or colocate a repo
- `jj_log(revset, template)` — query log with revsets
- `jj_bookmark_create(name, revision)` — create bookmark
- `jj_bookmark_list(pattern)` — list bookmarks matching glob
- `jj_bookmark_delete(name)` — delete bookmark
- `jj_new(parents, message)` — create new change
- `jj_describe(revision, message)` — set change description
- `jj_edit(revision)` — switch working copy
- `jj_diff(revision)` — show diff
- `jj_squash(from_rev, into_rev)` — squash changes

All functions take an optional `cwd` for the target repo.

**RED** (`tests/jj/test_repo.py`):
```python
def test_init_creates_jj_repo(tmp_path):
    """Start from bare tmp_path, init git + jj colocated."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    jj_init(tmp_path)  # should run jj git init --colocate
    assert (tmp_path / ".jj").exists()
    assert (tmp_path / ".git").exists()

def test_bookmark_roundtrip(jj_repo):
    jj_new(message="initial", cwd=jj_repo)
    jj_bookmark_create("feature/test", cwd=jj_repo)
    bookmarks = jj_bookmark_list("feature/*", cwd=jj_repo)
    assert "feature/test" in bookmarks

def test_log_with_template(jj_repo):
    jj_new(message="hello\n\nArborist-Step: implement", cwd=jj_repo)
    result = jj_log(revset="@", template="description", cwd=jj_repo)
    assert "Arborist-Step: implement" in result
```
**GREEN**: Implement `jj/repo.py` subprocess wrappers until all pass.

#### T1.0.3 — jj state reader (`jj/state.py`)
Parse jj commit descriptions to extract protocol state:
- `get_task_state(bookmark_name, cwd)` → `TaskState` enum (`pending | implementing | testing | reviewing | complete | failed`)
- `get_last_step(bookmark_name, cwd)` → last `Arborist-Step` trailer value
- `get_trailers(revision, cwd)` → dict of all `Arborist-*` trailers
- `is_task_ready(bookmark_name, cwd)` → bool (all child bookmarks merged)

Uses jj log with custom templates to extract trailers efficiently.

**RED** (`tests/jj/test_state.py`):
```python
def test_get_task_state_pending(jj_repo):
    """A bookmark with 'Arborist-Step: pending' trailer → TaskState.PENDING"""
    # set up bookmark with pending trailer
    state = get_task_state("feature/test/T001", cwd=jj_repo)
    assert state == TaskState.PENDING

def test_get_task_state_after_implement(jj_repo):
    """After implement commit → TaskState.IMPLEMENTING"""
    # add implement trailer
    state = get_task_state("feature/test/T001", cwd=jj_repo)
    assert state == TaskState.IMPLEMENTING

def test_get_trailers_parses_all(jj_repo):
    trailers = get_trailers("@", cwd=jj_repo)
    assert trailers["Arborist-Step"] == "implement"
    assert trailers["Arborist-Agent"] == "claude-sonnet"

def test_is_task_ready_no_children(jj_repo):
    """Leaf task with no deps and pending state → ready"""
    assert is_task_ready("feature/test/T001", cwd=jj_repo) is True

def test_is_task_ready_blocked_by_dep(jj_repo):
    """Task with incomplete dependency → not ready"""
    assert is_task_ready("feature/test/T002", cwd=jj_repo) is False
```
**GREEN**: Implement `jj/state.py` parsing logic.

---

### 1.1 — Tree Builder (spec → jj bookmarks)

#### T1.1.1 — Spec parser (`tree/spec_parser.py`)
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
**GREEN**: Implement `tree/spec_parser.py`.

#### T1.1.2 — Task tree model (`tree/model.py`)
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
**GREEN**: Implement `tree/model.py` dataclasses and methods.

#### T1.1.3 — AI-assisted tree generation (`tree/ai_planner.py`)
Use an LLM (via runner) to generate a TaskTree from a spec directory, similar to current `dag_generator.py`:
- Read all markdown files from spec/
- Prompt the LLM to produce a structured JSON task hierarchy
- Parse JSON into `TaskTree`
- Validate: no cycles, all dependencies exist, IDs unique

This is the "smart" path — T1.1.1 is the deterministic fallback for pre-structured specs.

**Test**: Mock the runner, verify JSON→TaskTree parsing and validation. Integration test with real LLM optional.

#### T1.1.4 — Tree materializer (`tree/materializer.py`)
Convert a `TaskTree` into jj bookmarks in the target repo:
- For each node in the tree (BFS order):
  - Create a jj change descending from the parent's bookmark (or trunk for roots)
  - Set description with `Arborist-Step: pending` trailer
  - Create bookmark: `{namespace}/{spec_id}/{path...}`
- Result: a jj repo with a bookmark tree mirroring the task hierarchy

```
trunk
├── feature/001-auth/phase1           (bookmark)
│   ├── feature/001-auth/phase1/T001  (bookmark, leaf)
│   └── feature/001-auth/phase1/T002  (bookmark, leaf)
└── feature/001-auth/phase2           (bookmark)
    └── feature/001-auth/phase2/T003  (bookmark, leaf)
```

**RED** (`tests/tree/test_materializer.py` — uses `jj_repo` fixture + parsed hello-world):
```python
def test_materialize_creates_bookmarks(jj_repo):
    tree = parse_spec(FIXTURES / "tasks-hello-world.md", spec_id="hello-world")
    materialize(tree, cwd=jj_repo)
    bookmarks = jj_bookmark_list("feature/hello-world/**", cwd=jj_repo)
    # 3 phases + 6 tasks = 9 bookmarks
    assert len(bookmarks) == 9
    assert "feature/hello-world/phase1/T001" in bookmarks

def test_materialize_sets_pending_trailers(jj_repo):
    tree = parse_spec(FIXTURES / "tasks-hello-world.md", spec_id="hello-world")
    materialize(tree, cwd=jj_repo)
    state = get_task_state("feature/hello-world/phase1/T001", cwd=jj_repo)
    assert state == TaskState.PENDING

def test_materialize_parent_child_topology(jj_repo):
    """Phase bookmark is ancestor of its task bookmarks in jj DAG."""
    tree = parse_spec(FIXTURES / "tasks-hello-world.md", spec_id="hello-world")
    materialize(tree, cwd=jj_repo)
    # jj log with revset: T001 should be descendant of phase1
    log = jj_log(
        revset='ancestors(bookmarks("feature/hello-world/phase1/T001")) & bookmarks("feature/hello-world/phase1")',
        template="bookmarks", cwd=jj_repo
    )
    assert "feature/hello-world/phase1" in log

def test_materialize_calculator_complex(jj_repo):
    """Calculator spec with 12 tasks materializes correctly."""
    tree = parse_spec(FIXTURES / "tasks-calculator.md", spec_id="calculator")
    materialize(tree, cwd=jj_repo)
    bookmarks = jj_bookmark_list("feature/calculator/**", cwd=jj_repo)
    assert len(bookmarks) == 16  # 4 phases + 12 tasks
```
**GREEN**: Implement `tree/materializer.py`.

#### T1.1.5 — `arborist build` CLI command
Wire it all together:
```
arborist build [--spec-dir ./spec] [--target-repo .] [--namespace feature] [--ai]
```
1. Parse spec dir → TaskTree (deterministic or AI-assisted with `--ai`)
2. Init/colocate jj in target repo
3. Materialize tree as bookmarks
4. Print summary: N tasks, M phases, bookmark tree

**Test**: End-to-end: create a temp dir with spec markdown, run `arborist build`, verify jj bookmarks in target.

---

### 1.2 — Protocol Commit State Machine

#### T1.2.1 — Protocol definition (`worker/protocol.py`)
Define the task lifecycle as a state machine:
```
States: pending → implementing → testing → reviewing → complete
                      ↑                         |
                      └─────── (review fail) ───┘
```

- `next_step(current_state) → Step` — what to do next
- `transition(current_state, result) → new_state` — apply result
- `Step` enum: `IMPLEMENT`, `TEST`, `REVIEW`
- Handle review failure → loop back to IMPLEMENT

Each transition produces a commit with `Arborist-Step: <step>` and `Arborist-Status: <status>` trailers.

**RED** (`tests/worker/test_protocol.py` — pure logic, no jj needed):
```python
def test_next_step_from_pending():
    assert next_step(TaskState.PENDING) == Step.IMPLEMENT

def test_next_step_from_implementing():
    assert next_step(TaskState.IMPLEMENTING) == Step.TEST

def test_next_step_from_testing():
    assert next_step(TaskState.TESTING) == Step.REVIEW

def test_next_step_from_complete_is_none():
    assert next_step(TaskState.COMPLETE) is None

def test_transition_implement_success():
    new = transition(TaskState.PENDING, StepResult(step=Step.IMPLEMENT, success=True))
    assert new == TaskState.IMPLEMENTING

def test_transition_test_pass():
    new = transition(TaskState.IMPLEMENTING, StepResult(step=Step.TEST, success=True))
    assert new == TaskState.TESTING

def test_transition_review_approved():
    new = transition(TaskState.TESTING, StepResult(step=Step.REVIEW, success=True))
    assert new == TaskState.COMPLETE

def test_transition_review_rejected_loops_back():
    new = transition(TaskState.TESTING, StepResult(step=Step.REVIEW, success=False))
    assert new == TaskState.PENDING  # back to implement

def test_transition_test_fail_loops_back():
    new = transition(TaskState.IMPLEMENTING, StepResult(step=Step.TEST, success=False))
    assert new == TaskState.PENDING  # back to implement

def test_full_happy_path():
    """pending → implement → test → review → complete"""
    state = TaskState.PENDING
    for step, success in [(Step.IMPLEMENT, True), (Step.TEST, True), (Step.REVIEW, True)]:
        state = transition(state, StepResult(step=step, success=success))
    assert state == TaskState.COMPLETE

def test_retry_path():
    """pending → implement → test ✓ → review ✗ → implement → test ✓ → review ✓"""
    state = TaskState.PENDING
    results = [
        (Step.IMPLEMENT, True), (Step.TEST, True), (Step.REVIEW, False),  # rejected
        (Step.IMPLEMENT, True), (Step.TEST, True), (Step.REVIEW, True),   # approved
    ]
    for step, success in results:
        state = transition(state, StepResult(step=step, success=success))
    assert state == TaskState.COMPLETE
```
**GREEN**: Implement `worker/protocol.py` — pure state machine, no side effects.

#### T1.2.2 — Step executors (`worker/steps.py`)
Execute each protocol step:

**implement(task, cwd, runner)**:
- Build prompt from task description + current repo state
- Invoke runner (Claude/OpenCode/Gemini)
- jj describe with `Arborist-Step: implement` trailer
- Return success/failure

**test(task, cwd)**:
- Auto-detect test command (pytest, npm test, etc.) or use configured command
- Run tests
- Create new change with `Arborist-Step: test` + `Arborist-Test-Result: pass/fail` trailers
- Return test results

**review(task, cwd, runner)**:
- Build review prompt with diff of all task changes
- Invoke runner for code review
- Create change with `Arborist-Step: review` + `Arborist-Status: approved/rejected` trailers
- Return approval/rejection + feedback

**RED** (`tests/worker/test_steps.py` — uses `jj_repo_with_bookmarks` fixture + mock runner):
```python
def test_implement_creates_change_with_trailer(jj_repo_with_bookmarks, mock_runner):
    repo, tree = jj_repo_with_bookmarks
    task = tree.nodes["T001"]
    result = implement(task, cwd=repo, runner=mock_runner)
    assert result.success is True
    state = get_task_state("feature/hello-world/phase1/T001", cwd=repo)
    assert state == TaskState.IMPLEMENTING

def test_test_step_records_pass(jj_repo_with_bookmarks):
    repo, tree = jj_repo_with_bookmarks
    # pre-condition: task already implemented
    result = test_step(tree.nodes["T001"], cwd=repo, test_command="true")
    trailers = get_trailers("@", cwd=repo)
    assert trailers["Arborist-Test-Result"] == "pass"

def test_test_step_records_fail(jj_repo_with_bookmarks):
    repo, tree = jj_repo_with_bookmarks
    result = test_step(tree.nodes["T001"], cwd=repo, test_command="false")
    assert result.success is False
    trailers = get_trailers("@", cwd=repo)
    assert trailers["Arborist-Test-Result"] == "fail"

def test_review_approved(jj_repo_with_bookmarks, mock_runner_approves):
    repo, tree = jj_repo_with_bookmarks
    result = review(tree.nodes["T001"], cwd=repo, runner=mock_runner_approves)
    trailers = get_trailers("@", cwd=repo)
    assert trailers["Arborist-Status"] == "approved"

def test_review_rejected(jj_repo_with_bookmarks, mock_runner_rejects):
    repo, tree = jj_repo_with_bookmarks
    result = review(tree.nodes["T001"], cwd=repo, runner=mock_runner_rejects)
    assert result.success is False
    trailers = get_trailers("@", cwd=repo)
    assert trailers["Arborist-Status"] == "rejected"
```
**GREEN**: Implement `worker/steps.py`.

---

### 1.3 — The Gardener Controller (Single Worker)

#### T1.3.1 — Task discovery & prioritization (`worker/controller.py`)
The control loop's "eyes":
- `discover_tasks(namespace, spec_id, cwd)` → list of active leaf bookmarks
- `inspect_task(bookmark, cwd)` → current protocol state (from trailers)
- `find_ready_task(cwd)` → first task that:
  1. Is a leaf
  2. All dependencies are `complete`
  3. Is not already `complete`
  4. Has the lowest priority/order among candidates

Uses jj revsets for efficient querying:
```
jj log -r "bookmarks(glob:'feature/spec-id/**')" --template "..."
```

**RED** (`tests/worker/test_controller.py` — uses `jj_repo_with_bookmarks`):
```python
def test_discover_finds_all_leaves(jj_repo_with_bookmarks):
    repo, tree = jj_repo_with_bookmarks  # hello-world: 6 leaf tasks
    tasks = discover_tasks("feature", "hello-world", cwd=repo)
    assert len(tasks) == 6

def test_find_ready_task_returns_first_unblocked(jj_repo_with_bookmarks):
    repo, tree = jj_repo_with_bookmarks
    task = find_ready_task(cwd=repo)
    assert task.id == "T001"  # only T001 has no deps

def test_find_ready_task_skips_completed(jj_repo_with_bookmarks):
    repo, tree = jj_repo_with_bookmarks
    # mark T001 complete
    mark_complete("feature/hello-world/phase1/T001", cwd=repo)
    task = find_ready_task(cwd=repo)
    assert task.id == "T002"  # T002 depends on T001, now unblocked

def test_find_ready_task_returns_none_when_all_done(jj_repo_with_bookmarks):
    repo, tree = jj_repo_with_bookmarks
    # mark all tasks complete
    for node in tree.leaves():
        mark_complete(tree.bookmark_name(node.id), cwd=repo)
    assert find_ready_task(cwd=repo) is None

def test_inspect_task_reads_state(jj_repo_with_bookmarks):
    repo, tree = jj_repo_with_bookmarks
    state = inspect_task("feature/hello-world/phase1/T001", cwd=repo)
    assert state == TaskState.PENDING
```
**GREEN**: Implement discovery/inspection in `worker/controller.py`.

#### T1.3.2 — Merge-up logic (`worker/controller.py`)
When a leaf task reaches `complete`:
1. Check if all sibling leaves under the same parent are `complete`
2. If yes: squash/merge all children into the parent bookmark's change
3. Mark parent as `complete`
4. Recurse: check if parent's parent is now complete
5. If root is complete: the spec is done

Uses `jj squash` or `jj rebase` to fold completed work upward.

**RED** (`tests/worker/test_merge_up.py`):
```python
def test_merge_up_single_leaf(jj_repo):
    """One leaf under parent. Complete leaf → parent auto-completes."""
    tree = make_simple_tree(phases=1, tasks_per_phase=1)
    materialize(tree, cwd=jj_repo)
    mark_complete(tree.bookmark_name("T001"), cwd=jj_repo)
    merge_up_if_complete("T001", tree, cwd=jj_repo)
    assert get_task_state(tree.bookmark_name("phase1"), cwd=jj_repo) == TaskState.COMPLETE

def test_merge_up_waits_for_siblings(jj_repo):
    """Two leaves under parent. Complete one → parent stays incomplete."""
    tree = make_simple_tree(phases=1, tasks_per_phase=2)
    materialize(tree, cwd=jj_repo)
    mark_complete(tree.bookmark_name("T001"), cwd=jj_repo)
    merge_up_if_complete("T001", tree, cwd=jj_repo)
    assert get_task_state(tree.bookmark_name("phase1"), cwd=jj_repo) != TaskState.COMPLETE

def test_merge_up_both_siblings(jj_repo):
    """Two leaves under parent. Complete both → parent auto-completes."""
    tree = make_simple_tree(phases=1, tasks_per_phase=2)
    materialize(tree, cwd=jj_repo)
    mark_complete(tree.bookmark_name("T001"), cwd=jj_repo)
    mark_complete(tree.bookmark_name("T002"), cwd=jj_repo)
    merge_up_if_complete("T002", tree, cwd=jj_repo)
    assert get_task_state(tree.bookmark_name("phase1"), cwd=jj_repo) == TaskState.COMPLETE

def test_merge_up_recursive(jj_repo):
    """All leaves done → phases done → root done (using hello-world fixture)."""
    tree = parse_spec(FIXTURES / "tasks-hello-world.md", spec_id="hello-world")
    materialize(tree, cwd=jj_repo)
    # complete all leaves in order
    for tid in ["T001","T002","T003","T004","T005","T006"]:
        mark_complete(tree.bookmark_name(tid), cwd=jj_repo)
        merge_up_if_complete(tid, tree, cwd=jj_repo)
    # all phases should be complete
    for pid in tree.root_ids:
        assert get_task_state(tree.bookmark_name(pid), cwd=jj_repo) == TaskState.COMPLETE
```
**GREEN**: Implement merge-up logic in `worker/controller.py`.

#### T1.3.3 — The main loop (`worker/controller.py`)
The "Gardener" single-worker loop:
```python
def run(namespace, spec_id, cwd, runner):
    while True:
        task = find_ready_task(cwd)
        if task is None:
            if all_complete(cwd):
                print("Spec complete!")
                break
            else:
                raise StallError("No ready tasks but spec not complete")

        execute_protocol(task, cwd, runner)  # implement → test → review
        merge_up_if_complete(task, cwd)
```

Key behaviors:
- Single-threaded, no concurrency
- On review failure: protocol loops back to implement (handled by protocol.py)
- Max retries per task (configurable, default 3)
- On stall: report which tasks are blocked and why

**RED** (`tests/worker/test_gardener_loop.py` — full e2e with mock runner + hello-world fixture):
```python
def test_gardener_completes_linear_spec(jj_repo, mock_runner_all_pass):
    """Build hello-world tree, run gardener loop, all tasks complete."""
    tree = parse_spec(FIXTURES / "tasks-hello-world.md", spec_id="hello-world")
    materialize(tree, cwd=jj_repo)
    result = run(namespace="feature", spec_id="hello-world", cwd=jj_repo, runner=mock_runner_all_pass)
    assert result.success is True
    assert result.tasks_completed == 6
    # all bookmarks should be complete
    for node in tree.leaves():
        assert get_task_state(tree.bookmark_name(node.id), cwd=jj_repo) == TaskState.COMPLETE

def test_gardener_handles_review_rejection(jj_repo, mock_runner_reject_then_pass):
    """Mock rejects first review, approves on retry. Task still completes."""
    tree = make_simple_tree(phases=1, tasks_per_phase=1)
    materialize(tree, cwd=jj_repo)
    result = run(namespace="feature", spec_id="test", cwd=jj_repo, runner=mock_runner_reject_then_pass)
    assert result.success is True

def test_gardener_respects_max_retries(jj_repo, mock_runner_always_reject):
    """Mock always rejects review. Gardener gives up after max_retries."""
    tree = make_simple_tree(phases=1, tasks_per_phase=1)
    materialize(tree, cwd=jj_repo)
    result = run(namespace="feature", spec_id="test", cwd=jj_repo,
                 runner=mock_runner_always_reject, max_retries=2)
    assert result.success is False

def test_gardener_processes_deps_in_order(jj_repo, mock_runner_all_pass):
    """Calculator spec: T001 before T002, etc."""
    tree = parse_spec(FIXTURES / "tasks-calculator.md", spec_id="calculator")
    materialize(tree, cwd=jj_repo)
    # capture processing order
    result = run(namespace="feature", spec_id="calculator", cwd=jj_repo, runner=mock_runner_all_pass)
    assert result.order.index("T001") < result.order.index("T002")
    assert result.order.index("T002") < result.order.index("T005")

def test_gardener_resumes_from_partial(jj_repo, mock_runner_all_pass):
    """Build tree, complete T001 manually, run gardener — skips T001."""
    tree = parse_spec(FIXTURES / "tasks-hello-world.md", spec_id="hello-world")
    materialize(tree, cwd=jj_repo)
    mark_complete(tree.bookmark_name("T001"), cwd=jj_repo)
    result = run(namespace="feature", spec_id="hello-world", cwd=jj_repo, runner=mock_runner_all_pass)
    assert "T001" not in result.order
    assert result.tasks_completed == 5
```
**GREEN**: Implement main loop in `worker/controller.py`.

#### T1.3.4 — `arborist run` CLI command
```
arborist run [--namespace feature] [--spec-id 001-auth] [--runner claude] [--model sonnet] [--max-retries 3]
```
1. Discover active spec from jj bookmarks (or use provided)
2. Start the Gardener loop
3. Print progress as tasks complete
4. Exit 0 on success, 1 on stall/failure

**Test**: Integration test with mock runner.

---

### 1.4 — Status & Observability

#### T1.4.1 — `arborist status` CLI command
```
arborist status [--spec-id 001-auth]
```
Read the jj bookmark tree and display:
```
feature/001-auth
├── phase1 ✓ complete
│   ├── T001 ✓ complete (implement → test ✓ → review ✓)
│   └── T002 ✓ complete (implement → test ✓ → review ✓)
└── phase2 ⧗ in-progress
    ├── T003 ⧗ testing (implement ✓ → test ...)
    └── T004 ○ pending (blocked by T003)
```

All data read from jj log + trailers. Zero sidecar state.

**Test**: Set up repo in known state, verify status output matches.

#### T1.4.2 — `arborist inspect` CLI command
Deep-dive into a single task:
```
arborist inspect T003
```
Shows: full commit history, all trailers, diffs, test results, review feedback.

**Test**: Verify output for a task with multiple protocol iterations.

---

### 1.5 — Configuration & Runner

#### T1.5.1 — Simplified config
Strip config to essentials for Phase 1:
```json
{
  "version": "2",
  "runner": "claude",
  "model": "sonnet",
  "timeouts": {
    "implement": 1800,
    "test": 300,
    "review": 600
  },
  "max_retries": 3,
  "test_command": null
}
```

Source: CLI flags > env vars > `.arborist.json` > defaults.

**Test**: Verify precedence chain.

#### T1.5.2 — Preserve runner abstraction
Keep `runner.py` largely as-is (ClaudeRunner, OpencodeRunner, GeminiRunner). Update interface to match new step signatures.

**Test**: Existing runner tests should pass with minimal changes.

---

### Phase 1 Integration Tests

#### IT-1 — Hello World end-to-end
1. Create temp dir with `spec/tasks.md` (simple 3-task linear spec)
2. `arborist build --spec-dir spec/`
3. Verify jj bookmarks created
4. `arborist run --runner mock`
5. Verify all tasks complete, tree merged to trunk
6. `arborist status` shows all green

#### IT-2 — Review failure & retry
1. Build a 1-task spec
2. Mock runner returns: implement ok → test pass → review REJECT → implement ok → test pass → review APPROVE
3. Verify the protocol loops correctly and task completes after retry

#### IT-3 — Dependency ordering
1. Build a spec with explicit dependencies (T001 → T002 → T003)
2. Verify worker processes in correct order
3. Verify T003 not started until T002 completes

#### IT-4 — Status recovery
1. Build and partially run a spec (kill mid-run)
2. `arborist status` correctly shows partial state
3. `arborist run` resumes from where it left off (no duplicate work)

---

## Phase 2: Devcontainer Support & Hooks (Future)

### 2.1 — Devcontainer Integration
- Detect `.devcontainer/` in target repo
- Wrap runner commands with `devcontainer exec`
- Container lifecycle management (build, start, stop)
- Environment variable passthrough

### 2.2 — Hooks System
- Pre/post hooks for each protocol step (implement, test, review)
- Shell hooks (run arbitrary commands)
- LLM evaluation hooks (quality gates)
- Hook config in `.arborist.json`
- Prompt template loading from `prompts/` directory

### 2.3 — Custom Protocol Steps
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
