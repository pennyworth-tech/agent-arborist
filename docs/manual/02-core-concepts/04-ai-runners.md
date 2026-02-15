# AI Runners

AI runners execute tasks within worktrees.

## Supported Runners

From [`src/agent_arborist/config.py`](../../src/agent_arborist/config.py):

```python
VALID_RUNNERS = ("claude", "opencode", "gemini")
```

## Runner Configuration

### Claude (Default)

```json
{
  "runners": {
    "claude": {
      "default_model": "sonnet",
      "models": {
        "sonnet": "claude-3-5-sonnet-20241022",
        "opus": "claude-3-opus-20240229",
        "haiku": "claude-3-haiku-20240307"
      }
    }
  }
}
```

### OpenCode

```json
{
  "runners": {
    "opencode": {
      "default_model": "default",
      "models": {
        "default": "default"
      }
    }
  }
}
```

### Gemini

```json
{
  "runners": {
    "gemini": {
      "default_model": "gemini-2.0-flash-exp",
      "models": {
        "flash": "gemini-2.0-flash-exp",
        "pro": "gemini-2.5-pro"
      }
    }
  }
}
```

## Using Runners

```bash
# Use default runner from config
arborist task run T001

# Specify runner
arborist task run T001 --runner claude --model sonnet

# Environment variable
export ARBORIST_RUNNER=gemini
```

## Runner Selection

See: [`src/agent_arborist/runner.py`](../../src/agent_arborist/runner.py)

```python
RunnerType = Literal["claude", "opencode", "gemini"]
```
