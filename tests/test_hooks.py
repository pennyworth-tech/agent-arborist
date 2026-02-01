"""Tests for hooks system.

Tests for prompt loading, variable substitution, and hook base classes.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from agent_arborist.config import ArboristConfig, HookInjection, HooksConfig, StepDefinition
from agent_arborist.dag_builder import DagBundle, DagConfig, SubDag, SubDagStep
from agent_arborist.hooks import (
    CustomStep,
    CustomStepExecutor,
    ExecutorContext,
    HookDiagnostics,
    HookInjector,
    InjectorConfig,
    LLMEvalStepExecutor,
    PromptLoader,
    QualityCheckStepExecutor,
    ShellStepExecutor,
    StepContext,
    get_executor,
    inject_hooks,
    substitute_variables,
)
from agent_arborist.hooks.prompt_loader import (
    PromptLoadError,
    get_available_variables,
    substitute_variables_dict,
    validate_prompt_variables,
)
from agent_arborist.step_results import (
    CustomStepResult,
    LLMEvalResult,
    QualityCheckResult,
    ShellStepResult,
    StepResultBase,
)


# =============================================================================
# StepContext Tests
# =============================================================================


class TestStepContext:
    """Tests for StepContext dataclass."""

    def test_step_context_creation(self, tmp_path):
        """StepContext should store all required fields."""
        ctx = StepContext(
            task_id="T001",
            spec_id="my-spec",
            worktree_path=tmp_path / "worktrees" / "T001",
            branch_name="feature/T001",
            parent_branch="main",
            arborist_home=tmp_path / ".arborist",
        )
        assert ctx.task_id == "T001"
        assert ctx.spec_id == "my-spec"
        assert ctx.branch_name == "feature/T001"
        assert ctx.parent_branch == "main"

    def test_step_context_to_variables(self, tmp_path):
        """to_variables should return dict for substitution."""
        ctx = StepContext(
            task_id="T001",
            spec_id="my-spec",
            worktree_path=tmp_path / "worktrees" / "T001",
            branch_name="feature/T001",
            parent_branch="main",
            arborist_home=tmp_path / ".arborist",
        )
        vars = ctx.to_variables()
        assert vars["task_id"] == "T001"
        assert vars["spec_id"] == "my-spec"
        assert vars["branch_name"] == "feature/T001"
        assert vars["parent_branch"] == "main"
        assert "timestamp" in vars
        assert str(tmp_path) in vars["worktree_path"]
        assert str(tmp_path) in vars["arborist_home"]

    def test_step_context_null_task_id(self, tmp_path):
        """StepContext should handle None task_id."""
        ctx = StepContext(
            task_id=None,
            spec_id="my-spec",
            worktree_path=None,
            branch_name="main",
            parent_branch="main",
            arborist_home=tmp_path / ".arborist",
        )
        vars = ctx.to_variables()
        assert vars["task_id"] == ""
        assert vars["worktree_path"] == ""

    def test_step_context_timestamp_is_current(self, tmp_path):
        """Timestamp variable should be current time."""
        ctx = StepContext(
            task_id="T001",
            spec_id="my-spec",
            worktree_path=tmp_path,
            branch_name="main",
            parent_branch="main",
            arborist_home=tmp_path / ".arborist",
        )
        vars = ctx.to_variables()
        # Timestamp should be close to now
        ts = datetime.fromisoformat(vars["timestamp"])
        now = datetime.now()
        assert abs((now - ts).total_seconds()) < 2


# =============================================================================
# PromptLoader Tests
# =============================================================================


class TestPromptLoader:
    """Tests for PromptLoader class."""

    def test_load_inline_prompt_string(self, tmp_path):
        """load() should return inline prompt string."""
        loader = PromptLoader(prompts_dir=tmp_path / "prompts")
        config = {"prompt": "Review the code quality"}
        prompt = loader.load(config)
        assert prompt == "Review the code quality"

    def test_load_inline_prompt_list(self, tmp_path):
        """load() should join prompt list with newlines."""
        loader = PromptLoader(prompts_dir=tmp_path / "prompts")
        config = {
            "prompt": [
                "Review the following code:",
                "1. Check for bugs",
                "2. Check for security issues",
            ]
        }
        prompt = loader.load(config)
        assert "Review the following code:" in prompt
        assert "1. Check for bugs" in prompt
        assert "2. Check for security issues" in prompt
        assert "\n" in prompt

    def test_load_from_file(self, tmp_path):
        """load() should load prompt from file."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "review.txt").write_text("Review the code in {{worktree_path}}")

        loader = PromptLoader(prompts_dir=prompts_dir)
        config = {"prompt_file": "review.txt"}
        prompt = loader.load(config)
        assert prompt == "Review the code in {{worktree_path}}"

    def test_load_file_not_found_raises_error(self, tmp_path):
        """load() should raise error for missing file."""
        loader = PromptLoader(prompts_dir=tmp_path / "prompts")
        config = {"prompt_file": "nonexistent.txt"}
        with pytest.raises(PromptLoadError) as exc:
            loader.load(config)
        assert "not found" in str(exc.value).lower()

    def test_load_no_prompt_source_raises_error(self, tmp_path):
        """load() should raise error when no prompt source."""
        loader = PromptLoader(prompts_dir=tmp_path / "prompts")
        config = {}
        with pytest.raises(PromptLoadError) as exc:
            loader.load(config)
        assert "prompt" in str(exc.value).lower()

    def test_prompt_file_takes_precedence(self, tmp_path):
        """prompt_file should take precedence over prompt."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "file.txt").write_text("From file")

        loader = PromptLoader(prompts_dir=prompts_dir)
        config = {
            "prompt_file": "file.txt",
            "prompt": "Inline prompt",
        }
        prompt = loader.load(config)
        assert prompt == "From file"

    def test_exists_returns_true_for_existing_file(self, tmp_path):
        """exists() should return True for existing file."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "test.txt").write_text("test")

        loader = PromptLoader(prompts_dir=prompts_dir)
        assert loader.exists("test.txt") is True

    def test_exists_returns_false_for_missing_file(self, tmp_path):
        """exists() should return False for missing file."""
        loader = PromptLoader(prompts_dir=tmp_path / "prompts")
        assert loader.exists("nonexistent.txt") is False


