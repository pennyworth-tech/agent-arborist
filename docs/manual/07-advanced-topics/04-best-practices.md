# Best Practices

This section covers production-grade best practices for using Agent Arborist effectively and securely.

## Overview

Best practices cover:
- Security considerations
- Performance optimization
- Error handling and monitoring
- CI/CD integration
- Documentation and maintenance
- Scalability patterns

## Security Best Practices

### 1. Never Commit Secrets

```yaml
# BAD
api_key: sk-ant-api03-abc123...

# GOOD
api_key: ${API_KEY}
```

Use environment variables or secret management:

```bash
export API_KEY=sk-ant-api03-abc123...
agent-arborist orchestrate "My task"
```

### 2. Use Read-Only Containers

```yaml
container:
  enabled: true
  security:
    read_only: true
    user: "1000:1000"
```

### 3. Validate External Input

```python
# In hooks/scripts/validate.sh
#!/bin/bash
INPUT=$(cat)

# Check for dangerous patterns
if echo "$INPUT" | grep -qi "rm -rf\|drop table\|delete.*all"; then
  echo "Error: Dangerous command detected" >&2
  exit 1
fi
```

### 4. Least Privilege Access

```yaml
container:
  security:
    user: "1000:1000"  # Non-root user
    network: bridge    # Not host network
```

### 5. Audit Configuration Changes

```yaml
# Include metadata in configuration
metadata:
  version: "1.0.0"
  last_updated: "2024-01-15"
  updated_by: "user@example.com"
```

## Performance Best Practices

### 1. Optimize Runner Selection

```yaml
# For high-quality specs
runner: claude
claude:
  models:
    task_spec: claude-3-5-sonnet

# For cost optimization
runner: claude
claude:
  models:
    task_spec: claude-3-5-sonnet
    dagu: claude-3-haiku  # Cheaper for DAGU
```

### 2. Use Parallel Execution

```yaml
steps:
  - name: process-region-1
    command: python process.py --region us-east-1
    parallel: true
  
  - name: process-region-2
    command: python process.py --region us-west-2
    parallel: true
```

### 3. Implement Caching

```python
# In custom runner
class CachingRunner(Runner):
    def generate_task_spec(self, description: str) -> str:
        cache_key = hashlib.sha256(description.encode()).hexdigest()
        cache_file = f".cache/{cache_key}.yaml"
        
        if os.path.exists(cache_file):
            return open(cache_file).read()
        
        result = self._call_api(description)
        open(cache_file, 'w').write(result)
        return result
```

### 4. Set Appropriate Timeout Values

```yaml
timeouts:
  generate_task_spec: 300   # 5 minutes
  generate_dagu: 300        # 5 minutes
  run_dagu: 3600          # 1 hour
```

### 5. Monitor Resource Usage

```yaml
container:
  resources:
    cpu: "2"
    memory: "4Gi"
```

## Workflow Design Best Practices

### 1. Define Clear Dependencies

```yaml
# Good: Explicit dependencies
steps:
  - name: finalize
    command: python finalize.py
    depends_on:
      - process-a
      - process-b
      - process-c

# Avoid: Implicit ordering
steps:
  - name: step1
    command: python step1.py
  - name: step2
    command: python step2.py  # Assumed to run after step1
```

### 2. Keep Workflows Modular

```yaml
# Good: Single responsibility per workflow
name: data-ingestion
steps:
  - name: fetch-data
    command: python fetch.py
  - name: validate-data
    command: python validate.py

# Also create separate workflow
name: data-transformation
steps:
  - name: transform-data
    command: python transform.py
```

### 3. Use Descriptive Names

```yaml
# Good: Descriptive
- name: validate-user-events-schema

# Avoid: Vague
- name: validate
```

### 4. Add Documentation

```yaml
name: user-event-pipeline
description: |
  Processes user events from Kafka, validates schema,
  transforms to standard format, and loads to PostgreSQL.

  Source: Kafka topic user-events
  Destination: PostgreSQL database.events table
  SLA: 5 minute delay
```

### 5. Implement Retry Logic

```yaml
steps:
  - name: api-call
    command: python call_api.py
    retry:
      count: 3
      delay_seconds: 30
      backoff: exponential
```

## Configuration Best Practices

### 1. Use Environment-Specific Configs

```yaml
# config/base.yaml
runner: claude
claude:
  models:
    task_spec: claude-3-5-sonnet

# config/production.yaml
timeouts:
  run_dagu: 7200  # 2 hours

# config/development.yaml
timeouts:
  run_dagu: 1800  # 30 minutes
```

### 2. Document Your Configuration

```yaml
# agent-arborist.yaml
# Configuration for production Agent Arborist deployment
# Maintainer: devops@example.com

# Runner configuration
runner: claude

# Timeouts (in seconds)
timeouts:
  generate_task_spec: 300
  generate_dagu: 300
  run_dagu: 3600
```

### 3. Use Default Values

```yaml
container:
  resources:
    cpu: ${CPU_LIMIT:-2}
    memory: ${MEMORY_LIMIT:-4Gi}
```

### 4. Validate Configuration

```python
# Configuration validation
def validate_config(config):
    required = ['runner', 'timeouts']
    for field in required:
        if field not in config:
            raise ValueError(f"Missing required field: {field}")
    
    if config['runner'] not in VALID_RUNNERS:
        raise ValueError(f"Invalid runner: {config['runner']}")
```

