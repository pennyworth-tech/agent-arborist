# Devcontainer Support

Arborist can run AI agents and test commands inside a [devcontainer](https://containers.dev/), providing isolated, reproducible environments for task execution.

## How It Works

**Bring your own `.devcontainer/`** — arborist detects and uses your devcontainer configuration but never creates one.

### Execution Model

| What | Where | Why |
|:-----|:------|:----|
| AI runner (claude, opencode, gemini) | Container | Isolated environment with correct dependencies |
| Test commands | Container | Tests run against the same environment as implementation |
| Git operations (commit, merge, checkout) | Host | Arborist orchestration uses host git; AI agent commits inside container are visible via volume mount |
| Arborist orchestration (gardener loop, state tracking) | Host | No container dependency for coordination |

The workspace is **volume-mounted**, so file changes made by AI agents inside the container are immediately visible on the host. AI agents may also `git commit` inside the container — these commits are visible to arborist on the host via the shared mount.

## Container Requirements

Your `.devcontainer/devcontainer.json` and Dockerfile must provide:

- **git** — AI agents commit inside the container; arborist health-checks this on first start
- **Runner CLIs** — `claude`, `opencode`, or `gemini` depending on your config
- **Project dependencies** — language runtime, package manager, test frameworks
- **API keys** — via `remoteEnv` (see below)

## API Keys via remoteEnv

Arborist does **not** manage API keys or environment variables for the container. Configure them in your `devcontainer.json` using `remoteEnv` with `localEnv` references:

```json
{
  "remoteEnv": {
    "ANTHROPIC_API_KEY": "${localEnv:ANTHROPIC_API_KEY}",
    "OPENAI_API_KEY": "${localEnv:OPENAI_API_KEY}",
    "GOOGLE_API_KEY": "${localEnv:GOOGLE_API_KEY}"
  }
}
```

This forwards your host environment variables into the container at runtime.

## Container Mode

Control container usage with `--container-mode` / `-c` on `garden`, `gardener`, and `build` commands:

| Mode | Behavior |
|:-----|:---------|
| `auto` (default) | Use container if `.devcontainer/devcontainer.json` exists, otherwise run on host |
| `enabled` | Require container; error if no `.devcontainer/` found |
| `disabled` | Always run on host, even if `.devcontainer/` exists |

### Config Precedence

```
CLI flag --container-mode      (highest)
    |
ARBORIST_CONTAINER_MODE env var
    |
.arborist/config.json -> defaults.container_mode
    |
~/.arborist_config.json -> defaults.container_mode
    |
hardcoded "auto"               (lowest)
```

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

# In config (.arborist/config.json)
{
  "defaults": {
    "container_mode": "enabled"
  }
}
```

## Lazy Start + Health Check

Arborist starts the container lazily on first use (`devcontainer up`). On first start, it verifies `git --version` is available inside the container. If git is missing, it fails with a clear error message.

The container is **not** explicitly torn down — it remains running for subsequent commands within the same session.

## Troubleshooting

| Problem | Cause | Fix |
|:--------|:------|:----|
| "git is not available inside the devcontainer" | Dockerfile doesn't install git | Add `RUN apt-get update && apt-get install -y git` to your Dockerfile |
| "Container mode is 'enabled' but no .devcontainer/devcontainer.json found" | Missing devcontainer config | Create `.devcontainer/devcontainer.json` or use `-c auto` |
| Runner not found in container | Runner CLI not installed in Dockerfile | Add runner installation to your Dockerfile |
| API keys not available | Missing `remoteEnv` config | Add `remoteEnv` entries to `devcontainer.json` (see above) |
| Container startup fails | Docker not running or devcontainer CLI not installed | Start Docker; install CLI with `npm install -g @devcontainers/cli` |