# =============================================================================
# Variable Substitution Tests
# =============================================================================


class TestVariableSubstitution:
    """Tests for variable substitution functions."""

    def test_substitute_single_variable(self, tmp_path):
        """substitute_variables should replace single variable."""
        ctx = StepContext(
            task_id="T001",
            spec_id="my-spec",
            worktree_path=tmp_path,
            branch_name="main",
            parent_branch="main",
            arborist_home=tmp_path / ".arborist",
        )
        text = "Working on task {{task_id}}"
        result = substitute_variables(text, ctx)
        assert result == "Working on task T001"

    def test_substitute_multiple_variables(self, tmp_path):
        """substitute_variables should replace multiple variables."""
        ctx = StepContext(
            task_id="T001",
            spec_id="my-spec",
            worktree_path=tmp_path / "work",
            branch_name="feature/T001",
            parent_branch="main",
            arborist_home=tmp_path / ".arborist",
        )
        text = "Task {{task_id}} in {{spec_id}} on branch {{branch_name}}"
        result = substitute_variables(text, ctx)
        assert result == "Task T001 in my-spec on branch feature/T001"

    def test_substitute_unknown_variable_unchanged(self, tmp_path):
        """Unknown variables should be left unchanged."""
        ctx = StepContext(
            task_id="T001",
            spec_id="my-spec",
            worktree_path=tmp_path,
            branch_name="main",
            parent_branch="main",
            arborist_home=tmp_path / ".arborist",
        )
        text = "Task {{task_id}} with {{unknown_var}}"
        result = substitute_variables(text, ctx)
        assert result == "Task T001 with {{unknown_var}}"

    def test_substitute_no_variables(self, tmp_path):
        """Text without variables should pass through unchanged."""
        ctx = StepContext(
            task_id="T001",
            spec_id="my-spec",
            worktree_path=tmp_path,
            branch_name="main",
            parent_branch="main",
            arborist_home=tmp_path / ".arborist",
        )
        text = "No variables here"
        result = substitute_variables(text, ctx)
        assert result == "No variables here"

    def test_substitute_variables_dict(self):
        """substitute_variables_dict should work with plain dict."""
        variables = {"name": "Alice", "age": "30"}
        text = "Hello {{name}}, you are {{age}} years old"
        result = substitute_variables_dict(text, variables)
        assert result == "Hello Alice, you are 30 years old"

    def test_substitute_path_variable(self, tmp_path):
        """Path variables should be converted to strings."""
        ctx = StepContext(
            task_id="T001",
            spec_id="my-spec",
            worktree_path=tmp_path / "worktrees" / "T001",
            branch_name="main",
            parent_branch="main",
            arborist_home=tmp_path / ".arborist",
        )
        text = "cd {{worktree_path}} && npm test"
        result = substitute_variables(text, ctx)
        assert str(tmp_path / "worktrees" / "T001") in result

    def test_substitute_empty_variable(self, tmp_path):
        """Empty variable values should substitute as empty string."""
        ctx = StepContext(
            task_id=None,
            spec_id="my-spec",
            worktree_path=None,
            branch_name="main",
            parent_branch="main",
            arborist_home=tmp_path / ".arborist",
        )
        text = "Task: {{task_id}}, Path: {{worktree_path}}"
        result = substitute_variables(text, ctx)
        assert result == "Task: , Path: "


