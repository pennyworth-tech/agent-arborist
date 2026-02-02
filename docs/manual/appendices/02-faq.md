# FAQ

Frequently asked questions about Agent Arborist.

## General Questions

### What is Agent Arborist?

Agent Arborist is an AI-powered tool that generates task specifications from natural language descriptions and creates executable workflows using DAGU. It simplifies workflow creation by leveraging AI capabilities to translate plain English requirements into structured workflows.

**Learn more:** [Introduction](../01-getting-started/02-introduction.md)

### What can I do with Agent Arborist?

You can:
- Generate task specifications from natural language descriptions
- Create DAGU workflow configurations automatically
- Execute workflows with Git worktree isolation
- Integrate with multiple AI providers (Claude, OpenAI)
- Run workflows in containers for reproducibility
- Customize workflows with hooks
- Orchestrate complete workflows end-to-end

**See examples:** [Quick Start](../01-getting-started/03-quick-start.md)

### Is Agent Arborist free?

The tool itself is open-source and free to use. However, you'll need API keys for AI runners (Claude, OpenAI), which have associated costs based on usage. You can use the Mock runner for testing without API costs.

### What are the system requirements?

- **Python:** 3.11 or higher
- **Docker** (optional, for container support)
- **Git** (for worktree management)
- **DAGU** (for workflow execution)
- **Disk space:** Minimum 500MB free

**See installation:** [Quick Start - Installation](../01-getting-started/03-quick-start.md)

## Usage Questions

### How do I get started?

1. Install Agent Arborist:
   ```bash
   pip install agent-arborist
   ```

2. Configure:
   ```yaml
   # agent-arborist.yaml
   runner: claude
   ```

3. Run:
   ```bash
   agent-arborist orchestrate "Build a data pipeline"
   ```

**Full guide:** [Quick Start](../01-getting-started/03-quick-start.md)

### What's the difference between the CLI commands?

- **`generate-task-spec`**: Only generates a task specification
- **`generate-dagu`**: Only generates a DAGU configuration from a spec
- **`run-dagu`**: Only runs an existing DAGU workflow
- **`orchestrate`**: Does it all: spec → DAGU → run

**Learn more:** [CLI Overview](../04-using-the-cli/01-cli-overview.md)

### Can I customize the generated workflows?

Yes! You can:
- Edit task specifications before DAGU generation
- Modify DAGU configurations
- Use hooks to customize execution
- Override container settings per task
- Configure retries, timeouts, and dependencies

**See:** [Hooks System](../05-hooks-system/01-hooks-overview.md)

### How do I use different AI models?

Configure in `agent-arborist.yaml`:

```yaml
runner: claude
claude:
  models:
    task_spec: claude-3-5-sonnet-20240620
    dagu: claude-3-haiku-20240307  # Cheaper for DAGU
```

**Details:** [Runners and Models](../03-configuration/02-runners-and-models.md)

## Configuration Questions

### Where should I put my configuration?

Default configuration file is `agent-arborist.yaml` in the project root. You can also:
- Use `--config` flag to specify a different file
- Set `AGENT_ARBORIST_CONFIG` environment variable
- Use environment-specific files (`config/production.yaml`)

**See:** [Configuration System](../03-configuration/01-configuration-system.md)

### How do I manage secrets?

**Best practices:**

1. **Never commit secrets** to version control
2. **Use environment variables:**
   ```yaml
   api_key: ${API_KEY}
   ```
3. **Use secret managers:**
   ```bash
   export API_KEY=$(aws secretsmanager get-secret-value --secret-id my-key --query SecretString --output text)
   ```

4. **Reference:** [Security Best Practices](../07-advanced-topics/04-best-practices.md)

### Can I use different configurations for different environments?

Yes! approaches:

1. **Multiple config files:**
   ```bash
   agent-arborist --config config/production.yaml orchestrate "Task"
   ```

2. **Environment variables:**
   ```bash
   export AGENT_ARBORIST_CONFIG=config/$ENVIRONMENT.yaml
   ```

3. **File includes:**
   ```yaml
   # agent-arborist.yaml
   include:
     - base.yaml
     - environments/${ENVIRONMENT}.yaml
   ```

## Workflow Questions

### How do parallel workflows work?

Set `parallel: true` in task steps:

```yaml
steps:
  - name: process-region-1
    command: python process.py --region us-east-1
    parallel: true
  
  - name: process-region-2
    command: python process.py --region us-west-2
    parallel: true
```

