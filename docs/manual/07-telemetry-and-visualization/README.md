# Part 7: Telemetry and Visualization

Monitor and visualize DAG execution metrics.

## Overview

Arborist provides built-in telemetry and visualization capabilities for tracking task execution and debugging workflow performance.

## Visualization Commands

Arborist CLI provides `viz` command group:

\`\`\`bash
arborist viz tree <dag-name>      # Display metrics dendrogram
arborist viz metrics <dag-name>   # Display metrics summary
arborist viz export <dag-name>    # Export visualizations
\`\`\`

See: [`src/agent_arborist/cli.py`](../../src/agent_arborist/cli.py#viz_*)
