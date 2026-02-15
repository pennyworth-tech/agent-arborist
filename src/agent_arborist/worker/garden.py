"""Single task executor — garden() runs one task through implement/test/review."""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

from agent_arborist.constants import (
    TRAILER_STEP,
    TRAILER_RESULT,
    TRAILER_TEST,
    TRAILER_REVIEW,
    TRAILER_RETRY,
    TRAILER_REPORT,
)
from agent_arborist.git.repo import (
    git_add_all,
    git_branch_exists,
    git_checkout,
    git_commit,
    git_current_branch,
    git_diff,
    git_merge,
)
from agent_arborist.git.state import scan_completed_tasks, TaskState
from agent_arborist.tree.model import TaskNode, TaskTree


@dataclass
class GardenResult:
    task_id: str
    success: bool
    error: str | None = None


def find_next_task(tree: TaskTree, cwd: Path) -> TaskNode | None:
    """Find the next task to execute based on execution order and completed state."""
    completed = scan_completed_tasks(tree, cwd)
    for task_id in tree.execution_order:
        if task_id in completed:
            continue
        node = tree.nodes[task_id]
        if all(d in completed for d in node.depends_on):
            return node
    return None


def _build_trailers(**kwargs: str) -> str:
    """Build trailer lines for a commit message."""
    return "\n".join(f"{k}: {v}" for k, v in kwargs.items())


def _truncate_output(text: str | None, max_chars: int = 2000) -> str:
    """Keep the last max_chars of text (tail), since errors are usually at the end."""
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return "[...truncated]\n" + text[-max_chars:]


def _truncate_name(name: str, max_len: int = 50) -> str:
    if len(name) <= max_len:
        return name
    return name[: max_len - 3] + "..."


def _commit_with_trailers(
    task_id: str, subject: str, cwd: Path,
    body: str | None = None, **trailers: str,
) -> str:
    """Stage all and commit with trailers."""
    git_add_all(cwd)
    trailer_block = _build_trailers(**trailers)
    parts = [f"task({task_id}): {subject}"]
    if body:
        parts.append(body)
    parts.append(trailer_block)
    message = "\n\n".join(parts)
    return git_commit(message, cwd, allow_empty=True)


def _merge_phase_if_complete(
    tree: TaskTree, task_id: str, cwd: Path, base_branch: str
) -> bool:
    """If all leaves under the root phase are complete, merge phase branch to base."""
    rp = tree.root_phase(task_id)
    if rp == task_id and tree.nodes[task_id].is_leaf:
        # Standalone root leaf — no phase to merge
        return False
    phase_leaves = tree.leaves_under(rp)
    completed = scan_completed_tasks(tree, cwd)
    if all(leaf.id in completed for leaf in phase_leaves):
        phase_branch = tree.branch_name(rp)
        git_merge(phase_branch, cwd, message=f"merge: {phase_branch} complete")
        return True
    return False


