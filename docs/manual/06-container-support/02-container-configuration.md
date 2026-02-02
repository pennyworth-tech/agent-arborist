# Container Configuration

This section details all container configuration options available in Agent Arborist.

## Configuration Structure

Container configuration is defined in `agent-arborist.yaml`:

```yaml
# agent-arborist.yaml
container:
  enabled: true
  runtime: docker
  image: python:3.11-slim
  
  resources:
    cpu: "2"
    memory: "4Gi"
    gpu: false
  
  mounts:
    - type: bind
      source: ./data
      target: /data
      read_only: false
  
  environment:
    PYTHONPATH: /app
    LOG_LEVEL: info
  
  security:
    read_only: false
    network: bridge
    user: root
  
  options:
    cap_add: []
    cap_drop: []
    devices: []
```

## Top-Level Options

### enabled

Enable or disable container execution:

```yaml
container:
  enabled: true   # Use containers for execution
  enabled: false  # Execute on host
```

### runtime

Choose the container runtime:

```yaml
container:
  runtime: docker   # Docker (default)
  runtime: podman   # Podman
  runtime: auto     # Auto-detect
```

### image

Specify the container image:

```yaml
container:
  image: python:3.11-slim
  image: tensorflow/tensorflow:2.14.0
  image: gcr.io/my-project/my-image:latest
  image: my-registry.local/my-image:v1.0
```

## Resource Configuration

Control container resource limits:

```yaml
container:
  resources:
    cpu: "2"          # 2 CPU cores
    memory: "4Gi"     # 4GB RAM
    gpu: false        # Disable GPU
```

### cpu

CPU limit in cores:

```yaml
resources:
  cpu: "0.5"   # 0.5 cores
  cpu: "1"     # 1 core
  cpu: "2"     # 2 cores
  cpu: "4"     # 4 cores
```

### memory

Memory limit:

```yaml
resources:
  memory: "256Mi"   # 256 MB
  memory: "1Gi"     # 1 GB
  memory: "4Gi"     # 4 GB
  memory: "16Gi"    # 16 GB
```

Memory units:
- `Ki` / `K`: Kilobytes
- `Mi` / `M`: Megabytes
- `Gi` / `G`: Gigabytes
- `Ti` / `T`: Terabytes

### gpu

Enable GPU support:

```yaml
resources:
  gpu: false          # Disable GPU
  gpu: true           # Enable GPU (default: all)
  gpu: 0              # Use GPU 0
  gpu: [0, 1]         # Use GPUs 0 and 1
```

## Mount Configuration

Mount volumes into containers:

```yaml
container:
  mounts:
    - type: bind
      source: ./data
      target: /data
      read_only: false
```

### type

Mount type:

```yaml
type: bind    # Host path (default)
type: volume  # Docker volume
type: tmpfs   # Temporary filesystem
```

### source

Host path or volume name:

```yaml
source: ./data          # Relative path
source: /absolute/path  # Absolute path
source: my-volume       # Volume name
```

### target

Container path:

```yaml
target: /data           # Container directory
target: /config/app.yaml  # Specific file
```

### read_only

Read-only mount:

```yaml
read_only: false   # Read-write (default)
read_only: true    # Read-only
```

### Mount Examples

#### Bind Mount

```yaml
mounts:
  - type: bind
    source: ./data
    target: /data
    read_only: false
```

#### Read-Only Mount

```yaml
mounts:
  - type: bind
    source: ./config
    target: /etc/app/config
    read_only: true
```

#### Docker Volume

```yaml
mounts:
  - type: volume
    source: my-data-volume
    target: /data
```

#### Temporary Filesystem

```yaml
mounts:
  - type: tmpfs
    target: /tmp
    size: "1Gi"
```

## Environment Configuration

Set environment variables in containers:

```yaml
container:
  environment:
    PYTHONPATH: /app
    LOG_LEVEL: info
    API_KEY: ${API_KEY}
```

### Value Types

**Literal values:**

```yaml
PYTHONPATH: /app
LOG_LEVEL: info
```

**From environment:**

```yaml
API_KEY: ${API_KEY}
DATABASE_URL: ${DATABASE_URL:-postgresql://localhost/db}
```

**Default values:**

```yaml
DATABASE_URL: ${DATABASE_URL:-postgresql://localhost/db}
PORT: ${PORT:-8080}
```

## Security Configuration

Control container security settings:

```yaml
container:
  security:
    read_only: false
    network: bridge
    user: root
```

### read_only

Read-only root filesystem:

```yaml
security:
  read_only: false   # Read-write (default)
  read_only: true    # Read-only
```