class TestVariableValidation:
    """Tests for prompt variable validation."""

    def test_get_available_variables(self):
        """get_available_variables should return list of valid variables."""
        available = get_available_variables()
        assert "task_id" in available
        assert "spec_id" in available
        assert "worktree_path" in available
        assert "branch_name" in available
        assert "parent_branch" in available
        assert "arborist_home" in available
        assert "timestamp" in available

    def test_validate_prompt_variables_valid(self):
        """validate_prompt_variables should return empty for valid vars."""
        text = "Task {{task_id}} in {{spec_id}}"
        unknown = validate_prompt_variables(text)
        assert unknown == []

    def test_validate_prompt_variables_unknown(self):
        """validate_prompt_variables should return unknown var names."""
        text = "Task {{task_id}} with {{unknown1}} and {{unknown2}}"
        unknown = validate_prompt_variables(text)
        assert "unknown1" in unknown
        assert "unknown2" in unknown
        assert "task_id" not in unknown

    def test_validate_prompt_variables_mixed(self):
        """validate_prompt_variables handles mix of known/unknown."""
        text = "{{task_id}} {{spec_id}} {{custom_var}}"
        unknown = validate_prompt_variables(text)
        assert unknown == ["custom_var"]


# =============================================================================
# HookDiagnostics Tests
# =============================================================================


class TestHookDiagnostics:
    """Tests for HookDiagnostics class."""

    def test_diagnostics_record_application(self):
        """record() should add hook application."""
        diag = HookDiagnostics()
        diag.record(
            step_name="lint",
            hook_point="post_task",
            task_id="T001",
            step_type="shell",
        )
        assert len(diag.applications) == 1
        app = diag.applications[0]
        assert app.step_name == "lint"
        assert app.hook_point == "post_task"
        assert app.task_id == "T001"
        assert app.step_type == "shell"

    def test_diagnostics_summary_empty(self):
        """summary() should handle no applications."""
        diag = HookDiagnostics()
        summary = diag.summary()
        assert "No hooks" in summary

    def test_diagnostics_summary_with_applications(self):
        """summary() should show application counts."""
        diag = HookDiagnostics()
        diag.record("lint", "post_task", "T001", "shell")
        diag.record("eval", "post_task", "T001", "llm_eval")
        diag.record("lint", "post_task", "T002", "shell")
        diag.record("final_report", "final", None, "llm_eval")

        summary = diag.summary()
        assert "4" in summary or "Total injections: 4" in summary
        assert "post_task" in summary
        assert "final" in summary

    def test_diagnostics_get_applications_for_task(self):
        """get_applications_for_task should filter by task_id."""
        diag = HookDiagnostics()
        diag.record("lint", "post_task", "T001", "shell")
        diag.record("eval", "post_task", "T002", "llm_eval")
        diag.record("test", "post_task", "T001", "shell")

        apps = diag.get_applications_for_task("T001")
        assert len(apps) == 2
        assert all(app.task_id == "T001" for app in apps)

    def test_diagnostics_get_applications_for_point(self):
        """get_applications_for_point should filter by hook_point."""
        diag = HookDiagnostics()
        diag.record("lint", "post_task", "T001", "shell")
        diag.record("setup", "pre_root", None, "shell")
        diag.record("test", "post_task", "T002", "shell")

        apps = diag.get_applications_for_point("post_task")
        assert len(apps) == 2
        assert all(app.hook_point == "post_task" for app in apps)


# =============================================================================
# Hook Step Result Tests
# =============================================================================


