# Test Fixture: All Runners DevContainer

This is a **test fixture** used by arborist integration tests to verify that arborist can correctly detect and use target project devcontainers.

## Purpose

This fixture demonstrates a target project that has:
- `.devcontainer/` configuration
- All three AI runner CLIs installed: Claude Code, OpenCode, Gemini
- Proper environment variable passthrough

## How It's Used

Integration tests:
1. Copy this fixture to a temporary directory
2. Initialize it as a git repository
3. Run `arborist` commands that detect this `.devcontainer/`
4. Verify arborist generates correct container lifecycle commands
5. Verify tasks execute inside the container

## Tools Installed

- **Claude Code CLI** - `@anthropic-ai/claude-code`
- **OpenCode CLI** - `opencode-ai`
- **Gemini CLI** - `@google/gemini-cli`
- **GitHub CLI** - `gh`
- **Node.js** - via nvm (LTS)
- **Python 3** - system package

## Environment Variables

Passed through from host via `remoteEnv`:
- `ANTHROPIC_API_KEY` - For Claude Code
- `OPENAI_API_KEY` - For OpenCode
- `GOOGLE_API_KEY` - For Gemini
- `ZAI_API_KEY` - Optional for OpenCode
- `CLAUDE_CODE_OAUTH_TOKEN` - For Claude authentication

## NOT for Arborist Development

This is **NOT** the devcontainer for developing arborist itself. It's a test fixture that represents a target project arborist would operate on.

Tests run from the HOST and use this fixture to verify container operations.
