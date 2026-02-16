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

## Usage

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

## Container Details

- **Base Image**: node:18-slim
- **Runner**: OpenCode CLI (`opencode-ai` npm package)
- **Default Model**: zai-coding-plan/glm-4.7
- API keys are inherited from local environment via `remoteEnv` in devcontainer.json
- Git safe.directory is configured in postCreateCommand
