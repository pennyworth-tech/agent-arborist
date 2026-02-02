# Hooks Configuration

This section details how to configure hooks in Agent Arborist.

## Configuration Structure

Hooks are configured in `agent-arborist.yaml` under the `hooks` key:

```yaml
# agent-arborist.yaml
hooks:
  pre_generation:
    - name: validate-input
      command: scripts/validate-input.sh
      enabled: true
      timeout: 60
      continue_on_failure: false
  
  post_spec:
    - name: review-spec
      command: scripts/review-spec.py
      enabled: true
  
  post_dagu:
    - name: modify-dagu
      command: scripts/modify-dagu.sh
      enabled: true
  
  pre_execution:
    - name: check-dependencies
      command: scripts/check-deps.sh
      enabled: true
  
  post_execution:
    - name: send-notification
      command: scripts/notify.py
      enabled: true
```

## Hook Configuration Options

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Unique identifier for the hook |
| `command` | string | Command to execute |

### Optional Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | true | Whether the hook is active |
| `timeout` | int | 60 | Timeout in seconds |
| `continue_on_failure` | bool | false | Whether to continue if hook fails |
| `env` | object | {} | Environment variables for the hook |
| `working_dir` | string | . | Working directory for the hook |

## Hook Phase Configurations

Each hook phase supports an array of hooks:

```yaml
hooks:
  pre_generation:
    - name: hook1
      command: cmd1.sh
    - name: hook2
      command: cmd2.sh
```

## Detailed Field Descriptions

### Name

The hook name must be unique within a phase:

```yaml
hooks:
  post_spec:
    - name: review-spec          # Good: descriptive
      command: scripts/review.sh
    - name: add-metadata         # Good: describes purpose
      command: scripts/metadata.sh
```

### Command

The command can be:
- Absolute path: `/path/to/script.sh`
- Relative path: relative to project root
- Shell command: `python scripts/hook.py arg1 arg2`

```yaml
hooks:
  post_spec:
    - name: simple-script
      command: scripts/hook.sh           # Relative path
    
    - name: absolute-path
      command: /usr/local/bin/validate.sh  # Absolute path
    
    - name: with-args
      command: python scripts/hook.py --verbose  # With arguments
```

### Enabled

Control whether a hook is active:

```yaml
hooks:
  post_spec:
    - name: active-hook
      command: scripts/active.sh
      enabled: true    # Hook will execute
    
    - name: disabled-hook
      command: scripts/disabled.sh
      enabled: false   # Hook will not execute
```

### Timeout

Set a custom timeout for long-running hooks:

```yaml
hooks:
  post_execution:
    - name: heavy-processing
      command: scripts/process.py
      timeout: 300  # 5 minutes
```

### Continue on Failure

Continue workflow even if hook fails:

```yaml
hooks:
  post_spec:
    - name: critical-validation
      command: scripts/validate.sh
      continue_on_failure: false  # Stop on failure (default)
    
    - name: optional-formatting
      command: scripts/format.py
      continue_on_failure: true   # Continue on failure
```

### Environment Variables

Pass environment variables to hooks:

```yaml
hooks:
  post_execution:
    - name: send-notification
      command: scripts/notify.sh
      env:
        SLACK_WEBHOOK: https://hooks.slack.com/..
        NOTIFICATION_LEVEL: info
```

### Working Directory

Set a specific working directory:

```yaml
hooks:
  post_spec:
    - name: validate-in-project
      command: scripts/validate.sh
      working_dir: /path/to/project
```

## Configuration Examples

### Example 1: Minimal Configuration

```yaml
hooks:
  post_spec:
    - name: review-spec
      command: scripts/review.sh
```

### Example 2: Production Configuration

```yaml
hooks:
  pre_generation:
    - name: validate-description
      command: scripts/validate-desc.sh
      enabled: true
      timeout: 30
  
  post_spec:
    - name: add-compliance-metadata
      command: scripts/compliance.py
      enabled: true
      timeout: 60
      continue_on_failure: false
      env:
        COMPLIANCE_MODE: strict
        REQUIRE_APPROVAL: true
  
  post_dagu:
    - name: apply-production-settings
      command: scripts/prod-settings.sh
      enabled: true
      timeout: 120
  
  pre_execution:
    - name: check-resources
      command: scripts/check-resources.sh
      enabled: true
      timeout: 60
  
  post_execution:
    - name: send-slack-notification
      command: scripts/notify.py
      enabled: true
      timeout: 30
      env:
        SLACK_WEBHOOK: https://hooks.slack.com/..
        NOTIFICATION_CHANNEL: #deployments
```

