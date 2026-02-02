# Part 6: Container Support

Execute tasks in devcontainers for isolated development environments.

## Overview

Arborist supports running AI tasks inside devcontainers for consistent development environments.

## Container Modes

From [`src/agent_arborist/container_runner.py`](../../src/agent_arborist/container_runner.py):

| Mode | Behavior |
|------|----------|
| `auto` | Use devcontainer if `.devcontainer/` exists (default) |
| `enabled` | Require devcontainer, fail if not present |
| `disabled` | Never use devcontainer, always run on host |

## Detection

Arborist automatically detects devcontainers by checking:
- `.devcontainer/devcontainer.json`
- `.devcontainer/Dockerfile`

## Configuration

Set container mode in `.arborist/config.json`:

```json
{
  "version": "1",
  "defaults": {
    "container_mode": "auto"
  }
}
```

Or require devcontainer:

```json
{
  "defaults": {
    "container_mode": "enabled"
  }
}
```

## Prerequisites

Install devcontainer CLI:

```bash
npm install -g @devcontainers/cli
```

Check with:

```bash
devcontainer --version
```

## Usage

If your project has `.devcontainer/`:

```bash
# Auto-detect and use (default)
arborist task run T001

# Force disable
export ARBORIST_CONTAINER_MODE=disabled
arborist task run T001
```

See: [`src/agent_arborist/container_context.py`](../../src/agent_arborist/container_context.py)
