# Runners and Models

Configure AI runners and models.

## Valid Runners

From [`src/agent_arborist/config.py`](../../src/agent_arborist/config.py):

```python
VALID_RUNNERS = ("claude", "opencode", "gemini")
```

## Claude Configuration

```json
{
  "runners": {
    "claude": {
      "default_model": "sonnet",
      "models": {
        "sonnet": "claude-3-5-sonnet-20241022",
        "opus": "claude-3-opus-20240229"
      }
    }
  }
}
```

Usage:
```bash
arborist task run T001 --runner claude --model sonnet
```

## OpenCode Configuration

```json
{
  "runners": {
    "opencode": {
      "default_model": "default"
    }
  }
}
```

## Gemini Configuration

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

## Model Aliases

Define aliases in config:
```json
{
  "runners": {
    "claude": {
      "models": {
        "cheap": "claude-3-haiku-20240307",
        "fast": "claude-3-5-sonnet-20241022"
      }
    }
  }
}
```

Then use:
```bash
arborist task run T001 --model fast
```

See also: [`src/agent_arborist/runner.py`](../../src/agent_arborist/runner.py)
