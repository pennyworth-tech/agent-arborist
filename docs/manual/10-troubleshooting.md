# Troubleshooting

## Common Issues

### "no ready task" error

**Cause:** All tasks are either completed or have unsatisfied dependencies.

**Fix:**
- Run `arborist status --tree task-tree.json` to see what's complete and what's blocked
- Check that your dependency graph doesn't have cycles
- Verify the task tree has leaf tasks with `execution_order` populated

### Runner times out

**Cause:** The AI runner takes longer than the configured timeout (default: 600s).

**Fix:**
- Increase the timeout: `ARBORIST_RUNNER_TIMEOUT=1200` or in config `timeouts.runner_timeout`
- Break tasks into smaller pieces in your spec
- Use a faster model for implementation

### Task fails after max retries

**Cause:** The implement → test → review cycle failed 5 times.

**Fix:**
- Check `.arborist/logs/` for runner output
- Look at git log on the phase branch: `git log arborist/<spec>/<phase> --oneline`
- The commit bodies contain test output and review feedback
- Consider: is the task too vague? Too large? Is the test command correct?

### "not a git repository" error

**Cause:** Arborist requires a git repository.

**Fix:** Run `git init` or `cd` into an existing repo.

### Build produces wrong task structure

**Cause:** The AI planner misinterpreted your spec.

**Fix:**
- Edit `task-tree.json` directly — it's just JSON
- Use more explicit formatting in your spec (headers, task IDs, dependency section)
- Try a different model: `arborist build --model opus`

### Branch conflicts

**Cause:** Manual changes on the base branch while Arborist is running.

**Fix:**
- Don't make manual changes during a gardener run
- If needed, stop the gardener, resolve conflicts, then restart

## FAQ

### Can I run tasks in parallel?

Not currently. Arborist executes tasks sequentially within each phase. Tasks across phases could theoretically run in parallel, but the current implementation is sequential.

### Can I skip a task?

Edit `task-tree.json` — remove the task from `execution_order` or mark it with a manual "complete" commit on the phase branch.

### Can I re-run a failed task?

Yes. The gardener picks up from where it left off. If a task is marked failed, you may need to reset the branch:

```bash
git checkout <base-branch>
git branch -D arborist/<spec>/<phase>
arborist gardener --tree task-tree.json
```

### What if I want to review changes manually before merging?

Use `garden` (single task) instead of `gardener` (loop). After each task completes, inspect the branch before proceeding.

### Where are the reports?

By default in a `reports/` directory next to your `task-tree.json`. Each completed task gets a JSON report:

```json
{
  "task_id": "T001",
  "result": "pass",
  "retries": 0
}
```

### Can I use Arborist without AI for planning?

Yes: `arborist build --no-ai`. This uses a deterministic markdown parser that requires a strict format (see `--no-ai` in [CLI Reference](09-cli-reference.md)). Useful for CI/CD or reproducible builds.
