# Other Commands

Setup, configuration, and diagnostics.

## Initialize

```bash
arborist init
```

Create `.arborist/` directory and project config.

## Version

```bash
arborist version
arborist version --check
```

Show version and check for updates.

## Doctor

```bash
arborist doctor
arborist doctor --runner claude
```

System diagnostics.

## Config

```bash
# Initialize
arborist config init
arborist config init --global

# Show config
arborist config show

# Validate
arborist config validate
```

## Hooks

```bash
# List hooks
arborist hooks list

# Validate hooks
arborist hooks validate

# Run hook
arborist hooks run pre_sync --task T001
```

See: [`src/agent_arborist/cli.py`](../../src/agent_arborist/cli.py)
