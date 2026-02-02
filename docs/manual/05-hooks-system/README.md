# Part 5: Hooks System

Hooks inject custom steps into task execution for testing, validation, notifications, and more.

## Overview

Hooks allow you to run custom commands or AI evaluations at specific points during task execution. They integrate seamlessly into the generated DAG workflow.

## When to Use Hooks

Common use cases:
- **Testing**: Run tests after AI completes a task
- **Validation**: Check code quality with linting or type checking
- **Documentation**: Generate or update docs after changes
- **Notifications**: Send Slack/Discord alerts on task completion
- **Metrics**: Extract and store performance metrics
- **Quality Checks**: Use AI to evaluate code quality

## Hook Types

### Shell Hooks

Execute shell commands:

```json
{
  "run_tests": {
    "type": "shell",
    "command": "cd $ARBORIST_WORKTREE && python -m pytest tests/ -v",
    "timeout": 120
  }
}
```

Available environment variables:
- `ARBORIST_WORKTREE` - Path to task's worktree
- `ARBORIST_MANIFEST` - Path to branch manifest
- `ARBORIST_TASK_ID` - Current task ID

### LLM Evaluation Hooks

Use AI to evaluate code quality or outputs:

```json
{
  "quality_check": {
    "type": "llm_eval",
    "prompt_file": "quality_check.md",
    "model": "haiku"
  }
}
```

The prompt file can reference:
- `{{task_id}}` - Current task ID
- `{{git_diff}}` - Git diff of changes
- `{{worktree_path}}` - Path to worktree

### Custom Hooks

Define your own hook implementations in Python:

```python
# .arborist/hooks/custom.py
def my_custom_hook(task_id, worktree_path, manifest):
    """Custom hook logic."""
    # Your code here
    return {"status": "success", "data": {...}}
```

## Hook Injection Points

Hooks can be injected at these points in task execution:

| Injection Point | Description | Example Use |
|----------------|-------------|-------------|
| `pre_sync` | Before syncing worktree | Dependency checks |
| `post_run` | After AI completes task | Run tests, lint code |
| `pre_commit` | Before committing changes | Quality checks |
| `post_commit` | After committing changes | Notifications |
| `pre_merge` | Before merging to parent | Integration tests |
| `post_merge` | After merging to parent | Update docs |
| `cleanup` | During cleanup | Delete temporary files |

## Configuration

Create `.arborist/config.json` to enable hooks:

```json
{
  "version": "1",
  "defaults": {
    "runner": "claude",
    "model": "sonnet"
  },
  "hooks": {
    "enabled": true,
    "prompts_dir": "prompts",
    "step_definitions": {
      "run_tests": {
        "type": "shell",
        "command": "cd $ARBORIST_WORKTREE && python -m pytest tests/ -v --tb=short 2>&1 || true",
        "timeout": 120,
        "extract_pattern": "(\\d+) passed",
        "continue_on_failure": true
      },
      "lint_code": {
        "type": "shell",
        "command": "cd $ARBORIST_WORKTREE && flake8 src/ --max-line-length=100 || true",
        "timeout": 60,
        "continue_on_failure": true
      },
      "quality_check": {
        "type": "llm_eval",
        "prompt_file": "quality_check.md",
        "model": "haiku",
        "continue_on_failure": true
      }
    },
    "injections": {
      "post_task": [
        {"step": "lint_code", "name": "lint"},
        {"step": "run_tests", "name": "test"},
        {"step": "quality_check", "name": "quality"}
      ]
    }
  }
}
```

## Hook Options

### Available Options

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `type` | string | Hook type (`shell`, `llm_eval`) | Required |
| `command` | string | Shell command to execute | (shell only) |
| `prompt_file` | string | Path to prompt template | (llm_eval only) |
| `model` | string | AI model for evaluation | (llm_eval only) |
| `timeout` | integer | Timeout in seconds | 60 |
| `continue_on_failure` | boolean | Continue if hook fails | false |
| `extract_pattern` | string | Regex to extract metrics | None |

### Extract Pattern

Use `extract_pattern` to extract data from hook output:

```json
{
  "run_tests": {
    "type": "shell",
    "command": "pytest tests/ -v",
    "extract_pattern": "(\\d+) passed, (\\d+) failed"
  }
}
```

Extracted values are stored in task state and can be visualized.

## Prompt Files

Store AI evaluation prompts in `.arborist/prompts/`:

### Example: Quality Check

**File:** `.arborist/prompts/quality_check.md`

