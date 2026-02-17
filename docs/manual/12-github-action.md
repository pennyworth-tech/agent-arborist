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
   arborist build
   git add specs/ && git commit -m "Add task tree"
   git push origin spec/my-feature
   ```

4. Trigger the workflow: **Actions > Arborist Run > Run workflow**, entering your spec branch name.

## Workflow Inputs

| Input | Required | Description |
|---|---|---|
| `spec_branch` | Yes | Branch containing task-tree.json |
| `runner_type` | No | Override AI runner (`claude`, `gemini`, `opencode`) |
| `model` | No | Override model name |
| `max_retries` | No | Override max retries per task |
| `container_mode` | No | Override devcontainer mode (`auto`, `enabled`, `disabled`) |

When optional inputs are omitted, the CLI uses defaults from `.arborist/config.json`.

## How Resume Works

Arborist uses git-native state — task completion is tracked via git trailers on commits. The workflow exploits this for automatic resume:

```
Run 1 (fails on task 8/10):
  startup:  checkout spec_branch
  execute:  tasks 1-7 complete, task 8 fails
  teardown: push spec_branch (with all task commits)

Run 2 (retry):
  startup:  checkout spec_branch (includes previous commits)
  execute:  gardener finds tasks 1-7 done via trailers, picks up at task 8
  teardown: push again
```

Key points:
- All commits land on the spec branch — no separate branches to manage.
- The teardown step runs on **every exit** (success or failure), so partial progress is always saved.
- Resume is automatic: gardener scans commit trailers to find completed tasks.

## Troubleshooting

**Workflow fails immediately with pip install error**
- Verify `GH_PAT_ARBORIST_RO` has `repo` scope and hasn't expired.

**Tasks fail with authentication errors**
- Check `CLAUDE_CODE_OAUTH_TOKEN` (for Claude) or `GOOGLE_API_KEY` (for Gemini) is set correctly.

**Resume doesn't pick up completed tasks**
- Ensure the teardown push step succeeded in the previous run (check logs).
- Verify commits with arborist trailers exist: `git log --grep="Arborist-Step:" --oneline`.

**Timeout after 720 minutes**
- Large trees may need the timeout increased, or split into smaller specs.
- Check if a task is stuck in a retry loop — use `arborist inspect` locally.

**Devcontainer build fails**
- Set `container_mode` to `disabled` to bypass, or ensure `.devcontainer/devcontainer.json` is valid.