### Example 3: Development Configuration

```yaml
hooks:
  post_spec:
    - name: quick-review
      command: scripts/review.py
      enabled: true
      continue_on_failure: true  # Less strict for dev
  
  post_execution:
    - name: local-notification
      command: scripts/notify.sh
      enabled: true
      env:
        NOTIFY_MODE: local
```

### Example 4: Multi-Environment Configuration

Create environment-specific hook configs:

```yaml
# agent-arborist.yaml
hooks:
  include:
    - hooks/common.yaml
    - hooks/${ENVIRONMENT}.yaml
```

Then define:

```yaml
# hooks/common.yaml
hooks:
  post_execution:
    - name: log-results
      command: scripts/log.sh
```

```yaml
# hooks/production.yaml
hooks:
  pre_execution:
    - name: production-checks
      command: scripts/prod-checks.sh
  
  post_execution:
    - name: send-alerts
      command: scripts/alerts.sh
```

```yaml
# hooks/development.yaml
hooks:
  post_spec:
    - name: dev-formatting
      command: scripts/format.sh
```

## Hook Command Patterns

### Shell Scripts

```yaml
hooks:
  post_spec:
    - name: shell-hook
      command: scripts/hook.sh
```

```bash
#!/bin/bash
# scripts/hook.sh
echo "Running hook..."
# Hook logic here
exit 0
```

### Python Scripts

```yaml
hooks:
  post_spec:
    - name: python-hook
      command: python scripts/hook.py
```

```python
#!/usr/bin/env python3
# scripts/hook.py
import sys
import json

# Read input from stdin
input_data = json.load(sys.stdin)

# Hook logic here
print("Processing...")

# Exit with status
sys.exit(0)
```

### Node.js Scripts

```yaml
hooks:
  post_execution:
    - name: node-hook
      command: node scripts/hook.js
```

```javascript
#!/usr/bin/env node
// scripts/hook.js
console.log("Running node hook...");
// Hook logic here
process.exit(0);
```

## Best Practices

### 1. Use Descriptive Names

```yaml
hooks:
  post_spec:
    - name: validate-task-spec-compliance  # Clear and descriptive
    - name: review-spec  # Too vague, what kind of review?
```

### 2. Set Appropriate Timeouts

```yaml
hooks:
  - name: quick-validation
    command: scripts/quick.sh
    timeout: 30  # Appropriate for quick validation
  
  - name: heavy-processing
    command: scripts/heavy.py
    timeout: 600  # Longer timeout for heavy processing
```

### 3. Use Environment Variables

```yaml
hooks:
  post_execution:
    - name: notify
      command: scripts/notify.sh
      env:
        # Don't hardcode sensitive values
        SLACK_WEBHOOK: ${SLACK_WEBHOOK}
```

### 4. Group Related Hooks

```yaml
hooks:
  post_execution:
    # Notification hooks grouped together
    - name: slack-notification
      command: scripts/slack.sh
    
    - name: email-notification
      command: scripts/email.sh
    
    - name: logging
      command: scripts/log.sh
```

### 5. Document Hook Purpose

```yaml
hooks:
  post_spec:
    # This hook ensures all specs comply with company standards
    - name: compliance-check
      command: scripts/compliance.py
```

## Troubleshooting

### Issue: Hook not executing

**Check:**
- Hook is enabled (`enabled: true`)
- Command path is correct
- Hook file has execute permissions (`chmod +x script.sh`)

### Issue: Hook timing out

**Solution:** Increase timeout:

```yaml
hooks:
  - name: slow-hook
    command: scripts/slow.py
    timeout: 300
```

### Issue: Environment variables not available

**Solution:** Use proper syntax:

```yaml
hooks:
  - name: hook
    command: scripts/hook.sh
    env:
      VAR: value  # Plain value
      ENV_VAR: ${ENV_VAR}  # From environment
```

## Code References

- Configuration schema: [`src/agent_arborist/config.py`](../../src/agent_arborist/config.py)
- Hook loading: [`src/agent_arborist/hooks.py:load_hooks()`](../../src/agent_arborist/hooks.py)
- Hook execution: [`src/agent_arborist/hooks.py:execute_hook()`](../../src/agent_arborist/hooks.py)

## Next Steps

- See practical [Hooks Examples](./04-hooks-examples.md)
- Learn about [Hooks Lifecycle](./02-hooks-lifecycle.md)