# Agent Arborist

Automated Task Tree Executor - DAG workflow orchestration with Claude Code and Dagu.

## Installation

```bash
pip install -e .
```

## Architecture: Host-Based with Optional Container Support

Agent Arborist runs on your **HOST machine** and can optionally execute tasks inside devcontainers:

```
┌─────────────────────────────────────────┐
│ Arborist (runs on HOST)                 │
│ - Detects target's .devcontainer/       │
│ - Generates DAG with container commands │
│ - Orchestrates via Dagu                 │
└─────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────┐
│ Target Project (user provides)          │
│ └── .devcontainer/                      │
│     ├── devcontainer.json               │
│     └── Dockerfile                      │
└─────────────────────────────────────────┘
              ↓
      Tasks execute inside
      target's container
```

**Key Points**:
- Arborist itself runs on your host (no devcontainer needed for arborist)
- Target projects can have `.devcontainer/` for isolated execution
- Tests run from host and verify container operations
- See `tests/fixtures/devcontainers/` for example target configurations

## Testing

### Environment Setup

Copy `.env.example` to `.env` and fill in your API keys:

```bash
cp .env.example .env
# Edit .env with your actual API keys
```

### Required API Keys

- **CLAUDE_CODE_OAUTH_TOKEN** - For Claude Code integration tests (OAuth token from Claude Pro/Max subscription)
- **OPENAI_API_KEY** - For OpenCode integration tests
- **GOOGLE_API_KEY** - For Gemini integration tests
- **ZAI_API_KEY** - (Optional) For OpenCode with ZAI

### Running Tests

All tests run from the HOST (not inside containers):

```bash
# Unit tests only (fast, no containers)
pytest tests/

# Integration tests (starts containers, requires Docker)
pytest tests/ -m integration

# Provider-specific tests (requires API keys)
pytest tests/ -m claude          # Claude Code tests
pytest tests/ -m opencode        # OpenCode tests
pytest tests/ -m gemini          # Gemini tests

# Dagu integration tests (requires dagu CLI on host)
pytest tests/ -m dagu
```

**Test Architecture**:
1. Tests run from HOST using pytest
2. Test fixtures in `tests/fixtures/devcontainers/` represent target projects
3. Tests start containers using `devcontainer` CLI
4. Tests execute commands inside containers via `devcontainer exec`
5. Tests verify results from HOST

## Usage

```bash
# Show version
arborist version

# Check dependencies
arborist doctor

# Generate DAG with optional container support
arborist spec dag-build spec/ --container-mode auto  # Use target's .devcontainer if present
arborist spec dag-build spec/ --container-mode enabled  # Require .devcontainer
arborist spec dag-build spec/ --container-mode disabled # Ignore .devcontainer
```
