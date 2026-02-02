# CLI Reference

Complete reference for all Agent Arborist CLI commands and options.

## Convention Syntax

```bash
command [OPTIONS] ARGUMENT
```

- **COMMAND**: The command name (required)
- **[OPTIONS]**: Optional flags and parameters
- **ARGUMENT**: Required argument (no brackets)
- `<VALUE>`: Placeholder for actual value
- `|`: Mutually exclusive options

## Global Options

Options available for all commands:

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `--config` | path | Path to configuration file | `agent-arborist.yaml` |
| `--verbose` | flag | Enable verbose logging | `-v` |
| `--quiet` | flag | Suppress non-error output | `-q` |
| `--help` | flag | Show help message | `-h` |
| `--version` | flag | Show version information | `--V` |

## Commands

### `agent-arborist generate-task-spec`

Generate a task specification from a natural language description.

#### Syntax

```bash
agent-arborist generate-task-spec [OPTIONS] DESCRIPTION
```

#### Arguments

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `DESCRIPTION` | string | Yes | Natural language task description |

#### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--spec-name` | string | Generated | Name for the task spec file |
| `--runner` | string | Config | Override AI runner (claude, openai, mock) |
| `--output-dir` | path | Config | Override spec output directory |
| `--timeout` | int | Config | Timeout in seconds |
| `--dry-run` | flag | false | Show what would happen without executing |

#### Examples

```bash
# Basic usage
agent-arborist generate-task-spec "Build a data pipeline"

# Custom spec name
agent-arborist generate-task-spec "Process events" \
  --spec-name event-pipeline-v2

# Override runner
agent-arborist generate-task-spec "ETL pipeline" \
  --runner claude

# Dry run
agent-arborist generate-task-spec "Test task" \
  --dry-run

# With timeout
agent-arborist generate-task-spec "Long task" \
  --timeout 600
```

#### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Configuration error |
| 2 | Invalid arguments |
| 3 | Runner error |
| 4 | Timeout |

#### Output

Success output:
```bash
✓ Generated task specification: spec/data-pipeline.yaml

Summary:
  - Name: data-pipeline
  - Steps: 5
  - Estimated time: 30 minutes
```

#### See Also

