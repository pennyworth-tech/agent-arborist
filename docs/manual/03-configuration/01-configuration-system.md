# Configuration System

Agent Arborist uses configuration files to control runtime behavior, AI runners, and execution settings. Configuration follows a precedence hierarchy that allows flexible customization.

## Configuration Precedence (Highest to Lowest)

1. **CLI flags** - Command-line arguments override everything
2. **Environment variables** - Set environment-specific values
3. **Project config** - `.arborist/config.json` - Project-specific settings
4. **Global config** - `~/.arborist_config.json` - System-wide defaults
5. **Code defaults** - Built-in defaults in Arborist code

## Configuration Formats

### JSON Configuration (Managed by Arborist)

**File locations:**
- Project config: `.arborist/config.json`
- Global config: `~/.arborist_config.json`

**When to use JSON:**
- Configuration files stored in `.arborist/` directory (managed internally by Arborist)
- Project-specific settings tracked in version control
- Generated or managed by Arborist commands

JSON is used for `.arborist/` configuration because:
- These files are programmatically read and written by Arborist
- Stored alongside other Arborist state (specs, DAGs, manifests)
- Part of Arborist's internal directory structure

**Example:**
```json
{
  "version": "1",
  "defaults": {
    "runner": "claude",
    "model": "sonnet",
    "container_mode": "enabled"
  },
  "timeouts": {
    "task_run": 3600
  },
  "hooks": {
    "enabled": true,
    "injections": {
      "post_task": [
        {"step": "run_tests", "name": "test"}
      ]
    }
  }
}
```

### YAML Configuration (External to Arborist)

**Note:** Arborist does not currently use YAML configuration files. The FAQ mentions `agent-arborist.yaml` as documentation artifacts, but the actual implementation uses JSON for all configuration files managed by Arborist.

## Initial Setup Commands

### Initialize Project Config

```bash
arborist init  # Creates .arborist/ directory
```

Then create your config:

```bash
# Create project config manually
cat > .arborist/config.json << 'EOF'
{
  "version": "1",
  "defaults": {
    "runner": "claude",
    "model": "sonnet"
  }
}
EOF
```

### Initialize Global Config

```bash
arborist config init --global
```

This creates `~/.arborist_config.json` with defaults.

## Configuration Fields

### Version

Required field, currently always `"1"`:

```json
{
  "version": "1",
  ...
}
```

### Defaults

Global default settings:

```json
{
  "version": "1",
  "defaults": {
    "runner": "claude",        // AI runner: claude, opencode, gemini
    "model": "sonnet",         // Model alias or name
    "container_mode": "auto"   // auto, enabled, disabled
  }
}
```

**Container Modes:**
- `auto` - Use container if `.devcontainer/` exists
- `enabled` - Require container (fails if missing)
- `disabled` - Never use container

### Timeouts

Set execution timeouts in seconds:

```json
{
  "timeouts": {
    "task_run": 3600,     // Maximum time per AI task
    "dag_run": 7200,      // Maximum time for entire DAG
    "test_run": 300,      // Maximum time for test hooks
    "default": 300        // Default timeout for other operations
  }
}
```

### Hooks

Configure hook system:

```json
{
  "hooks": {
    "enabled": true,
    "prompts_dir": "prompts",
    "step_definitions": {
      "run_tests": {
        "type": "shell",
        "command": "cd $ARBORIST_WORKTREE && pytest tests/",
        "timeout": 120
      }
    },
    "injections": {
      "post_task": [
        {"step": "run_tests", "name": "test"}
      ]
    }
  }
}
```

See [Hooks System](../05-hooks-system/README.md) for full details.

### Runners

Configure AI runners and models:

```json
{
  "runners": {
    "claude": {
      "default_model": "sonnet",
      "models": {
        "sonnet": "claude-3-5-sonnet-20241022",
        "opus": "claude-3-opus-20240229",
        "haiku": "claude-3-haiku-20240307"
      }
    },
    "gemini": {
      "default_model": "flash",
      "models": {
        "flash": "gemini-2.0-flash-exp",
        "pro": "gemini-2.5-pro"
      }
    },
    "opencode": {
      "default_model": "default"
    }
  }
}
```

See [Runners and Models](./02-runners-and-models.md) for full details.

## Environment Variables

Override config with environment variables:

```bash
# Set default runner
export ARBORIST_RUNNER=opencode

# Set default model
export ARBORIST_MODEL=haiku

# Set Dagu home directory
export DAGU_HOME=/custom/dagu/path

# Set model for specific runner
export ARBORIST_CLAUDE_MODEL=sonnet
export ARBORIST_GEMINI_MODEL=flash
export ARBORIST_OPENCODE_MODEL=default
```

## CLI Flag Overrides

CLI flags override both config and environment variables:

```bash
# Override runner
arborist task run T001 --runner gemini

# Override model
arborist spec dag-build 001-feature --model opus

# Override timeout
arborist dag run 001-feature --timeout 1800
```

## Complete Example Configuration

**File:** `.arborist/config.json`