class TestHookStepResults:
    """Tests for hook step result dataclasses."""

    def test_shell_step_result(self):
        """ShellStepResult should store shell execution data."""
        result = ShellStepResult(
            success=True,
            command="npm run lint",
            return_code=0,
            stdout="All good!",
            stderr="",
            duration_seconds=1.5,
        )
        assert result.success is True
        assert result.command == "npm run lint"
        assert result.return_code == 0
        assert result.stdout == "All good!"
        assert result.duration_seconds == 1.5

    def test_llm_eval_result(self):
        """LLMEvalResult should store evaluation data."""
        result = LLMEvalResult(
            success=True,
            score=0.85,
            summary="Code looks good with minor issues",
            raw_response="Full response text...",
            runner="claude",
            model="haiku",
            prompt_tokens=100,
            completion_tokens=50,
            duration_seconds=2.0,
        )
        assert result.success is True
        assert result.score == 0.85
        assert result.summary == "Code looks good with minor issues"
        assert result.runner == "claude"

    def test_quality_check_result(self):
        """QualityCheckResult should store quality check data."""
        result = QualityCheckResult(
            success=True,
            score=90.0,
            min_score=80.0,
            passed=True,
            command="coverage report",
            return_code=0,
            output="Coverage: 90%",
            duration_seconds=3.0,
        )
        assert result.success is True
        assert result.score == 90.0
        assert result.passed is True

    def test_custom_step_result(self):
        """CustomStepResult should store arbitrary data."""
        result = CustomStepResult(
            success=True,
            class_name="mymodule.MyValidator",
            data={
                "validated": True,
                "issues": [],
                "metrics": {"lines": 100},
            },
            duration_seconds=0.5,
        )
        assert result.success is True
        assert result.class_name == "mymodule.MyValidator"
        assert result.data["validated"] is True
        assert result.data["metrics"]["lines"] == 100

    def test_step_result_to_json(self):
        """Step results should serialize to JSON."""
        result = ShellStepResult(
            success=True,
            command="echo test",
            return_code=0,
            stdout="test",
            stderr="",
            duration_seconds=0.1,
        )
        json_str = result.to_json()
        assert "success" in json_str
        assert "true" in json_str.lower()
        assert "echo test" in json_str

    def test_step_result_skipped(self):
        """Step results should support skipped flag."""
        result = ShellStepResult(
            success=True,
            skipped=True,
            skip_reason="Already completed in previous run",
            command="",
            return_code=0,
            stdout="",
            stderr="",
        )
        assert result.skipped is True
        assert "previous run" in result.skip_reason


# =============================================================================
# Step Executor Tests
# =============================================================================


@pytest.fixture
def executor_context(tmp_path):
    """Create a standard ExecutorContext for testing."""
    worktree = tmp_path / "worktrees" / "T001"
    worktree.mkdir(parents=True)

    step_ctx = StepContext(
        task_id="T001",
        spec_id="test-spec",
        worktree_path=worktree,
        branch_name="feature/T001",
        parent_branch="main",
        arborist_home=tmp_path / ".arborist",
    )

    step_def = StepDefinition(type="shell", command="echo test")

    arborist_config = ArboristConfig()

    prompts_dir = tmp_path / ".arborist" / "prompts"
    prompts_dir.mkdir(parents=True)

    return ExecutorContext(
        step_ctx=step_ctx,
        step_def=step_def,
        arborist_config=arborist_config,
        prompts_dir=prompts_dir,
    )


class TestShellStepExecutor:
    """Tests for ShellStepExecutor."""

    def test_execute_simple_command(self, executor_context):
        """ShellStepExecutor should run simple commands."""
        executor_context.step_def = StepDefinition(
            type="shell",
            command="echo hello",
        )
        executor = ShellStepExecutor()
        result = executor.execute(executor_context)

        assert result.success is True
        assert result.stdout == "hello"
        assert result.return_code == 0
        assert result.duration_seconds > 0

    def test_execute_with_variable_substitution(self, executor_context):
        """ShellStepExecutor should substitute variables in command."""
        executor_context.step_def = StepDefinition(
            type="shell",
            command="echo task={{task_id}}",
        )
        executor = ShellStepExecutor()
        result = executor.execute(executor_context)

        assert result.success is True
        assert "task=T001" in result.stdout

    def test_execute_with_working_dir(self, executor_context, tmp_path):
        """ShellStepExecutor should run in specified directory."""
        test_dir = tmp_path / "testdir"
        test_dir.mkdir()

        executor_context.step_def = StepDefinition(
            type="shell",
            command="pwd",
            working_dir=str(test_dir),
        )
        executor = ShellStepExecutor()
        result = executor.execute(executor_context)

        assert result.success is True
        assert str(test_dir) in result.stdout

    def test_execute_with_env_vars(self, executor_context):
        """ShellStepExecutor should pass env vars to command."""
        executor_context.step_def = StepDefinition(
            type="shell",
            command="echo $MY_VAR",
            env={"MY_VAR": "hello_world"},
        )
        executor = ShellStepExecutor()
        result = executor.execute(executor_context)

        assert result.success is True
        assert "hello_world" in result.stdout

    def test_execute_env_var_substitution(self, executor_context):
        """ShellStepExecutor should substitute variables in env values."""
        executor_context.step_def = StepDefinition(
            type="shell",
            command="echo $TASK_INFO",
            env={"TASK_INFO": "Task={{task_id}}"},
        )
        executor = ShellStepExecutor()
        result = executor.execute(executor_context)

        assert result.success is True
        assert "Task=T001" in result.stdout

    def test_execute_failing_command(self, executor_context):
        """ShellStepExecutor should handle failing commands."""
        executor_context.step_def = StepDefinition(
            type="shell",
            command="exit 1",
        )
        executor = ShellStepExecutor()
        result = executor.execute(executor_context)

        assert result.success is False
        assert result.return_code == 1

    def test_execute_timeout(self, executor_context):
        """ShellStepExecutor should handle timeouts."""
        executor_context.step_def = StepDefinition(
            type="shell",
            command="sleep 10",
            timeout=1,
        )
        executor = ShellStepExecutor()
        result = executor.execute(executor_context)

        assert result.success is False
        assert "timed out" in result.error.lower()

    def test_execute_uses_worktree_as_default_cwd(self, executor_context):
        """ShellStepExecutor should use worktree as default cwd."""
        executor_context.step_def = StepDefinition(
            type="shell",
            command="pwd",
        )
        executor = ShellStepExecutor()
        result = executor.execute(executor_context)

        assert result.success is True
        assert str(executor_context.step_ctx.worktree_path) in result.stdout