def garden(
    tree: TaskTree,
    cwd: Path,
    runner,
    *,
    test_command: str = "true",
    max_retries: int = 3,
    base_branch: str = "main",
) -> GardenResult:
    """Execute one task through the implement → test → review pipeline."""
    task = find_next_task(tree, cwd)
    if task is None:
        return GardenResult(task_id="", success=False, error="no ready task")

    logger.info("Starting task %s: %s", task.id, task.name)
    phase_branch = tree.branch_name(task.id)

    # Lazy branch creation
    if not git_branch_exists(phase_branch, cwd):
        logger.debug("Creating branch %s from %s", phase_branch, base_branch)
        git_checkout(phase_branch, cwd, create=True, start_point=base_branch)
    else:
        logger.debug("Checking out existing branch %s", phase_branch)
        git_checkout(phase_branch, cwd)

    try:
        for attempt in range(max_retries):
            retry_trailer = str(attempt)
            logger.info("Task %s attempt %d/%d", task.id, attempt + 1, max_retries)

            # --- implement ---
            prompt = (
                f"Implement task {task.id}: {task.name}\n\n"
                f"Description: {task.description}\n\n"
                f"Work in the current directory. Make all necessary file changes."
            )
            logger.debug("Implement prompt: %.200s", prompt)
            result = runner.run(prompt, cwd=cwd)
            tname = _truncate_name(task.name)
            if not result.success:
                logger.info("Task %s implement failed", task.id)
                body = f"Runner error:\n{_truncate_output(result.error or result.output)}"
                _commit_with_trailers(
                    task.id,
                    f'implement "{tname}" (failed, attempt {attempt + 1}/{max_retries})',
                    cwd, body=body,
                    **{TRAILER_STEP: "implement", TRAILER_RESULT: "fail", TRAILER_RETRY: retry_trailer},
                )
                continue

            logger.info("Task %s implement passed", task.id)
            body = f"Runner output (truncated to 2000 chars):\n{_truncate_output(result.output)}"
            _commit_with_trailers(
                task.id, f'implement "{tname}"', cwd, body=body,
                **{TRAILER_STEP: "implement", TRAILER_RESULT: "pass", TRAILER_RETRY: retry_trailer},
            )

            # --- test ---
            try:
                test_result = subprocess.run(
                    test_command, shell=True, cwd=cwd,
                    capture_output=True, text=True, timeout=300,
                )
                test_passed = test_result.returncode == 0
                test_stdout = test_result.stdout or ""
                test_stderr = test_result.stderr or ""
            except subprocess.TimeoutExpired:
                test_passed = False
                test_stdout = ""
                test_stderr = "Test timed out after 300s"

            test_val = "pass" if test_passed else "fail"
            logger.info("Task %s test %s", task.id, test_val)

            test_body_parts = []
            if not test_passed and test_stderr:
                test_body_parts.append(f"Test stderr (last 1000 chars):\n{_truncate_output(test_stderr, 1000)}")
            if test_stdout:
                test_body_parts.append(f"Test stdout (last 1000 chars):\n{_truncate_output(test_stdout, 1000)}")
            test_body = "\n\n".join(test_body_parts) or None

            test_subject = f'tests {test_val} for "{tname}"'
            if not test_passed:
                test_subject += f" (attempt {attempt + 1}/{max_retries})"
            _commit_with_trailers(
                task.id, test_subject, cwd, body=test_body,
                **{TRAILER_STEP: "test", TRAILER_TEST: test_val, TRAILER_RETRY: retry_trailer},
            )

            if not test_passed:
                continue

            # --- review ---
            try:
                diff = git_diff(base_branch, "HEAD", cwd)
            except Exception:
                diff = "(no diff available)"

            review_prompt = (
                f"Review the changes for task {task.id}: {task.name}\n\n"
                f"Diff:\n{diff[:8000]}\n\n"
                f"Reply APPROVED if the code is correct, or REJECTED with reasons."
            )
            review_result = runner.run(review_prompt, cwd=cwd)
            approved = review_result.success and "APPROVED" in review_result.output.upper()

            logger.info("Task %s review %s", task.id, "approved" if approved else "rejected")
            review_val = "approved" if approved else "rejected"
            review_body = f"Review:\n{_truncate_output(review_result.output)}"
            review_subject = f'review {review_val} for "{tname}"'
            if not approved:
                review_subject += f" (attempt {attempt + 1}/{max_retries})"
            _commit_with_trailers(
                task.id, review_subject, cwd, body=review_body,
                **{TRAILER_STEP: "review", TRAILER_REVIEW: review_val, TRAILER_RETRY: retry_trailer},
            )

            if not approved:
                continue

            # --- complete (success) ---
            report_path = f"spec/reports/{task.id}.json"
            report_dir = cwd / "spec" / "reports"
            report_dir.mkdir(parents=True, exist_ok=True)
            (report_dir / f"{task.id}.json").write_text(
                json.dumps({"task_id": task.id, "result": "pass", "retries": attempt}, indent=2)
            )

            complete_body = f"Completed after {attempt + 1} attempt(s). Report: {report_path}"
            _commit_with_trailers(
                task.id, f'complete "{tname}"', cwd, body=complete_body,
                **{TRAILER_STEP: "complete", TRAILER_RESULT: "pass", TRAILER_REPORT: report_path},
            )

            logger.info("Task %s complete", task.id)
            git_checkout(base_branch, cwd)
            merged = _merge_phase_if_complete(tree, task.id, cwd, base_branch)
            if merged:
                logger.info("Phase merge completed for %s", task.id)
            return GardenResult(task_id=task.id, success=True)

        logger.info("Task %s failed after %d retries", task.id, max_retries)
        # --- exhausted retries ---
        _commit_with_trailers(
            task.id, f'failed "{_truncate_name(task.name)}" after {max_retries} retries', cwd,
            **{TRAILER_STEP: "complete", TRAILER_RESULT: "fail"},
        )

        git_checkout(base_branch, cwd)
        return GardenResult(task_id=task.id, success=False, error=f"failed after {max_retries} retries")

    except Exception:
        # Ensure we return to base branch on unexpected errors
        try:
            git_checkout(base_branch, cwd)
        except Exception:
            pass
        raise
