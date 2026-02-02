# Part 2: Core Concepts

This section explains the fundamental concepts you need to understand to use Agent Arborist effectively.

## Contents

- **[Specs and Tasks](./01-specs-and-tasks.md)** - How to define task specifications
- **[DAGs and Dagu](./02-dags-and-dagu.md)** - Workflow generation and execution
- **[Git and Worktrees](./03-git-and-worktrees.md)** - Branch-based task isolation
- **[AI Runners](./04-ai-runners.md)** - AI execution options

## Core Concepts Overview

Agent Arborist operates on these fundamental concepts:

1. **Specs** - Markdown files describing tasks in a declarative format
2. **Tasks** - Individual units of work with specific IDs and descriptions
3. **DAGs** - Directed Acyclic Graphs representing task dependencies
4. **Worktrees** - Git worktrees providing isolated workspaces
5. **AI Runners** - The AI systems that execute tasks

## The Execution Pipeline

```mermaid
graph LR
    A[Spec<br/>tasks.md] --> B[DAG Generator]
    B --> C[Dagu YAML<br/>Root + Sub-DAGs]
    C --> D[Branch Creation]
    D --> E[Task Execution]
    E --> F[AI Runner]
    F --> G[Git Worktree]
    G --> H[Commit & Merge]
    H --> I[Status Update]
```

## Key Relationships

```mermaid
graph TB
    Spec[Spec File] --> contains[Contains]
    contains --> Task1[Task T001]
    contains --> Task2[Task T002]
    contains --> Task3[Task T003]

    Task1 --> hasDep[Has Dependency]
    Task2 --> hasDep
    Task3 --> hasDep

    hasDep --> DAG[Creates DAG]
    DAG --> SubDAG1[Sub-DAG T001]
    DAG --> SubDAG2[Sub-DAG T002]
    DAG --> SubDAG3[Sub-DAG T003]

    Task1 --> createsBranch[Creates Branch]
    Task2 --> createsBranch
    Task3 --> createsBranch

    createsBranch --> Branch1[feature/001/ T001]
    createsBranch --> Branch2[feature/001/ T002]
    createsBranch --> Branch3[feature/001/ T003]

    Branch1 --> hasWorktree[Has Worktree]
    Branch2 --> hasWorktree
    Branch3 --> hasWorktree
```

## Next Steps

Start with [Specs and Tasks](./01-specs-and-tasks.md) to learn how to define your first task specification.