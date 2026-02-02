# Metrics Reference

## Node Metrics

\`\`\`python
class NodeMetrics:
    start_time: str           # ISO timestamp
    end_time: str             # ISO timestamp
    duration_seconds: float   # Execution time
    status: str               # success, failed, running
    error: str | None         # Error message
\`\`\`

## Aggregated Metrics

\`\`\`python
class AggregatedMetrics:
    total_duration: float     # Sum of durations
    total_tasks: int          # Task count
    success_count: int        # Successful
    failed_count: int         # Failed
    pass_rate: float          # success / total
\`\`\`

## Aggregation Strategies

| Strategy | Description |
|----------|-------------|
| \`totals\` | Sum of all durations |
| \`average\` | Average per task |
| \`min\` | Minimum |
| \`max\` | Maximum |

## Output Formats

- \`ascii\` - Text tree
- \`json\` - JSON data
- \`svg\` - Vector graphics
- \`table\` - Tables
