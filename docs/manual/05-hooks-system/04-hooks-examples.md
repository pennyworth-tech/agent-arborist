# Hooks Examples

This section provides practical examples of common hook implementations.

## Example 1: Input Validation Hook

Validate task descriptions before generation.

### Configuration

```yaml
hooks:
  pre_generation:
    - name: validate-input
      command: scripts/validate-input.sh
      enabled: true
```

### Hook Script

```bash
#!/bin/bash
# scripts/validate-input.sh

# Read input
INPUT=$(cat)

# Check for forbidden terms
if echo "$INPUT" | grep -qi "delete.*all\|drop.*table\|rm -rf"; then
  echo "Error: Forbidden terms found in description" >&2
  exit 1
fi

# Check minimum length
LENGTH=$(echo "$INPUT" | jq -r '.description' | wc -c)
if [ $LENGTH -lt 20 ]; then
  echo "Error: Description too short (minimum 20 characters)" >&2
  exit 1
fi

echo "Input validation passed"
exit 0
```

## Example 2: Compliance Metadata Hook

Add required metadata to generated specs.

### Configuration

```yaml
hooks:
  post_spec:
    - name: add-compliance-metadata
      command: scripts/add-metadata.py
      enabled: true
```

### Hook Script

```python
#!/usr/bin/env python3
# scripts/add-metadata.py

import sys
import yaml
from datetime import datetime

# Read input
input_data = yaml.safe_load(sys.stdin)

# Read spec file
spec_file = input_data['spec_file']
with open(spec_file, 'r') as f:
    spec = yaml.safe_load(f)

# Add compliance metadata
spec['compliance'] = {
    'reviewed': True,
    'reviewer': 'compliance-bot',
    'reviewed_at': datetime.utcnow().isoformat(),
    'classification': 'internal',
    'data_retention_days': 90
}

# Write modified spec
with open(spec_file, 'w') as f:
    yaml.dump(spec, f)

print("Compliance metadata added")
sys.exit(0)
```

## Example 3: Environment-Specific Settings Hook

Apply environment-specific DAGU settings.

### Configuration

```yaml
hooks:
  post_dagu:
    - name: apply-environment-settings
      command: scripts/apply-env.sh
      enabled: true
      env:
        ENVIRONMENT: production
```

### Hook Script

```bash
#!/bin/bash
# scripts/apply-env.sh

ENVIRONMENT=${ENVIRONMENT:-development}
OUTPUT_DIR=${ENVIRONMENT}

# Read input
INPUT=$(cat)
DAG_FILE=$(echo "$INPUT" | jq -r '.dag_file')

# Apply environment-specific changes
case $ENVIRONMENT in
  production)
    # Production settings
    yq eval '.tasks[].retries = 3 | .tasks[].timeout_seconds = 3600' -i "$DAG_FILE"
    yq eval ".resources.cpu = \"2\" | .resources.memory = \"4Gi\"" -i "$DAG_FILE"
    ;;
  staging)
    # Staging settings
    yq eval '.tasks[].retries = 2 | .tasks[].timeout_seconds = 1800' -i "$DAG_FILE"
    ;;
  development)
    # Development settings
    yq eval '.tasks[].retries = 1 | .tasks[].timeout_seconds = 600' -i "$DAG_FILE"
    ;;
esac

echo "Applied $ENVIRONMENT environment settings"
exit 0
```

## Example 4: Dependency Check Hook

Verify system dependencies before execution.

### Configuration

```yaml
hooks:
  pre_execution:
    - name: check-dependencies
      command: scripts/check-deps.sh
      enabled: true
      timeout: 60
      continue_on_failure: false
```

### Hook Script

```bash
#!/bin/bash
# scripts/check-deps.sh

# Required tools
REQUIRED_TOOLS=("python3" "docker" "kubectl" "jq")
MISSING_TOOLS=()

# Check each tool
for tool in "${REQUIRED_TOOLS[@]}"; do
  if ! command -v "$tool" &> /dev/null; then
    MISSING_TOOLS+=("$tool")
  fi
done

# Report missing tools
if [ ${#MISSING_TOOLS[@]} -gt 0 ]; then
  echo "Error: Missing required tools: ${MISSING_TOOLS[*]}" >&2
  exit 1
fi

# Check resources
TOTAL_MEMORY=$(free -g | awk '/^Mem:/{print $2}')
if [ $TOTAL_MEMORY -lt 8 ]; then
  echo "Warning: Low memory detected (${TOTAL_MEMORY}GB, minimum 8GB recommended)" >&2
fi

echo "All dependencies satisfied"
exit 0
```

## Example 5: Slack Notification Hook

Send notifications to Slack on completion.

### Configuration

```yaml
hooks:
  post_execution:
    - name: slack-notification
      command: scripts/notify-slack.sh
      enabled: true
      env:
        SLACK_WEBHOOK: ${SLACK_WEBHOOK_URL}
        SLACK_CHANNEL: #deployments
```

### Hook Script

