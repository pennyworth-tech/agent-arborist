# Tasks: URL Shortener API

**Project**: REST API for URL shortening
**Total Tasks**: 15

## Phase 1: Setup

- [ ] T001 Create project structure: `src/shortener/`, `tests/`
- [ ] T002 Create `pyproject.toml` with fastapi, sqlalchemy, pytest
- [ ] T003 [P] Create `src/shortener/__init__.py`
- [ ] T004 [P] Create `tests/__init__.py`

**Checkpoint**: Project scaffolded

---

## Phase 2: Data Layer

- [ ] T005 Create `src/shortener/models.py` with URL model
- [ ] T006 Create `src/shortener/database.py` with engine setup
- [ ] T007 Create `src/shortener/repository.py` with CRUD operations

**Checkpoint**: Database layer works

---

## Phase 3: Business Logic

- [ ] T008 Create `src/shortener/hasher.py` with short code generation
- [ ] T009 Create `src/shortener/service.py` with shorten_url()
- [ ] T010 Add resolve_url() to service.py

**Checkpoint**: Core logic works

---

## Phase 4: API Layer

- [ ] T011 Create `src/shortener/schemas.py` with Pydantic models
- [ ] T012 Create `src/shortener/routes.py` with POST /shorten
- [ ] T013 Add GET /{code} redirect endpoint
- [ ] T014 Create `src/shortener/main.py` with FastAPI app

**Checkpoint**: API is functional

---

## Phase 5: Polish

- [ ] T015 Create `README.md` with API documentation

---

## Dependencies

```
Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5

Within Phase 2:
T005 → T006 → T007

Within Phase 3:
T008 → T009 → T010

Within Phase 4:
T011 → T012 → T013 → T014
```
