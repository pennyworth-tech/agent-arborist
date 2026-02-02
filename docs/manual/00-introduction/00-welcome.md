# Welcome to Agent Arborist

Agent Arborist is an AI-powered task orchestration tool that transforms natural language specifications into executable workflows with complete Git-based reproducibility.

## Quick Links

- [📚 Full Manual](../README.md)
- [🚀 Quick Start](../01-getting-started/02-quick-start.md) - Get up and running in 5 minutes
- [🏗️ Architecture](../01-getting-started/03-architecture.md) - How Arborist works
- [⚙️ Configuration](../03-configuration/README.md) - Configure runners and settings

## What is Agent Arborist?

Agent Arborist bridges the gap between AI coding assistants and production-ready workflows:

1. **Define** your project as a structured markdown specification
2. **Orchestrate** tasks automatically with dependency-aware execution
3. **Isolate** each task in its own Git worktree
4. **Track** all changes in Git with complete history
5. **Reproduce** any output by replaying the same spec

## Key Features

### Task Specifications
Write your requirements in simple markdown:
```markdown
## Phase 1: Setup
- [ ] T001 Create project structure
- [ ] T002 Configure dependencies

## Phase 2: Implementation
- [ ] T003 [P] Implement core module
- [ ] T004 [P] Implement API endpoints

## Dependencies
T001 → T002 → T003, T004
```

### AI Execution
Arborist orchestrates AI agents to complete tasks:
- **Claude Code** - Advanced coding with stateful conversations
- **OpenCode** - Fast, efficient code generation
- **Gemini** - Google's AI for diverse use cases

### Git Worktree Isolation
Each task runs in its own isolated environment:
```
project/
├── .arborist/worktrees/001-feature/
│   ├── T001/  # Isolated workspace for task 1
│   ├── T002/  # Isolated workspace for task 2
│   └── T003/  # Isolated workspace for task 3
```

### DAG Orchestration
Powered by Dagu for robust task execution:
- Dependency-aware execution order
- Parallel task support
- Automatic retries and failure handling
- Web UI for monitoring

## When to Use Agent Arborist

✅ **Good fits:**
- Building new features with multiple sub-tasks
- Refactoring large codebases
- Generating comprehensive test suites
- Setting up new projects from scratch
- Automating repetitive development workflows

❌ **Not ideal for:**
- Single-line code changes
- Simple scripts under 50 lines
- One-off quick fixes
- Projects without Git

## Typical Workflow

```bash
# 1. Define your project
arborist spec create "Build a REST API with user auth"

# 2. Review and edit the generated spec
# Edit .arborist/specs/001-rest-api/tasks.md

# 3. Generate workflow DAG
arborist spec dag-build 001-rest-api

# 4. Create Git branches
arborist spec branch-create-all 001-rest-api

# 5. Execute the workflow
arborist dag run 001-rest-api

# 6. Monitor progress
arborist dag status 001-rest-api
```

## Installation

```bash
pip install agent-arborist

# Verify
arborist version  # 0.1.0
arborist doctor   # Check dependencies
```

## What makes Arborist different?

| Feature | Arborist | Other Tools |
|---------|----------|-------------|
| **Natural language specs** | ✅ Markdown-first | ❌ YAML/JSON required |
| **AI integration** | ✅ Multiple AI runners | ⚠️ Limited AI support |
| **Git isolation** | ✅ Worktree per task | ❌ Manual branch mgmt |
| **Parallel execution** | ✅ Built-in | ⚠️ Complex setup |
| **Reproducibility** | ✅ Git-tracked | ⚠️ Partial |
| **Observability** | ✅ Dagu UI + metrics | ⚠️ Basic |
| **Hooks** | ✅ Extensible | ⚠️ Limited |

## System Requirements

- **Python**: 3.11 or higher
- **Git**: Any recent version
- **Dagu**: 1.30.3 or higher (workflow executor)
- **AI Runner**:
  - Claude Code (Claude Pro/Max) - Recommended
  - OpenCode CLI
  - Gemini API key

## Next Steps

**New to Arborist?**
1. Start with [Quick Start](../01-getting-started/02-quick-start.md)
2. Build your first Hello World Calculator
3. Explore [Architecture](../01-getting-started/03-architecture.md)

**Ready to customize?**
1. [Configure your AI runners](../03-configuration/02-runners-and-models.md)
2. [Write advanced task specs](../02-core-concepts/01-specs-and-tasks.md)
3. [Set up hooks for custom execution](../05-hooks-system/README.md)

**Need help?**
- [Troubleshooting](../appendices/01-troubleshooting.md)
- [FAQ](../appendices/02-faq.md)
- [GitHub Issues](https://github.com/your-org/agent-arborist/issues)

## Version

This documentation covers **Agent Arborist 0.1.0**.

Check your version:
```bash
arborist version
```

## License

MIT License - see LICENSE file for details.

## Community

- GitHub: https://github.com/your-org/agent-arborist
- Discussions: https://github.com/your-org/agent-arborist/discussions
- Issues: https://github.com/your-org/agent-arborist/issues

---

Ready to get started? → [Quick Start](../01-getting-started/02-quick-start.md)