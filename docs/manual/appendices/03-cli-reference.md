# Full CLI Reference

Complete reference for all Arborist CLI commands.

## Global Options

| Option | Description |
|--------|-------------|
| `--spec, -s` | Spec identifier (auto-detected from directory) |
| `--home, -h` | Arborist home directory |
| `--output-format, -f` | Output format: json, text |
| `--quiet, -q` | Suppress output |
| `--echo-for-testing` | Echo commands for testing |

## arborist init

Initialize `.arborist/` directory structure.

```bash
arborist init
```

**Output:** Creates `.arborist/` with config.json, manifests/, dagu/, worktrees/, task-state/, prompts/, logs/

---

## arborist version

Show Arborist version information.

```bash
arborist version              # Show version
arborist version --check      # Check for updates
```

---

## arborist doctor

Run system diagnostics.

```bash
arborist doctor                          # All checks
arborist doctor --runner claude          # Check specific runner
```

Checks:
- Git installation
- Dagu installation
- Runner availability (claude, opencode, gemini)
- Configuration validity

---

## arborist config

Configuration management.

### config init

Create configuration file.

```bash
arborist config init                # Project config
arborist config init --global       # Global config (~/.arborist_config.json)
arborist config init --force        # Overwrite existing
```

### config show

Display current configuration.

```bash
arborist config show
```

### config validate

Validate configuration files.

```bash
arborist config validate
```

---

## arborist hooks

Hooks system management.

### hooks list

List configured hooks.

```bash
arborist hooks list
```

### hooks validate

Validate hook configurations.

```bash
arborist hooks validate
```

### hooks run

Run a specific hook manually.

```bash
arborist hooks run pre_sync --task T001
arborist hooks run post_run --task T001 --dry-run
```

---

## arborist task

Individual task operations.

Task steps: pre-sync → run → commit → post-merge → cleanup

### task status

Show task execution status.

```bash
arborist task status
arborist task status --spec 001-feature
arborist task status --as-json
```

### task pre-sync

Sync worktree from parent branch.

```bash
arborist task pre-sync T001
```

### task run

Execute task with AI runner.

```bash
arborist task run T001
arborist task run T001 --runner claude
arborist task run T001 --runner claude --model sonnet
arborist task run T001 --timeout 1800
arborist task run T001 --force
```

### task commit

Commit changes to task branch.

```bash
arborist task commit T001
```

### task post-merge

Merge task branch to parent.

```bash
arborist task post-merge T001
arborist task post-merge T001 --continue-on-error
arborist task post-merge T001 --timeout 300
arborist task post-merge T001 --runner claude --model sonnet
```

### task post-cleanup

Remove worktree and optionally branch.

```bash
arborist task post-cleanup T001
arborist task post-cleanup T001 --keep-branch
```

### task container-up

Start devcontainer for task.

```bash
arborist task container-up T001
```

### task container-stop

Stop devcontainer for task.

```bash
arborist task container-stop T001
```

---

## arborist spec

Task specification management.

### spec whoami

Display current spec information.

```bash
arborist spec whoami
```

### spec branch-create-all

Create Git branches for all tasks.

```bash
arborist spec branch-create-all
arborist spec branch-create-all --spec 001-feature
arborist spec branch-create-all --dry-run
```

### spec dag-build

Generate Dagu DAG files from spec.

```bash
arborist spec dag-build 001-feature
arborist spec dag-build 001-feature --name custom-dag
arborist spec dag-build 001-feature --description "My feature"
arborist spec dag-build 001-feature --dry-run
arborist spec dag-build 001-feature --output /path/to/output
arborist spec dag-build 001-feature --force
```

### spec dag-show

Display generated DAG structure.

```bash
arborist spec dag-show 001-feature
arborist spec dag-show 001-feature --format yaml
arborist spec dag-show 001-feature --format json
```

---

## arborist dag

DAG workflow operations.

### dag run

