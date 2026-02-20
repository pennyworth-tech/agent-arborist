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

"""Tests for implement/review step config resolution."""

import os
import json

import pytest

from agent_arborist.config import (
    VALID_STEPS,
    ArboristConfig,
    DefaultsConfig,
    RunnerConfig,
    StepConfig,
    get_step_runner_model,
    generate_config_template,
)


def test_valid_steps_includes_implement_review():
    assert "implement" in VALID_STEPS
    assert "review" in VALID_STEPS


def test_get_step_runner_model_implement_fallback_to_run():
    cfg = ArboristConfig()
    cfg.steps["run"] = StepConfig(runner="gemini", model="flash")
    runner, model = get_step_runner_model(cfg, "implement", fallback_step="run")
    assert runner == "gemini"
    assert model == "flash"


def test_get_step_runner_model_implement_overrides_run():
    cfg = ArboristConfig()
    cfg.steps["run"] = StepConfig(runner="gemini", model="flash")
    cfg.steps["implement"] = StepConfig(runner="claude", model="sonnet")
    runner, model = get_step_runner_model(cfg, "implement", fallback_step="run")
    assert runner == "claude"
    assert model == "sonnet"


def test_get_step_runner_model_review_independent():
    cfg = ArboristConfig()
    cfg.steps["implement"] = StepConfig(runner="claude", model="sonnet")
    cfg.steps["review"] = StepConfig(runner="gemini", model="pro")
    impl_r, impl_m = get_step_runner_model(cfg, "implement", fallback_step="run")
    rev_r, rev_m = get_step_runner_model(cfg, "review", fallback_step="run")
    assert impl_r == "claude"
    assert rev_r == "gemini"
    assert impl_m == "sonnet"
    assert rev_m == "pro"


def test_env_var_step_implement_runner(monkeypatch):
    monkeypatch.setenv("ARBORIST_STEP_IMPLEMENT_RUNNER", "opencode")
    from agent_arborist.config import apply_env_overrides
    cfg = apply_env_overrides(ArboristConfig())
    assert cfg.steps["implement"].runner == "opencode"


def test_env_var_step_review_model(monkeypatch):
    monkeypatch.setenv("ARBORIST_STEP_REVIEW_MODEL", "pro")
    from agent_arborist.config import apply_env_overrides
    cfg = apply_env_overrides(ArboristConfig())
    assert cfg.steps["review"].model == "pro"


def test_cli_flag_overrides_step_config():
    cfg = ArboristConfig()
    cfg.steps["implement"] = StepConfig(runner="gemini", model="flash")
    runner, model = get_step_runner_model(cfg, "implement", cli_runner="claude", cli_model="opus", fallback_step="run")
    assert runner == "claude"
    assert model == "opus"


def test_config_json_roundtrip_with_new_steps():
    cfg = ArboristConfig()
    cfg.steps["implement"] = StepConfig(runner="claude", model="sonnet")
    cfg.steps["review"] = StepConfig(runner="gemini", model="pro")
    data = cfg.to_dict()
    restored = ArboristConfig.from_dict(data)
    assert restored.steps["implement"].runner == "claude"
    assert restored.steps["review"].runner == "gemini"
    assert restored.steps["review"].model == "pro"


def test_generate_template_includes_implement_review():
    template = generate_config_template()
    assert "implement" in template["steps"]
    assert "review" in template["steps"]


def test_env_override_review_only(monkeypatch):
    """Base config uses claude; env overrides review to gemini."""
    from agent_arborist.config import apply_env_overrides
    cfg = ArboristConfig()
    cfg.steps["run"] = StepConfig(runner="claude", model="sonnet")
    monkeypatch.setenv("ARBORIST_STEP_REVIEW_RUNNER", "gemini")
    monkeypatch.setenv("ARBORIST_STEP_REVIEW_MODEL", "pro")
    cfg = apply_env_overrides(cfg)

    impl_r, impl_m = get_step_runner_model(cfg, "implement", fallback_step="run")
    rev_r, rev_m = get_step_runner_model(cfg, "review", fallback_step="run")

    assert impl_r == "claude"
    assert impl_m == "sonnet"
    assert rev_r == "gemini"
    assert rev_m == "pro"


def test_cli_overrides_all_steps():
    """CLI flag overrides both step configs."""
    cfg = ArboristConfig()
    cfg.steps["implement"] = StepConfig(runner="gemini", model="flash")
    cfg.steps["review"] = StepConfig(runner="opencode", model="llama")

    impl_r, _ = get_step_runner_model(cfg, "implement", cli_runner="claude", fallback_step="run")
    rev_r, _ = get_step_runner_model(cfg, "review", cli_runner="claude", fallback_step="run")

    assert impl_r == "claude"
    assert rev_r == "claude"


def test_runner_timeout_default():
    cfg = ArboristConfig()
    assert cfg.timeouts.runner_timeout == 600


def test_runner_timeout_env_override(monkeypatch):
    monkeypatch.setenv("ARBORIST_RUNNER_TIMEOUT", "120")
    from agent_arborist.config import apply_env_overrides
    cfg = apply_env_overrides(ArboristConfig())
    assert cfg.timeouts.runner_timeout == 120


def test_runner_timeout_from_dict():
    cfg = ArboristConfig.from_dict({"timeouts": {"runner_timeout": 300}})
    assert cfg.timeouts.runner_timeout == 300


def test_max_retries_default():
    cfg = ArboristConfig()
    assert cfg.defaults.max_retries == 5


def test_max_retries_from_dict():
    cfg = ArboristConfig.from_dict({"defaults": {"max_retries": 5}})
    assert cfg.defaults.max_retries == 5


def test_max_retries_roundtrip():
    cfg = ArboristConfig()
    cfg.defaults.max_retries = 7
    data = cfg.to_dict()
    restored = ArboristConfig.from_dict(data)
    assert restored.defaults.max_retries == 7


def test_max_retries_env_override(monkeypatch):
    monkeypatch.setenv("ARBORIST_MAX_RETRIES", "5")
    from agent_arborist.config import apply_env_overrides
    cfg = apply_env_overrides(ArboristConfig())
    assert cfg.defaults.max_retries == 5


def test_max_retries_validation():
    from agent_arborist.config import ConfigValidationError
    cfg = ArboristConfig()
    cfg.defaults.max_retries = 0
    with pytest.raises(ConfigValidationError):
        cfg.validate()


def test_runner_config_no_timeout_field():
    """RunnerConfig should not have a timeout field."""
    assert not hasattr(RunnerConfig(), "timeout")


def test_fallback_chain():
    """No implement/review config, only run config — both use run config."""
    cfg = ArboristConfig()
    cfg.steps["run"] = StepConfig(runner="gemini", model="flash")

    impl_r, impl_m = get_step_runner_model(cfg, "implement", fallback_step="run")
    rev_r, rev_m = get_step_runner_model(cfg, "review", fallback_step="run")

    assert impl_r == "gemini"
    assert impl_m == "flash"
    assert rev_r == "gemini"
    assert rev_m == "flash"
