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

"""Constants for agent-arborist."""

TRAILER_PREFIX = "Arborist"
TRAILER_STEP = f"{TRAILER_PREFIX}-Step"
TRAILER_RESULT = f"{TRAILER_PREFIX}-Result"
TRAILER_TEST = f"{TRAILER_PREFIX}-Test"
TRAILER_REVIEW = f"{TRAILER_PREFIX}-Review"
TRAILER_RETRY = f"{TRAILER_PREFIX}-Retry"
TRAILER_REPORT = f"{TRAILER_PREFIX}-Report"
TRAILER_REVIEW_LOG = f"{TRAILER_PREFIX}-Review-Log"
TRAILER_TEST_LOG = f"{TRAILER_PREFIX}-Test-Log"
TRAILER_TEST_TYPE = f"{TRAILER_PREFIX}-Test-Type"
TRAILER_TEST_PASSED = f"{TRAILER_PREFIX}-Test-Passed"
TRAILER_TEST_FAILED = f"{TRAILER_PREFIX}-Test-Failed"
TRAILER_TEST_SKIPPED = f"{TRAILER_PREFIX}-Test-Skipped"
TRAILER_TEST_RUNTIME = f"{TRAILER_PREFIX}-Test-Runtime"

DEFAULT_MAX_RETRIES = 5
