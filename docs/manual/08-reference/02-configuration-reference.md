# Configuration Reference

Complete reference for Agent Arborist configuration schema and all options.

## Configuration File Location

Default configuration file: `agent-arborist.yaml` in project root.

Alternative locations (priority order):
1. `--config` CLI flag
2. `$AGENT_ARBORIST_CONFIG` environment variable
3. `agent-arborist.yaml` in current directory
4. `agent-arborist.yaml` in parent directory (up to 3 levels)

## Schema Overview

```yaml
# agent-arborist.yaml
runner: string
claude: { models: { task_spec: string, dagu: string } }
openai: { models: { task_spec: string, dagu: string } }
timeouts: { generate_task_spec: int, generate_dagu: int, run_dagu: int, default: int }
paths: { spec_dir: string, dag_dir: string, dagu_dir: string, output_dir: string, work_dir: string, temp_dir: string }
git: { worktree_dir: string, worktree_prefix: string }
container: { enabled: bool, runtime: string, image: string, resources: {...}, mounts: [...], environment: {...}, security: {...}, options: {...} }
hooks: { pre_generation: [...], post_spec: [...], post_dagu: [...], pre_execution: [...], post_execution: [...] }
```

## Top-Level Fields

### runner

The default AI runner to use.

| Type | Required | Default | Description |
|------|----------|---------|-------------|
| string | Yes | `claude` | AI runner (claude, openai, mock) |

**Values:**
- `claude`: Anthropic Claude
- `openai`: OpenAI GPT models
- `mock`: Mock runner for testing

**Example:**
```yaml
runner: claude
```

