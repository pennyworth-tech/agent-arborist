# CLI Overview

Agent Arborist CLI built with Click.

## Command Groups

```bash
arborist init          # Initialize project
arborist version       # Show version
arborist doctor        # System diagnostics
arborist config        # Configuration
arborist hooks         # Hooks system
arborist task          # Task operations
arborist spec          # Spec operations  
arborist dag           # DAG operations
```

## Help

```bash
arborist --help
arborist task --help
arborist task run --help
```

## Global Options

```bash
arborist --spec 001-feature dag run
arborist --home /path/to/dagu dag status
```

See: [`src/agent_arborist/cli.py`](../../src/agent_arborist/cli.py)
