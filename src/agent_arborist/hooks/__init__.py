"""Hooks system for DAG augmentation.

This module provides a hook-based architecture for injecting additional
steps into Arborist DAGs at strategic points. Hooks are fully configurable
via JSON configuration.

Step Types:
- llm_eval: Run LLM with configurable prompt, returns score + summary
- shell: Execute arbitrary shell commands
- quality_check: Run command and extract numeric score
- python: Custom Python classes for advanced logic

Hook Points:
- pre_root: Before branches-setup (DAG-level)
- post_roots: After branches-setup, before task calls (DAG-level)
- pre_task: Before pre-sync for each task (task-level)
- post_task: After post-merge for each task (task-level)
- final: After all tasks complete (DAG-level)
"""

from agent_arborist.hooks.base import (
    CustomStep,
    HookDiagnostics,
    StepContext,
)
from agent_arborist.hooks.executors import (
    CustomStepExecutor,
    ExecutorContext,
    LLMEvalStepExecutor,
    QualityCheckStepExecutor,
    ShellStepExecutor,
    StepExecutionError,
    StepExecutor,
    get_executor,
)
from agent_arborist.hooks.injector import (
    HookInjector,
    InjectorConfig,
    inject_hooks,
)
from agent_arborist.hooks.prompt_loader import (
    PromptLoader,
    substitute_variables,
)

__all__ = [
    # Base classes
    "CustomStep",
    "HookDiagnostics",
    "StepContext",
    # Executors
    "CustomStepExecutor",
    "ExecutorContext",
    "LLMEvalStepExecutor",
    "QualityCheckStepExecutor",
    "ShellStepExecutor",
    "StepExecutionError",
    "StepExecutor",
    "get_executor",
    # Injector
    "HookInjector",
    "InjectorConfig",
    "inject_hooks",
    # Prompt loading
    "PromptLoader",
    "substitute_variables",
]
