# Part 3: Configuration

Agent Arborist uses a flexible, hierarchical configuration system that allows you to customize behavior at multiple levels.

## Contents

- **[Configuration System](./01-configuration-system.md)** - Understanding the configuration hierarchy
- **[Runners and Models](./02-runners-and-models.md)** - Configuring AI runners and models
- **[Timeouts and Paths](./03-timeouts-and-paths.md)** - Setting timeouts and directory paths
- **[Test Configuration](./04-test-configuration.md)** - Configuring test execution

## Configuration Hierarchy

```mermaid
graph TB
    A[Configuration Precedence<br/>(Highest to Lowest)] --> B[CLI Flags]
    B --> C[Environment Variables]
    C --> D[Step-Specific Config]
    D --> E[Project Config<br/>.arborist/config.json]
    E --> F[Global Config<br/>~/.arborist_config.json]
    F --> G[Hardcoded Defaults]

    style B fill:#e1ffe1
    style C fill:#e1f5ff
    style D fill:#fff4e1
    style E fill:#e1f5ff
    style F fill:#fff4e1
    style G fill:#e1ffe1
```

## Quick Reference

### Basic Configuration

```bash
# Create project config
arborist config init

# Create global config
arborist config init --global

# Show effective config
arborist config show

# Validate config
arborist config validate
```

### Common Settings

```json
{
  "version": "1",
  "defaults": {
    "runner": "claude",
    "model": "sonnet",
    "container_mode": "auto"
  },
  "timeouts": {
    "task_run": 1800,
    "task_post_merge": 300
  }
}
```

## Next Steps

Start with [Configuration System](./01-configuration-system.md) to understand how configuration works in Arborist.