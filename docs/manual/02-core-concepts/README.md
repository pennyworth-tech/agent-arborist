# Part 2: Core Concepts

Fundamental concepts for using Agent Arborist.

## Contents

- **[Specs and Tasks](./01-specs-and-tasks.md)** - Markdown task specification format
- **[DAGs and Dagu](./02-dags-and-dagu.md)** - DAG generation and execution
- **[Git and Worktrees](./03-git-and-worktrees.md)** - Task isolation with worktrees
- **[AI Runners](./04-ai-runners.md)** - Available AI runners (claude, opencode, gemini)

## Overview

| Concept | Description | Location |
|---------|-------------|----------|
| Specs | Markdown task definitions | `.arborist/specs/{spec_id}/tasks.md` |
| DAGs | Dagu workflow files | `.arborist/dagu/{spec_id}/` |
| Worktrees | Isolated Git workspaces | `.arborist/worktrees/{spec_id}/{task_id}/` |
| Configs | JSON configuration | Global: `~/.arborist_config.json`, Project: `.arborist/config.json` |
