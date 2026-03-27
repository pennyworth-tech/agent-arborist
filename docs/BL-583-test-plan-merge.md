# BL-583: Deterministic test-plan.json merge for task-tree generation

## Context

When Arborist's AI planner reads a spec directory containing a large test-plan.json (199 tests), it tries to output the complete task-tree.json with all test_commands inlined (~380KB). This exceeds the AI's output capacity, causing truncation or summaries instead of valid JSON.

**Solution:** Split the work — AI outputs just the task structure with `requirement_ids` per leaf task (small JSON), then Python deterministically merges test commands from test-plan.json using requirement_ids as the join key.

## Files to Modify

- `src/agent_arborist/tree/model.py` — add `requirement_ids` field to TaskNode
- `src/agent_arborist/tree/ai_planner.py` — modify prompt, add merge function, wire into plan_tree()
- `tests/tree/test_ai_planner.py` — tests for merge logic
- `tests/tree/test_model.py` — test for requirement_ids serialization

## Steps

### 1. Add `requirement_ids` to TaskNode (model.py)

Add `requirement_ids: list[str] = field(default_factory=list)` to TaskNode dataclass. Update `to_dict()` to include it and `from_dict()` to read it with `nd.get("requirement_ids", [])`.

### 2. Modify TASK_ANALYSIS_PROMPT (ai_planner.py)

Replace the TEST COMMANDS section. Remove instructions to inline test_commands. Instead:
- Tell AI to include `requirement_ids` array on each leaf task
- Tell AI to read test-plan.json/quality artifacts to discover requirement IDs
- Tell AI to NOT include test_commands (they'll be merged post-hoc)
- Keep fallback framework templates for when no test-plan.json exists

### 3. Update `_build_tree_from_json()` (ai_planner.py)

Add `requirement_ids=t.get("requirement_ids", [])` to the TaskNode constructor call.

### 4. Add `_find_test_plan()` helper (ai_planner.py)

Search for test-plan.json in priority order:
1. `spec_dir/quality/test-plan.json`
2. `spec_dir/test-plan.json`
3. Any `test-plan.json` in immediate subdirectories

### 5. Add `_merge_test_plan()` function (ai_planner.py)

- Load test-plan.json, build index: `requirement_id -> list[test]`
- For each leaf node with requirement_ids, collect matching tests
- Deduplicate by test_id, sort by test_id for determinism
- Create TestCommand objects with test_id, name, type, command, framework, timeout
- Replace node's test_commands with merged results
- Log warning for any orphaned tests not matched to any task
- No-op if test-plan.json not found (preserves backward compat)

### 6. Wire into `plan_tree()` (ai_planner.py)

Call `_merge_test_plan(tree, spec_dir)` after `_build_tree_from_json()` succeeds, before returning.

### 7. Add tests

- `test_build_tree_from_json_with_requirement_ids` — requirement_ids parsed from JSON
- `test_merge_test_plan_basic` — tests matched to nodes by requirement_id
- `test_merge_test_plan_deduplicates` — same test via multiple req_ids appears once
- `test_merge_test_plan_no_file` — no test-plan.json, test_commands unchanged
- `test_merge_test_plan_sorted_by_test_id` — deterministic ordering
- `test_requirement_ids_roundtrip` — serialization/deserialization in model.py

## Verification

1. Run existing tests: `cd ~/Documents/backlit-testing/agent-arborist && python -m pytest tests/tree/ -v`
2. Run new tests to confirm merge logic works
3. Test end-to-end: `arborist --log-level DEBUG build --spec-dir /path/to/openspec/changes/todolist-manager --output planning/task-tree.json`
4. Verify the output task-tree.json has test_commands with test_id and name from test-plan.json
5. Verify output JSON is small (~10-20KB for structure) before merge, and complete after merge
