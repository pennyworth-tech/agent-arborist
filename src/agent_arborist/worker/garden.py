"""Single task executor — garden() runs one task through implement/test/review."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from dataclasses import dataclass, field
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
    TRAILER_TEST_TYPE,
    TRAILER_TEST_PASSED,
    TRAILER_TEST_FAILED,
    TRAILER_TEST_SKIPPED,
    TRAILER_TEST_RUNTIME,
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
from agent_arborist.tree.model import TaskNode, TaskTree, TestCommand, TestType


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


@dataclass
class TestResult:
    passed: bool
    test_type: str  # "unit", "integration", "e2e"
    stdout: str
    stderr: str
    runtime_secs: float
    counts: dict | None = None  # {"passed": N, "failed": N, "skipped": N} or None


def _parse_test_counts(output: str, framework: str | None) -> dict | None:
    """Extract test counts from combined stdout+stderr based on framework."""
    if not framework:
        # Try all patterns
        for fw in ("pytest", "jest", "go"):
            result = _parse_test_counts(output, fw)
            if result is not None:
                return result
        return None

    if framework == "pytest":
        # e.g. "5 passed, 2 failed, 1 skipped in 3.45s"
        m = re.search(r"(\d+) passed", output)
        f = re.search(r"(\d+) failed", output)
        s = re.search(r"(\d+) skipped", output)
        if m or f:
            return {
                "passed": int(m.group(1)) if m else 0,
                "failed": int(f.group(1)) if f else 0,
                "skipped": int(s.group(1)) if s else 0,
            }

    elif framework in ("jest", "vitest"):
        # e.g. "Tests:  3 passed, 1 failed, 4 total"
        m = re.search(r"Tests:\s+(\d+)\s+passed(?:,\s+(\d+)\s+failed)?(?:,\s+(\d+)\s+skipped)?", output)
        if m:
            return {
                "passed": int(m.group(1)),
                "failed": int(m.group(2)) if m.group(2) else 0,
                "skipped": int(m.group(3)) if m.group(3) else 0,
            }

    elif framework == "go":
        # e.g. "ok  	pkg	0.123s" or "FAIL	pkg	0.456s"
        passed = len(re.findall(r"^ok\s+", output, re.MULTILINE))
        failed = len(re.findall(r"^FAIL\s+", output, re.MULTILINE))
        if passed or failed:
            return {"passed": passed, "failed": failed, "skipped": 0}

    return None


def _run_tests(
    node: TaskNode, cwd: Path, global_test_command: str, config_timeout: int | None,
    container_workspace: Path | None = None,
) -> list[TestResult]:
    """Run test commands for a node. Falls back to global_test_command if no per-node tests."""
    commands: list[tuple[str, str, str | None, int | None]] = []  # (command, type, framework, timeout)

    if node.test_commands:
        for tc in node.test_commands:
            commands.append((tc.command, tc.type.value, tc.framework, tc.timeout))
    else:
        commands.append((global_test_command, "unit", None, None))

    results: list[TestResult] = []
    for cmd, test_type, framework, cmd_timeout in commands:
        timeout = cmd_timeout or config_timeout or 300
        start = time.monotonic()
        try:
            if container_workspace:
                from agent_arborist.devcontainer import ensure_container_running, devcontainer_exec
                ensure_container_running(container_workspace)
                proc = devcontainer_exec(cmd, container_workspace, timeout=timeout)
            else:
                proc = subprocess.run(
                    cmd, shell=True, cwd=cwd,
                    capture_output=True, text=True, timeout=timeout,
                )
            elapsed = time.monotonic() - start
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            passed = proc.returncode == 0
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - start
            stdout = ""
            stderr = f"Test timed out after {timeout}s"
            passed = False

        counts = _parse_test_counts(stdout + stderr, framework)
        results.append(TestResult(
            passed=passed, test_type=test_type,
            stdout=stdout, stderr=stderr,
            runtime_secs=round(elapsed, 3), counts=counts,
        ))

    return results


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
    tree: TaskTree, task_id: str, cwd: Path, base_branch: str,
    global_test_command: str = "true", config_timeout: int | None = None,
    container_workspace: Path | None = None,
) -> bool | str:
    """If all leaves under the root phase are complete, merge phase branch to base.

    Returns True on successful merge, False if not ready, or an error string
    if phase tests failed.
    """
    rp = tree.root_phase(task_id)
    if rp == task_id and tree.nodes[task_id].is_leaf:
        return False
    phase_leaves = tree.leaves_under(rp)
    completed = scan_completed_tasks(tree, cwd)
    if not all(leaf.id in completed for leaf in phase_leaves):
        return False

    # Run phase-level tests (integration/e2e) from the parent node
    parent_node = tree.nodes[rp]
    phase_tests = [tc for tc in parent_node.test_commands
                   if tc.type in (TestType.INTEGRATION, TestType.E2E)]
    if phase_tests:
        phase_branch = tree.branch_name(rp)
        git_checkout(phase_branch, cwd)
        for tc in phase_tests:
            timeout = tc.timeout or config_timeout or 300
            start = time.monotonic()
            try:
                if container_workspace:
                    from agent_arborist.devcontainer import ensure_container_running, devcontainer_exec
                    ensure_container_running(container_workspace)
                    proc = devcontainer_exec(tc.command, container_workspace, timeout=timeout)
                else:
                    proc = subprocess.run(
                        tc.command, shell=True, cwd=cwd,
                        capture_output=True, text=True, timeout=timeout,
                    )
                passed = proc.returncode == 0
            except subprocess.TimeoutExpired:
                passed = False
            if not passed:
                git_checkout(base_branch, cwd)
                return f"Phase test failed: {tc.command} ({tc.type.value})"
        git_checkout(base_branch, cwd)

    phase_branch = tree.branch_name(rp)
    git_merge(phase_branch, cwd, message=f"merge: {phase_branch} complete")
    return True


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
    test_timeout: int | None = None,
    container_workspace: Path | None = None,
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
            run_kwargs = {"cwd": cwd, "container_workspace": container_workspace}
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
            test_results = _run_tests(task, cwd, test_command, test_timeout, container_workspace)
            all_tests_passed = all(tr.passed for tr in test_results)
            test_val = "pass" if all_tests_passed else "fail"
            logger.info("Task %s test %s", task.id, test_val)

            # Build combined test body and trailers for each result
            test_body_parts = []
            for tr in test_results:
                if not tr.passed and tr.stderr:
                    test_body_parts.append(f"Test ({tr.test_type}) stderr (last 1000 chars):\n{_truncate_output(tr.stderr, 1000)}")
                if tr.stdout:
                    test_body_parts.append(f"Test ({tr.test_type}) stdout (last 1000 chars):\n{_truncate_output(tr.stdout, 1000)}")
            test_body = "\n\n".join(test_body_parts) or None

            test_subject = f'tests {test_val} for "{tname}"'
            if not all_tests_passed:
                test_subject += f" (attempt {attempt + 1}/{max_retries})"

            # Write test log file on failure
            test_log_path = None
            if not all_tests_passed and log_dir is not None:
                from datetime import datetime, timezone as _tz
                log_dir.mkdir(parents=True, exist_ok=True)
                _ts = datetime.now(_tz.utc).strftime("%Y%m%dT%H%M%S")
                test_log_file = log_dir / f"{task.id}_test_{_ts}.log"
                log_parts = []
                for tr in test_results:
                    log_parts.append(f"=== {tr.test_type} stdout ===\n{tr.stdout}\n=== {tr.test_type} stderr ===\n{tr.stderr}")
                test_log_file.write_text("\n".join(log_parts))
                try:
                    test_log_path = str(test_log_file.relative_to(cwd))
                except ValueError:
                    test_log_path = str(test_log_file)

            test_trailers = {TRAILER_STEP: "test", TRAILER_TEST: test_val, TRAILER_RETRY: retry_trailer}
            if test_log_path:
                test_trailers[TRAILER_TEST_LOG] = test_log_path
            # Enhanced trailers from first (or only) test result
            if test_results:
                tr0 = test_results[0]
                test_trailers[TRAILER_TEST_TYPE] = tr0.test_type
                test_trailers[TRAILER_TEST_RUNTIME] = str(tr0.runtime_secs)
                if tr0.counts is not None:
                    test_trailers[TRAILER_TEST_PASSED] = str(tr0.counts["passed"])
                    test_trailers[TRAILER_TEST_FAILED] = str(tr0.counts["failed"])
                    test_trailers[TRAILER_TEST_SKIPPED] = str(tr0.counts["skipped"])
            _commit_with_trailers(
                task.id, test_subject, cwd, body=test_body,
                **test_trailers,
            )

            if not all_tests_passed:
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
            merge_result = _merge_phase_if_complete(
                tree, task.id, cwd, base_branch,
                global_test_command=test_command, config_timeout=test_timeout,
                container_workspace=container_workspace,
            )
            if merge_result is True:
                logger.info("Phase merge completed for %s", task.id)
            elif isinstance(merge_result, str):
                logger.error("Phase merge blocked for %s: %s", task.id, merge_result)
                return GardenResult(task_id=task.id, success=False, error=merge_result)
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