class TestQualityCheckStepExecutor:
    """Tests for QualityCheckStepExecutor."""

    def test_extract_percentage_score(self, executor_context):
        """QualityCheckStepExecutor should extract percentage scores."""
        executor_context.step_def = StepDefinition(
            type="quality_check",
            command="echo 'Coverage: 85%'",
        )
        executor = QualityCheckStepExecutor()
        result = executor.execute(executor_context)

        assert result.success is True
        assert result.score == 0.85
        assert result.passed is True

    def test_extract_fraction_score(self, executor_context):
        """QualityCheckStepExecutor should extract fraction scores."""
        executor_context.step_def = StepDefinition(
            type="quality_check",
            command="echo 'Tests passed: 8/10'",
        )
        executor = QualityCheckStepExecutor()
        result = executor.execute(executor_context)

        assert result.success is True
        assert result.score == 0.8

    def test_check_min_score_pass(self, executor_context):
        """QualityCheckStepExecutor should pass when score >= min_score."""
        executor_context.step_def = StepDefinition(
            type="quality_check",
            command="echo 'Coverage: 90%'",
            min_score=0.80,
        )
        executor = QualityCheckStepExecutor()
        result = executor.execute(executor_context)

        assert result.success is True
        assert result.passed is True
        assert result.score == 0.90
        assert result.min_score == 0.80

    def test_check_min_score_fail(self, executor_context):
        """QualityCheckStepExecutor should fail when score < min_score."""
        executor_context.step_def = StepDefinition(
            type="quality_check",
            command="echo 'Coverage: 50%'",
            min_score=0.80,
            fail_on_threshold=True,
        )
        executor = QualityCheckStepExecutor()
        result = executor.execute(executor_context)

        assert result.success is False
        assert result.passed is False
        assert result.score == 0.50
        assert "threshold" in result.error.lower()

    def test_check_min_score_no_fail(self, executor_context):
        """QualityCheckStepExecutor can warn without failing."""
        executor_context.step_def = StepDefinition(
            type="quality_check",
            command="echo 'Coverage: 50%'",
            min_score=0.80,
            fail_on_threshold=False,
        )
        executor = QualityCheckStepExecutor()
        result = executor.execute(executor_context)

        assert result.success is True  # Command succeeded
        assert result.passed is False  # Below threshold
        assert result.score == 0.50

    def test_custom_extraction_pattern(self, executor_context):
        """QualityCheckStepExecutor should use custom extraction pattern."""
        executor_context.step_def = StepDefinition(
            type="quality_check",
            command="echo 'Quality Index: 7.5 out of 10'",
            score_extraction={
                "pattern": r"Quality Index:\s*(\d+(?:\.\d+)?)",
                "format": "raw",
            },
        )
        executor = QualityCheckStepExecutor()
        result = executor.execute(executor_context)

        assert result.success is True
        assert result.score == 7.5


