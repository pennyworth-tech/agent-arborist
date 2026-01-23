# Tasks: CLI Calculator

**Project**: Simple command-line calculator
**Total Tasks**: 12

## Phase 1: Setup

- [ ] T001 Create project directory structure: `src/`, `tests/`
- [ ] T002 Create `pyproject.toml` with project metadata
- [ ] T003 [P] Create `src/__init__.py`
- [ ] T004 [P] Create `tests/__init__.py`

**Checkpoint**: Project structure exists

---

## Phase 2: Core Operations

- [ ] T005 Create `src/operations.py` with add() function
- [ ] T006 Add subtract() function to operations.py
- [ ] T007 [P] Add multiply() function to operations.py
- [ ] T008 [P] Add divide() function to operations.py with zero check

**Checkpoint**: All basic operations work

---

## Phase 3: CLI Interface

- [ ] T009 Create `src/cli.py` with argument parser
- [ ] T010 Add REPL mode to cli.py
- [ ] T011 Create `src/__main__.py` entry point

**Checkpoint**: CLI is usable

---

## Phase 4: Polish

- [ ] T012 Add `README.md` with usage examples

---

## Dependencies

```
T001 → T002 → T003, T004
T003 → T005 → T006 → T007, T008
T005 → T009 → T010 → T011
T011 → T012
```
