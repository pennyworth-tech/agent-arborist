# Agent Arborist User Manual

Automated Task Tree Executor - DAG workflow orchestration with Claude Code and Dagu.

## Table of Contents

- [Part 1: Getting Started](./01-getting-started/README.md)
  - [Introduction](./01-getting-started/01-introduction.md)
  - [Quick Start](./01-getting-started/02-quick-start.md)
  - [Architecture Overview](./01-getting-started/03-architecture.md)

- [Part 2: Core Concepts](./02-core-concepts/README.md)
  - [Specs and Tasks](./02-core-concepts/01-specs-and-tasks.md)
  - [DAGs and Dagu](./02-core-concepts/02-dags-and-dagu.md)
  - [Git and Worktrees](./02-core-concepts/03-git-and-worktrees.md)
  - [AI Runners](./02-core-concepts/04-ai-runners.md)

- [Part 3: Configuration](./03-configuration/README.md)
  - [Configuration System](./03-configuration/01-configuration-system.md)
  - [Runners and Models](./03-configuration/02-runners-and-models.md)
  - [Timeouts and Paths](./03-configuration/03-timeouts-and-paths.md)
  - [Test Configuration](./03-configuration/04-test-configuration.md)

- [Part 4: Using the CLI](./04-using-the-cli/README.md)
  - [Setup Commands](./04-using-the-cli/01-setup-commands.md)
  - [Spec Commands](./04-using-the-cli/02-spec-commands.md)
  - [Task Commands](./04-using-the-cli/03-task-commands.md)
  - [DAG Commands](./04-using-the-cli/04-dag-commands.md)
  - [Visualization Commands](./04-using-the-cli/05-visualization-commands.md)
  - [Configuration Commands](./04-using-the-cli/06-configuration-commands.md)

- [Part 5: Hooks System](./05-hooks-system/README.md)
  - [Hooks Overview](./05-hooks-system/01-hooks-overview.md)
  - [Step Definitions](./05-hooks-system/02-step-definitions.md)
  - [Hook Injections](./05-hooks-system/03-hook-injections.md)
  - [Hooks Commands](./05-hooks-system/04-hooks-commands.md)

- [Part 6: Container Support](./06-container-support/README.md)
  - [Devcontainer Integration](./06-container-support/01-devcontainer-integration.md)
  - [Container Execution](./06-container-support/02-container-execution.md)

- [Part 7: Advanced Topics](./07-advanced-topics/README.md)
  - [Restart Context](./07-advanced-topics/01-restart-context.md)
  - [Monitoring and Debugging](./07-advanced-topics/02-monitoring-and-debugging.md)
  - [Parallelism and Performance](./07-advanced-topics/03-parallelism-and-performance.md)
  - [Customization](./07-advanced-topics/04-customization.md)

- [Part 8: Reference](./08-reference/README.md)
  - [CLI Reference](./08-reference/01-cli-reference.md)
  - [Configuration Reference](./08-reference/02-configuration-reference.md)
  - [Task Spec Format Reference](./08-reference/03-task-spec-format-reference.md)
  - [DAG YAML Format Reference](./08-reference/04-dag-yaml-format-reference.md)

## Appendices

- [Examples](./appendices/A-examples.md)
- [Migration Guide](./appendices/B-migration-guide.md)
- [Troubleshooting](./appendices/C-troubleshooting.md)
- [Glossary](./appendices/D-glossary.md)
- [Contributing](./appendices/E-contributing.md)

## Quick Links

- [Installation Guide](./01-getting-started/02-quick-start.md#installation)
- [Configuration Guide](./03-configuration/01-configuration-system.md)
- [CLI Commands](./04-using-the-cli/README.md)
- [Troubleshooting](./appendices/C-troubleshooting.md)