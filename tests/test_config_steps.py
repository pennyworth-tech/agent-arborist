"""Tests for implement/review step config resolution."""

import os
import json

import pytest

from agent_arborist.config import (
    VALID_STEPS,
    ArboristConfig,
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
