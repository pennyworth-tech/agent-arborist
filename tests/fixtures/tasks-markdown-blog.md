# Tasks: Static Markdown Blog Generator

**Project**: Convert markdown files to static HTML blog
**Total Tasks**: 14

## Phase 1: Setup

- [ ] T001 Create project structure: `src/blog/`, `templates/`, `tests/`
- [ ] T002 Create `pyproject.toml` with markdown, jinja2, click
- [ ] T003 [P] Create `src/blog/__init__.py`
- [ ] T004 [P] Create base HTML template `templates/base.html`

**Checkpoint**: Project exists

---

## Phase 2: Parsing

- [ ] T005 Create `src/blog/parser.py` with parse_frontmatter()
- [ ] T006 Add parse_markdown() to parser.py
- [ ] T007 Create `src/blog/models.py` with Post dataclass

**Checkpoint**: Can parse markdown posts

---

## Phase 3: Rendering

- [ ] T008 Create `src/blog/renderer.py` with render_post()
- [ ] T009 Add render_index() for post listing
- [ ] T010 Create `templates/post.html` template
- [ ] T011 [P] Create `templates/index.html` template

**Checkpoint**: Can render HTML

---

## Phase 4: CLI

- [ ] T012 Create `src/blog/cli.py` with build command
- [ ] T013 Add serve command for local preview

**Checkpoint**: CLI works

---

## Phase 5: Polish

- [ ] T014 Create `README.md` with usage guide

---

## Dependencies

```
T001 → T002 → T003, T004
T003 → T005 → T006 → T007
T007 → T008 → T009
T004 → T010, T011
T009 → T012 → T013 → T014
```