class TestLLMEvalStepExecutor:
    """Tests for LLMEvalStepExecutor parsing (mocked LLM calls)."""

    def test_parse_json_response(self, executor_context):
        """LLMEvalStepExecutor should parse JSON response."""
        executor = LLMEvalStepExecutor()
        result = executor._parse_response('{"score": 0.85, "summary": "Good code"}')

        assert result["score"] == 0.85
        assert result["summary"] == "Good code"

    def test_parse_json_in_markdown(self, executor_context):
        """LLMEvalStepExecutor should parse JSON from markdown blocks."""
        executor = LLMEvalStepExecutor()
        response = '''Here's my evaluation:

```json
{"score": 0.75, "summary": "Some issues found"}
```

Let me know if you need more details.'''
        result = executor._parse_response(response)

        assert result["score"] == 0.75
        assert result["summary"] == "Some issues found"

    def test_parse_messy_response(self, executor_context):
        """LLMEvalStepExecutor should extract score from text."""
        executor = LLMEvalStepExecutor()
        response = "After reviewing, I give this a score: 0.65. Overall decent."
        result = executor._parse_response(response)

        assert result["score"] == 0.65

    def test_parse_percentage_in_text(self, executor_context):
        """LLMEvalStepExecutor should handle text without JSON."""
        executor = LLMEvalStepExecutor()
        response = "The code quality is acceptable."
        result = executor._parse_response(response)

        # Should extract something (even if just the text as summary)
        assert "summary" in result


class TestCustomStepExecutor:
    """Tests for CustomStepExecutor."""

    def test_custom_step_class_not_found(self, executor_context):
        """CustomStepExecutor should handle missing class."""
        executor_context.step_def = StepDefinition(
            type="python",
            class_path="nonexistent.module.MyClass",
        )
        executor = CustomStepExecutor()
        result = executor.execute(executor_context)

        assert result.success is False
        assert "load" in result.error.lower() or "import" in result.error.lower()

    def test_custom_step_no_class_path(self, executor_context):
        """CustomStepExecutor should fail without class_path."""
        executor_context.step_def = StepDefinition(
            type="python",
            class_path=None,
        )
        executor = CustomStepExecutor()
        result = executor.execute(executor_context)

        assert result.success is False
        assert "class_path" in result.error.lower()


class TestGetExecutor:
    """Tests for get_executor factory function."""

    def test_get_shell_executor(self):
        """get_executor should return ShellStepExecutor for 'shell'."""
        executor = get_executor("shell")
        assert isinstance(executor, ShellStepExecutor)

    def test_get_llm_eval_executor(self):
        """get_executor should return LLMEvalStepExecutor for 'llm_eval'."""
        executor = get_executor("llm_eval")
        assert isinstance(executor, LLMEvalStepExecutor)

    def test_get_quality_check_executor(self):
        """get_executor should return QualityCheckStepExecutor for 'quality_check'."""
        executor = get_executor("quality_check")
        assert isinstance(executor, QualityCheckStepExecutor)

    def test_get_custom_executor(self):
        """get_executor should return CustomStepExecutor for 'python'."""
        executor = get_executor("python")
        assert isinstance(executor, CustomStepExecutor)

    def test_get_unknown_executor_raises(self):
        """get_executor should raise for unknown type."""
        with pytest.raises(ValueError) as exc:
            get_executor("unknown_type")
        assert "unknown_type" in str(exc.value)


# =============================================================================
# Hook Injector Tests
# =============================================================================


@pytest.fixture
def sample_dag_bundle():
    """Create a sample DAG bundle for testing."""
    # Create root DAG
    root = SubDag(
        name="test-spec",
        is_root=True,
        steps=[
            SubDagStep(name="branches-setup", command="arborist task branches-setup"),
            SubDagStep(name="call-T001", call="T001", depends=["branches-setup"]),
            SubDagStep(name="call-T002", call="T002", depends=["call-T001"]),
        ],
    )

    # Create task subdags
    t001 = SubDag(
        name="T001",
        steps=[
            SubDagStep(name="pre-sync", command="arborist task pre-sync T001"),
            SubDagStep(name="run", command="arborist task run T001", depends=["pre-sync"]),
            SubDagStep(name="post-merge", command="arborist task post-merge T001", depends=["run"]),
        ],
    )

    t002 = SubDag(
        name="T002",
        steps=[
            SubDagStep(name="pre-sync", command="arborist task pre-sync T002"),
            SubDagStep(name="run", command="arborist task run T002", depends=["pre-sync"]),
            SubDagStep(name="post-merge", command="arborist task post-merge T002", depends=["run"]),
        ],
    )

    return DagBundle(root=root, subdags=[t001, t002])


@pytest.fixture
def injector_config(tmp_path):
    """Create an injector config for testing."""
    hooks_config = HooksConfig(
        enabled=True,
        step_definitions={
            "lint": StepDefinition(type="shell", command="npm run lint"),
            "eval": StepDefinition(type="llm_eval", prompt="Review code"),
        },
    )

    return InjectorConfig(
        hooks_config=hooks_config,
        spec_id="test-spec",
        arborist_home=tmp_path / ".arborist",
    )