```bash
#!/bin/bash
# scripts/notify-slack.sh

SLACK_WEBHOOK=${SLACK_WEBHOOK}
SLACK_CHANNEL=${SLACK_CHANNEL:-#notifications}

# Read input
INPUT=$(cat)
STATUS=$(echo "$INPUT" | jq -r '.status')
DAG_NAME=$(echo "$INPUT" | jq -r '.dag_file' | xargs basename | sed 's/.yaml$//')
DURATION=$(echo "$INPUT" | jq -r '.duration_seconds')

# Format duration
if [ $DURATION -lt 60 ]; then
  DURATION_FMT="${DURATION}s"
elif [ $DURATION -lt 3600 ]; then
  DURATION_FMT="$((DURATION / 60))m $((DURATION % 60))s"
else
  DURATION_FMT="$((DURATION / 3600))h $((DURATION % 3600 / 60))m"
fi

# Set color based on status
if [ "$STATUS" = "success" ]; then
  COLOR="#36a64f"
  EMOJI="✅"
else
  COLOR="#dc3545"
  EMOJI="❌"
fi

# Create message
MESSAGE=$(cat <<EOF
{
  "channel": "$SLACK_CHANNEL",
  "attachments": [
    {
      "color": "$COLOR",
      "title": "Workflow ${EMOJI}",
      "fields": [
        {
          "title": "Workflow",
          "value": "$DAG_NAME",
          "short": true
        },
        {
          "title": "Status",
          "value": "$STATUS",
          "short": true
        },
        {
          "title": "Duration",
          "value": "$DURATION_FMT",
          "short": true
        }
      ]
    }
  ]
}
EOF
)

# Send notification
curl -X POST -H 'Content-Type: application/json' \
  --data "$MESSAGE" \
  "$SLACK_WEBHOOK"

echo "Slack notification sent"
exit 0
```

## Example 6: Results Archival Hook

Archive workflow results to S3.

### Configuration

```yaml
hooks:
  post_execution:
    - name: archive-results
      command: scripts/archive-s3.sh
      enabled: true
      timeout: 300
      env:
        AWS_BUCKET: workflow-results
        AWS_REGION: us-east-1
```

### Hook Script

```bash
#!/bin/bash
# scripts/archive-s3.sh

AWS_BUCKET=${AWS_BUCKET}
AWS_REGION=${AWS_REGION}
TIMESTAMP=$(date +%Y%m%d-%H%M%S)

# Read input
INPUT=$(cat)
DAG_NAME=$(echo "$INPUT" | jq -r '.dag_file' | xargs basename | sed 's/.yaml$//')
OUTPUT_DIR=$(echo "$INPUT" | jq -r '.output_dir')

# Create archive
ARCHIVE_NAME="${DAG_NAME}-${TIMESTAMP}.tar.gz"
tar -czf /tmp/$ARCHIVE_NAME -C $OUTPUT_DIR .

# Upload to S3
S3_PATH="s3://${AWS_BUCKET}/${DAG_NAME}/${ARCHIVE_NAME}"
aws s3 cp /tmp/$ARCHIVE_NAME "$S3_PATH" \
  --region "$AWS_REION"

# Set lifecycle policy
aws s3api put-object-tagging \
  --bucket "$AWS_BUCKET" \
  --key "${DAG_NAME}/${ARCHIVE_NAME}" \
  --tagging 'TagSet=[{Key=Workflow,Value=DAGU},{Key=AutoExpire,Value=true}]'

# Cleanup
rm /tmp/$ARCHIVE_NAME

echo "Results archived to $S3_PATH"
exit 0
```

## Example 7: Output Processing Hook

Post-process workflow output data.

### Configuration

```yaml
hooks:
  post_execution:
    - name: process-output
      command: scripts/process-output.py
      enabled: true
```

### Hook Script

```python
#!/usr/bin/env python3
# scripts/process-output.py

import sys
import yaml
import json
import pandas as pd

# Read input
input_data = json.load(sys.stdin)
output_dir = input_data['output_dir']

# Process each task output
summary = {
    'workflow': input_data['dag_file'],
    'timestamp': input_data.get('timestamp'),
    'tasks': []
}

results_file = f"{output_dir}/summary.json"
with open(results_file, 'r') as f:
    results = json.load(f)

# Process task results
for task in results.get('tasks', []):
    task_name = task['name']
    task_output = f"{output_dir}/{task_name}.json"
    
    # Load task output
    with open(task_output, 'r') as f:
        output_data = json.load(f)
    
    # Add summary
    summary['tasks'].append({
        'name': task_name,
        'status': task['status'],
        'duration': task['duration_seconds'],
        'records_processed': output_data.get('count', 0),
        'output_size': output_data.get('size_bytes', 0)
    })

# Save processed summary
processed_file = f"{output_dir}/processed_summary.json"
with open(processed_file, 'w') as f:
    json.dump(summary, f, indent=2)

print(f"Processed output saved to {processed_file}")
sys.exit(0)
```

## Example 8: Multi-Hook Pipeline

Chain multiple hooks together.

### Configuration

