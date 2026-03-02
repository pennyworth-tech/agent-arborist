# Copyright 2026 Pennyworth Technologies, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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
    git_commit,
    git_diff_stat,
    git_log,
    git_rev_parse,
)
from agent_arborist.git.state import get_run_start_sha, scan_completed_tasks, TaskState
from agent_arborist.tree.model import TaskNode, TaskTree, TestCommand, TestType


@dataclass
class GardenResult:
    task_id: str
    success: bool
    error: str | None = None


def find_next_task(tree: TaskTree, cwd: Path, *, spec_id: str) -> TaskNode | None:
    """Find the next task to execute based on execution order and completed state."""
    completed = scan_completed_tasks(tree, cwd, spec_id=spec_id)
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
    container_up_timeout: int | None = None,
    container_check_timeout: int | None = None,
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
                kwargs = {}
                if container_up_timeout is not None:
                    kwargs["timeout_up"] = container_up_timeout
                if container_check_timeout is not None:
                    kwargs["timeout_check"] = container_check_timeout
                ensure_container_running(container_workspace, **kwargs)
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
    *, spec_id: str, status: str,
    body: str | None = None, **trailers: str,
) -> str:
    """Stage all and commit with trailers.

    Commit prefix: ``task({spec_id}@{task_id}@{status}): {subject}``
    """
    git_add_all(cwd)
    trailer_block = _build_trailers(**trailers)
    parts = [f"task({spec_id}@{task_id}@{status}): {subject}"]
    if body:
        parts.append(body)
    parts.append(trailer_block)
    message = "\n\n".join(parts)
    return git_commit(message, cwd, allow_empty=True)


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
    content = "\n".join(parts) if parts else f"=== {step} completed (no output) ==="
    log_file.write_text(content)
    return log_file


