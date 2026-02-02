# Spec Commands

Manage task specifications.

## Whoami

```bash
arborist spec whoami
```

Show current spec information.

## Create Branches

```bash
arborist spec branch-create-all
arborist spec branch-create-all --spec 001-feature
```

Create Git branches for all tasks in spec.

## Build DAG

```bash
arborist spec dag-build 001-feature
arborist spec dag-build 001-feature --dry-run
arborist spec dag-build 001-feature --output /path/to/dag
```

Generate Dagu YAML from markdown spec.

Output: `.arborist/dagu/{spec_id}/`

## Show DAG

```bash
arborist spec dag-show 001-feature
arborist spec dag-show 001-feature --format yaml
```

Display generated DAG structure.

See: [`src/agent_arborist/cli.py`](../../src/agent_arborist/cli.py#spec_*)
