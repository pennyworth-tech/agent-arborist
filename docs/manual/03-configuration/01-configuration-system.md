# Configuration System

Agent Arborist uses JSON configuration.

## Configuration Precedence

From [`src/agent_arborist/config.py`](../../src/agent_arborist/config.py):

1. CLI flags (highest)
2. Environment variables
3. Project config (`.arborist/config.json`)
4. Global config (`~/.arborist_config.json`)
5. Code defaults (lowest)

## Global Config

Location: `~/.arborist_config.json`

```json
{
  "version": "1",
  "defaults": {
    "runner": "claude",
    "model": "sonnet",
    "container_mode": "auto"
  }
}
```

Create with:
```bash
arborist config init --global
```

## Project Config

Location: `.arborist/config.json`

```json
{
  "version": "1",
  "defaults": {
    "runner": "claude",
    "model": "sonnet",
    "container_mode": "enabled"
  },
  "timeouts": {
    "task_run": 3600,
    "test": 300
  },
  "hooks": {
    "pre_sync": "scripts/pre-sync.sh"
  }
}
```

Create with:
```bash
arborist config init
```

## Configuration Fields

See [`src/agent_arborist/config.py`](../../src/agent_arborist/config.py) for full schema.
