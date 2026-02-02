# API Reference

Reference documentation for Agent Arborist Python API.

## Modules

### agent_arborist.config

Configuration loading and validation.

#### Classes

##### `AgentArboristConfig`

Main configuration class.

```python
from agent_arborist.config import AgentArboristConfig

config = AgentArboristConfig(
    runner="claude",
    claude=ClaudeConfig(models=ModelConfig(task_spec="claude-3-5-sonnet")),
    timeouts=TimeoutsConfig(generate_task_spec=300),
    paths=PathsConfig(spec_dir="spec"),
    git=GitConfig(worktree_dir="work")
)
```

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `runner` | str | AI runner (claude, openai, mock) |
| `claude` | ClaudeConfig | Claude runner config |
| `openai` | OpenAIConfig | OpenAI runner config |
| `timeouts` | TimeoutsConfig | Timeout settings |
| `paths` | PathsConfig | Path settings |
| `git` | GitConfig | Git worktree config |
| `container` | ContainerConfig | Container config |
| `hooks` | HooksConfig | Hooks config |

**Methods:**

```python
# Validate configuration
config.validate()

# Get runner instance
runner = config.get_runner()

# Get timeout for operation
timeout = config.get_timeout("generate_task_spec")
```

**Code Reference:** [`src/agent_arborist/config.py:AgentArboristConfig`](../../src/agent_arborist/config.py#L40)

##### `load_config(config_path: str) -> AgentArboristConfig`

Load configuration from file.

```python
from agent_arborist.config import load_config

config = load_config("agent-arborist.yaml")
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `config_path` | str | Path to configuration file |

**Returns:** `AgentArboristConfig`

**Raises:**
- `FileNotFoundError`: Config file not found
- `ValueError`: Invalid configuration

**Code Reference:** [`src/agent_arborist/config.py:load_config()`](../../src/agent_arborist/config.py#L100)

---

### agent_arborist.runner

Runner interface and implementations.

#### Classes

##### `Runner` (ABC 🟢)

Abstract base class for AI runners.

```python
from agent_arborist.runner import Runner

class MyRunner(Runner):
    def generate_task_spec(self, description: str, **kwargs) -> str:
        """Generate task specification."""
        pass
    
    def generate_dagu_config(self, spec: str, **kwargs) -> str:
        """Generate DAGU configuration."""
        pass
```

**Methods:**

| Method | Return Type | Description |
|--------|-------------|-------------|
| `generate_task_spec(description, **kwargs)` | str | Generate task spec |
| `generate_dagu_config(spec, **kwargs)` | str | Generate DAGU config |

**Code Reference:** [`src/agent_arborist/runner.py:Runner`](../../src/agent_arborist/runner.py)

##### `ClaudeRunner` 🟢

Anthropic Claude runner implementation.

```python
from agent_arborist.runner import ClaudeRunner

runner = ClaudeRunner(api_key="sk-ant...")
spec = runner.generate_task_spec("Build a data pipeline")
```

**Parameters (init):**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `api_key` | str | No | Claude API key |
| `model` | str | No | Model to use |
| `timeout` | int | No | Request timeout |

**Code Reference:** [`src/agent_arborist/runner.py:ClaudeRunner`](../../src/agent_arborist/runner.py)

##### `OpenAIRunner` 🟢

OpenAI runner implementation.

```python
from agent_arborist.runner import OpenAIRunner

runner = OpenAIRunner(api_key="sk-...")
spec = runner.generate_task_spec("Build a data pipeline")
```

**Parameters (init):**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `api_key` | str | No | OpenAI API key |
| `model` | str | No | Model to use |
| `timeout` | int | No | Request timeout |

**Code Reference:** [`src/agent_arborist/runner.py:OpenAIRunner`](../../src/agent_arborist/runner.py)

##### `MockRunner` 🟢

Mock runner for testing.

```python
from agent_arborist.runner import MockRunner

runner = MockRunner()
spec = runner.generate_task_spec("Test task")
# Returns predefined test spec
```

**Code Reference:** [`src/agent_arborist/runner.py:MockRunner`](../../src/agent_arborist/runner.py)

---

### agent_arborist.dagu

DAGU generation and execution.

#### Classes

##### `DAGUGenerator` 🟢

Generates DAGU configurations from task specifications.

```python
from agent_arborist.dagu import DAGUGenerator

generator = DAGUGenerator()
dagu_config = generator.generate_from_spec("spec/my-task.yaml")
```

**Methods:**

| Method | Return Type | Description |
|--------|-------------|-------------|
| `generate_from_spec(spec_path)` | str | Generate DAGU config |
| `validate_dagu_config(dagu_yaml)` | bool | Validate DAGU YAML |

**Code Reference:** [`src/agent_arborist/dagu.py:DAGUGenerator`](../../src/agent_arborist/dagu.py)

##### `DAGURunner` 🟢

Executes DAGU workflows.

```python
from agent_arborist.dagu import DAGURunner

runner = DAGURunner()
results = runner.run("dag/my-task.yaml")
```

**Methods:**

| Method | Return Type | Description |
|--------|-------------|-------------|
| `run(dag_path, **kwargs)` | dict | Run DAGU workflow |
| `wait_for_completion(dag_name)` | dict | Wait for completion |
| `get_status(dag_name)` | str | Get workflow status |

**Code Reference:** [`src/agent_arborist/dagu.py:DAGURunner`](../../src/agent_arborist/dagu.py)

---

### agent_arborist.hooks

Hooks system for workflow customization.

#### Classes

##### `HookExecutor` 🟢

Executes hooks at various workflow phases.

```python
from agent_arborist.hooks import HookExecutor

executor = HookExecutor(config=hooks_config)
executor.execute_hooks("post_execution", context=context)
```

**Methods:**

| Method | Return Type | Description |
|--------|-------------|-------------|
| `execute_hooks(phase, context)` | dict | Execute hooks for phase |
| `get_hook(name)` | Hook | Get hook by name |
| `register_hook(hook)` | None | Register new hook |

**Code Reference:** [`src/agent_arborist/hooks.py:HookExecutor`](../../src/agent_arborist/hooks.py)

##### `Hook` 🟢

Represents a single hook.

```python
from agent_arborist.hooks import Hook

hook = Hook(
    name="my-hook",
    command="scripts/hook.sh",
    enabled=True,
    timeout=60
)
```

**Parameters (init):**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | str | Yes | Hook name |
| `command` | str | Yes | Command to execute |
| `enabled` | bool | No | Whether enabled |
| `timeout` | int | No | Timeout in seconds |
| `env` | dict | No | Environment variables |

**Methods:**

| Method | Return Type | Description |
|--------|-------------|-------------|
| `execute(context)` | int | Execute hook |

**Code Reference:** [`src/agent_arborist/hooks.py:Hook`](../../src/agent_arborist/hooks.py)

---

### agent_arborist.container

Container execution support.

#### Classes

##### `ContainerManager` 🟢

Manages container execution.

```python
from agent_arborist.container import ContainerManager

manager = ContainerManager(runtime="docker", image="python:3.11")
results = manager.run_workflow("dag/my-task.yaml")
```

**Methods:**

| Method | Return Type | Description |
|--------|-------------|-------------|
| `run_workflow(dag_path, **kwargs)` | dict | Run workflow in container |
| `create_container(image, config)` | str | Create container |
| `execute_command(container, command)` | dict | Execute command |
| `cleanup(container_id)` | None | Cleanup container |

**Code Reference:** [`src/agent_arborist/container.py:ContainerManager`](../../src/agent_arborist/container.py)

---

## Data Models

### Task Specification

```python
@dataclass
class TaskSpecification:
    name: str
    description: str
    steps: List[TaskStep]
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class TaskStep:
    name: str
    command: str
    description: str
    depends_on: List[str] = field(default_factory=list)
    parallel: bool = False
    retry: Optional[RetryConfig] = None
```

**Code Reference:** [`src/agent_arborist/models.py`](../../src/agent_arborist/models.py)

### DAGU Configuration

```python
@dataclass
class DAGUConfig:
    name: str
    description: str
    tasks: List[DAGUTask]
    schedule: Optional[Schedule] = None
    parameters: Dict[str, Any] = field(default_factory=dict)

@dataclass
class DAGUTask:
    name: str
    command: str
    depends_on: List[str] = field(default_factory=list)
    retry: Optional[RetryConfig] = None
    timeout_seconds: Optional[int] = None
```

**Code Reference:** [`src/agent_arborist/models.py`](../../src/agent_arborist/models.py)

### Retry Configuration

```python
@dataclass
class RetryConfig:
    count: int = 3
    delay_seconds: int = 30
    backoff: Literal["constant", "exponential"] = "exponential"
```

## Constants

### Valid Runners

```python
VALID_RUNNERS = ["claude", "openai", "mock"]
```

**Code Reference:** [`src/agent_arborist/config.py:VALID_RUNNERS`](../../src/agent_arborist/config.py#L22)

### Default Timeouts

```python
DEFAULT_TIMEOUTS = {
    "generate_task_spec": 300,
    "generate_dagu": 300,
    "run_dagu": 3600,
    "default": 300,
}
```

### Hook Phases

```python
HOOK_PHASES = [
    "pre_generation",
    "post_spec",
    "post_dagu",
    "pre_execution",
    "post_execution",
]
```

## Utility Functions

### validate_config(config: AgentArboristConfig)

Validate configuration.

```python
from agent_arborist.config import validate_config

errors = validate_config(config)
if errors:
    for error in errors:
        print(f"Error: {error}")
```

**Code Reference:** [`src/agent_arborist/config.py:validate_config()`](../../src/agent_arborist/config.py)

### parse_spec(spec_path: str) -> TaskSpecification

Parse task specification file.

```python
from agent_arborist.parser import parse_spec

spec = parse_spec("spec/my-task.yaml")
print(f"Task: {spec.name}")
for step in spec.steps:
    print(f"  Step: {step.name}")
```

**Code Reference:** [`src/agent_arborist/parser.py:parse_spec()`](../../src/agent_arborist/parser.py)

## Exception Classes

### ArboristError

Base exception for Agent Arborist errors.

```python
from agent_arborist.exceptions import ArboristError

try:
    run_workflow()
except ArboristError as e:
    print(f"Error: {e}")
```

### ConfigurationError

Raised for configuration errors.

```python
from agent_arborist.exceptions import ConfigurationError

try:
    config = load_config("invalid.yaml")
except ConfigurationError as e:
    print(f"Config error: {e}")
```

### RunnerError

Raised for runner errors.

```python
from agent_arborist.exceptions import RunnerError

try:
    spec = runner.generate_task_spec("Task")
except RunnerError as e:
    print(f"Runner error: {e}")
```

## Usage Examples

### Example 1: Generate Task Spec

```python
from agent_arborist.config import load_config
from agent_arborist.runner import ClaudeRunner

config = load_config("agent-arborist.yaml")
runner = ClaudeRunner(api_key=config.claude.api_key)

spec = runner.generate_task_spec(
    "Build a data pipeline",
    model="claude-3-5-sonnet"
)

with open("spec/pipeline.yaml", "w") as f:
    f.write(spec)
```

### Example 2: Generate DAGU Config

```python
from agent_arborist.dagu import DAGUGenerator

generator = DAGUGenerator()
dagu_config = generator.generate_from_spec("spec/pipeline.yaml")

with open("dag/pipeline.yaml", "w") as f:
    f.write(dagu_config)
```

### Example 3: Run Workflow

```python
from agent_arborist.dagu import DAGURunner

runner = DAGURunner()
results = runner.run(
    "dag/pipeline.yaml",
    timeout=3600,
    watch=True
)

print(f"Status: {results['status']}")
print(f"Duration: {results['duration']}")
```

### Example 4: Custom Runner

```python
from agent_arborist.runner import Runner

class MyCustomRunner(Runner):
    def generate_task_spec(self, description: str, **kwargs) -> str:
        # Custom implementation
        return generated_spec
    
    def generate_dagu_config(self, spec: str, **kwargs) -> str:
        # Custom implementation
        return generated_dagu

# Register runner
from agent_arborist.config import RUNNER_CLASSES
RUNNER_CLASSES["custom"] = MyCustomRunner
```

### Example 5: Execute Hooks

```python
from agent_arborist.hooks import HookExecutor, Hook

hooks_config = {
    "post_execution": [
        Hook(
            name="notify",
            command="scripts/notify.sh",
            enabled=True
        )
    ]
}

executor = HookExecutor(config=hooks_config)
executor.execute_hooks(
    "post_execution",
    context={"status": "success", "dag_name": "my-pipeline"}
)
```

## API Stability

| API | Status | Notes |
|-----|--------|-------|
| `AgentArboristConfig` | 🟢 Stable | Production-ready |
| `Runner` | 🟢 Stable | Interface stable |
| `ClaudeRunner` | 🟢 Stable | Production-ready |
| `OpenAIRunner` | 🟢 Stable | Production-ready |
| `DAGUGenerator` | 🟢 Stable | Production-ready |
| `DAGURunner` | 🟢 Stable | Production-ready |
| `HookExecutor` | 🟢 Stable | Production-ready |
| `ContainerManager` | 🟡 Beta | May change |

## Code References

- Configuration: [`src/agent_arborist/config.py`](../../src/agent_arborist/config.py)
- Runners: [`src/agent_arborist/runner.py`](../../src/agent_arborist/runner.py)
- DAGU: [`src/agent_arborist/dagu.py`](../../src/agent_arborist/dagu.yaml)
- Hooks: [`src/agent_arborist/hooks.py`](../../src/agent_arborist/hooks.py)
- Containers: [`src/agent_arborist/container.py`](../../src/agent_arborist/container.py)