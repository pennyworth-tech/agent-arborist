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
2. **Test creates .devcontainer/.env from .devcontainer/.env.example with actual keys**
3. Initialize it as a git repository
4. Run `arborist` commands that detect this `.devcontainer/`
5. git_tasks.py copies .devcontainer/.env to worktree/.devcontainer/.env
6. Container starts and loads `.env` from `.devcontainer/.env`
7. Verify tasks execute inside the container with API keys available

## Environment Variable Flow

```
Fixture .devcontainer/.env.example (template)
        ↓
   Test creates .devcontainer/.env with actual API keys
        ↓
   git_tasks.py copies git_root/.devcontainer/.env → worktree/.devcontainer/.env
        ↓
   devcontainer.json uses runArgs: ["--env-file", ".devcontainer/.env"]
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

Tests create `.devcontainer/.env` from `.devcontainer/.env.example` with actual API keys.

The `.env` file must contain:
- `ANTHROPIC_API_KEY` - For Claude Code
- `OPENAI_API_KEY` - For OpenCode
- `GOOGLE_API_KEY` - For Gemini
- `ZAI_API_KEY` - Optional for OpenCode
- `CLAUDE_CODE_OAUTH_TOKEN` - For Claude authentication

**Location**: `.devcontainer/.env.example` (template in .devcontainer/)
**Test creates**: `.devcontainer/.env` (with actual keys from host environment)

This matches the arborist pattern where `git_tasks.py` copies:
`git_root/.devcontainer/.env` → `worktree/.devcontainer/.env`

## NOT for Arborist Development

This is **NOT** the devcontainer for developing arborist itself. It's a test fixture that represents a target project arborist would operate on.

Tests run from the HOST and use this fixture to verify container operations.