def _collect_feedback_from_git(task_id: str, cwd: Path, *, spec_id: str) -> str:
    """Collect previous review/test feedback from git commit history.

    Reads commit bodies for this task's review-rejected and test-fail commits,
    so feedback survives process restarts.
    """
    sections: list[str] = []

    # Get all commits for this task on the current spec_id
    grep_pattern = f"task({spec_id}@{task_id}"
    try:
        raw = git_log(
            "HEAD", "%B---COMMIT_SEP---", cwd,
            n=50, grep=grep_pattern, fixed_strings=True,
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
    report_dir: Path | None = None,
    log_dir: Path | None = None,
    runner_timeout: int | None = None,
    test_timeout: int | None = None,
    container_workspace: Path | None = None,
    container_up_timeout: int | None = None,
    container_check_timeout: int | None = None,
    spec_id: str,
    run_start_sha: str | None = None,
) -> GardenResult:
    """Execute one task through the implement → test → review pipeline."""
    # Resolve runners: explicit implement/review runners take precedence,
    # then fall back to the single `runner` param for backward compatibility.
    if implement_runner is None:
        implement_runner = runner
    if review_runner is None:
        review_runner = runner

    task = find_next_task(tree, cwd, spec_id=spec_id)
    if task is None:
        return GardenResult(task_id="", success=False, error="no ready task")

    _impl_id = f"{getattr(implement_runner, 'name', '?')}/{getattr(implement_runner, 'model', '?')}"
    _rev_id = f"{getattr(review_runner, 'name', '?')}/{getattr(review_runner, 'model', '?')}"
    logger.info("Starting task %s: %s (implement=%s, review=%s)", task.id, task.name, _impl_id, _rev_id)

    # Use run-start SHA for scoping review diffs
    if run_start_sha is None:
        run_start_sha = get_run_start_sha(cwd, spec_id=spec_id)
    start_sha = run_start_sha

    try:
        for attempt in range(max_retries):
            retry_trailer = str(attempt)
            logger.info("Task %s attempt %d/%d", task.id, attempt + 1, max_retries)

            # --- implement ---
            prompt = (
                f"Implement task {task.id}: {task.name}\n\n"
                f"Description: {task.description}\n\n"
                f"Work in the current directory. Make all necessary file changes.\n\n"
                f"IMPORTANT: Before making changes, check whether this task has already been "
                f"implemented (e.g. the files, variables, or state it requires already exist). "
                f"If a previous step has deterministically verified the work is already done "
                f"and shown its reasoning, you may confirm completion without making changes."
            )
            if attempt > 0:
                feedback = _collect_feedback_from_git(task.id, cwd, spec_id=spec_id)
                if feedback:
                    prompt += feedback
            logger.debug("Implement prompt: %.200s", prompt)
            run_kwargs = {
                "cwd": cwd,
                "container_workspace": container_workspace,
                "container_up_timeout": container_up_timeout,
                "container_check_timeout": container_check_timeout,
            }
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
                    cwd, spec_id=spec_id, status="implement-fail", body=body,
                    **{TRAILER_STEP: "implement", TRAILER_RESULT: "fail", TRAILER_RETRY: retry_trailer},
                )
                continue

            logger.info("Task %s implement passed (%s)", task.id, _impl_id)
            body = f"Runner output (truncated to 2000 chars):\n{_truncate_output(result.output)}"
            _commit_with_trailers(
                task.id, f'implement "{tname}"', cwd, spec_id=spec_id, status="implement-pass", body=body,
                **{TRAILER_STEP: "implement", TRAILER_RESULT: "pass", TRAILER_RETRY: retry_trailer},
            )

            # --- test ---
            test_results = _run_tests(
                task, cwd, test_command, test_timeout, container_workspace,
                container_up_timeout, container_check_timeout,
            )
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

            test_status = "test-pass" if all_tests_passed else "test-fail"
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
                task.id, test_subject, cwd, spec_id=spec_id, status=test_status,
                body=test_body,
                **test_trailers,
            )

            if not all_tests_passed:
                continue

            # --- review ---
            try:
                diff_stat = git_diff_stat(start_sha, "HEAD", cwd)
            except Exception:
                diff_stat = "(no diff available)"

            review_prompt = (
                f"Review the changes for task {task.id}: {task.name}\n\n"
                f"Task description: {task.description}\n\n"
                f"Files changed since run start:\n{diff_stat}\n\n"
                f"Focus on whether the right files are present and changed for this task. "
                f"Tests have already passed.\n\n"
                f"NOTE: If the implement step made no file changes but deterministically "
                f"verified that the required state already exists (and showed its work), "
                f"that is acceptable — approve if the task's goals are met.\n\n"
                f"Reply APPROVED if the deliverables look correct, or REJECTED with reasons."
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

            review_status = "review-approved" if approved else "review-rejected"
            review_trailers = {TRAILER_STEP: "review", TRAILER_REVIEW: review_val, TRAILER_RETRY: retry_trailer}
            if review_log_file is not None:
                try:
                    review_trailers[TRAILER_REVIEW_LOG] = str(review_log_file.relative_to(cwd))
                except ValueError:
                    review_trailers[TRAILER_REVIEW_LOG] = str(review_log_file)
            _commit_with_trailers(
                task.id, review_subject, cwd, spec_id=spec_id, status=review_status,
                body=review_body,
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
                task.id, f'complete "{tname}"', cwd, spec_id=spec_id, status="complete",
                body=complete_body,
                **{TRAILER_STEP: "complete", TRAILER_RESULT: "pass", TRAILER_REPORT: report_path},
            )

            logger.info("Task %s complete", task.id)
            return GardenResult(task_id=task.id, success=True)

        logger.info("Task %s failed after %d retries", task.id, max_retries)
        # --- exhausted retries ---
        _commit_with_trailers(
            task.id, f'failed "{_truncate_name(task.name)}" after {max_retries} retries', cwd,
            spec_id=spec_id, status="failed",
            **{TRAILER_STEP: "complete", TRAILER_RESULT: "fail"},
        )

        return GardenResult(task_id=task.id, success=False, error=f"failed after {max_retries} retries")

    except Exception:
        raise
