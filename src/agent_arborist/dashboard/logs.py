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

"""Scan log files on disk, keyed by known task IDs."""

from __future__ import annotations

import re
from pathlib import Path


def scan_log_files(
    log_dir: Path,
    task_ids: list[str],
) -> dict[str, list[dict[str, str | int]]]:
    """Find log files for the given task IDs.

    Log filenames are written by ``_write_log`` as ``{task_id}_{phase}_{timestamp}.log``.
    Task IDs are free-form, so we glob for ``{task_id}_*.log`` per ID rather than
    trying to regex-parse the ID out of the filename.

    Returns ``{task_id: [{phase, timestamp, filename, size}, ...]}``,
    sorted by timestamp within each task.
    """
    if not log_dir.exists():
        return {}

    result: dict[str, list[dict[str, str | int]]] = {}
    for tid in task_ids:
        entries: list[dict[str, str | int]] = []
        for fname in sorted(log_dir.glob(f"{tid}_*.log")):
            suffix = fname.stem[len(tid) + 1:]  # strip "{tid}_"
            ts_match = re.search(r"_(\d{8}T\d{6})$", suffix)
            if ts_match:
                timestamp = ts_match.group(1)
                phase = suffix[: ts_match.start()]
            else:
                timestamp = ""
                phase = suffix
            entries.append({
                "task_id": tid,
                "phase": phase,
                "timestamp": timestamp,
                "filename": fname.name,
                "size": fname.stat().st_size,
            })
        if entries:
            entries.sort(key=lambda e: e["timestamp"])
            result[tid] = entries

    return result
