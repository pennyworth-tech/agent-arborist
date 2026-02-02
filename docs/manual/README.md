# Agent Arborist User Manual

**Version 0.1.0**

Automated Task Tree Executor - DAG workflow orchestration with Dagu.

## Table of Contents

- [Introduction](./00-introduction/00-welcome.md) - What is Agent Arborist?

- [Part 1: Getting Started](./01-getting-started/README.md)
  - [Introduction](./01-getting-started/01-introduction.md) - Core concepts and terminology
  - [Quick Start](./01-getting-started/02-quick-start.md) - Build a Hello World Calculator in 5 minutes
  - [Architecture](./01-getting-started/03-architecture.md) - System architecture and components

- [Part 2: Core Concepts](./02-core-concepts/README.md)
  - [Specs and Tasks](./02-core-concepts/01-specs-and-tasks.md) - Markdown task specification format
  - [DAGs and Dagu](./02-core-concepts/02-dags-and-dagu.md) - DAG generation and execution
  - [Git and Worktrees](./02-core-concepts/03-git-and-worktrees.md) - Task isolation with worktrees
  - [AI Runners](./02-core-concepts/04-ai-runners.md) - Available AI runners (claude, opencode, gemini)

- [Part 3: Configuration](./03-configuration/README.md)
  - [Configuration System](./03-configuration/01-configuration-system.md) - Config hierarchy and locations
  - [Runners and Models](./03-configuration/02-runners-and-models.md) - Configure AI runners

- [Part 4: Using the CLI](./04-using-the-cli/README.md)
  - [CLI Overview](./04-using-the-cli/01-cli-overview.md) - CLI structure and help
  - [Task Commands](./04-using-the-cli/02-task-commands.md) - Individual task operations
  - [Spec Commands](./04-using-the-cli/03-spec-commands.md) - Spec management
  - [DAG Commands](./04-using-the-cli/04-dag-commands.md) - Workflow execution
  - [Other Commands](./04-using-the-cli/05-other-commands.md) - Setup, config, diagnostics

- [Part 5: Hooks System](./05-hooks-system/README.md) - Hook customization
- [Part 6: Container Support](./06-container-support/README.md) - Container execution
- [Part 7: Telemetry and Visualization](./07-telemetry-and-visualization/README.md) - Monitoring and visualization

## Appendices

- [Troubleshooting](./appendices/01-troubleshooting.md) - Common issues and solutions
- [FAQ](./appendices/02-faq.md) - Frequently asked questions
- [CLI Reference](./appendices/03-cli-reference.md) - Complete CLI command reference

## Quick Links

- [🚀 Quick Start](./01-getting-started/02-quick-start.md) - Get started in 5 minutes
- [⚙️ Configuration](./03-configuration/README.md) - Configure Arborist
- [📋 CLI Commands](./04-using-the-cli/README.md) - CLI reference
- [📊 Visualization](./07-telemetry-and-visualization/README.md) - Monitor workflows