**Note:** You'll need writable mounts when using read-only containers.

### network

Network mode:

```yaml
security:
  network: bridge    # Bridge network (default)
  network: host      # Use host network
  network: none      # No network
  network: container:existing  # Share network
```

### user

Run as specific user:

```yaml
security:
  user: root           # Run as root (default)
  user: 1000           # Run as UID 1000
  user: user:group     # Run as user:group
  user: "1000:1000"    # Run as UID:GID
```

## Additional Options

### cap_add / cap_drop

Manage Linux capabilities:

```yaml
options:
  cap_add:
    - NET_BIND_SERVICE
    - SYS_TIME
  
  cap_drop:
    - NET_RAW
    - MKNOD
```

### devices

Expose devices to container:

```yaml
options:
  devices:
    - /dev/sda
    - /dev/nvidia0
```

## Complete Configuration Examples

### Example 1: Minimal Container Config

```yaml
container:
  enabled: true
  runtime: docker
  image: python:3.11-slim
```

### Example 2: Production Config

```yaml
container:
  enabled: true
  runtime: docker
  image: python:3.11-slim
  
  resources:
    cpu: "4"
    memory: "8Gi"
  
  mounts:
    - type: bind
      source: ./data
      target: /data
      read_only: true
  
  environment:
    PYTHONPATH: /app
    LOG_LEVEL: warning
  
  security:
    read_only: true
    user: "1000:1000"
```

### Example 3: GPU-Enabled Config

```yaml
container:
  enabled: true
  runtime: docker
  image: tensorflow/tensorflow:2.14.0
  
  resources:
    cpu: "8"
    memory: "32Gi"
    gpu: true
  
  options:
    devices:
      - /dev/nvidia0
      - /dev/nvidia1
```

### Example 4: Development Config

```yaml
container:
  enabled: true
  runtime: docker
  image: python:3.11-dev
  
  resources:
    cpu: "2"
    memory: "4Gi"
  
  mounts:
    - type: bind
      source: ./src
      target: /app/src
      read_only: false
  
  security:
    read_only: false
    network: host
```

## Task-Specific Container Override

Override container settings per task in spec files:

```yaml
# spec/my-task.yaml
name: my-task
steps:
  - name: data-processing
    command: python process.py
    container:
      image: python:3.11-slim
      resources:
        memory: "4Gi"
  
  - name: ml-training
    command: python train.py
    container:
      image: tensorflow/tensorflow:latest
      resources:
        cpu: "8"
        memory: "32Gi"
        gpu: true
```

## Runtime-Specific Options

### Docker Options

```yaml
options:
  docker:
    runtime: nvidia    # Use nvidia runtime for GPU
    platform: linux/amd64
```

### Podman Options

```yaml
options:
  podman:
    rootless: true
    security-opt: no-new-privileges
```

## Configuration File Locations

### Global Config

Default location: `agent-arborist.yaml` in project root.

### Environment-Specific Configs

Use environment variables:

```bash
export AGENT_ARBORIST_CONFIG=config/production.yaml
agent-arborist orchestrate "My task"
```

### CLI Override

Specify config with `--config` flag:

```bash
agent-arborist --config config/production.yaml orchestrate "My task"
```

## Best Practices

### 1. Use Specific Image Versions

```yaml
# Good
image: python:3.11.7-slim

# Avoid
image: python:latest
```

### 2. Mount Read-Only When Possible

```yaml
mounts:
  - type: bind
    source: ./config
    target: /config
    read_only: true
```

### 3. Limit Resources

```yaml
resources:
  cpu: "2"
  memory: "4Gi"
```

### 4. Use Non-Root User

```yaml
security:
  user: "1000:1000"
```

### 5. Isolate Networks

```yaml
security:
  network: bridge
  read_only: true
```

## Troubleshooting

### Issue: Container runtime not found

**Solution:** Install Docker or podman, configure auto detect:

```yaml
runtime: auto
```

### Issue: Permission denied on mounts

**Solution:** Ensure correct permissions, adjust UID/GID:

```yaml
security:
  user: "1000:1000"
```

### Issue: Out of memory errors

**Solution:** Increase memory limit:

```yaml
resources:
  memory: "8Gi"
```

### Issue: GPU not accessible

**Solution:** Ensure GPU is available, configure GPU support:

```yaml
resources:
  gpu: true

options:
  devices:
    - /dev/nvidia0
```

## Code References

- Container implementation: [`src/agent_arborist/container.py`](../../src/agent_arborist/container.py)
- Configuration schema: [`src/agent_arborist/config.py:container`](../../src/agent_arborist/config.py)