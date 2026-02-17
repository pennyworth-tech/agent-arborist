# GitHub Action Setup Guide

Run agent-arborist in CI using a GitHub Actions workflow in your target repo.

## Prerequisites

- A **task-tree.json** committed to a branch in your repo (built locally with `arborist build`)
- A GitHub runner with sufficient resources (`ubuntu-latest-m` or larger recommended)
- Required secrets configured (see below)

## Secrets

| Secret | Required | Purpose |
|---|---|---|
| `GH_PAT_ARBORIST_RO` | Yes | PAT with `repo` scope to clone the private agent-arborist repo |
| `CLAUDE_CODE_OAUTH_TOKEN` | Yes (for Claude runner) | Claude Code authentication token |
| `GOOGLE_API_KEY` | Optional | Gemini runner authentication |

## Setup

1. Copy the [template workflow](../examples/arborist-run.yml) to `.github/workflows/arborist-run.yml` in your target repo.

2. Configure secrets in your repo: **Settings > Secrets and variables > Actions**.

3. Prepare a spec branch with your `task-tree.json`:
   ```bash
   git checkout -b spec/my-feature
   arborist build --spec spec.md -o task-tree.json
   git add task-tree.json && git commit -m "Add task tree"
   git push origin spec/my-feature
   ```

4. Trigger the workflow: **Actions > Arborist Run > Run workflow**, entering your spec branch name.

## Workflow Inputs

| Input | Default | Description |
|---|---|---|
| `spec_branch` | *(required)* | Branch containing task-tree.json |
| `tree_path` | `task-tree.json` | Path to the task tree JSON file |
| `runner_type` | `claude` | AI runner: `claude`, `gemini`, or `opencode` |
| `model` | `sonnet` | Model name passed to the runner |
| `max_retries` | `5` | Maximum retries per task |
| `container_mode` | `auto` | Devcontainer mode: `auto`, `enabled`, or `disabled` |

## How Resume Works

Arborist uses git-native state — task completion is tracked via git trailers on commits in `arborist/*` branches. The workflow exploits this for automatic resume:

```
Run 1 (fails on task 8/10):
  startup:  checkout spec_branch, fetch arborist/* branches (none yet)
  execute:  tasks 1-7 complete, task 8 fails
  teardown: push arborist/* branches + spec_branch
            → 7 tasks' state preserved in remote branches

Run 2 (retry):
  startup:  checkout spec_branch, fetch arborist/* branches
            → local branches restored from remote
  execute:  gardener finds tasks 1-7 done via trailers, picks up at task 8
  teardown: push everything again
```

Key points:
- **Branches are never deleted** after merge — they persist with trailer state.
- The teardown step runs on **every exit** (success or failure), so partial progress is always saved.
- One branch per root phase (not per task): `arborist/{spec_id}/{phase}`.

## Artifacts

Every run uploads artifacts (retained 30 days) containing:
- `status.txt` — Overall tree status
- `inspect-{task_id}.txt` — Per-task inspection reports
- `task-tree.json` — Copy of the tree used
- Logs and reports from the gardener run

## Troubleshooting

**Workflow fails immediately with pip install error**
- Verify `GH_PAT_ARBORIST_RO` has `repo` scope and hasn't expired.

**Tasks fail with authentication errors**
- Check `CLAUDE_CODE_OAUTH_TOKEN` (for Claude) or `GOOGLE_API_KEY` (for Gemini) is set correctly.

**Resume doesn't pick up completed tasks**
- Ensure the teardown push step succeeded in the previous run (check logs).
- Verify arborist branches exist on the remote: `git ls-remote origin 'refs/heads/arborist/*'`.

**Timeout after 720 minutes**
- Large trees may need the timeout increased, or split into smaller specs.
- Check if a task is stuck in a retry loop — inspect artifacts from the failed run.

**Devcontainer build fails**
- Set `container_mode` to `disabled` to bypass, or ensure `.devcontainer/devcontainer.json` is valid.
