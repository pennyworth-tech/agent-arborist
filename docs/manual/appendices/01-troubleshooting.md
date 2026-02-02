# Troubleshooting

Common issues and solutions for Agent Arborist.

## Quick Reference

| Issue | Section |
|-------|---------|
| Configuration errors | [Configuration Issues](#configuration-issues) |
| Runner errors | [Runner Issues](#runner-issues) |
| Workflow execution errors | [Workflow Execution Issues](#workflow-execution-issues) |
| Container errors | [Container Issues](#container-issues) |
| Hook errors | [Hook Issues](#hook-issues) |
| Git worktree errors | [Git Worktree Issues](#git-worktree-issues) |

## Configuration Issues

### Issue: "Configuration file not found"

**Error:**
```
Error: Configuration file not found: agent-arborist.yaml
```

**Cause:** Configuration file missing or incorrect path.

**Solutions:**

1. **Check file exists in current directory:**
   ```bash
   ls agent-arborist.yaml
   ```

2. **Specify correct path with `--config` flag:**
   ```bash
   agent-arborist --config /path/to/config.yaml orchestrate "My task"
   ```

3. **Set environment variable:**
   ```bash
   export AGENT_ARBORIST_CONFIG=/path/to/config.yaml
   agent-arborist orchestrate "My task"
   ```

4. **Create default config file:**
   ```bash
   cat > agent-arborist.yaml << EOF
   runner: claude
   EOF
   ```

### Issue: "Invalid runner"

**Error:**
```
Error: Invalid runner: unknown-runner
Valid runners: claude, openai, mock
```

**Cause:** Runner not in supported list.

**Solutions:**

1. **Use a valid runner:**
   ```yaml
   runner: claude  # or openai or mock
   ```

2. **Check available runners:**
   ```bash
   agent-arborist --help
   ```

3. **Register custom runner (if available):**
   ```python
   # See Custom Runners documentation
   from agent_arborist.config import RUNNER_CLASSES
   RUNNER_CLASSES["my-runner"] = MyCustomRunner
   ```

### Issue: "Required field missing"

**Error:**
```
Error: Required field missing: 'timeouts'
```

**Cause:** Incomplete configuration.

**Solutions:**

1. **Add missing required fields:**
   ```yaml
   # Add to agent-arborist.yaml
   runner: claude
   timeouts:
     generate_task_spec: 300
     generate_dagu: 300
     run_dagu: 3600
     default: 300
   ```

2. **Use default config template:**
   ```yaml
   runner: claude
   claude:
     models:
       task_spec: claude-3-5-sonnet
   timeouts:
     default: 300
   paths:
     spec_dir: spec
     dag_dir: dag
   ```

## Runner Issues

### Issue: "API key not found"

**Error:**
```
Error: API key not found for claude runner
```

**Cause:** API credentials not configured.

**Solutions:**

1. **Set environment variable:**
   ```bash
   export ANTHROPIC_API_KEY=sk-ant-...
   ```

2. **Set in config file (not recommended):**
   ```yaml
   claude:
     api_key: sk-ant-...
   ```

3. **Use key management service:**
   ```bash
   export ANTHROPIC_API_KEY=$(aws secretsmanager get-secret-value --secret-id claude-api-key --query SecretString --output text)
   ```

### Issue: "Runner timeout"

**Error:**
```
Error: Runner timeout after 300 seconds
```

**Cause:** Runner took longer than configured timeout.

**Solutions:**

1. **Increase timeout in config:**
   ```yaml
   timeouts:
     generate_task_spec: 600  # Increase from 300
   ```

2. **Override with CLI flag:**
   ```bash
   agent-arborist --timeout 600 orchestrate "My task"
   ```

3. **Simplify task description:**
   ```bash
   # Use simpler, more focused description
   agent-arborist orchestrate "Simple ETL pipeline"
   ```

### Issue: "Invalid API response"

**Error:**
```
Error: Invalid API response from runner: Failed to parse JSON
```

**Cause:** API returned malformed response.

**Solutions:**

1. **Check API status:**
   ```bash
   # CheckAnthropic status
   curl https://status.anthropic.com
   
   # Check OpenAI status
   curl https://status.openai.com
   ```

2. **Retry the request:**
   ```bash
   agent-arborist orchestrate "My task"
   ```

3. **Use different runner:**
   ```bash
   agent-arborist --runner openai orchestrate "My task"
   ```

4. **Contact API provider support** if issue persists.

## Workflow Execution Issues

### Issue: "DAGU initialization failed"

**Error:**
```
Error: DAGU initialization failed
```

**Cause:** DAGU not installed or misconfigured.

**Solutions:**

1. **Check DAGU installation:**
   ```bash
   dagu version
   ```

2. **Install DAGU:**
   ```bash
   # Using install script
   curl -L https://raw.githubusercontent.com/dagu-dev/dagu/main/scripts/install.sh | bash

   # Or using brew
   brew install dagu
   ```

3. **Check DAGU configuration:**
   ```bash
   dagu init
   ```

### Issue: "Task execution failed"

**Error:**
```
Error: Task 'data-ingestion' failed with exit code 1
```

**Cause:** Task command failed.

**Solutions:**

1. **Check task logs:**
   ```bash
   cat output/workflow-name/logs/data-ingestion.log
   ```

2. **Test task command manually:**
   ```bash
   python scripts/data-ingestion.py
   ```

3. **Check task dependencies:**
   ```bash
   # Ensure required files exist
   ls data/input.json
   
   # Check dependencies installed
   pip install -r requirements.txt
   ```

4. **Review task configuration:**
   ```yaml
   # Check dag/file.yaml
   tasks:
     - name: data-ingestion
       command: python scripts/data-ingestion.py  # Verify path
   ```

### Issue: "Workflow hanging"

**Symptom:** Workflow appears to be stuck or making no progress.

**Causes & Solutions:**

1. **Check if tasks are waiting:**
   ```bash
   dagu status workflow-name
   ```

2. **Enable verbose logging:**
   ```bash
   agent-arborist orchestrate "My task" --verbose
   ```

3. **Check system resources:**
   ```bash
   # Check CPU/Memory usage
   top
   
   # Check disk space
   df -h
   ```

4. **Kill and retry:**
   ```bash
   # Stop workflow
   dagu stop workflow-name
   
   # Restart
   agent-arborist run-dagu dag/workflow.yaml --watch
   ```

## Container Issues

### Issue: "Container runtime not found"

**Error:**
```
Error: Container runtime not found: docker
```

**Cause:** Container runtime not installed or not in PATH.

**Solutions:**

1. **Check if Docker is installed:**
   ```bash
   docker --version
   ```

2. **Install Docker:**
   ```bash
   # Ubuntu/Debian
   sudo apt-get install docker.io
   
   # macOS
   brew install --cask docker
   
   # Use podman as alternative
   # Update config: runtime: podman
   ```

3. **Check Docker is running:**
   ```bash
   sudo systemctl status docker
   
   # macOS: Start Docker Desktop
   ```

### Issue: "Permission denied"

**Error:**
```
Error: Permission denied: cannot connect to Docker daemon
```

**Cause:** User not in docker group.

**Solutions:**

1. **Add user to docker group:**
   ```bash
   sudo usermod -aG docker $USER
   
   # Log out and log back in for changes to take effect
   ```

2. **Use sudo (temporary):**
   ```bash
   sudo docker ps
   ```

3. **Use podman (rootless):**
   ```yaml
   container:
     runtime: podman
   ```

### Issue: "Out of memory in container"

**Error:**
```
Error: Container exited with code 137 (OOM killed)
```

**Cause:** Container exceeded memory limit.

**Solutions:**

1. **Increase memory limit:**
   ```yaml
   container:
     resources:
       memory: "8Gi"  # Increase from 4Gi
   ```

2. **Check container logs for memory usage:**
   ```bash
   docker stats
   ```

3. **Optimize task memory usage:**
   ```python
   # Use generators instead of loading all data
   with open('large_file.json') as f:
       for line in f:
           process(line)
   ```

## Hook Issues

### Issue: "Hook not executing"

**Symptom:** Hook script not running when expected.

**Solutions:**

1. **Check hook is enabled:**
   ```yaml
   hooks:
     post_execution:
       - name: my-hook
         command: scripts/hook.sh
         enabled: true  # Ensure this is true
   ```

2. **Check hook file exists and is executable:**
   ```bash
   ls -la scripts/hook.sh
   chmod +x scripts/hook.sh
   ```

3. **Check hook command path:**
   ```yaml
   # Use absolute path
   command: /full/path/to/scripts/hook.sh
   
   # Or relative from project root
   command: scripts/hook.sh
   ```

4. **Enable verbose logging:**
   ```bash
   agent-arborist orchestrate "My task" --verbose
   ```

### Issue: "Hook timeout"

**Error:**
```
Error: Hook 'my-hook' timed out after 60 seconds
```

**Cause:** Hook took longer than configured timeout.

**Solutions:**

1. **Increase hook timeout:**
   ```yaml
   hooks:
     post_execution:
       - name: my-hook
         command: scripts/hook.sh
         timeout: 300  # Increase from 60
   ```

2. **Optimize hook execution:**
   ```bash
   # Make hookscript more efficient
   # Use faster tools, reduce I/O operations
   ```

3. **Set `continue_on_failure` for non-critical hooks:**
   ```yaml
   hooks:
     post_execution:
       - name: optional-hook
         command: scripts/hook.sh
         timeout: 60
         continue_on_failure: true
   ```

## Git Worktree Issues

### Issue: "Worktree creation failed"

**Error:**
```
Error: Failed to create Git worktree
```

**Cause:** Git error or permission issue.

**Solutions:**

1. **Check Git status:**
   ```bash
   git status
   ```

2. **Ensure working directory is clean:**
   ```bash
   git stash  # If you have uncommitted changes
   ```

3. **Check Git configuration:**
   ```bash
   git config --list | grep worktree
   ```

4. **Manually create worktree:**
   ```bash
   git worktree add work/arborist-test HEAD
   ```

5. **Check permissions:**
   ```bash
   ls -la work/
   chmod 755 work/
   ```

### Issue: "Worktree already exists"

**Error:**
```
Error: Worktree 'arborist-my-task' already exists
```

**Cause:** Previous worktree wasn't cleaned up.

**Solutions:**

1. **Remove existing worktree:**
   ```bash
   cd work
   git worktree remove arborist-my-task
   ```

2. **List all worktrees:**
   ```bash
   git worktree list
   ```

3. **Enable auto cleanup:**
   ```bash
   agent-arborist run-dagu dag/workflow.yaml --cleanup
   ```

## Debugging Tips

### Enable Debug Logging

```bash
# Enable verbose output
agent-arborist orchestrate "My task" --verbose

# Check logs in .agent-arborist/
ls .agent-arborist/logs/
```

### Check Configuration

```bash
# Validate configuration
python -c "from agent_arborist.config import load_config; print(load_config('agent-arborist.yaml'))"

# Check environment variables
env | grep AGENT_ARBORIST
```

### Test Components Individually

```bash
# Test runner only
agent-arborist generate-task-spec "Test" --runner mock

# Test DAGU generation only
agent-arborist generate-dagu spec/test.yaml --dry-run

# Test workflow only (with existing DAGU)
agent-arborist run-dagu dag/test.yaml --dry-run
```

### Check System Resources

```bash
# Check available memory
free -h

# Check disk space
df -h

# Check CPU
top -bn1 | head -20

# Check Docker resources
docker system df
```

## Getting More Help

### Enable Detailed Logs

```bash
# Set log level
export LOG_LEVEL=DEBUG
agent-arborist orchestrate "My task"
```

### Create Bug Report

Include:
1. **Configuration:** `agent-arborist.yaml` (with secrets removed)
2. **Error logs:** Full error message and stack trace
3. **Environment:** OS, Python version, Agent Arborist version
4. **Steps to reproduce:** Minimal reproduction case
5. **Expected vs actual:** What you expected vs what happened

### Code References

- Error handling: [`src/agent_arborist/exceptions.py`](../../src/agent_arborist/exceptions.py)
- Logging: [`src/agent_arborist/logging.py`](../../src/agent_arborist/logging.py)
- Validation: [`src/agent_arborist/config.py:validate_config()`](../../src/agent_arborist/config.py)

## See Also

- [FAQ](./02-faq.md) - Common questions
- [Best Practices](../07-advanced-topics/04-best-practices.md) - Avoiding issues
- [API Reference](../08-reference/03-api-reference.md) - Exception classes