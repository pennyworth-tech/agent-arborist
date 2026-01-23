# Tasks: Weather CLI

**Project**: Command-line weather lookup using OpenWeather API
**Total Tasks**: 10

## Phase 1: Setup

- [ ] T001 Create project structure with `src/weather/`
- [ ] T002 Create `pyproject.toml` with httpx, click, rich
- [ ] T003 [P] Create `src/weather/__init__.py`
- [ ] T004 [P] Create `.env.example` with OPENWEATHER_API_KEY

**Checkpoint**: Project scaffolded

---

## Phase 2: API Client

- [ ] T005 Create `src/weather/client.py` with WeatherClient class
- [ ] T006 Add get_current() method to client
- [ ] T007 Add get_forecast() method to client

**Checkpoint**: API client works

---

## Phase 3: CLI

- [ ] T008 Create `src/weather/cli.py` with current command
- [ ] T009 Add forecast command to cli.py

**Checkpoint**: CLI functional

---

## Phase 4: Polish

- [ ] T010 Create `README.md` with setup and usage

---

## Dependencies

```
T001 → T002 → T003, T004
T003 → T005 → T006 → T007
T007 → T008 → T009 → T010
```
