# Part 4: Using the CLI

Command-line interface reference.

## Contents

- **[CLI Overview](./01-cli-overview.md)** - CLI structure and help
- **[Task Commands](./02-task-commands.md)** - Individual task operations
- **[Spec Commands](./03-spec-commands.md)** - Spec management
- **[DAG Commands](./04-dag-commands.md)** - Workflow execution
- **[Other Commands](./05-other-commands.md)** - Setup, config, diagnostics

## Typical Workflow

```bash
arborist init                          # Initialize
arborist spec dag-build 001-feature    # Build DAG
arborist spec branch-create-all        # Create branches
arborist dag run 001-feature           # Run workflow
arborist dag status 001-feature        # Check status
```

## Next Steps

- [Configuration](../03-configuration/README.md) - Configure Arborist
- [Hooks System](../05-hooks-system/README.md) - Hook customization