class TestHookInjector:
    """Tests for HookInjector class."""

    def test_injector_disabled_hooks(self, sample_dag_bundle, tmp_path):
        """Injector should skip when hooks disabled."""
        config = InjectorConfig(
            hooks_config=HooksConfig(enabled=False),
            spec_id="test-spec",
            arborist_home=tmp_path / ".arborist",
        )
        injector = HookInjector(config)

        original_step_count = len(sample_dag_bundle.root.steps)
        result = injector.inject(sample_dag_bundle)

        assert len(result.root.steps) == original_step_count

    def test_inject_pre_root_hook(self, sample_dag_bundle, tmp_path):
        """Injector should add pre_root hooks after branches-setup."""
        hooks_config = HooksConfig(
            enabled=True,
            step_definitions={
                "setup_check": StepDefinition(type="shell", command="echo setup"),
            },
            injections={
                "pre_root": [HookInjection(step="setup_check")],
            },
        )
        config = InjectorConfig(
            hooks_config=hooks_config,
            spec_id="test-spec",
            arborist_home=tmp_path / ".arborist",
        )
        injector = HookInjector(config)
        result = injector.inject(sample_dag_bundle)

        # Should have one more step
        assert len(result.root.steps) == 4

        # Hook should be after branches-setup
        step_names = [s.name for s in result.root.steps]
        assert "hook_pre_root_setup_check" in step_names
        branches_idx = step_names.index("branches-setup")
        hook_idx = step_names.index("hook_pre_root_setup_check")
        assert hook_idx == branches_idx + 1

    def test_inject_final_hook(self, sample_dag_bundle, tmp_path):
        """Injector should add final hooks at end of root DAG."""
        hooks_config = HooksConfig(
            enabled=True,
            step_definitions={
                "report": StepDefinition(type="llm_eval", prompt="Generate report"),
            },
            injections={
                "final": [HookInjection(step="report")],
            },
        )
        config = InjectorConfig(
            hooks_config=hooks_config,
            spec_id="test-spec",
            arborist_home=tmp_path / ".arborist",
        )
        injector = HookInjector(config)
        result = injector.inject(sample_dag_bundle)

        # Hook should be at end
        assert result.root.steps[-1].name == "hook_final_report"
        # Should depend on previous step
        assert "call-T002" in result.root.steps[-1].depends

    def test_inject_post_task_hook_all_tasks(self, sample_dag_bundle, tmp_path):
        """Injector should add post_task hooks to all tasks with *."""
        hooks_config = HooksConfig(
            enabled=True,
            step_definitions={
                "lint": StepDefinition(type="shell", command="npm run lint"),
            },
            injections={
                "post_task": [HookInjection(step="lint", tasks=["*"])],
            },
        )
        config = InjectorConfig(
            hooks_config=hooks_config,
            spec_id="test-spec",
            arborist_home=tmp_path / ".arborist",
        )
        injector = HookInjector(config)
        result = injector.inject(sample_dag_bundle)

        # Both T001 and T002 should have the hook
        t001 = next(s for s in result.subdags if s.name == "T001")
        t002 = next(s for s in result.subdags if s.name == "T002")

        assert any("lint" in s.name for s in t001.steps)
        assert any("lint" in s.name for s in t002.steps)

    def test_inject_post_task_hook_specific_task(self, sample_dag_bundle, tmp_path):
        """Injector should add post_task hooks only to specified tasks."""
        hooks_config = HooksConfig(
            enabled=True,
            step_definitions={
                "lint": StepDefinition(type="shell", command="npm run lint"),
            },
            injections={
                "post_task": [HookInjection(step="lint", tasks=["T001"])],
            },
        )
        config = InjectorConfig(
            hooks_config=hooks_config,
            spec_id="test-spec",
            arborist_home=tmp_path / ".arborist",
        )
        injector = HookInjector(config)
        result = injector.inject(sample_dag_bundle)

        t001 = next(s for s in result.subdags if s.name == "T001")
        t002 = next(s for s in result.subdags if s.name == "T002")

        # Only T001 should have the hook
        assert any("lint" in s.name for s in t001.steps)
        assert not any("lint" in s.name for s in t002.steps)

    def test_inject_post_task_hook_exclude_task(self, sample_dag_bundle, tmp_path):
        """Injector should exclude specified tasks."""
        hooks_config = HooksConfig(
            enabled=True,
            step_definitions={
                "lint": StepDefinition(type="shell", command="npm run lint"),
            },
            injections={
                "post_task": [
                    HookInjection(step="lint", tasks=["*"], tasks_exclude=["T002"])
                ],
            },
        )
        config = InjectorConfig(
            hooks_config=hooks_config,
            spec_id="test-spec",
            arborist_home=tmp_path / ".arborist",
        )
        injector = HookInjector(config)
        result = injector.inject(sample_dag_bundle)

        t001 = next(s for s in result.subdags if s.name == "T001")
        t002 = next(s for s in result.subdags if s.name == "T002")

        # T001 should have hook, T002 should not
        assert any("lint" in s.name for s in t001.steps)
        assert not any("lint" in s.name for s in t002.steps)

    def test_inject_pre_task_hook(self, sample_dag_bundle, tmp_path):
        """Injector should add pre_task hooks at start of task subdags."""
        hooks_config = HooksConfig(
            enabled=True,
            step_definitions={
                "setup": StepDefinition(type="shell", command="echo setup"),
            },
            injections={
                "pre_task": [HookInjection(step="setup", tasks=["*"])],
            },
        )
        config = InjectorConfig(
            hooks_config=hooks_config,
            spec_id="test-spec",
            arborist_home=tmp_path / ".arborist",
        )
        injector = HookInjector(config)
        result = injector.inject(sample_dag_bundle)

        t001 = next(s for s in result.subdags if s.name == "T001")

        # Hook should be first step
        assert "setup" in t001.steps[0].name
        # Original first step should depend on hook
        assert t001.steps[0].name in t001.steps[1].depends

    def test_inject_inline_step(self, sample_dag_bundle, tmp_path):
        """Injector should handle inline step definitions."""
        hooks_config = HooksConfig(
            enabled=True,
            injections={
                "post_task": [
                    HookInjection(
                        type="shell",
                        command="echo inline test",
                        tasks=["T001"],
                    )
                ],
            },
        )
        config = InjectorConfig(
            hooks_config=hooks_config,
            spec_id="test-spec",
            arborist_home=tmp_path / ".arborist",
        )
        injector = HookInjector(config)
        result = injector.inject(sample_dag_bundle)

        t001 = next(s for s in result.subdags if s.name == "T001")
        assert any("shell" in s.name for s in t001.steps)

    def test_inject_glob_pattern_matching(self, sample_dag_bundle, tmp_path):
        """Injector should support glob patterns for task matching."""
        hooks_config = HooksConfig(
            enabled=True,
            step_definitions={
                "lint": StepDefinition(type="shell", command="npm run lint"),
            },
            injections={
                "post_task": [HookInjection(step="lint", tasks=["T00*"])],
            },
        )
        config = InjectorConfig(
            hooks_config=hooks_config,
            spec_id="test-spec",
            arborist_home=tmp_path / ".arborist",
        )
        injector = HookInjector(config)
        result = injector.inject(sample_dag_bundle)

        # Both T001 and T002 match T00*
        t001 = next(s for s in result.subdags if s.name == "T001")
        t002 = next(s for s in result.subdags if s.name == "T002")

        assert any("lint" in s.name for s in t001.steps)
        assert any("lint" in s.name for s in t002.steps)

    def test_diagnostics_tracking(self, sample_dag_bundle, tmp_path):
        """Injector should track hook applications in diagnostics."""
        hooks_config = HooksConfig(
            enabled=True,
            step_definitions={
                "lint": StepDefinition(type="shell", command="npm run lint"),
            },
            injections={
                "post_task": [HookInjection(step="lint", tasks=["*"])],
                "final": [HookInjection(step="lint")],
            },
        )
        config = InjectorConfig(
            hooks_config=hooks_config,
            spec_id="test-spec",
            arborist_home=tmp_path / ".arborist",
        )
        injector = HookInjector(config)
        injector.inject(sample_dag_bundle)

        # Should have recorded 3 applications (2 tasks + 1 final)
        assert len(injector.diagnostics.applications) == 3

        # Check post_task applications
        post_task_apps = injector.diagnostics.get_applications_for_point("post_task")
        assert len(post_task_apps) == 2

        # Check final application
        final_apps = injector.diagnostics.get_applications_for_point("final")
        assert len(final_apps) == 1


class TestInjectHooksConvenience:
    """Tests for inject_hooks convenience function."""

    def test_inject_hooks_function(self, sample_dag_bundle, tmp_path):
        """inject_hooks should work as convenience function."""
        hooks_config = HooksConfig(
            enabled=True,
            step_definitions={
                "lint": StepDefinition(type="shell", command="npm run lint"),
            },
            injections={
                "final": [HookInjection(step="lint")],
            },
        )

        result = inject_hooks(
            bundle=sample_dag_bundle,
            hooks_config=hooks_config,
            spec_id="test-spec",
            arborist_home=tmp_path / ".arborist",
        )

        assert result.root.steps[-1].name == "hook_final_lint"