**Details:** [Workflows and Dependencies](../07-advanced-topics/03-workflows-and-dependencies.md)

### How do retries work?

Configure retry settings:

```yaml
steps:
  - name: unreliable-task
    command: python task.py
    retry:
      count: 3
      delay_seconds: 30
      backoff: exponential
```

### Can I run workflows in containers?

Yes! Configure container execution:

```yaml
container:
  enabled: true
  runtime: docker
  image: python:3.11-slim
  
  resources:
    cpu: "2"
    memory: "4Gi"
```

**Details:** [Container Support](../06-container-support/01-container-overview.md)

## Hooks Questions

### What are hooks used for?

Hooks are used to:
- Validate inputs and outputs
- Send notifications
- Integrate with external systems
- Post-process results
- Add company-specific metadata

**See:** [Hooks Overview](../05-hooks-system/01-hooks-overview.md)

### When do hooks execute?

Hooks execute at specific phases:
- **pre_generation**: Before generating spec
- **post_spec**: After generating spec, before DAGU
- **post_dagu**: After generating DAGU, before execution
- **pre_execution**: Before running workflow
- **post_execution**: After workflow completes

**Details:** [Hooks Lifecycle](../05-hooks-system/02-hooks-lifecycle.md)

## Cost Questions

### How much does it cost to use Agent Arborist?

**Costs:**
- **Agent Arborist**: Free (open-source)
- **Claude API**: $0.015 per 1K tokens (Sonnet)
- **OpenAI GPT-4**: $0.03 per 1K tokens (input)
- **Storage/Compute**: Depends on your infrastructure

### How can I reduce costs?

**Strategies:**

1. **Use cheaper models for DAGU:**
   ```yaml
   claude:
     models:
       task_spec: claude-3-5-sonnet
       dagu: claude-3-haiku  # Cheaper
   ```

2. **Use Mock runner for testing:**
   ```bash
   export AGENT_ARBORIST_RUNNER=mock
   ```

3. **Cache generated specs** to avoid regeneration

4. **Reuse specifications** across workflows

### How do I estimate costs?

Approximate costs for a typical workflow:

| Component | Claude Sonnet | Claude Haiku |
|-----------|---------------|--------------|
| Spec Generation | ~$0.10 | ~$0.03 |
| DAGU Generation | ~$0.05 | ~$0.01 |
| **Total per workflow** | ~$0.15 | ~$0.04 |

## Troubleshooting Questions

### Why is my workflow hanging?

Common causes:
1. Task waiting for dependencies
2. Insufficient system resources
3. Task stuck in loop
4. Network connectivity issues

**Solutions:**
- [Troubleshooting](./01-troubleshooting.md)
- Check task logs
- Enable verbose mode
- System resource monitoring

### Why is my runner timing out?

**Possible causes:**
1. Task description too complex
2. API rate limiting
3. Network issues
4. Timeout too low

**Solutions:**
- Increase timeout: `--timeout 600`
- Simplify description
- Check network connectivity
- Use different model

**See:** [Troubleshooting](./01-troubleshooting.md)

## Integration Questions

### Can I integrate with GitHub Actions?

Yes! Example workflow:

```yaml
# .github/workflows/arborist.yml
name: Agent Arborist

on: [push]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install dependencies
        run: pip install -e "."
      - name: Run workflow
        env:
          AGENT_ARBORIST_RUNNER: mock
        run: agent-arborist orchestrate "Test task"
```

### Can I use custom AI services?

Yes! Implement custom runner:

**See:** [Custom Runners](../07-advanced-topics/02-custom-runners.md)

### Can I run on Kubernetes?

Yes! Using Docker containers and K8s:

```yaml
container:
  enabled: true
  runtime: docker
  image: python:3.11-slim
```

Then deploy the container image with K8s.

**Best practices:** [Container Support](../06-container-support/01-container-overview.md)

## Best Practices Questions

### Should I use orchestrate or individual commands?

**Use `orchestrate` when:**
- Quick prototyping
- One-off workflows
- Simple requirements

**Use individual commands when:**
- Need to review specs before execution
- Want to customize generated workflows
- Complex multi-step requirements
- Production with review processes

**See:** [CLI Commands](../04-using-the-cli/01-cli-overview.md)

### How should I organize my project?

**Recommended structure:**

