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
    TRAILER_REVIEW_LOG,
    TRAILER_TEST_LOG,
)
from agent_arborist.git.repo import (
    git_add_all,
    git_branch_exists,
    git_checkout,
    git_commit,
    git_current_branch,
    git_diff,
    git_log,
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


def _write_log(log_dir: Path | None, task_id: str, step: str, result) -> Path | None:
    """Write runner stdout/stderr to a log file. Returns the path written."""
    if log_dir is None:
        return None
    from datetime import datetime, timezone
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    log_file = log_dir / f"{task_id}_{step}_{ts}.log"
    parts = []
    if result.output:
        parts.append(f"=== stdout ===\n{result.output}")
    if result.error:
        parts.append(f"=== stderr ===\n{result.error}")
    if parts:
        log_file.write_text("\n".join(parts))
        return log_file
    return None


def _collect_feedback_from_git(task_id: str, cwd: Path) -> str:
    """Collect previous review/test feedback from git commit history.

    Reads commit bodies for this task's review-rejected and test-fail commits,
    so feedback survives process restarts.
    """
    sections: list[str] = []

    # Get all commits for this task on the current branch
    try:
        raw = git_log(
            "HEAD", "%B---COMMIT_SEP---", cwd,
            n=50, grep=f"task({task_id}):", fixed_strings=True,
        )
    except Exception:
        return ""

    for block in raw.split("---COMMIT_SEP---"):
        block = block.strip()
        if not block:
            continue
        # Review rejections
        if f"{TRAILER_REVIEW}: rejected" in block:
            # Extract the body between subject and trailers
            lines = block.split("\n")
            body_lines = []
            for line in lines[1:]:  # skip subject
                if line.startswith("Arborist-"):
                    break
                body_lines.append(line)
            body = "\n".join(body_lines).strip()
            if body:
                sections.append(f"--- Previous review (rejected) ---\n{body}")

        # Test failures
        if f"{TRAILER_TEST}: fail" in block:
            lines = block.split("\n")
            body_lines = []
            for line in lines[1:]:
                if line.startswith("Arborist-"):
                    break
                body_lines.append(line)
            body = "\n".join(body_lines).strip()
            if body:
                sections.append(f"--- Previous test failure ---\n{body}")

    if not sections:
        return ""
    return "\n\nPrevious feedback from failed attempts:\n\n" + "\n\n".join(sections)


def garden(
    tree: TaskTree,
    cwd: Path,
    runner=None,
    *,
    implement_runner=None,
    review_runner=None,
    test_command: str = "true",
    max_retries: int = 3,
    base_branch: str = "main",
    report_dir: Path | None = None,
    log_dir: Path | None = None,
    runner_timeout: int | None = None,
) -> GardenResult:
    """Execute one task through the implement → test → review pipeline."""
    # Resolve runners: explicit implement/review runners take precedence,
    # then fall back to the single `runner` param for backward compatibility.
    if implement_runner is None:
        implement_runner = runner
    if review_runner is None:
        review_runner = runner

    task = find_next_task(tree, cwd)
    if task is None:
        return GardenResult(task_id="", success=False, error="no ready task")

    _impl_id = f"{getattr(implement_runner, 'name', '?')}/{getattr(implement_runner, 'model', '?')}"
    _rev_id = f"{getattr(review_runner, 'name', '?')}/{getattr(review_runner, 'model', '?')}"
    logger.info("Starting task %s: %s (implement=%s, review=%s)", task.id, task.name, _impl_id, _rev_id)
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
            if attempt > 0:
                feedback = _collect_feedback_from_git(task.id, cwd)
                if feedback:
                    prompt += feedback
            logger.debug("Implement prompt: %.200s", prompt)
            run_kwargs = {"cwd": cwd}
            if runner_timeout is not None:
                run_kwargs["timeout"] = runner_timeout
            result = implement_runner.run(prompt, **run_kwargs)
            _write_log(log_dir, task.id, "implement", result)
            tname = _truncate_name(task.name)
            if not result.success:
                logger.info("Task %s implement failed (%s)", task.id, _impl_id)
                body = f"Runner error:\n{_truncate_output(result.error or result.output)}"
                _commit_with_trailers(
                    task.id,
                    f'implement "{tname}" (failed, attempt {attempt + 1}/{max_retries})',
                    cwd, body=body,
                    **{TRAILER_STEP: "implement", TRAILER_RESULT: "fail", TRAILER_RETRY: retry_trailer},
                )
                continue

            logger.info("Task %s implement passed (%s)", task.id, _impl_id)
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

            # Write test log file and get path for trailer
            test_log_path = None
            if not test_passed and log_dir is not None:
                from datetime import datetime, timezone as _tz
                log_dir.mkdir(parents=True, exist_ok=True)
                _ts = datetime.now(_tz.utc).strftime("%Y%m%dT%H%M%S")
                test_log_file = log_dir / f"{task.id}_test_{_ts}.log"
                test_log_file.write_text(
                    f"=== stdout ===\n{test_stdout}\n=== stderr ===\n{test_stderr}"
                )
                try:
                    test_log_path = str(test_log_file.relative_to(cwd))
                except ValueError:
                    test_log_path = str(test_log_file)

            test_trailers = {TRAILER_STEP: "test", TRAILER_TEST: test_val, TRAILER_RETRY: retry_trailer}
            if test_log_path:
                test_trailers[TRAILER_TEST_LOG] = test_log_path
            _commit_with_trailers(
                task.id, test_subject, cwd, body=test_body,
                **test_trailers,
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
            review_result = review_runner.run(review_prompt, **run_kwargs)
            review_log_file = _write_log(log_dir, task.id, "review", review_result)
            approved = review_result.success and "APPROVED" in review_result.output.upper()

            logger.info("Task %s review %s (%s)", task.id, "approved" if approved else "rejected", _rev_id)
            review_val = "approved" if approved else "rejected"
            review_body = f"Review:\n{_truncate_output(review_result.output)}"
            review_subject = f'review {review_val} for "{tname}"'
            if not approved:
                review_subject += f" (attempt {attempt + 1}/{max_retries})"

            review_trailers = {TRAILER_STEP: "review", TRAILER_REVIEW: review_val, TRAILER_RETRY: retry_trailer}
            if review_log_file is not None:
                try:
                    review_trailers[TRAILER_REVIEW_LOG] = str(review_log_file.relative_to(cwd))
                except ValueError:
                    review_trailers[TRAILER_REVIEW_LOG] = str(review_log_file)
            _commit_with_trailers(
                task.id, review_subject, cwd, body=review_body,
                **review_trailers,
            )

            if not approved:
                continue

            # --- complete (success) ---
            from datetime import datetime, timezone
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            effective_report_dir = report_dir if report_dir is not None else cwd / "spec" / "reports"
            effective_report_dir.mkdir(parents=True, exist_ok=True)
            report_filename = f"{task.id}_run_{ts}.json"
            (effective_report_dir / report_filename).write_text(
                json.dumps({"task_id": task.id, "result": "pass", "retries": attempt}, indent=2)
            )
            abs_report = effective_report_dir / report_filename
            try:
                report_path = str(abs_report.relative_to(cwd))
            except ValueError:
                report_path = str(abs_report)

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
