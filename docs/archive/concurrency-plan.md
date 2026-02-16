# Concurrency Limiting Plan for Agent Arborist

## Overview

This plan adds **simple concurrency limiting** using DAGU's queue system to control the maximum number of concurrent AI tasks.

**Design Principle**: KISS - Keep It Simple. Since DAGs don't embed runner/model info (resolved at runtime), we use a single queue for all AI steps.

## Background

### DAGU Queue System

From DAGU documentation:
- DAGU supports global queues defined in `~/.config/dagu/config.yaml`
- Each queue has a `maxConcurrency` limit
- DAGs can be assigned to queues via the `queue` field in YAML
- If no queue is assigned, DAGs use a local queue with concurrency of 1

### Current Arborist Architecture

- DAG commands are simple: `arborist task run T001` (no --runner/--model flags)
- Runner/model resolved at **runtime** from config, not at DAG generation time
- This means we can't differentiate queues by runner/model at DAG build time

### Why Simple?

Since we don't know which runner/model will execute until runtime:
- ❌ Can't do per-runner queues (`arborist:claude`)
- ❌ Can't do per-model queues (`arborist:claude:sonnet`)
- ✅ Can only limit total concurrent AI steps

## Configuration

Add to global (`~/.arborist_config.json`) or project (`.arborist/config.json`) config:

```json
{
  "concurrency": {
    "max_ai_tasks": 2
  }
}
```

That's it. One number.

### Environment Variable

```bash
export ARBORIST_MAX_AI_TASKS=2
```

## Implementation

### 1. Add Config Field

```python
# src/agent_arborist/config.py

@dataclass
class ConcurrencyConfig:
    max_ai_tasks: int = 2  # Default: 2 concurrent AI tasks

@dataclass
class ArboristConfig:
    # ... existing fields ...
    concurrency: ConcurrencyConfig = field(default_factory=ConcurrencyConfig)
```

### 2. Add Queue Field to SubDagStep

```python
# src/agent_arborist/dag_builder.py

@dataclass
class SubDagStep:
    name: str
    command: str | None = None
    call: str | None = None
    depends: list[str] = field(default_factory=list)
    output: str | None = None
    queue: str | None = None  # NEW
```

### 3. Assign Queue to AI Steps

```python
def _build_leaf_subdag(self, task_id: str) -> SubDag:
    # ... existing code ...

    # Run step - uses AI queue
    steps.append(SubDagStep(
        name="run",
        command=f"arborist task run {task_id}",
        depends=["pre-sync"],
        output=output_var("run"),
        queue="arborist:ai",  # Rate limited
    ))

    # Commit step - no queue (git operations, not rate limited)
    steps.append(SubDagStep(
        name="commit",
        command=f"arborist task commit {task_id}",
        depends=["run"],
    ))

    # Post-merge step - uses AI queue
    steps.append(SubDagStep(
        name="post-merge",
        command=f"arborist task post-merge {task_id}",
        depends=["run-test"],
        output=output_var("post-merge"),
        queue="arborist:ai",  # Rate limited
    ))
```

### 4. Generate DAGU Queue Config

```python
# src/agent_arborist/cli.py

@config.command("sync-queues")
def config_sync_queues() -> None:
    """Sync concurrency config to DAGU queues."""
    config = get_config()

    dagu_home = Path(os.environ.get("DAGU_HOME", "~/.config/dagu")).expanduser()
    dagu_config_path = dagu_home / "config.yaml"

    # Read existing or create new
    if dagu_config_path.exists():
        dagu_config = yaml.safe_load(dagu_config_path.read_text()) or {}
    else:
        dagu_config = {}

    # Set queue config
    dagu_config["queues"] = {
        "enabled": True,
        "config": [
            {
                "name": "arborist:ai",
                "maxConcurrency": config.concurrency.max_ai_tasks
            }
        ]
    }

    dagu_config_path.parent.mkdir(parents=True, exist_ok=True)
    dagu_config_path.write_text(yaml.dump(dagu_config, default_flow_style=False))

    click.echo(
        f"✓ Queue 'arborist:ai' set to max {config.concurrency.max_ai_tasks} concurrent tasks"
    )
```

