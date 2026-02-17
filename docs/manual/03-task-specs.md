# Task Specs

Task specs are markdown files that describe the work to be done. Arborist's AI planner reads these and extracts a hierarchical task tree.

## Spec Directory

By default Arborist looks for specs in `spec/` relative to the current directory. You can override with `--spec-dir`.

```
spec/
├── tasks.md          # Main task specification
├── requirements.md   # Additional context
└── api-design.md     # Reference docs
```

All `.md` files in the spec directory are sent to the AI planner as context.

## Writing Good Specs

The AI planner is flexible — it can extract tasks from various markdown patterns. Here are some approaches:

### Phases with Task Lists

```markdown
## Phase 1: Database Layer
Set up the persistence layer with proper schema and migrations.

- [ ] T001 Design and create the database schema
- [ ] T002 Write migration scripts for initial tables
- [ ] T003 Add seed data for development

## Phase 2: API
Build the REST API on top of the database layer.

- [ ] T004 Implement CRUD endpoints for users
- [ ] T005 Add authentication middleware
- [ ] T006 Write API integration tests
```

### Nested Groupings

```markdown
## Phase 1: Frontend
### User Management
- [ ] T001 Build user registration form
- [ ] T002 Build user profile page

### Dashboard
- [ ] T003 Create main dashboard layout
- [ ] T004 Add data visualization widgets
```

### Dependencies

Declare dependencies either inline or in a dedicated section:

```markdown
## Dependencies
T004 -> T001   # T004 depends on T001
T005 -> T004   # T005 depends on T004
T006 -> T004, T005  # T006 depends on both
```

Or inline:

```markdown
- [ ] T005 Add auth middleware (depends on T004)
```

## What the AI Planner Extracts

The planner identifies:

- **Parent tasks** from headers and groupings (these become organizational nodes)
- **Leaf tasks** from list items (these are the executable work)
- **Dependencies** from explicit declarations or contextual clues
- **Task IDs** from patterns like `T001`, `TXXX`, or it generates them
- **Descriptions** from surrounding context

## Build Command

```bash
# Default: AI planning with Claude Opus
arborist build --spec-dir spec/

# Use a different runner/model for planning
arborist build --spec-dir spec/ --runner gemini --model gemini-2.5-pro

# Custom output path
arborist build --spec-dir spec/ -o my-tree.json
```

## Tips for Better Specs

1. **Be specific in task descriptions** — the AI runner will use these as implementation prompts
2. **Keep tasks small** — each leaf task should be a single coherent change
3. **Declare dependencies explicitly** — don't rely on ordering alone
4. **Group related tasks** under phases — they enable phase-level testing
5. **Include context** — additional markdown files in the spec directory provide background for the planner

---

> **Note:** Arborist also includes a deterministic markdown parser (`--no-ai` flag) that parses a strict format without calling any AI. This is primarily used for testing and CI scenarios where you want reproducible output without API calls. The format requires exact patterns like `## Phase N: Name` headers and `- [ ] TXXX Description` list items.
