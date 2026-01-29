# Agent Arborist

Automated Task Tree Executor - DAG workflow orchestration with Claude Code and Dagu.

## Installation

```bash
pip install -e .
```

## DevContainer Setup

Agent Arborist includes a DevContainer configuration for consistent development environments with all necessary AI CLI tools pre-installed.

### Environment Variables

Copy `.devcontainer/.env.example` to `.devcontainer/.env` and fill in your API keys:

```bash
cp .devcontainer/.env.example .devcontainer/.env
# Edit .devcontainer/.env with your actual API keys
```

### Required API Keys

- **ANTHROPIC_API_KEY** - For Claude Code CLI (`claude`)
- **OPENAI_API_KEY** - For OpenCode CLI (`opencode`)
- **GOOGLE_API_KEY** - For Gemini CLI (`gemini`)
- **CLAUDE_CODE_OAUTH_TOKEN** - For Claude Code authentication
- **ZAI_API_KEY** - (Optional) For OpenCode with ZAI provider

### Installed Tools

The DevContainer includes:
- **Claude Code CLI** (`@anthropic-ai/claude-code`)
- **OpenCode CLI** (`opencode-ai`)
- **Gemini CLI** (`@google/gemini-cli`)
- **GitHub CLI** (`gh`)
- **Node.js** (via nvm)
- **Python 3** with pip
- **tmux** terminal multiplexer

### Testing

The DevContainer includes all tools needed to run tests:

```bash
# Run unit tests (default, excludes integration tests)
pytest tests/

# Run integration tests with AI providers
pytest tests/ -m integration

# Run provider-specific tests
pytest tests/ -m claude          # Claude Code tests
pytest tests/ -m opencode        # OpenCode tests
pytest tests/ -m gemini          # Gemini tests
```

**Note**: Dagu tests are excluded from the DevContainer as Dagu runs on the host system, not inside containers.

## Usage

```bash
# Show version
arborist version

# Check dependencies
arborist doctor
```
