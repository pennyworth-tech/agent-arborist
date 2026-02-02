# Part 3: Configuration

Configure Agent Arborist behavior.

## Contents

- **[Configuration System](./01-configuration-system.md)** - Config hierarchy and locations
- **[Runners and Models](./02-runners-and-models.md)** - Configure AI runners

## Quick Reference

| Config Type | Location | Purpose |
|-------------|----------|---------|
| Global | `~/.arborist_config.json` | System-wide defaults |
| Project | `.arborist/config.json` | Project-specific settings |

## Common Commands

```bash
# Initialize config
arborist config init
arborist config init --global

# Show config
arborist config show

# Validate config
arborist config validate
```

## Next Steps

- [Using the CLI](../04-using-the-cli/README.md) - CLI commands