```yaml
hooks:
  post_execution:
    - name: collect-metrics
      command: scripts/collect-metrics.sh
      enabled: true
      continue_on_failure: true
    
    - name: send-summary-email
      command: scripts/notify-email.sh
      enabled: true
      continue_on_failure: true
    
    - name: update-dashboard
      command: scripts/update-dashboard.py
      enabled: true
      continue_on_failure: true
    
    - name: archive-results
      command: scripts/archive-s3.sh
      enabled: true
```

### Execution Flow

```mermaid
graph LR
    A[Workflow Completes] --> B[Collect Metrics]
    B --> C[Send Email]
    C --> D[Update Dashboard]
    D --> E[Archive Results]
    E --> F[Complete]
    
    style B fill:#e1f5ff
    style C fill:#e1f5ff
    style D fill:#e1f5ff
    style E fill:#e1f5ff
```

## Example 9: Conditional Hook Execution

Run hooks based on conditions.

### Configuration

```yaml
hooks:
  post_execution:
    - name: conditional-notification
      command: scripts/conditional-notify.sh
      enabled: true
      env:
        NOTIFY_ON_FAILURE: true
        NOTIFY_ON_SUCCESS: false
```

### Hook Script

```bash
#!/bin/bash
# scripts/conditional-notify.sh

NOTIFY_ON_FAILURE=${NOTIFY_ON_FAILURE:-false}
NOTIFY_ON_SUCCESS=${NOTIFY_ON_SUCCESS:-true}

# Read input
INPUT=$(cat)
STATUS=$(echo "$INPUT" | jq -r '.status')

# Determine if notification should be sent
SHOULD_NOTIFY=false

if [ "$STATUS" = "success" ] && [ "$NOTIFY_ON_SUCCESS" = "true" ]; then
  SHOULD_NOTIFY=true
elif [ "$STATUS" = "failure" ] && [ "$NOTIFY_ON_FAILURE" = "true" ]; then
  SHOULD_NOTIFY=true
fi

if [ "$SHOULD_NOTIFY" = "true" ]; then
  # Send notification
  scripts/notify-slack.sh "$INPUT"
  echo "Notification sent"
else
  echo "Notification skipped (status: $STATUS)"
fi

exit 0
```

## Example 10: Spec Review Hook with Approval

Require manual approval before proceeding.

### Configuration

```yaml
hooks:
  post_spec:
    - name: request-approval
      command: scripts/request-approval.sh
      enabled: true
      timeout: 600  # 10 minutes for approval
```

### Hook Script

```bash
#!/bin/bash
# scripts/request-approval.sh

# Read input
INPUT=$(cat)
SPEC_NAME=$(echo "$INPUT" | jq -r '.spec_file' | xargs basename)

# Create approval request
REQUEST_FILE=".approvals/${SPEC_NAME}.pending"
mkdir -p .approvals

cat > "$REQUEST_FILE" <<EOF
{
  "spec_file": "$(echo "$INPUT" | jq -r '.spec_file')",
  "spec_content": "$(echo "$INPUT" | jq -r '.spec_content' | base64)",
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "status": "pending"
}
EOF

echo "Approval request created: $REQUEST_FILE"
echo "Please approve with: agent-arborist approve $SPEC_NAME"
echo "Waiting for approval..."
timeout 600 bash -c "while [ ! -f .approvals/${SPEC_NAME}.approved ]; do sleep 5; done"

if [ -f ".approvals/${SPEC_NAME}.approved" ]; then
  echo "✓ Approval received"
  rm "$REQUEST_FILE"
  exit 0
else
  echo "✗ Approval timeout"
  rm "$REQUEST_FILE"
  exit 1
fi
```

## Best Practices

### 1. Make Hooks Idempotent

```bash
# Good: Can run multiple times safely
if [ ! -f "$FLAG_FILE" ]; then
  # Create file only if it doesn't exist
  touch "$FLAG_FILE"
fi

# Bad: Always creates/overwrites
touch "$FLAG_FILE"
```

### 2. Handle Errors Gracefully

```bash
#!/bin/bash
set -euo pipefail

# Trap errors
trap 'echo "Error in hook at line $LINENO" >&2' ERR
```

### 3. Log Detailed Information

```bash
#!/bin/bash
LOG_FILE=".agent-arborist/hook-$(basename $0).log"

log() {
  echo "[$(date -Iseconds)] $*" | tee -a "$LOG_FILE"
}

log "Starting hook"
# Hook logic
log "Hook completed"
```

### 4. Validate Input

```python
#!/usr/bin/env python3
import sys
import json

data = json.load(sys.stdin)

# Validate required fields
required = ['phase', 'spec_file']
for field in required:
    if field not in data:
        print(f"Error: Missing required field: {field}", file=sys.stderr)
        sys.exit(1)
```

### 5. Keep Hooks Focused

```bash
# Good: Single responsibility
scripts/validate-input.sh   # Only validates
scripts/notify-slack.sh     # Only notifies

# Bad: Multiple responsibilities
scripts/validate-and-notify.sh  # Validates AND notifies
```

## Code References

- Hook execution: [`src/agent_arborist/hooks.py:execute_hook()`](../../src/agent_arborist/hooks.py)
- Hook configuration: [`src/agent_arborist/config.py:hooks`](../../src/agent_arborist/config.py)