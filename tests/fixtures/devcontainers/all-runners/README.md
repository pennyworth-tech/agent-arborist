# Test Fixture: All Runners DevContainer

This is a **test fixture** used by arborist integration tests to verify that arborist can correctly detect and use target project devcontainers.

## Purpose

This fixture demonstrates a target project that has:
- `.devcontainer/` configuration
- All three AI runner CLIs installed: Claude Code, OpenCode, Gemini
- Proper environment variable loading from `.env` file

## How It's Used

Integration tests:
1. Copy this fixture to a temporary directory
2. **Copy `agent-arborist/.env` to the temp directory** (simulates user's .env)
3. Initialize it as a git repository
4. Run `arborist` commands that detect this `.devcontainer/`
5. Container starts and loads `.env` via `--env-file` runArgs
6. Verify tasks execute inside the container with API keys available

## Environment Variable Flow

```
agent-arborist/.env (your API keys)
        ↓
   conftest.py loads into test process
        ↓
   Test copies to temp-project/.env
        ↓
   devcontainer.json uses runArgs: ["--env-file", ".env"]
        ↓
   Container has API keys available
```

## Tools Installed

- **Claude Code CLI** - `@anthropic-ai/claude-code`
- **OpenCode CLI** - `opencode-ai`
- **Gemini CLI** - `@google/gemini-cli`
- **GitHub CLI** - `gh`
- **Node.js** - via nvm (LTS)
- **Python 3** - system package

## Required .env File

Tests must create `.env` in the target project root with:
- `ANTHROPIC_API_KEY` - For Claude Code
- `OPENAI_API_KEY` - For OpenCode
- `GOOGLE_API_KEY` - For Gemini
- `ZAI_API_KEY` - Optional for OpenCode
- `CLAUDE_CODE_OAUTH_TOKEN` - For Claude authentication

See `.env.example` for template.

## NOT for Arborist Development

This is **NOT** the devcontainer for developing arborist itself. It's a test fixture that represents a target project arborist would operate on.

Tests run from the HOST and use this fixture to verify container operations.