## Monitoring and Observability

### 1. Add Logging

```yaml
hooks:
  post_execution:
    - name: log-metrics
      command: scripts/log-metrics.sh
      enabled: true
```

```bash
#!/bin/bash
# scripts/log-metrics.sh
echo "Workflow: $DAG_NAME" >> metrics.log
echo "Duration: $DURATION" >> metrics.log
echo "Status: $STATUS" >> metrics.log
```

### 2. Send Notifications

```yaml
hooks:
  post_execution:
    - name: slack-notification
      command: scripts/notify-slack.sh
      enabled: true
      env:
        SLACK_WEBHOOK: ${SLACK_WEBHOOK_URL}
```

### 3. Track Metrics

```python
# scripts/track-metrics.py
import json
from datetime import datetime

metrics = {
    'workflow': dag_name,
    'timestamp': datetime.utcnow().isoformat(),
    'duration': duration,
    'status': status,
    'tasks': tasks
}

# Send to metrics system
requests.post('https://metrics.example.com/', json=metrics)
```

## Testing Best Practices

### 1. Test Locally First

```bash
# Use mock runner for testing
export AGENT_ARBORIST_RUNNER=mock
agent-arborist orchestrate "Test task"
```

### 2. Use Dry Run

```bash
agent-arborist orchestrate "My task" --dry-run
```

### 3. Validate Specs

```yaml
hooks:
  post_spec:
    - name: validate-spec
      command: scripts/validate-spec.py
      enabled: true
```

### 4. Test in Isolation

```bash
# Create test environment
cp -r . test-instance
cd test-instance
agent-arborist orchestrate "Test task"
```

## CI/CD Integration

### 1. GitHub Actions

```yaml
# .github/workflows/arborist.yml
name: Agent Arborist

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Test with mock runner
        env:
          AGENT_ARBORIST_RUNNER: mock
        run: |
          pip install -e .
          agent-arborist orchestrate "Test task" --dry-run
```

### 2. GitLab CI

```yaml
# .gitlab-ci.yml
test:
  image: python:3.11
  script:
    - pip install -e .
    - export AGENT_ARBORIST_RUNNER=mock
    - agent-arborist orchestrate "Test task" --dry-run
```

### 3. Pre-Commit Hooks

```bash
#!/bin/bash
# pre-commit hook
for spec in spec/*.yaml; do
  agent-arborist generate-dagu "$spec" --dry-run || exit 1
done
```

## Maintenance Best Practices

### 1. Version Your Config

```yaml
# agent-arborist.yaml
version: "2.0"  # Schema version

# Use specific model versions
claude:
  models:
    task_spec: claude-3-5-sonnet-20240620  # Specific version
```

### 2. Archive Old Specs

```yaml
hooks:
  post_execution:
    - name:Archive
      command: scripts/archive.sh
      enabled: true
```

```bash
#!/bin/bash
# scripts/archive.sh
DATE=$(date +%Y%m%d)
mv "spec/$SPEC_NAME" "spec/archive/$DATE.$SPEC_NAME"
```

### 3. Regular Audits

```python
# scripts/audit.py
import yaml

def audit_configs():
    """Audit all configurations."""
    for config_file in glob('**/*.yaml'):
        with open(config_file) as f:
            config = yaml.safe_load(f)
        validate_config(config)
```

## Scalability Best Practices

### 1. Use Container Scaling

```yaml
container:
  resources:
    cpu: "4"
    memory: "8Gi"
  
  mounts:
    - type: volume
      source: data-volume
      target: /data
```

### 2. Implement Horizontal Scaling

```yaml
steps:
  - name: distribute-tasks
    command: python distribute.py
  
  - name:-worker-1
    command: python worker.py --id 1
    depends_on:
      - distribute-tasks
    parallel: true
  
  - name: worker-2
    command: python worker.py --id 2
    depends_on:
      - distribute-tasks
    parallel: true
```

### 3. Use Distributed Systems

```yaml
# Integrate with Kubernetes
container:
  network: bridge

options:
  kubernetes:
    namespace: arborist
    replicas: 3
```

## Troubleshooting Checklist

### Before Deployment
- [ ] Configuration validated
- [ ] Secrets not committed
- [ ] Dependencies available
- [ ] Permissions correct
- [ ] Resources sufficient

### During Deployment
- [ ] Check logs
- [ ] Monitor progress
- [ ] Verify outputs
- [ ] Test rollback

### After Deployment
- [ ] Verify results
- [ ] Check metrics
- [ ] Review logs
- [ ] Archive outputs

## Code References

- Configuration: [`src/agent_arborist/config.py`](../../src/agent_arborist/config.py)
- Workflows: [`src/agent_arborist/workflow.py`](../../src/agent_arborist/workflow.py)
- Hooks: [`src/agent_arborist/hooks.py`](../../src/agent_arborist/hooks.py)
- Tests: [`tests/`](../../tests/)

## Additional Resources

- [CLI Reference](../08-reference/01-cli-reference.md)
- [Configuration Reference](../08-reference/02-configuration-reference.md)
- [API Reference](../08-reference/03-api-reference.md)
- [Troubleshooting](../appendices/01-troubleshooting.md)