```
project/
├── agent-arborist.yaml      # Config
├── spec/                     # Specifications
│   └── my-task.yaml
├── dag/                      # DAGU configs
│   └── my-task.yaml
├── scripts/                  # Task scripts
│   └── process.py
├── .dagu/                    # DAGU runtime
├── output/                   # Outputs
├── work/                     # Worktrees
└── hooks/                    # Custom hooks
    └── notify.sh
```

### How do I ensure production readiness?

**Checklist:**
- [ ] Use versioned configuration
- [ ] Enable proper timeouts
- [ ] Implement retry logic
- [ ] Add monitoring and alerts
- [ ] Use containers for reproducibility
- [ ] Back up specifications and outputs
- [ ] Test with Mock runner first
- [ ] Review generated workflows

**Details:** [Best Practices](../07-advanced-topics/04-best-practices.md)

## Security Questions

### Is Agent Arborist secure?

Agent Arborist follows security best practices:
- Never commits secrets
- Supports read-only containers
- Non-root user support
- Network isolation
- Secure hooks execution

**See:** [Security Best Practices](../07-advanced-topics/04-best-practices.md)

### Can Agent Arborist access my files?

Agent Arborist creates and manages files only within configured directories:
- `spec/` - Task specifications
- `dag/` - DAGU configurations
- `output/` - Workflow outputs
- `work/` - Git worktrees
- `temp/` - Temporary files

It respects file permissions and requires access only to these directories.

### How are API keys handled?

API keys should:
1. Never be committed to version control
2. Be stored as environment variables
3. Use secret managers in production
4. Be rotated regularly

**See:** [Secrets Management](../07-advanced-topics/04-best-practices.md)

## Community Questions

### How can I contribute?

Contributions welcome! See:

1. Development setup
2. Code of conduct
3. Pull request process

**Details:** [Contributing](./03-contributing.md)

### Where can I get help?

Resources:
- [Documentation](../00-introduction/00-welcome.md)
- [Troubleshooting](./01-troubleshooting.md)
- GitHub Issues: Report bugs
- GitHub Discussions: Ask questions
- Community: Join the conversation

### Is there a community?

Yes! Join via:
- GitHub Discussions
- Slack/Discord (check repo for links)
- Office hours (check announcements)

## Technical Questions

### What is Git worktree isolation?

Git worktree isolation creates separate working directories for each workflow execution, preventing conflicts when running multiple workflows in parallel.

**See:** [Git and Worktrees](../02-core-concepts/03-git-and-worktrees.md)

### What models does Agent Arborist support?

**Built-in runners:**
- **Claude**: claude-3-5-sonnet, claude-3-opus, claude-3-haiku
- **OpenAI**: gpt-4, gpt-4-turbo, gpt-3.5-turbo
- **Mock**: Testing without API calls
- **Custom**: Your own runner implementation

**See:** [Runners and Models](../03-configuration/02-runners-and-models.md)

### Can I run multiple workflows simultaneously?

Yes! The Git worktree isolation enables parallel workflow execution without conflicts.

```bash
# Run in parallel
agent-arborist orchestrate "Task 1" &
agent-arborist orchestrate "Task 2" &
agent-arborist orchestrate "Task 3" &
```

## Related Questions

### How does Agent Arborist compare to other tools?

**Agent Arborist** focuses on:
- AI-generated specifications from natural language
- Simplicity and ease of use
- Flexible runner support
- Workflow isolation

**Comparison:**
- **Airflow**: Requires technical knowledge, less AI assistance
- **Prefect**: More complex, steeper learning curve
- **dbt**: Narrower focus (data transformations)

### What's the relationship with DAGU?

DAGU is the workflow execution engine that Agent Arborist uses. Agent Arborist generates DAGU configurations and manages their execution, while DAGU provides the runtime, UI, and scheduling.

**See:** [DAGs and DAGU](../02-core-concepts/02-dags-and-dagu.md)

### Can I use this for non-development workflows?

Yes! Agent Arborist can orchestrate workflows for:
- Data engineering (ETL pipelines)
- DevOps (CI/CD, deployments)
- Machine learning (training pipelines)
- Business processes (automated tasks)
- System administration (maintenance scripts)

## Still Have Questions?

- Check [Troubleshooting](./01-troubleshooting.md)
- Review [Documentation](../00-introduction/00-welcome.md)
- Open a [GitHub Discussion](https://github.com/your-org/agent-arborist/discussions)
- Report a [GitHub Issue](https://github.com/your-org/agent-arborist/issues)