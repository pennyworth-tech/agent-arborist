# Part 5: Hooks System

Hooks inject custom steps into task execution.

## Overview

Hooks allow running custom commands during task execution. They are defined in the hooks system and injected into generated DAGs.

## Hook Points

From [`src/agent_arborist/dag_builder.py`](../../src/agent_arborist/dag_builder.py):

- `pre_sync` - Before syncing worktree
- `post_run` - After AI task execution  
- `pre_commit` - Before committing changes
- `post_commit` - After committing changes
- `pre_merge` - Before merging to parent
- `post_merge` - After merging to parent
- `cleanup` - During cleanup phase

## Configuration

```json
{
  "hooks": {
    "pre_sync": "scripts/pre-sync.sh",
    "post_run": "scripts/post-run.sh"
  }
}
```

## Hook Commands

```bash
# List hooks
arborist hooks list

# Validate hooks
arborist hooks validate

# Run hook manually
arborist hooks run pre_sync --task T001
```

## Hook Prompts

Store hook prompts in `.arborist/prompts/`:

```
.arborist/prompts/
├── pre_sync.txt
└── post_run.txt
```

See: [`src/agent_arborist/hooks/`](../../src/agent_arborist/hooks/)
