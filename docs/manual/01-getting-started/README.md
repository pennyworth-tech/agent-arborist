# Part 1: Getting Started

Welcome to Agent Arborist - an automated task tree executor that orchestrates AI-driven workflows using Dagu.

## Contents

- **[Introduction](./01-introduction.md)** - What is Agent Arborist and key concepts
- **[Quick Start](./02-quick-start.md)** - Install and run your first spec
- **[Architecture](./03-architecture.md)** - System architecture and components

## What You'll Learn

This section covers:
- Installing prerequisites (Python 3.10+, Git, Dagu)
- Initializing an Arborist project
- Writing your first task specification
- Running workflows with Dagu
- Choosing and configuring AI runners

## Key Concepts

- **Specs** - Markdown task specs in `.arborist/specs/`
- **Tasks** - Individual units of work with IDs (T001, T002)
- **DAGs** - Dagu YAML files generated from specs
- **Runners** - AI systems (claude, opencode, gemini)
- **Worktrees** - Git worktrees for isolated execution
- **Config** - JSON config files (global and project)

## Typical Workflow

```bash
arborist init                     # Initialize .arborist/
arborist spec dag-build 001-spec  # Generate DAGs
arborist spec branch-create-all   # Create branches
arborist dag run 001-spec         # Run workflow
```

## System Requirements

| Requirement | Version |
|-------------|---------|
| Python | 3.10+ |
| Git | Any recent version |
| Dagu | Latest stable |