**Code Reference:** [`src/agent_arborist/config.py:runner`](../../src/agent_arborist/config.py#L44)

## Runner-Specific Configuration

### claude

Claude runner configuration.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `models` | object | No | See below | Model settings |

#### claude.models

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `task_spec` | string | No | `claude-3-5-sonnet` | Model for task specs |
| `dagu` | string | No | `claude-3-5-sonnet` | Model for DAGU generation |

**Example:**
```yaml
claude:
  models:
    task_spec: claude-3-5-sonnet-20240620
    dagu: claude-3-haiku-20240307
```

**Code Reference:** [`src/agent_arborist/config.py:ClaudeConfig`](../../src/agent_arborist/config.py)

### openai

OpenAI runner configuration.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `models` | object | No | See below | Model settings |

#### openai.models

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `task_spec` | string | No | `gpt-4` | Model for task specs |
| `dagu` | string | No | `gpt-3.5-turbo` | Model for DAGU generation |

**Example:**
```yaml
openai:
  models:
    task_spec: gpt-4-turbo
    dagu: gpt-3.5-turbo
```

**Code Reference:** [`src/agent_arborist/config.py:OpenAIConfig`](../../src/agent_arborist/config.py)

## Timeouts Configuration

### timeouts

Timeout settings for various operations.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `generate_task_spec` | int | No | `300` | Spec generation timeout (seconds) |
| `generate_dagu` | int | No | `300` | DAGU generation timeout (seconds) |
| `run_dagu` | int | No | `3600` | Workflow execution timeout (seconds) |
| `default` | int | No | `300` | Default timeout (seconds) |

**Example:**
```yaml
timeouts:
  generate_task_spec: 300
  generate_dagu: 300
  run_dagu: 7200
  default: 300
```

**Code Reference:** [`src/agent_arborist/config.py:TimeoutsConfig`](../../src/agent_arborist/config.py)

## Paths Configuration

### paths

File path configurations.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `spec_dir` | string | No | `spec` | Task spec directory |
| `dag_dir` | string | No | `dag` | DAGU config directory |
| `dagu_dir` | string | No | `.dagu` | DAGU runtime directory |
| `output_dir` | string | No | `output` | Output directory |
| `work_dir` | string | No | `work` | Worktree directory |
| `temp_dir` | string | No | `.agent-arborist/tmp` | Temporary directory |

**Example:**
```yaml
paths:
  spec_dir: spec
  dag_dir: dag
  dagu_dir: .dagu
  output_dir: output
  work_dir: work
  temp_dir: .agent-arborist/tmp
```

**Code Reference:** [`src/agent_arborist/config.py:PathsConfig`](../../src/agent_arborist/config.py)

## Git Configuration

### git

Git worktree configuration.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `worktree_dir` | string | No | `work` | Worktree directory |
| `worktree_prefix` | string | No | `arborist-` | Worktree name prefix |

**Example:**
```yaml
git:
  worktree_dir: work
  worktree_prefix: arborist-
```

**Code Reference:** [`src/agent_arborist/config.py:GitConfig`](../../src/agent_arborist/config.py)

## Container Configuration

### container

Container execution configuration.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `enabled` | bool | No | `false` | Enable container execution |
| `runtime` | string | No | `docker` | Container runtime |
| `image` | string | No | - | Container image to use |
| `resources` | object | No | See below | Resource limits |
| `mounts` | array | No | See below | Volume mounts |
| `environment` | object | No | See below | Environment variables |
| `security` | object | No | See below | Security settings |
| `options` | object | No | See below | Additional options |

#### container.resources

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `cpu` | string | No | - | CPU limit (e.g., "2") |
| `memory` | string | No | - | Memory limit (e.g., "4Gi") |
| `gpu` | bool/int/array | No | `false` | GPU configuration |

**Example:**
```yaml
resources:
  cpu: "2"
  memory: "4Gi"
  gpu: false
```

#### container.mounts

Array of mount objects.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Mount type (bind, volume, tmpfs) |
| `source` | string | Yes | Host path or volume name |
| `target` | string | Yes | Container path |
| `read_only` | bool | No | Read-only mount |

**Example:**
```yaml
mounts:
  - type: bind
    source: ./data
    target: /data
    read_only: true
  
  - type: tmpfs
    target: /tmp
    size: "1Gi"
```

#### container.environment

Object of environment variables.

**Example:**
```yaml
environment:
  PYTHONPATH: /app
  LOG_LEVEL: info
  API_KEY: ${API_KEY}
```

#### container.security

Security settings.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `read_only` | bool | No | `false` | Read-only root filesystem |
| `network` | string | No | `bridge` | Network mode (bridge, host, none) |
| `user` | string | No | `root` | Run as user (UID or user:group) |

**Example:**
```yaml
security:
  read_only: true
  network: bridge
  user: "1000:1000"
```

#### container.options

Runtime-specific options.

**Example:**
```yaml
options:
  docker:
    runtime: nvidia
    platform: linux/amd64
```

**Code Reference:** [`src/agent_arborist/config.py:ContainerConfig`](../../src/agent_arborist/config.py)

## Hooks Configuration

### hooks

Hooks configuration for workflow customization.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `pre_generation` | array | No | Pre-generation hooks |
| `post_spec` | array | No | Post-spec hooks |
| `post_dagu` | array | No | Post-DAGU hooks |
| `pre_execution` | array | No | Pre-execution hooks |
| `post_execution` | array | No | Post-execution hooks |

### Hook Object

Each hook has the following fields:

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | Yes | - | Unique hook name |
| `command` | string | Yes | - | Command to execute |
| `enabled` | bool | No | `true` | Whether hook is enabled |
| `timeout` | int | No | `60` | Timeout in seconds |
| `continue_on_failure` | bool | No | `false` | Continue on failure |
| `env` | object | No | `{}` | Environment variables |
| `working_dir` | string | No | `.` | Working directory |

**Example:**
```yaml
hooks:
  post_execution:
    - name: slack-notification
      command: scripts/notify-slack.sh
      enabled: true
      timeout: 30
      continue_on_failure: true
      env:
        SLACK_WEBHOOK: ${SLACK_WEBHOOK_URL}
```

**Code Reference:** [`src/agent_arborist/config.py:hooks`](../../src/agent_arborist/config.py)

## Complete Example

```yaml
# agent-arborist.yaml

# Runner configuration
runner: claude

# Claude specific settings
claude:
  models:
    task_spec: claude-3-5-sonnet-20240620
    dagu: claude-3-5-sonnet-20240620

# OpenAI configuration
openai:
  models:
    task_spec: gpt-4-turbo
    dagu: gpt-3.5-turbo

# Timeouts (seconds)
timeouts:
  generate_task_spec: 300
  generate_dagu: 300
  run_dagu: 3600
  default: 300

# File paths
paths:
  spec_dir: spec
  dag_dir: dag
  dagu_dir: .dagu
  output_dir: output
  work_dir: work
  temp_dir: .agent-arborist/tmp

# Git worktree settings
git:
  worktree_dir: work
  worktree_prefix: arborist-

# Container configuration
container:
  enabled: true
  runtime: docker
  image: python:3.11-slim
  
  resources:
    cpu: "2"
    memory: "4Gi"
    gpu: false
  
  mounts:
    - type: bind
      source: ./data
      target: /data
      read_only: false
  
  environment:
    PYTHONPATH: /app
    LOG_LEVEL: info
  
  security:
    read_only: false
    network: bridge
    user: root

# Hooks
hooks:
  post_execution:
    - name: slack-notification
      command: scripts/notify-slack.sh
      enabled: true
      timeout: 30
      continue_on_failure: true
      env:
        SLACK_WEBHOOK: ${SLACK_WEBHOOK_URL}
```

## Configuration Validation

Configuration is validated on load:

```python
from agent_arborist.config import load_config

config = load_config('agent-arborist.yaml')
```

### Validation Rules

1. **Required fields**: `runner` must be specified
2. **Valid runners**: Must be one of `claude`, `openai`, `mock`
3. **Timeouts**: Must be positive integers
4. **Paths**: Must be valid paths (directories are created if missing)
5. **Hooks**: Hook names must be unique within each phase

## Environment Variable Substitution

Configuration supports environment variable substitution:

```yaml
# Use environment variable
api_key: ${API_KEY}

# With default value
timeout: ${TIMEOUT:-300}

# Multiple variables
database_url: ${DB_HOST}:${DB_PORT}/${DB_NAME}
```

## Configuration Merging

Configurations are merged in order:

1. Base configuration
2. Environment-specific configuration
3. Environment variables
4. CLI overrides

```yaml
# base.yaml
runner: claude
timeouts:
  default: 300

# production.yaml
timeouts:
  run_dagu: 7200

# Final config includes both:
# runner: claude
# timeouts:
#   default: 300
#   run_dagu: 7200
```

## Code References

- Configuration loading: [`src/agent_arborist/config.py:load_config()`](../../src/agent_arborist/config.py#L100)
- Validation: [`src/agent_arborist/config.py:validate_config()`](../../src/agent_arborist/config.py#L150)
- Schema: [`src/agent_arborist/config.py:AgentArboristConfig`](../../src/agent_arborist/config.py#L40)

## Related Documentation

- [CLI Reference](./01-cli-reference.md)
- [Configuration System](../03-configuration/01-configuration-system.md)
- [Test Configuration](../03-configuration/04-test-configuration.md)