```markdown
# Code Quality Evaluation

Evaluate the code changes for task {{task_id}}.

## Git Diff
```
{{git_diff}}
```

## Evaluation Criteria

Rate the code from 1-10 based on:
1. **Correctness** - Does it work as intended?
2. **Readability** - Is the code clear and well-named?
3. **Best Practices** - Does it follow Python conventions?
4. **Testing** - Are appropriate tests included?

## Response Format

Respond with JSON only:
```json
{
  "score": <1-10>,
  "summary": "<one sentence summary>",
  "suggestions": ["<suggestion 1>", "<suggestion 2>"]
}
```
```

## CLI Commands

### List Hooks

```bash
arborist hooks list
# Output:
# Hook Name      Type     Injection Points
# -----------     ----     ------------------
# lint_code       shell    post_task
# run_tests       shell    post_task
# quality_check   llm_eval post_task
```

### Validate Hooks

```bash
arborist hooks validate
# Checks:
# - Hook commands are executable
# - Prompt files exist
# - Models are valid
```

### Run Hook Manually

```bash
arborist hooks run lint_code --task T001
```

### Show Hook Output

```bash
arborist viz metrics 001-calculator
# Shows hook outputs including tests passed, lint errors, quality scores
```

## Example: Complete Setup

### 1. Create Config

```bash
cat > .arborist/config.json << 'EOF'
{
  "version": "1",
  "defaults": {
    "runner": "claude",
    "model": "sonnet"
  },
  "hooks": {
    "enabled": true,
    "prompts_dir": "prompts",
    "step_definitions": {
      "run_tests": {
        "type": "shell",
        "command": "cd $ARBORIST_WORKTREE && python -m pytest tests/ -v 2>&1 || true",
        "timeout": 120,
        "extract_pattern": "(\\d+) passed"
      }
    },
    "injections": {
      "post_task": [
        {"step": "run_tests", "name": "test"}
      ]
    }
  }
}
EOF
```

### 2. Create Prompt (for LLM eval)

```bash
mkdir -p .arborist/prompts

cat > .arborist/prompts/quality_check.md << 'EOF'
# Quality Check

Task: {{task_id}}

Diff:
{{git_diff}}

Evaluate: 1-10
JSON: {"score": N, "summary": "..."}
EOF
```

### 3. Generate DAG with Hooks

```bash
arborist spec dag-build 001-feature
#Hooks are automatically injected into generated DAG
```

### 4. Verify Hooks in DAG

```bash
grep -A 5 "name: run-test" .arborist/dagu/dags/001-feature.yaml
```

## Extracting and Visualizing Hook Results

After running the DAG, extract metrics:

```bash
# View metrics
arborist viz metrics 001-calculator

# Expected output:
{
  "summary": {
    "total_tasks": 5,
    "hooks_run": 15,
    "pass_rate": 0.93
  },
  "tasks": {
    "T001": {
      "test": {"passed": 8, "failed": 0},
      "quality": {"score": 9, "summary": "Clean code"}
    },
    ...
  }
}
```

Export metrics for external analysis:

```bash
arborist viz export 001-calculator --output-dir reports --formats json,csv
```

## Best Practices

### 1. Use `continue_on_failure` for Non-Critical Hooks

```json
{
  "run_tests": {
    "type": "shell",
    "command": "pytest tests/",
    "continue_on_failure": true  # Don't fail the task if tests fail
  }
}
```

### 2. Set Appropriate Timeouts

```json
{
  "run_tests": {
    "timeout": 300  # Longer for comprehensive test suites
  },
  "quick_check": {
    "timeout": 30  # Shorter for fast linting
  }
}
```

### 3. Extract Quantitative Metrics

```json
{
  "run_tests": {
    "extract_pattern": "(\\d+) passed, (\\d+) failed, (\\d+) errors"
  }
}
```

### 4. Use Fast Models for Evaluation

```json
{
  "quality_check": {
    "model": "haiku",  // Fast and cheap model
    "type": "llm_eval"
  }
}
```

### 5. Keep Prompts Focused

Write clear, specific prompts without excess context to:
- Reduce AI inference cost
- Improve response quality
- Speed up execution

## Troubleshooting

### Hook Not Executing

**Symptom:** Hook doesn't run

**Solutions:**
1. Check `hooks.enabled` is `true` in config
2. Verify hook command is executable
3. Check hook is in correct `injections` section

### Hook Timeout

**Symptom:** Hook times out

**Solutions:**
1. Increase `timeout` value
2. Optimize hook command
3. Set `continue_on_failure: true`

### Pattern Not Matching

**Symptom:** `extract_pattern` returns null

**Solutions:**
1. Test pattern with online regex tester
2. Ensure output contains expected format
3. Hook output: `arborist viz metrics 001-feature`

See [Troubleshooting](../appendices/01-troubleshooting.md) for more help.

## See Also

- [Configuration System](../03-configuration/01-configuration-system.md)
- [DAGs and Dagu](../02-core-concepts/02-dags-and-dagu.md)
- [Visualization](../07-telemetry-and-visualization/README.md)