```json
{
  "version": "1",
  "defaults": {
    "runner": "claude",
    "model": "sonnet",
    "container_mode": "disabled"
  },
  "timeouts": {
    "task_run": 1800,
    "dag_run": 3600,
    "default": 300
  },
  "hooks": {
    "enabled": true,
    "prompts_dir": "prompts",
    "step_definitions": {
      "run_tests": {
        "type": "shell",
        "command": "cd $ARBORIST_WORKTREE && python -m pytest tests/ -v 2>&1 || true",
        "timeout": 120,
        "extract_pattern": "(\\d+) passed",
        "continue_on_failure": true
      },
      "lint": {
        "type": "shell",
        "command": "cd $ARBORIST_WORKTREE && flake8 src/",
        "timeout": 30
      },
      "quality_check": {
        "type": "llm_eval",
        "prompt_file": "quality_check.md",
        "model": "haiku"
      }
    },
    "injections": {
      "post_task": [
        {"step": "lint", "name": "lint"},
        {"step": "run_tests", "name": "test"},
        {"step": "quality_check", "name": "quality"}
      ]
    }
  },
  "runners": {
    "claude": {
      "default_model": "sonnet",
      "models": {
        "fast": "claude-3-5-sonnet-20241022",
        "quality": "claude-3-opus-20240229",
        "cheap": "claude-3-haiku-20240307"
      }
    }
  }
}
```

## Configuration Commands

### Show Current Configuration

```bash
# Show full config (merged precedence)
arborist config show

# Show global config only
arborist config show --global

# Show project config only
arborist config show --project
```

### Validate Configuration

```bash
arborist config validate
```

Checks:
- Valid JSON syntax
- Required fields present
- Valid runner and model names
- Valid container mode

### Set Configuration Values

```bash
# Set default runner
arborist config set defaults.runner claude

# Set model
arborist config set defaults.model sonnet

# Set timeout
arborist config set timeouts.task_run 1800

# Global vs project
arborist config set --global defaults.runner opencode
```

## Multiple Project Configurations

You can have multiple projects with different configurations:

```bash
# Project A with Claude
cd project-a
echo '{"version":"1","defaults":{"runner":"claude"}}' > .arborist/config.json

# Project B with Gemini
cd project-b
echo '{"version":"1","defaults":{"runner":"gemini"}}' > .arborist/config.json
```

Use global config for defaults and project config for overrides:

```bash
# Global (shared across all projects)
cat > ~/.arborist_config.json << 'EOF'
{
  "version": "1",
  "defaults": {
    "runner": "claude",
    "model": "sonnet"
  }
}
EOF

# Project-specific override
cat > project-a/.arborist/config.json << 'EOF'
{
  "version": "1",
  "defaults": {
    "runner": "gemini"  // Override global for this project
  }
}
EOF
```

## Best Practices

1. **Use global config** for shared settings across projects
2. **Use project config** for project-specific overrides
3. **Commit project config** to version control for reproducibility
4. **Never commit secrets** - use environment variables for API keys
5. **Use model aliases** for easy switching
6. **Test configuration** with `arborist config validate`

## Secrets Management

Never store API keys in configuration files:

❌ **Wrong:**
```json
{
  "runners": {
    "gemini": {
      "api_key": "AIzaSy..."  // DON'T DO THIS
    }
  }
}
```

✅ **Correct:**
```bash
# Set as environment variable
export GOOGLE_API_KEY=AIzaSy...

# Or use secret manager in production
export GOOGLE_API_KEY=$(aws secretsmanager get-secret-value ...)
```

## Error Recovery and Cleanup

When tasks fail or you need to recover from errors:

### View Task State

```bash
# Check DAG status
arborist dag status 001-feature

# View task state file
cat .arborist/task-state/001-feature.json
```

### Inspect Failed Tasks

```bash
# View logs for failed task
ls .arborist/dagu/data/dags/001-feature/
cat .arborist/dagu/data/dags/001-feature/latest/stdout.log

# Inspect workspace (stored outside repo)
ls -la ~/.arborist/workspaces/my-project/001-feature/T003/
cd ~/.arborist/workspaces/my-project/001-feature/T003/
jj log --oneline
```

### Retry Failed Tasks

```bash
# Rerun the DAG (will skip completed tasks)
arborist dag run 001-feature
```

### Manual Fixes

```bash
# Go to the workspace and fix code manually
cd ~/.arborist/workspaces/my-project/001-feature/T003/
# Edit files...
jj describe -m "Fix: Manual fix for failed task"

# Retry
cd /path/to/project
arborist dag run 001-feature
```

### Clean Up Completely

```bash
# Remove all Arborist state
rm -rf .arborist

# Remove feature branches
git checkout main
git branch -D main_a main_a_T001 main_a_T002 main_a_T003

# Forget jj workspaces
jj workspace forget --all
```

### Reset Specific Spec

```bash
# Remove specific spec and its branches
rm -rf .arborist/specs/001-feature
rm -rf .arborist/dagu/dags/001-feature*
rm -rf ~/.arborist/workspaces/my-project/001-feature
rm -f .arborist/task-state/001-feature.json

# Remove branches
git checkout main
git branch -D main_a main_a_T001 main_a_T002 main_a_T003

# Prune worktrees
git worktree prune
```

## See Also

- [Runners and Models](./02-runners-and-models.md) - AI runner configuration
- [Hooks System](../05-hooks-system/README.md) - Hook configuration
- [CLI Reference](../appendices/03-cli-reference.md) - CLI flag reference
- [Troubleshooting](../appendices/01-troubleshooting.md) - Common issues