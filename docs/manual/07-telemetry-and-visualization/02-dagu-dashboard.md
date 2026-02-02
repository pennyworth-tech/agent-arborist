# Dagu Dashboard

## Starting

\`\`\`bash
# Default port 8080
arborist dag dashboard

# Custom port
arborist dag dashboard --port 9000
\`\`\`

Access at: \`http://localhost:8080\`

## Features

- Live task status
- Task dependencies (DAG graphs)
- Log viewing
- Run history
- Manual control

## Monitoring

1. Start dashboard: \`arborist dag dashboard\`
2. Run DAG: \`arborist dag run 001-my-feature\`
3. Open: http://localhost:8080
