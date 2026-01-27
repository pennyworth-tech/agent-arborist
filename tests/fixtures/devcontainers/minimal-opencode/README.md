# Minimal OpenCode DevContainer Test Fixture

This fixture provides a minimal devcontainer environment for testing arborist's container runner integration with OpenCode.

## Purpose

Tests that arborist can:
1. Detect and use a target project's `.devcontainer/`
2. Start containers per worktree
3. Execute OpenCode runner commands inside containers
4. Clean up containers after task completion

## Requirements

- Docker running locally
- DevContainer CLI: `npm install -g @devcontainers/cli`
- API key for ZAI (ZhipuAI) or OpenAI

## Setup

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and add your API keys:
   ```bash
   ZAI_API_KEY=your_actual_key_here
   ```

## Usage

### Manual Testing

Start the container:
```bash
devcontainer up --workspace-folder .
```

Run OpenCode inside container:
```bash
devcontainer exec --workspace-folder . opencode run -m zai-coding-plan/glm-4.7 "Echo hello world"
```

Stop the container:
```bash
docker stop $(docker ps -q --filter label=devcontainer.local_folder=$(pwd))
```

### Integration Tests

Run with pytest:
```bash
# All integration tests
pytest -m integration tests/test_container_runner.py

# Just the OpenCode tests
pytest -m opencode tests/test_container_runner.py
```

## Test Spec

The `test_spec.md` file contains a minimal task specification used by integration tests to verify end-to-end functionality.

## Container Details

- **Base Image**: node:18-slim
- **Runner**: OpenCode CLI (`opencode-ai` npm package)
- **Default Model**: zai-coding-plan/glm-4.7
- **Workspace**: /workspaces/agent-arborist

## Notes

- API keys are inherited from local environment via `remoteEnv` in devcontainer.json
- Git safe.directory is scoped to `/workspaces/agent-arborist` (not wildcard `*`)
- Container is stopped after each test run for isolation