### 5. Update _step_to_dict

```python
def _step_to_dict(self, step: SubDagStep) -> dict[str, Any]:
    d: dict[str, Any] = {"name": step.name}

    if step.command is not None:
        d["command"] = step.command
    if step.call is not None:
        d["call"] = step.call
    if step.depends:
        d["depends"] = step.depends
    if step.output is not None:
        d["output"] = step.output
    if step.queue is not None:
        d["queue"] = step.queue

    return d
```

## Which Steps Get Rate Limited?

| Step | Queue | Why |
|------|-------|-----|
| `run` | `arborist:ai` | AI task execution |
| `post-merge` | `arborist:ai` | AI-assisted merging |
| `pre-sync` | None | Git operations |
| `commit` | None | Git operations |
| `run-test` | None | Test execution |
| `container-up/down` | None | Docker lifecycle |
| `branches-setup` | None | Branch management |

## Generated DAG Example

```yaml
name: T001
steps:
  - name: pre-sync
    command: arborist task pre-sync T001

  - name: run
    command: arborist task run T001
    depends: [pre-sync]
    queue: arborist:ai              # ← Rate limited

  - name: commit
    command: arborist task commit T001
    depends: [run]

  - name: run-test
    command: arborist task run-test T001
    depends: [commit]

  - name: post-merge
    command: arborist task post-merge T001
    depends: [run-test]
    queue: arborist:ai              # ← Rate limited
```

## Generated DAGU Config

```yaml
# ~/.config/dagu/config.yaml
queues:
  enabled: true
  config:
    - name: arborist:ai
      maxConcurrency: 2
```

## Usage

```bash
# Set concurrency limit
echo '{"concurrency": {"max_ai_tasks": 3}}' > .arborist/config.json

# Sync to DAGU
arborist config sync-queues

# Build DAG (automatically includes queue assignments)
arborist spec dag-build my-spec

# Run - DAGU will limit to 3 concurrent AI steps
arborist dag run my-spec
```

## Testing

```python
# tests/test_concurrency.py

def test_ai_steps_have_queue():
    """AI steps should have arborist:ai queue."""
    builder = SubDagBuilder(DagConfig(name="test"))
    subdag = builder._build_leaf_subdag("T001")

    run_step = next(s for s in subdag.steps if s.name == "run")
    assert run_step.queue == "arborist:ai"

    post_merge = next(s for s in subdag.steps if s.name == "post-merge")
    assert post_merge.queue == "arborist:ai"

def test_non_ai_steps_no_queue():
    """Non-AI steps should not have queue."""
    builder = SubDagBuilder(DagConfig(name="test"))
    subdag = builder._build_leaf_subdag("T001")

    for step_name in ["pre-sync", "commit", "run-test"]:
        step = next(s for s in subdag.steps if s.name == step_name)
        assert step.queue is None

def test_config_sync_queues(tmp_path, monkeypatch):
    """sync-queues should create DAGU config."""
    monkeypatch.setenv("DAGU_HOME", str(tmp_path))

    # Set config
    config = ArboristConfig()
    config.concurrency.max_ai_tasks = 3

    # Run sync
    sync_queues(config)

    # Verify
    dagu_config = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert dagu_config["queues"]["config"][0]["name"] == "arborist:ai"
    assert dagu_config["queues"]["config"][0]["maxConcurrency"] == 3
```

## Success Criteria

- [ ] Single `concurrency.max_ai_tasks` config option
- [ ] `ARBORIST_MAX_AI_TASKS` environment variable support
- [ ] `arborist config sync-queues` generates DAGU queue config
- [ ] DAG generation adds `queue: arborist:ai` to `run` and `post-merge` steps
- [ ] Tests verify queue assignment
- [ ] Backward compatible (no queue = unlimited)

## Future Considerations

If we later need per-runner/model limits, we could:
1. Embed runner/model in DAG commands (architecture change)
2. Or accept the current simple approach is sufficient

For now: **KISS**