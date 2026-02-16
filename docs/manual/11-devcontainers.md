# Devcontainers

Arborist can run AI agents and test commands inside a [devcontainer](https://containers.dev/), providing isolated, reproducible environments for task execution.

## Overview

**Bring your own `.devcontainer/`** — arborist detects and uses your project's devcontainer configuration but never creates one.

| What | Where | Why |
|:-----|:------|:----|
| AI runner (claude, opencode, gemini) | Container | Isolated environment with correct dependencies |
| Test commands | Container | Tests run against the same environment as implementation |
| Git operations (commit, merge, checkout) | Host | Arborist orchestration uses host git; AI commits inside the container are visible via volume mount |
| Arborist orchestration (gardener loop, state tracking) | Host | No container dependency for coordination |

The workspace is **volume-mounted**, so file changes made by AI agents inside the container are immediately visible on the host — including git commits.

## Prerequisites

- **Docker** running locally
- **DevContainer CLI**: `npm install -g @devcontainers/cli`
- A `.devcontainer/devcontainer.json` in your project

## Setting Up Your Devcontainer

### Option A: Use a pre-built image

The simplest approach — no Dockerfile needed:

```json
{
  "name": "my-project",
  "image": "ghcr.io/pennyworth-tech/backlit-core/devcontainer:latest",
  "remoteUser": "vscode",
  "remoteEnv": {
    "CLAUDE_CODE_OAUTH_TOKEN": "${localEnv:CLAUDE_CODE_OAUTH_TOKEN}"
  }
}
```

This image includes `claude`, `git`, and `node` pre-installed.

### Option B: Custom Dockerfile

For projects that need specific runtimes or tools:

```json
{
  "name": "my-project",
  "build": {
    "dockerfile": "Dockerfile"
  },
  "remoteEnv": {
    "OPENAI_API_KEY": "${localEnv:OPENAI_API_KEY}"
  },
  "postCreateCommand": "git config --global --add safe.directory /workspaces"
}
```

Your Dockerfile must provide:

- **git** — AI agents commit inside the container; arborist health-checks this on startup
- **Runner CLIs** — `claude`, `opencode`, or `gemini` depending on your configuration
- **Project dependencies** — language runtime, package manager, test frameworks

## API Keys and Authentication

Arborist does **not** manage API keys for the container. Use `remoteEnv` in your `devcontainer.json` to forward host environment variables:

```json
{
  "remoteEnv": {
    "CLAUDE_CODE_OAUTH_TOKEN": "${localEnv:CLAUDE_CODE_OAUTH_TOKEN}",
    "OPENAI_API_KEY": "${localEnv:OPENAI_API_KEY}",
    "GOOGLE_API_KEY": "${localEnv:GOOGLE_API_KEY}"
  }
}
```

| Runner | Required Variable |
|:-------|:------------------|
| Claude | `CLAUDE_CODE_OAUTH_TOKEN` (OAuth) or `ANTHROPIC_API_KEY` (API key) |
| OpenCode | `OPENAI_API_KEY` or runner-specific key |
| Gemini | `GOOGLE_API_KEY` |

Set these in your shell before running arborist:

```bash
export CLAUDE_CODE_OAUTH_TOKEN="sk-ant-oat01-..."
arborist garden --tree task-tree.json
```

### Git Credentials

The devcontainer CLI automatically copies your host `~/.gitconfig` into the container, so `user.name` and `user.email` are inherited — no manual configuration needed.

## Container Mode

Control container usage with `--container-mode` / `-c`:

| Mode | Behavior |
|:-----|:---------|
| `auto` (default) | Use container if `.devcontainer/devcontainer.json` exists, otherwise run on host |
| `enabled` | Require container; error if no `.devcontainer/` found |
| `disabled` | Always run on host, even if `.devcontainer/` exists |

### Examples

```bash
# Auto-detect (default)
arborist garden --tree task-tree.json

# Force container
arborist gardener --tree task-tree.json -c enabled

# Force host execution
arborist garden --tree task-tree.json -c disabled

# Via environment variable
ARBORIST_CONTAINER_MODE=enabled arborist gardener --tree task-tree.json
```

### Config file

```json
{
  "defaults": {
    "container_mode": "enabled"
  }
}
```

See [Configuration](07-configuration.md) for full precedence rules.

## Lifecycle

1. **Lazy start** — Arborist starts the container on first use via `devcontainer up`
2. **Health check** — Verifies `git --version` runs inside the container
3. **Execution** — AI runner and test commands execute inside the container
4. **No teardown** — The container remains running for subsequent commands within the session

To manually stop a container:

```bash
docker stop $(docker ps -q --filter label=devcontainer.local_folder=$(pwd))
```

## Troubleshooting

| Problem | Cause | Fix |
|:--------|:------|:----|
| "git is not available inside the devcontainer" | Image doesn't include git | Add git to your Dockerfile or use a base image that includes it |
| "Container mode is 'enabled' but no .devcontainer/devcontainer.json found" | Missing config | Create `.devcontainer/devcontainer.json` or use `-c auto` |
| Runner not found in container | Runner CLI not installed | Install the runner in your Dockerfile or use the pre-built image |
| API keys not available | Missing `remoteEnv` | Add `remoteEnv` entries to `devcontainer.json` (see above) |
| Container startup fails | Docker not running | Start Docker; install CLI with `npm install -g @devcontainers/cli` |
| Git commits fail with "user.email not set" | Container doesn't have git config | The devcontainer CLI should copy host `.gitconfig` automatically; if not, add git config commands to `postCreateCommand` |
