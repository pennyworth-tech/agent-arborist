# Runners and Models Configuration

Agent Arborist supports multiple AI runners and model configurations, giving you flexibility to choose which AI services to use for different aspects of the workflow.

## Overview of Runners

Runners are external AI services that Agent Arborist connects to for generating task specs. Each runner has its own configuration options and supported models.

See [`src/agent_arborist/config.py:VALID_RUNNERS`](../../src/agent_arborist/config.py#L22) for the list of supported runners.

```python
VALID_RUNNERS = ["claude", "openai", "mock"]
```

## Configuration Structure

### Top-Level Runner Config

The main runner is specified in the root of your configuration:

```yaml
# agent-arborist.yaml
runner: claude  # or "openai" or "mock"
```

### Runner-Specific Sections

Each runner has its own configuration section:

```yaml
# agent-arborist.yaml
claude:
  models:
    task_spec: claude-3-5-sonnet-20240620
    dagu: claude-3-5-sonnet-20240620

openai:
  models:
    task_spec: gpt-4
    dagu: gpt-3.5-turbo
```

## Claude Runner Configuration

Claude is the default runner and recommended for generating high-quality task specifications.

### Required Configuration

```yaml
runner: claude
claude:
  models:
    task_spec: claude-3-5-sonnet-20240620
    dagu: claude-3-5-sonnet-20240620
```

### Available Models

- **task_spec**: Model used for generating task specifications
  - Recommended: `claude-3-5-sonnet-20240620`
  - Alternative: `claude-3-opus-20240229`
  
- **dagu**: Model used for generating DAGU configurations
  - Recommended: `claude-3-5-sonnet-20240620`
  - Alternative: `claude-3-haiku-20240307` for faster, lower-cost generation

### Example

```yaml
runner: claude
claude:
  models:
    task_spec: claude-3-5-sonnet-20240620
    dagu: claude-3-5-sonnet-20240620
```

## OpenAI Runner Configuration

OpenAI provides access to GPT models for task specification generation.

### Required Configuration

```yaml
runner: openai
openai:
  models:
    task_spec: gpt-4
    dagu: gpt-3.5-turbo
```

### Available Models

- **task_spec**: Model used for generating task specifications
  - `gpt-4`: Best for complex specifications
  - `gpt-4-turbo`: Faster alternative
  
- **dagu**: Model used for generating DAGU configurations
  - `gpt-3.5-turbo`: Recommended for DAGU generation
  - `gpt-4`: For more complex workflows

### Example

```yaml
runner: openai
openai:
  models:
    task_spec: gpt-4-turbo
    dagu: gpt-3.5-turbo
```

## Mock Runner Configuration

The mock runner is useful for testing and development without making actual API calls.

### Configuration

```yaml
runner: mock
```

The mock runner doesn't require any additional configuration. It returns predefined responses suitable for testing.

### Use Cases

- **Testing**: Verify workflow without API costs
- **Development**: Test integration patterns
- **CI/CD**: Validate configuration changes

## Model Selection Guidelines

### For Task Specifications

Use more capable models for task spec generation:

| Runner | Recommended Model | Notes |
|--------|------------------|-------|
| Claude | `claude-3-5-sonnet` | Best balance of quality and speed |
| OpenAI | `gpt-4` | Best quality, higher cost |

### For DAGU Configuration

You can use slightly faster/cheaper models:

| Runner | Recommended Model | Notes |
|--------|------------------|-------|
| Claude | `claude-3-5-sonnet` | Recommended for complex DAGs |
| Claude | `claude-3-haiku` | For simple DAGs, lower cost |
| OpenAI | `gpt-3.5-turbo` | Good balance of quality and speed |

## Per-Task Runner Configuration

The running runner (for generating task specifications) can be overridden per-task in the task spec file:

```yaml
# spec/my-task.yaml
runner: claude  # Override global runner for this task
```

This allows you to use different runners for different tasks based on complexity, cost, or other requirements.

## Common Configuration Examples

### Production Setup (Claude)

```yaml
runner: claude
claude:
  models:
    task_spec: claude-3-5-sonnet-20240620
    dagu: claude-3-5-sonnet-20240620
```

### Cost-Optimized Setup

```yaml
runner: claude
claude:
  models:
    task_spec: claude-3-5-sonnet-20240620  # Good quality for specs
    dagu: claude-3-haiku-20240307  # Cheaper for DAGU
```

### OpenAI Setup

```yaml
runner: openai
openai:
  models:
    task_spec: gpt-4-turbo
    dagu: gpt-3.5-turbo
```

### Development Setup

```yaml
runner: mock
```

## Code References

- Configuration structure: [`src/agent_arborist/config.py:AgentArboristConfig`](../../src/agent_arborist/config.py#L40)
- Valid runners: [`src/agent_arborist/config.py:VALID_RUNNERS`](../../src/agent_arborist/config.py#L22)
- Model configuration fields: [`src/agent_arborist/config.py:ModelConfig`](../../src/agent_arborist/config.py#L34)