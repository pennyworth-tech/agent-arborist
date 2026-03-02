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

"""Pydantic schemas for dashboard API responses."""

from pydantic import BaseModel
from typing import Dict, List, Literal


class TaskCommit(BaseModel):
    sha: str
    subject: str
    step: str
    result: str
    retry: str
    trailers: Dict[str, str] = {}


class TaskStateData(BaseModel):
    id: str
    name: str
    state: Literal["pending", "implementing", "testing", "reviewing", "complete", "failed"]
    trailers: Dict[str, str] = {}
    commits: List[TaskCommit] = []


class StatusOutput(BaseModel):
    tree: dict
    spec_id: str
    completed: List[str]
    tasks: Dict[str, TaskStateData]
    generated_at: str


class Report(BaseModel):
    task_id: str
    result: Literal["pass", "fail"]
    retries: int


class ReportsOutput(BaseModel):
    reports: List[Report]
    summary: Dict[str, float | int]


class LogEntry(BaseModel):
    task_id: str
    phase: str
    timestamp: str
    filename: str
    size: int


class LogsOutput(BaseModel):
    logs: Dict[str, List[LogEntry]]
