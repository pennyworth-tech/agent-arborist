# Viz Commands

## Tree Visualization

\`\`\`bash
# ASCII tree of latest run
arborist viz tree 001-my-feature

# With expanded sub-DAGs
arborist viz tree 001-my-feature --expand

# Show metrics inline
arborist viz tree 001-my-feature --show-metrics
\`\`\`

From [`src/agent_arborist/cli.py`](../../src/agent_arborist/cli.py#viz_tree):

| Option | Description |
|--------|-------------|
| \`--expand, -e\` | Expand sub-DAGs in tree |
| \`--output-format, -f\` | Format: ascii, json, svg |
| \`--color-by\` | Color scheme: status, quality, pass-rate |
| \`--show-metrics, -m\` | Show metrics inline |

## Metrics Summary

\`\`\`bash
arborist viz metrics 001-my-feature
arborist viz metrics 001-my-feature --output-format table
\`\`\`

## Export

\`\`\`bash
arborist viz export 001-my-feature --output-dir ./reports/
arborist viz export 001-my-feature --formats svg,png,json
\`\`\`