Execute DAG workflow.

```bash
arborist dag run 001-feature
arborist dag run 001-feature --restart
arborist dag run 001-feature --run-id specific-run-id
arborist dag run 001-feature --dry-run
```

### dag status

Show DAG execution status.

```bash
arborist dag status 001-feature
arborist dag status 001-feature --json
arborist dag status --all
arborist dag status 001-feature --run-id specific-run-id
```

### dag show

Display DAG structure as tree.

```bash
arborist dag show 001-feature
arborist dag show 001-feature --format ascii
arborist dag show 001-feature --format json
arborist dag show 001-feature --color-by status
```

### dag run list

List historical DAG runs.

```bash
arborist dag run list
arborist dag run list 001-feature
arborist dag run list 001-feature --limit 10
```

### dag run show

Show details of a specific run.

```bash
arborist dag run show 001-feature
arborist dag run show 001-feature --run-id specific-run-id
```

### dag restart

Restart a DAG run.

```bash
arborist dag restart 001-feature
arborist dag restart 001-feature --run-id specific-run-id
```

### dag dashboard

Launch Dagu web dashboard.

```bash
arborist dag dashboard
arborist dag dashboard --host 0.0.0.0
arborist dag dashboard --port 9000
arborist dag dashboard --host 0.0.0.0 --port 9000
```

Access at: http://localhost:8080

### dag cleanup

Clean up old DAG runs.

```bash
arborist dag cleanup
arborist dag cleanup --dry-run
arborist dag cleanup --all
```

---

## arborist viz

Visualization and metrics.

### viz tree

Display metrics dendrogram.

```bash
arborist viz tree 001-feature
arborist viz tree 001-feature --run-id specific-run-id
arborist viz tree 001-feature --expand
arborist viz tree 001-feature --output-format ascii
arborist viz tree 001-feature --output-format json
arborist viz tree 001-feature --output-format svg
arborist viz tree 001-feature --aggregation totals
arborist viz tree 001-feature --color-by status
arborist viz tree 001-feature --show-metrics
arborist viz tree 001-feature --depth 5
```

Options:
- `--expand, -e`: Expand sub-DAGs
- `--output-format, -f`: ascii, json, svg
- `--aggregation`: totals, average, min, max
- `--color-by`: status, quality, pass-rate
- `--show-metrics, -m`: Show inline metrics
- `--depth, -d`: Max depth

### viz metrics

Display metrics summary.

```bash
arborist viz metrics 001-feature
arborist viz metrics 001-feature --run-id specific-run-id
arborist viz metrics 001-feature --output-format json
arborist viz metrics 001-feature --output-format table
arborist viz metrics 001-feature --task T001
```

### viz export

Export visualizations to files.

```bash
arborist viz export 001-feature
arborist viz export 001-feature --run-id specific-run-id
arborist viz export 001-feature --output-dir ./reports/
arborist viz export 001-feature --formats svg,png,json
```

---

## arborist dashboard

Launch Arborist dashboard (alias for dag dashboard).

```bash
arborist dashboard
arborist dashboard --port 9000
```

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `ARBORIST_MANIFEST` | Path to branch manifest file |
| `ARBORIST_DEFAULT_RUNNER` | Default AI runner (claude, opencode, gemini) |
| `ARBORIST_DEFAULT_MODEL` | Default model for runner |
| `DAGU_HOME` | Dagu directory path |
| `ARBORIST_CONTAINER_MODE` | Container mode (auto, enabled, disabled) |
| `ARBORIST_CONFIG` | Path to config file |

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Configuration error |
| 3 | Dependency not found |
| 4 | Task execution failed |

---

## See Also

- [Using the CLI](../04-using-the-cli/README.md) - Practical CLI usage examples
- [Configuration](../03-configuration/README.md) - CLI configuration
- Source: [`src/agent_arborist/cli.py`](../../src/agent_arborist/cli.py)
