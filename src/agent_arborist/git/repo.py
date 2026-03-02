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

"""Thin git subprocess wrapper."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class GitError(Exception):
    """Error from a git command."""


def _run(args: list[str], cwd: Path) -> str:
    """Run a git command and return stdout."""
    logger.debug("git %s", " ".join(args))
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        raise GitError(f"git {' '.join(args)}: {e.stderr.strip()}") from e


def git_toplevel(cwd: Path | None = None) -> Path:
    """Return the root of the git repository containing cwd."""
    return Path(_run(["rev-parse", "--show-toplevel"], cwd or Path.cwd()))


def git_init(cwd: Path) -> None:
    _run(["init"], cwd)
    _run(["config", "user.email", "arborist@test.com"], cwd)
    _run(["config", "user.name", "Arborist"], cwd)


def git_checkout(branch: str, cwd: Path, *, create: bool = False, start_point: str | None = None) -> None:
    args = ["checkout"]
    if create:
        args.append("-b")
    args.append(branch)
    if start_point:
        args.append(start_point)
    _run(args, cwd)


def git_branch_exists(branch: str, cwd: Path) -> bool:
    try:
        _run(["rev-parse", "--verify", f"refs/heads/{branch}"], cwd)
        return True
    except GitError:
        return False


def git_add_all(cwd: Path) -> None:
    _run(["add", "-A"], cwd)


def git_commit(message: str, cwd: Path, *, allow_empty: bool = False) -> str:
    """Commit and return the SHA."""
    args = ["commit", "-m", message]
    if allow_empty:
        args.append("--allow-empty")
    _run(args, cwd)
    return _run(["rev-parse", "HEAD"], cwd)


def git_log(branch: str, fmt: str, cwd: Path, *, n: int = 1, grep: str | None = None, fixed_strings: bool = False) -> str:
    args = ["log", branch, f"--format={fmt}", f"-n{n}"]
    if grep:
        args.extend(["--grep", grep])
        if fixed_strings:
            args.append("--fixed-strings")
    return _run(args, cwd)


def git_current_branch(cwd: Path) -> str:
    return _run(["rev-parse", "--abbrev-ref", "HEAD"], cwd)


def git_merge(branch: str, cwd: Path, *, message: str = "", no_ff: bool = True) -> None:
    args = ["merge"]
    if no_ff:
        args.append("--no-ff")
    if message:
        args.extend(["-m", message])
    args.append(branch)
    _run(args, cwd)


def git_diff(ref1: str, ref2: str, cwd: Path) -> str:
    return _run(["diff", f"{ref1}..{ref2}"], cwd)


def git_diff_stat(ref1: str, ref2: str, cwd: Path) -> str:
    return _run(["diff", "--stat", f"{ref1}..{ref2}"], cwd)


def git_branch_list(cwd: Path, pattern: str | None = None) -> list[str]:
    args = ["branch", "--list", "--format=%(refname:short)"]
    if pattern:
        args.append(pattern)
    try:
        out = _run(args, cwd)
    except GitError:
        return []
    return [b for b in out.split("\n") if b]


def git_rev_parse(rev: str, cwd: Path) -> str:
    """Resolve a revision to its full SHA."""
    return _run(["rev-parse", rev], cwd)


def git_merge_base(branch1: str, branch2: str, cwd: Path) -> str | None:
    """Find the common ancestor of two refs.

    Returns None if no common ancestor exists (e.g., unrelated histories).
    Raises GitError if one of the refs doesn't exist.
    """
    try:
        return _run(["merge-base", branch1, branch2], cwd)
    except GitError:
        return None


def git_log_since(
    rev: str,
    since: str,
    fmt: str,
    cwd: Path,
    *,
    grep: str | None = None,
    fixed_strings: bool = False,
    n: int = 500,
) -> str:
    """Run git log for commits since branching point, returning formatted output.

    Args:
        rev: The revision to log (e.g., 'HEAD', branch name)
        since: The branch/ref to find divergence from (e.g., 'main')
        fmt: Format string for git log
        cwd: Working directory
        grep: Optional grep pattern
        fixed_strings: Use fixed string matching for grep
        n: Maximum number of commits to return
    """
    args = [
        "log", f"{since}..{rev}", f"--format={fmt}%n---COMMIT_SEP---",
        f"-n{n}",
    ]
    if grep:
        args.extend(["--grep", grep])
        if fixed_strings:
            args.append("--fixed-strings")
    return _run(args, cwd)


def spec_id_from_branch(branch: str) -> str:
    """Extract spec ID from branch name.

    Strips optional 'feature/' prefix and everything after the first '/'.

    Examples:
        'bl-jjjj-blah-blah' -> 'bl-jjjj-blah-blah'
        'bl-jjjj-blah-blah/ver2' -> 'bl-jjjj-blah-blah'
        'feature/bl-jjjj-blah-blah' -> 'bl-jjjj-blah-blah'
        'feature/bl-jjjj-blah-blah/ver2' -> 'bl-jjjj-blah-blah'
    """
    if branch.startswith("feature/"):
        branch = branch[8:]
    if "/" in branch:
        branch = branch.split("/")[0]
    return branch
