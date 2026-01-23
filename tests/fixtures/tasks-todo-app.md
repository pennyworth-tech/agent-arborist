# Tasks: Todo List Application

**Project**: Simple todo list with SQLite storage
**Total Tasks**: 18

## Phase 1: Setup

- [ ] T001 Create project directory structure
- [ ] T002 Create `pyproject.toml` with dependencies (click, sqlite3)
- [ ] T003 [P] Create `src/todo/__init__.py`
- [ ] T004 [P] Create `tests/__init__.py`
- [ ] T005 [P] Create `tests/conftest.py` with fixtures

**Checkpoint**: Project structure exists

---

## Phase 2: Data Layer

- [ ] T006 Create `src/todo/models.py` with TodoItem dataclass
- [ ] T007 Create `src/todo/database.py` with init_db()
- [ ] T008 Add create_todo() to database.py
- [ ] T009 Add list_todos() to database.py
- [ ] T010 Add update_todo() to database.py
- [ ] T011 Add delete_todo() to database.py

**Checkpoint**: Database operations work

---

## Phase 3: CLI Interface

- [ ] T012 Create `src/todo/cli.py` with click group
- [ ] T013 Add `add` command to cli.py
- [ ] T014 Add `list` command to cli.py
- [ ] T015 Add `done` command to cli.py
- [ ] T016 Add `remove` command to cli.py

**Checkpoint**: CLI is functional

---

## Phase 4: Polish

- [ ] T017 [P] Add `README.md` with usage
- [ ] T018 [P] Create `tests/test_database.py` with unit tests

---

## Dependencies

```
Phase 1 → Phase 2 → Phase 3 → Phase 4

Within Phase 2:
T006 → T007 → T008, T009, T010, T011

Within Phase 3:
T012 → T013, T014, T015, T016
```
