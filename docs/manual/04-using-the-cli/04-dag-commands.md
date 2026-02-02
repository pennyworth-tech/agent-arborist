# DAG Commands

Execute and manage DAG workflows.

## Run DAG

```bash
arborist dag run 001-feature
arborist dag run 001-feature --restart
```

Execute complete workflow.

## DAG Status

```bash
arborist dag status 001-feature
arborist dag status 001-feature --json
arborist dag status --all
```

Show execution status.

## Show DAG

```bash
arborist dag show 001-feature
arborist dag show 001-feature --format ascii
```

Display DAG structure as tree.

## List Runs

```bash
arborist dag run list
arborist dag run list 001-feature
```

List historical DAG runs.

## Restart DAG

```bash
arborist dag restart 001-feature
```

Restart failed or stopped DAG.

## Dashboard

```bash
arborist dag dashboard
```

Launch visualization dashboard.

See: [`src/agent_arborist/cli.py`](../../src/agent_arborist/cli.py#dag_*)