- Configuration: [`src/agent_arborist/cli.py:generate_task_spec()`](../../src/agent_arborist/cli.py#L18)

---

### `agent-arborist generate-dagu`

Generate a DAGU configuration from a task specification.

#### Syntax

```bash
agent-arborist generate-dagu [OPTIONS] SPEC_FILE
```

#### Arguments

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `SPEC_FILE` | path | Yes | Path to task specification file |

#### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--dag-name` | string | Generated | Name for the DAGU config file |
| `--output-dir` | path | Config | Override DAGU output directory |
| `--timeout` | int | Config | Timeout in seconds |
| `--dry-run` | flag | false | Show what would happen without executing |

#### Examples

```bash
# Basic usage
agent-arborist generate-dagu spec/data-pipeline.yaml

# Custom DAG name
agent-arborist generate-dagu spec/pipeline.yaml \
  --dag-name production-pipeline

# Use different output dir
agent-arborist generate-dagu spec/pipeline.yaml \
  --output-dir custom/dags

# Dry run
agent-arborist generate-dagu spec/pipeline.yaml \
  --dry-run
```

#### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Spec file not found |
| 2 | Invalid spec format |
| 3 | Generation error |
| 4 | Timeout |

#### Output

Success output:
```bash
✓ Generated DAGU configuration: dag/data-pipeline.yaml

Summary:
  - DAG name: data-pipeline
  - Tasks: 5
  - Schedule: None (manual trigger)
```

#### See Also

- Configuration: [`src/agent_arborist/cli.py:generate_dagu()`](../../src/agent_arborist/cli.py#L45)

---

### `agent-arborist run-dagu`

Execute a DAGU workflow configuration.

#### Syntax

```bash
agent-arborist run-dagu [OPTIONS] DAG_FILE
```

#### Arguments

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `DAG_FILE` | path | Yes | Path to DAGU configuration file |

#### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--output-dir` | path | Config | Override output directory |
| `--timeout` | int | Config | Timeout in seconds |
| `--dry-run` | flag | false | Show what would happen without executing |
| `--watch` | flag | false | Watch execution in real-time |
| `--cleanup` | flag | false | Clean up worktree after completion |

#### Examples

```bash
# Basic usage
agent-arborist run-dagu dag/data-pipeline.yaml

# Watch execution
agent-arborist run-dagu dag/pipeline.yaml \
  --watch

# With cleanup
agent-arborist run-dagu dag/pipeline.yaml \
  --cleanup

# Use custom output directory
agent-arborist run-dagu dag/pipeline.yaml \
  --output-dir results/run-001

# Dry run
agent-arborist run-dagu dag/pipeline.yaml \
  --dry-run

# With timeout
agent-arborist run-dagu dag/pipeline.yaml \
  --timeout 7200
```

#### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | DAG file not found |
| 2 | Invalid DAG format |
| 3 | Execution error |
| 4 | Timeout |
| 5 | Task failure (if fail-fast enabled) |

#### Output

Success output:
```bash
✓ DAGU workflow completed: data-pipeline

Execution Summary:
  - Tasks executed: 5
  - Successful: 5
  - Failed: 0
  - Duration: 12m 34s

Output:
  - Results: output/data-pipeline/
  - Logs: output/data-pipeline/logs/
  - Summary: output/data-pipeline/summary.json
```

Watch mode output (during execution):
```bash
→ Running workflow: data-pipeline
  Task 1/5: data-ingestion ✓ (2m 10s)
  Task 2/5: data-validation ✓ (45s)
  Task 3/5: data-transformation ... →
```

#### See Also

- Configuration: [`src/agent_arborist/cli.py:run_dagu()`](../../src/agent_arborist/cli.py#L72)

---

### `agent-arborist orchestrate`

Execute the complete workflow: generate spec → generate DAGU → run workflow.

#### Syntax

```bash
agent-arborist orchestrate [OPTIONS] DESCRIPTION
```

#### Arguments

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `DESCRIPTION` | string | Yes | Natural language task description |

#### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--spec-name` | string | Generated | Name for the task spec file |
| `--dag-name` | string | Generated | Name for the DAGU config file |
| `--runner` | string | Config | Override AI runner |
| `--output-dir` | path | Config | Override output directory |
| `--timeout` | int | Config | Timeout in seconds |
| `--dry-run` | flag | false | Show what would happen without executing |
| `--verbose` | flag | false | Show detailed logs |
| `--watch` | flag | false | Watch execution in real-time |
| `--cleanup` | flag | false | Clean up worktree after completion |
| `--spec-only` | flag | false | Only generate spec, stop before DAGU |
| `--no-run` | flag | false | Generate spec and DAGU, but don't run |

#### Examples

```bash
# Quick start
agent-arborist orchestrate "Build a data pipeline"

# Custom names
agent-arborist orchestrate "Process events" \
  --spec-name event-spec \
  --dag-name event-dag

# Override runner
agent-arborist orchestrate "ETL pipeline" \
  --runner claude

# Watch execution
agent-arborist orchestrate "Long workflow" \
  --watch

# Generate only spec (stop before DAGU)
agent-arborist orchestrate "Review my spec" \
  --spec-only

# Generate spec and DAGU only (don't run)
agent-arborist orchestrate "Test DAGU config" \
  --no-run

# With cleanup
agent-arborist orchestrate "Production pipeline" \
  --cleanup

# Dry run
agent-arborist orchestrate "Test workflow" \
  --dry-run

# Verbose mode
agent-arborist orchestrate "Debug workflow" \
  --verbose
```

#### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Configuration error |
| 2 | Invalid arguments |
| 3 | Spec generation error |
| 4 | DAGU generation error |
| 5 | Execution error |
| 6 | Timeout |

#### Output

Success output:
```bash
→ Generating task specification...
  Step 1/4: Analyzing requirements
  Step 2/4: Identifying components
  Step 3/4: Defining workflow steps
  Step 4/4: Creating specification
✓ Task specification generated: spec/data-pipeline.yaml

→ Generating DAGU configuration...
  Step 1/3: Parsing specification
  Step 2/3: Creating DAG structure
  Step 3/3: Writing configuration
✓ DAGU configuration generated: dag/data-pipeline.yaml

→ Running workflow...
  Task 1/5: data-ingestion ✓ (2m 10s)
  Task 2/5: data-validation ✓ (45s)
  Task 3/5: data-transformation ✓ (5m 30s)
  Task 4/5: data-loading ✓ (3m 15s)
  Task 5/5: data-enrichment ✓ (1m 05s)
✓ Workflow completed

→ Cleanup complete

✓ Orchestration complete: data-pipeline

Summary:
  - Tasks executed: 5
  - Successful: 5
  - Failed: 0
  - Duration: 12m 45s

Artifacts:
  - Spec: spec/data-pipeline.yaml
  - DAGU: dag/data-pipeline.yaml
  - Output: output/data-pipeline/
```

#### Progress Indicators

| Symbol | Meaning |
|--------|---------|
| `→` | In progress |
| `✓` | Success/completed |
| `✗` | Failure |
| `⏱` | Timeout |
| `⏸` | Paused |
| `⟳` | Retrying |

#### See Also

- Configuration: [`src/agent_arborist/cli.py:orchestrate()`](../../src/agent_arborist/cli.py#L99)

---

### `agent-arborist version`

Display Agent Arborist version information.

#### Syntax

```bash
agent-arborist version
```

#### Options

None

#### Examples

```bash
agent-arborist version
# Output: Agent Arborist v0.1.0

# Or use --version flag
agent-arborist --version
# Output: Agent Arborist v0.1.0
```

#### See Also

- Implementation: [`src/agent_arborist/cli.py:version()`](../../src/agent_arborist/cli.py)

---

## Environment Variables

Environment variables override configuration file settings.

| Variable | Description | Example |
|----------|-------------|---------|
| `AGENT_ARBORIST_RUNNER` | AI runner to use | `claude` |
| `AGENT_ARBORIST_CONFIG` | Path to config file | `config/production.yaml` |
| `AGENT_ARBORIST_SPEC_DIR` | Spec directory | `specs/` |
| `AGENT_ARBORIST_DAG_DIR` | DAG directory | `dags/` |
| `AGENT_ARBORIST_DAGU_DIR` | DAGU directory | `.dagu/` |
| `AGENT_ARBORIST_OUTPUT_DIR` | Output directory | `output/` |
| `AGENT_ARBORIST_WORK_DIR` | Work tree directory | `work/` |
| `AGENT_ARBORIST_TEMP_DIR` | Temp directory | `tmp/` |

### Setting Environment Variables

```bash
# Set single variable
export AGENT_ARBORIST_RUNNER=claude

# Set multiple variables
export AGENT_ARBORIST_RUNNER=claude
export AGENT_ARBORIST_OUTPUT_DIR=custom/output

# Use inline
AGENT_ARBORIST_RUNNER=claude agent-arborist orchestrate "My task"

# Use default value
export AGENT_ARBORIST_TIMEOUT=${TIMEOUT:-300}
```

## Exit Codes

### Code Summary

| Code | Meaning | Recovery |
|------|---------|----------|
| 0 | Success | N/A |
| 1 | General error | Check logs/syntax |
| 2 | Invalid arguments | Check command syntax |
| 3 | Configuration error | Validate config file |
| 4 | File not found | Check file paths |
| 5 | Permission error | Check permissions |
| 6 | Network error | Check connection |
| 7 | Timeout | Increase timeout |
| 8 | API error | Check API credentials |
| 9 | Hook error | Fix hook script |
| 10 | Container error | Check docker/runtime |
| 11 | Git error | Check git status |
| 12 | Dependency error | Install dependencies |

### Checking Exit Codes

```bash
agent-arborist orchestrate "My task"
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
  echo "Success!"
else
  echo "Error: $EXIT_CODE"
fi
```

## Shell Completion

### Bash

```bash
# Enable bash completion
source <(agent-arborist --completion bash)

# Or add to .bashrc
echo 'source <(agent-arborist --completion bash)' >> ~/.bashrc
```

### Zsh

```bash
# Enable zsh completion
source <(agent-arborist --completion zsh)

# Or add to .zshrc
echo 'source <(agent-arborist --completion zsh)' >> ~/.zshrc
```

### Fish

```bash
# Enable fish completion
agent-arborist --completion fish > ~/.config/fish/completions/agent-arborist.fish
```

## Code References

- CLI definitions: [`src/agent_arborist/cli.py`](../../src/agent_arborist/cli.py)
- Click framework: https://click.palletsprojects.com/

## Related Documentation

- [Configuration Reference](./02-configuration-reference.md)
- [Getting Started](../01-getting-started/03-quick-start.md)