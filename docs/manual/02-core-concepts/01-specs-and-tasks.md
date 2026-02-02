# Specs and Tasks

Task specifications are markdown files defining tasks for AI execution.

## Spec Format

Specs are markdown files in `.arborist/specs/{spec_id}/tasks.md`.

**Example:**
```markdown
# Tasks: Calculator App

**Project**: Simple calculator application
**Total Tasks**: 3

## Phase 1: Core

- [ ] T001 Create add() function
- [ ] T002 Create subtract() function
- [ ] T003 Create multiply() function

## Dependencies

T001 → T002 → T003
```

## Spec Components

### Header Fields
- `# Tasks:` - Title (required)
- `**Project**` - Description
- `**Total Tasks**` - Task count (reference)

### Phases
- `## Phase N: Name` - Groups tasks
- Optional checkpoints: `**Checkpoint**: Description`

### Tasks
- `- [ ] TXXX Description` - Task definition
- `[P]` marker for parallel tasks: `- [ ] T002 [P] Description`

### Dependencies
- `## Dependencies` section
- Arrow notation: `T001 → T002`
- Multiple deps: `T001 → T002, T003`

## Spec Location

Specs live in `.arborist/specs/{spec_id}/`:

```
.arborist/specs/
├── 001-hello-world/
│   └── tasks.md
├── 002-add-feature/
│   └── tasks.md
```

The directory name (`001-hello-world`) is the `spec_id`.

## Task Format

Each task has:
- **ID**: T001, T002, ...
- **Description**: What to do
- **Parallel flag**: Optional `[P]` for execution in parallel

**From [`src/agent_arborist/task_spec.py`](../../src/agent_arborist/task_spec.py#L8-41):**
```python
class Task:
    id: str              # "T001"
    description: str     # Description
    parallel: bool       # [P] flag
    phase: str | None    # Phase name
```

## Dependencies

Dependencies define task execution order.

**Linear:**
```markdown
T001 → T002 → T003
```

**Branching:**
```markdown
T001 → T002, T003 → T004
```

T002 and T003 run in parallel after T001 completes.

**From [`src/agent_arborist/task_spec.py`](../../src/agent_arborist/task_spec.py#L104-106):**
```python
DEP_ARROW_PATTERN = re.compile(r"(T\d+)\s*→\s*([^→\n]+)")
```

## Parallel Tasks

Mark tasks as parallel with `[P]`:

```markdown
## Phase 1: Setup

- [ ] T001 Create database schema
- [ ] T002 [P] Create frontend components
- [ ] T003 [P] Setup authentication

## Dependencies

T002, T003 → T004
```

T002 and T003 can execute in parallel.

## Task Best Practices

1. **Size**: Tasks should take 15-30 minutes for AI
2. **Clarity**: Be specific about expected outputs
3. **Independence**: Tasks should have clear boundaries
4. **Testing**: Include test requirements in task descriptions

## Example: Real-World Spec

```markdown
# Tasks: Add User Authentication

**Project**: User authentication feature
**Total Tasks**: 5

## Phase 1: Backend

- [ ] T001 Create users table migration
- [ ] T002 Create User model with password hashing
- [ ] T003 Implement login endpoint
- [ ] T004 Add JWT token generation

## Phase 2: Frontend

- [ ] T005 Create login form component

## Dependencies

T001 → T002 → T003 → T004
T001 → T005
```

See also: [`src/agent_arborist/task_spec.py`](../../src/agent_arborist/task_spec.py)