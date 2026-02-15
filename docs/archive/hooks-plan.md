# Hooks-Based DAG Augmentation System - Implementation Plan

## Overview

This system introduces a hook-based architecture that allows programmatic injection of additional steps into Arborist DAGs at strategic points. Hooks are **fully configurable via JSON** - no Python code required for standard use cases. The system supports:

- **Built-in step types**: `llm_eval`, `shell`, `quality_check`
- **Custom Python steps**: For advanced use cases requiring custom logic
- **Prompt library**: Reusable prompts stored in `.arborist/prompts/`
- **Variable substitution**: Dynamic values like `{{task_id}}`, `{{worktree_path}}`

**Key Design Principle**: Hooks are applied as a **post-processing phase** after AI-generated DAG construction. The AI does not build hooks - they are deterministically injected based on configuration.

## Architecture

### Design Decisions

1. **Config Location**: Hooks config is part of `ArboristConfig` (not a separate file)
   - Inherits existing precedence: global → project → env → CLI
   - Single source of truth for all Arborist configuration

2. **Step Types vs Hooks Separation**:
   - **Step Types**: Define _what_ gets executed (LLM call, shell command, etc.)
   - **Injections**: Define _when/where_ to inject steps (after post-merge, at DAG end)

3. **Post-AI Phase**: Hooks are applied after initial DAG generation
   - AI generates base DAG from task spec
   - Hook system augments DAG deterministically
   - Clear separation of concerns

4. **Default Behavior**: Hooks disabled by default - existing DAGs unchanged

### Hook Points

```
pre_root    → Before branches-setup (DAG-level)
post_roots  → After branches-setup, before task calls (DAG-level)
pre_task    → Before pre-sync for each task (task-level)
post_task   → After post-merge for each task (task-level)
final       → After all tasks complete (DAG-level)
```

### File Structure

```
src/agent_arborist/
├── hooks/
│   ├── __init__.py
│   ├── base.py                    # Hook base classes and types
│   ├── steps.py                   # Built-in step type implementations
│   ├── injector.py                # Step injection engine
│   ├── prompt_loader.py           # Prompt file loading and variable substitution
│   ├── config.py                  # HooksConfig dataclass (integrates with ArboristConfig)
│   └── registry.py                # Step type registry for custom Python steps
├── config.py                      # Updated with hooks section
├── dag_builder.py                 # Updated with post-generation hook phase
└── step_results.py                # Extended with hook result schemas

.arborist/
├── config.json                    # Project config (includes hooks section)
└── prompts/                       # Prompt library directory
    ├── code_quality.md
    ├── security_review.md
    └── test_coverage.md

tests/
├── unit/
│   ├── test_hooks_config.py       # Config parsing and validation
│   ├── test_hooks_steps.py        # Step type implementations
│   ├── test_hooks_injector.py     # Injection logic
│   └── test_hooks_prompts.py      # Prompt loading and variables
├── integration/
│   ├── test_hooks_dag_build.py    # Full DAG generation with hooks
│   ├── test_hooks_config_merge.py # Config precedence with hooks
│   └── test_hooks_e2e_mock.py     # E2E with mocked runners
└── e2e/
    └── test_hooks_e2e_claude.py   # E2E with actual Claude Code
```

## Configuration Schema

### Full Configuration Example

```json
{
  "version": "1",
  "defaults": { ... },
  "timeouts": { ... },
  "hooks": {
    "enabled": true,
    "prompts_dir": "prompts",

    "step_definitions": {
      "code_quality_eval": {
        "type": "llm_eval",
        "prompt_file": "code_quality.md",
        "runner": "claude",
        "model": "sonnet",
        "timeout": 120
      },
      "security_scan": {
        "type": "shell",
        "command": "bandit -r {{worktree_path}} -f json",
        "timeout": 60
      },
      "test_coverage": {
        "type": "quality_check",
        "command": "pytest --cov={{worktree_path}} --cov-report=json",
        "min_score": 80.0,
        "score_path": "$.totals.percent_covered"
      },
      "custom_validator": {
        "type": "python",
        "class": "my_hooks.CustomValidatorStep",
        "config": {
          "strict_mode": true
        }
      }
    },

    "injections": {
      "post_task": [
        {
          "step": "code_quality_eval",
          "tasks": ["*"],
          "after": "post-merge"
        },
        {
          "step": "test_coverage",
          "tasks": ["T001", "T002"],
          "after": "post-merge"
        }
      ],
      "final": [
        {
          "type": "shell",
          "command": "arborist spec branch-cleanup {{spec_id}} --merged-only"
        }
      ]
    }
  }
}
```

### Inline Step Definition

Steps can be defined inline within injections (for one-off steps):

```json
{
  "hooks": {
    "enabled": true,
    "injections": {
      "post_task": [
        {
          "type": "llm_eval",
          "prompt": "Review the code changes in {{worktree_path}} and provide a quality score from 0-100.",
          "tasks": ["*"]
        }
      ]
    }
  }
}
```

### Prompt Sources

Prompts can come from three sources:

```json
{
  "step_definitions": {
    "from_file": {
      "type": "llm_eval",
      "prompt_file": "code_quality.md"
    },
    "inline_text": {
      "type": "llm_eval",
      "prompt": "Evaluate the code in {{worktree_path}}..."
    },
    "multiline_inline": {
      "type": "llm_eval",
      "prompt": [
        "You are reviewing code for task {{task_id}}.",
        "",
        "Evaluate the following aspects:",
        "1. Code quality",
        "2. Test coverage",
        "3. Documentation",
        "",
        "Provide a score from 0-100 and a brief summary."
      ]
    }
  }
}
```

For `prompt` as array, lines are joined with newlines.

### Available Variables

Variables use `{{variable_name}}` syntax and are substituted at injection time:

| Variable | Description | Example |
|----------|-------------|---------|
| `{{task_id}}` | Current task ID | `T001` |
| `{{spec_id}}` | Spec identifier | `002-my-feature` |
| `{{worktree_path}}` | Absolute path to task workspace | `~/.arborist/workspaces/repo/002/T001` |
| `{{branch_name}}` | Git branch for task | `002-my-feature_T001` |
| `{{parent_branch}}` | Parent branch name | `002-my-feature` or `main` |
| `{{arborist_home}}` | Path to .arborist directory | `/home/user/.arborist` |
| `{{timestamp}}` | ISO timestamp | `2024-01-15T10:30:00` |

### Task Filtering

Tasks can be filtered using several patterns:

```json
{
  "injections": {
    "post_task": [
      { "step": "quality", "tasks": ["*"] },
      { "step": "security", "tasks": ["T001", "T002", "T003"] },
      { "step": "perf", "tasks": ["T00[1-5]"] },
      { "step": "review", "tasks_exclude": ["T001"] }
    ]
  }
}
```

| Filter | Description |
|--------|-------------|
| `["*"]` | All tasks (default) |
| `["T001", "T002"]` | Explicit task list |
| `["T00[1-5]"]` | Glob/regex pattern |
| `tasks_exclude` | Exclude specific tasks |

## Step Type Implementations

### 1. LLM Eval Step (`llm_eval`)

Runs an LLM with a configurable prompt and returns structured results.

**Configuration:**

```json
{
  "type": "llm_eval",
  "prompt": "...",
  "prompt_file": "quality.md",
  "runner": "claude",
  "model": "sonnet",
  "timeout": 120,
  "output_format": "score_and_summary"
}
```

**Implementation:**

```python
@dataclass
class LLMEvalStep:
    """LLM evaluation step - runs prompt and extracts structured result."""

    prompt: str
    runner: str = "claude"
    model: str | None = None
    timeout: int = 120

    def execute(self, ctx: StepContext) -> LLMEvalResult:
        """Execute LLM evaluation."""
        # Substitute variables in prompt
        resolved_prompt = substitute_variables(self.prompt, ctx)

        # Add result format instructions
        full_prompt = f"""{resolved_prompt}

IMPORTANT: End your response with a JSON block in this exact format:
```json
{{"score": <number 0-100>, "summary": "<brief summary>"}}
```"""

        # Run via configured runner
        runner = get_runner(self.runner, self.model)
        result = runner.run(full_prompt, timeout=self.timeout, cwd=ctx.worktree_path)

        # Parse score and summary from output
        score, summary = parse_llm_eval_output(result.output)

        return LLMEvalResult(
            success=result.success,
            score=score,
            summary=summary,
            raw_output=result.output,
            prompt_used=resolved_prompt,
            runner=self.runner,
            model=self.model,
        )
```

**Result Schema:**

```python
@dataclass
class LLMEvalResult(StepResultBase):
    """Result from LLM evaluation step."""

    score: float = 0.0              # Numeric result (0-100)
    summary: str = ""               # Text summary from LLM
    raw_output: str = ""            # Full LLM response
    prompt_used: str = ""           # Resolved prompt (for debugging)
    runner: str = ""                # Runner used
    model: str | None = None        # Model used
```

### 2. Shell Step (`shell`)

Runs an arbitrary shell command.

**Configuration:**

```json
{
  "type": "shell",
  "command": "bandit -r {{worktree_path}} -f json",
  "timeout": 60,
  "working_dir": "{{worktree_path}}",
  "env": {
    "PYTHONPATH": "{{worktree_path}}/src"
  }
}
```

**Implementation:**

```python
@dataclass
class ShellStep:
    """Shell command step."""

    command: str
    timeout: int = 60
    working_dir: str | None = None
    env: dict[str, str] = field(default_factory=dict)

    def execute(self, ctx: StepContext) -> ShellResult:
        """Execute shell command."""
        resolved_cmd = substitute_variables(self.command, ctx)
        resolved_cwd = substitute_variables(self.working_dir or ctx.worktree_path, ctx)
        resolved_env = {k: substitute_variables(v, ctx) for k, v in self.env.items()}

        result = subprocess.run(
            resolved_cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=self.timeout,
            cwd=resolved_cwd,
            env={**os.environ, **resolved_env},
        )

        return ShellResult(
            success=result.returncode == 0,
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            command=resolved_cmd,
        )
```

**Result Schema:**

```python
@dataclass
class ShellResult(StepResultBase):
    """Result from shell command step."""

    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    command: str = ""               # Resolved command (for debugging)
```

### 3. Quality Check Step (`quality_check`)

Runs a command and extracts a numeric score from its output.

**Configuration:**

```json
{
  "type": "quality_check",
  "command": "pytest --cov={{worktree_path}} --cov-report=json -q",
  "min_score": 80.0,
  "fail_on_threshold": true,
  "score_extraction": {
    "type": "json_path",
    "path": "$.totals.percent_covered"
  }
}
```

**Score Extraction Methods:**

```json
{
  "score_extraction": {
    "type": "json_path",
    "path": "$.coverage.percentage"
  }
}

{
  "score_extraction": {
    "type": "regex",
    "pattern": "Coverage: (\\d+\\.?\\d*)%"
  }
}

{
  "score_extraction": {
    "type": "exit_code",
    "success_score": 100,
    "failure_score": 0
  }
}
```

**Result Schema:**

```python
@dataclass
class QualityCheckResult(StepResultBase):
    """Result from quality check step."""

    score: float = 0.0
    min_score: float = 0.0
    passed: bool = False
    command: str = ""
    raw_output: str = ""
    extraction_method: str = ""
```

### 4. Custom Python Step (`python`)

For advanced use cases requiring custom logic.

**Configuration:**

```json
{
  "type": "python",
  "class": "my_project.hooks.CustomValidator",
  "config": {
    "strict_mode": true,
    "allowed_patterns": ["*.py", "*.ts"]
  }
}
```

**Implementation Interface:**

```python
# In user's code: my_project/hooks.py

from agent_arborist.hooks.base import CustomStep, StepContext, StepResultBase

class CustomValidator(CustomStep):
    """Custom validation step."""

    def __init__(self, config: dict):
        self.strict_mode = config.get("strict_mode", False)
        self.allowed_patterns = config.get("allowed_patterns", ["*"])

    def execute(self, ctx: StepContext) -> StepResultBase:
        """Execute custom validation logic."""
        # Custom validation logic here
        issues = self.validate_files(ctx.worktree_path)

        return CustomStepResult(
            success=len(issues) == 0,
            data={
                "issues_found": len(issues),
                "issues": issues,
                "strict_mode": self.strict_mode,
            }
        )

    def validate_files(self, path: Path) -> list[str]:
        # Custom logic
        ...
```

**Base Class:**

```python
class CustomStep(ABC):
    """Base class for custom Python steps."""

    @abstractmethod
    def __init__(self, config: dict):
        """Initialize with configuration from JSON."""
        pass

    @abstractmethod
    def execute(self, ctx: StepContext) -> StepResultBase:
        """Execute the step and return a result."""
        pass


@dataclass
class CustomStepResult(StepResultBase):
    """Result from custom Python step."""

    data: dict = field(default_factory=dict)  # Arbitrary data from custom step
```

## Prompt Library

### Directory Structure

```
.arborist/
└── prompts/
    ├── code_quality.md
    ├── security_review.md
    ├── test_analysis.md
    └── templates/
        └── evaluation_base.md
```

### Example Prompt File

`.arborist/prompts/code_quality.md`:

```markdown
# Code Quality Evaluation

You are reviewing code changes for task **{{task_id}}** in the {{spec_id}} project.

## Context

- Worktree: {{worktree_path}}
- Branch: {{branch_name}}

## Instructions

Analyze the code in the worktree and evaluate:

1. **Code Style**: Follows project conventions, readable, well-organized
2. **Error Handling**: Proper error handling, no silent failures
3. **Testing**: Adequate test coverage for new code
4. **Documentation**: Clear comments where needed, updated docs
5. **Security**: No obvious security issues

## Output Format

Provide your evaluation with:
- A score from 0-100
- A brief summary (2-3 sentences)
- Top 3 issues (if any)

End with:
```json
{"score": <number>, "summary": "<your summary>"}
```
```

### Prompt Loading

```python
class PromptLoader:
    """Loads and processes prompts from files or inline text."""

    def __init__(self, prompts_dir: Path):
        self.prompts_dir = prompts_dir

    def load(self, step_config: dict) -> str:
        """Load prompt from config (file or inline)."""
        if "prompt_file" in step_config:
            return self._load_file(step_config["prompt_file"])
        elif "prompt" in step_config:
            prompt = step_config["prompt"]
            if isinstance(prompt, list):
                return "\n".join(prompt)
            return prompt
        else:
            raise ConfigError("Step requires 'prompt' or 'prompt_file'")

    def _load_file(self, filename: str) -> str:
        """Load prompt from file."""
        path = self.prompts_dir / filename
        if not path.exists():
            raise ConfigError(f"Prompt file not found: {path}")
        return path.read_text()


def substitute_variables(text: str, ctx: StepContext) -> str:
    """Substitute {{variable}} placeholders with context values."""
    variables = {
        "task_id": ctx.task_id,
        "spec_id": ctx.spec_id,
        "worktree_path": str(ctx.worktree_path),
        "branch_name": ctx.branch_name,
        "parent_branch": ctx.parent_branch,
        "arborist_home": str(ctx.arborist_home),
        "timestamp": datetime.now().isoformat(),
    }

    result = text
    for var_name, value in variables.items():
        result = result.replace(f"{{{{{var_name}}}}}", str(value))

    return result
```

## Integration with ArboristConfig

### Updated config.py

```python
@dataclass
class StepDefinition:
    """Definition of a reusable step."""

    type: str  # "llm_eval", "shell", "quality_check", "python"
    # LLM eval options
    prompt: str | list[str] | None = None
    prompt_file: str | None = None
    runner: str | None = None
    model: str | None = None
    # Shell options
    command: str | None = None
    working_dir: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    # Quality check options
    min_score: float | None = None
    fail_on_threshold: bool = True
    score_extraction: dict | None = None
    # Python step options
    class_path: str | None = None  # "module.ClassName"
    config: dict = field(default_factory=dict)
    # Common options
    timeout: int = 120

    @classmethod
    def from_dict(cls, data: dict) -> "StepDefinition":
        """Create from dictionary."""
        return cls(
            type=data.get("type", "shell"),
            prompt=data.get("prompt"),
            prompt_file=data.get("prompt_file"),
            runner=data.get("runner"),
            model=data.get("model"),
            command=data.get("command"),
            working_dir=data.get("working_dir"),
            env=data.get("env", {}),
            min_score=data.get("min_score"),
            fail_on_threshold=data.get("fail_on_threshold", True),
            score_extraction=data.get("score_extraction"),
            class_path=data.get("class"),
            config=data.get("config", {}),
            timeout=data.get("timeout", 120),
        )


@dataclass
class HookInjection:
    """Definition of when/where to inject a step."""

    step: str | None = None  # Reference to step_definitions key
    type: str | None = None  # Inline step type (alternative to step reference)
    tasks: list[str] = field(default_factory=lambda: ["*"])
    tasks_exclude: list[str] = field(default_factory=list)
    after: str | None = None  # Step name to inject after
    before: str | None = None  # Step name to inject before
    # Inline step definition (when not referencing step_definitions)
    inline_config: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "HookInjection":
        """Create from dictionary."""
        # Extract known fields, rest goes to inline_config
        known_fields = {"step", "type", "tasks", "tasks_exclude", "after", "before"}
        inline_config = {k: v for k, v in data.items() if k not in known_fields}

        return cls(
            step=data.get("step"),
            type=data.get("type"),
            tasks=data.get("tasks", ["*"]),
            tasks_exclude=data.get("tasks_exclude", []),
            after=data.get("after"),
            before=data.get("before"),
            inline_config=inline_config,
        )


@dataclass
class HooksConfig:
    """Configuration for hook system."""

    enabled: bool = False
    prompts_dir: str = "prompts"
    step_definitions: dict[str, StepDefinition] = field(default_factory=dict)
    injections: dict[str, list[HookInjection]] = field(default_factory=dict)

    def validate(self) -> None:
        """Validate hooks configuration."""
        valid_hook_points = {"pre_root", "post_roots", "pre_task", "post_task", "final"}
        for hook_point in self.injections.keys():
            if hook_point not in valid_hook_points:
                raise ConfigValidationError(
                    f"Invalid hook point '{hook_point}'. "
                    f"Valid: {', '.join(valid_hook_points)}"
                )

        # Validate step references
        for hook_point, injections in self.injections.items():
            for injection in injections:
                if injection.step and injection.step not in self.step_definitions:
                    raise ConfigValidationError(
                        f"Unknown step '{injection.step}' in {hook_point} injection. "
                        f"Define it in step_definitions first."
                    )

    @classmethod
    def from_dict(cls, data: dict) -> "HooksConfig":
        """Create from dictionary."""
        step_defs = {}
        for name, step_data in data.get("step_definitions", {}).items():
            step_defs[name] = StepDefinition.from_dict(step_data)

        injections = {}
        for hook_point, injection_list in data.get("injections", {}).items():
            injections[hook_point] = [
                HookInjection.from_dict(inj) for inj in injection_list
            ]

        return cls(
            enabled=data.get("enabled", False),
            prompts_dir=data.get("prompts_dir", "prompts"),
            step_definitions=step_defs,
            injections=injections,
        )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "enabled": self.enabled,
            "prompts_dir": self.prompts_dir,
            "step_definitions": {
                name: asdict(step) for name, step in self.step_definitions.items()
            },
            "injections": {
                point: [asdict(inj) for inj in injections]
                for point, injections in self.injections.items()
            },
        }


# Update ArboristConfig to include hooks
@dataclass
class ArboristConfig:
    """Main configuration container."""

    version: str = "1"
    defaults: DefaultsConfig = field(default_factory=DefaultsConfig)
    timeouts: TimeoutConfig = field(default_factory=TimeoutConfig)
    steps: dict[str, StepConfig] = field(default_factory=...)
    test: TestingConfig = field(default_factory=TestingConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    runners: dict[str, RunnerConfig] = field(default_factory=dict)
    concurrency: ConcurrencyConfig = field(default_factory=ConcurrencyConfig)
    hooks: HooksConfig = field(default_factory=HooksConfig)  # NEW

    def validate(self) -> None:
        """Validate entire configuration."""
        self.defaults.validate()
        self.timeouts.validate()
        self.concurrency.validate()
        self.hooks.validate()  # NEW
        # ... rest of validation
```

## DAG Builder Integration

### Hook Application Phase

The key insight is that hooks are applied **after** the AI generates the base DAG:

```python
class SubDagBuilder:
    """Builds DAGU DAG with subdags from a TaskSpec."""

    def __init__(self, config: DagConfig):
        self.config = config
        self._task_tree: TaskTree | None = None
        self._use_containers = False

    def build(self, spec: TaskSpec, task_tree: TaskTree) -> DagBundle:
        """Build a complete DAG bundle from a TaskSpec and TaskTree."""
        self._task_tree = task_tree
        self._use_containers = should_use_container(...)

        # PHASE 1: Build base DAG (unchanged from current implementation)
        subdags = self._build_all_subdags(task_tree)
        root = self._build_root_dag(task_tree)
        bundle = DagBundle(root=root, subdags=subdags)

        # PHASE 2: Apply hooks (NEW)
        if self.config.arborist_config and self.config.arborist_config.hooks.enabled:
            bundle = self._apply_hooks(bundle, task_tree)

        return bundle

    def _apply_hooks(self, bundle: DagBundle, task_tree: TaskTree) -> DagBundle:
        """Apply configured hooks to the DAG bundle.

        This is a POST-PROCESSING phase - the base DAG is already built.
        """
        from agent_arborist.hooks.injector import HookInjector

        hooks_config = self.config.arborist_config.hooks
        injector = HookInjector(hooks_config, self.config)

        # Apply to root DAG
        bundle.root = injector.apply_to_dag(
            bundle.root,
            hook_points=["pre_root", "post_roots", "final"],
            task_tree=task_tree,
        )

        # Apply to each subdag
        augmented_subdags = []
        for subdag in bundle.subdags:
            task_id = subdag.name
            augmented = injector.apply_to_dag(
                subdag,
                hook_points=["pre_task", "post_task"],
                task_tree=task_tree,
                task_id=task_id,
            )
            augmented_subdags.append(augmented)

        bundle.subdags = augmented_subdags

        # Print diagnostic summary
        print(injector.diagnostics.summary())

        return bundle
```

### Hook Injector

```python
@dataclass
class StepContext:
    """Context available to steps during execution."""

    task_id: str | None
    spec_id: str
    worktree_path: Path | None
    branch_name: str
    parent_branch: str
    arborist_home: Path


class HookInjector:
    """Injects hook steps into DAGs based on configuration."""

    def __init__(self, hooks_config: HooksConfig, dag_config: DagConfig):
        self.hooks_config = hooks_config
        self.dag_config = dag_config
        self.diagnostics = HookDiagnostics()
        self.prompt_loader = PromptLoader(
            Path(get_arborist_home()) / hooks_config.prompts_dir
        )

    def apply_to_dag(
        self,
        dag: SubDag,
        hook_points: list[str],
        task_tree: TaskTree,
        task_id: str | None = None,
    ) -> SubDag:
        """Apply hooks to a DAG at specified hook points."""
        steps = list(dag.steps)  # Copy

        for hook_point in hook_points:
            injections = self.hooks_config.injections.get(hook_point, [])

            for injection in injections:
                # Check task filter
                if task_id and not self._matches_task_filter(task_id, injection):
                    continue

                # Build the step
                step = self._build_step(injection, task_id, task_tree)

                # Inject at appropriate position
                steps = self._inject_step(steps, step, injection, hook_point)

                # Record diagnostic
                self.diagnostics.record(
                    step_name=step.name,
                    hook_point=hook_point,
                    task_id=task_id,
                )

        return SubDag(
            name=dag.name,
            description=dag.description,
            env=dag.env,
            steps=steps,
            is_root=dag.is_root,
        )

    def _matches_task_filter(self, task_id: str, injection: HookInjection) -> bool:
        """Check if task matches injection filter."""
        # Check exclusions first
        if task_id in injection.tasks_exclude:
            return False

        # Check inclusions
        if "*" in injection.tasks:
            return True

        for pattern in injection.tasks:
            if fnmatch.fnmatch(task_id, pattern):
                return True
            if task_id == pattern:
                return True

        return False

    def _build_step(
        self,
        injection: HookInjection,
        task_id: str | None,
        task_tree: TaskTree,
    ) -> SubDagStep:
        """Build a SubDagStep from injection configuration."""
        # Get step definition
        if injection.step:
            step_def = self.hooks_config.step_definitions[injection.step]
        else:
            # Inline definition
            step_def = StepDefinition.from_dict({
                "type": injection.type,
                **injection.inline_config
            })

        # Build context for variable substitution
        ctx = self._build_context(task_id, task_tree)

        # Generate command based on step type
        command = self._build_command(step_def, ctx)

        # Generate unique step name
        step_name = self._generate_step_name(injection, task_id)

        return SubDagStep(
            name=step_name,
            command=command,
            output=f"{task_id or 'ROOT'}_{step_name.upper().replace('-', '_')}_RESULT",
        )

    def _build_command(self, step_def: StepDefinition, ctx: StepContext) -> str:
        """Build command string for a step."""
        if step_def.type == "llm_eval":
            prompt = self._get_prompt(step_def)
            resolved_prompt = substitute_variables(prompt, ctx)
            # Use arborist hooks llm-eval command
            return self._build_llm_eval_command(step_def, resolved_prompt)

        elif step_def.type == "shell":
            return substitute_variables(step_def.command, ctx)

        elif step_def.type == "quality_check":
            cmd = substitute_variables(step_def.command, ctx)
            return self._build_quality_check_command(step_def, cmd)

        elif step_def.type == "python":
            return self._build_python_step_command(step_def, ctx)

        else:
            raise ConfigError(f"Unknown step type: {step_def.type}")

    def _build_llm_eval_command(self, step_def: StepDefinition, prompt: str) -> str:
        """Build command for LLM eval step."""
        # Escape prompt for shell
        import shlex
        escaped_prompt = shlex.quote(prompt)

        cmd = f"arborist hooks llm-eval --prompt {escaped_prompt}"
        if step_def.runner:
            cmd += f" --runner {step_def.runner}"
        if step_def.model:
            cmd += f" --model {step_def.model}"
        if step_def.timeout:
            cmd += f" --timeout {step_def.timeout}"

        return cmd

    def _inject_step(
        self,
        steps: list[SubDagStep],
        new_step: SubDagStep,
        injection: HookInjection,
        hook_point: str,
    ) -> list[SubDagStep]:
        """Inject step at appropriate position."""
        if injection.after:
            # Find anchor step and insert after it
            for i, step in enumerate(steps):
                if step.name == injection.after:
                    new_step.depends = [injection.after]
                    steps.insert(i + 1, new_step)
                    return steps

        if injection.before:
            # Find anchor step and insert before it
            for i, step in enumerate(steps):
                if step.name == injection.before:
                    steps.insert(i, new_step)
                    # Update anchor's dependencies
                    steps[i + 1].depends = [new_step.name]
                    return steps

        # Default positions based on hook point
        if hook_point == "pre_root":
            steps.insert(0, new_step)
        elif hook_point == "post_roots":
            # After branches-setup
            for i, step in enumerate(steps):
                if step.name == "branches-setup":
                    new_step.depends = ["branches-setup"]
                    steps.insert(i + 1, new_step)
                    return steps
        elif hook_point == "pre_task":
            steps.insert(0, new_step)
        elif hook_point == "post_task":
            # After post-merge
            for i, step in enumerate(steps):
                if step.name == "post-merge":
                    new_step.depends = ["post-merge"]
                    steps.insert(i + 1, new_step)
                    return steps
            # Fallback: append
            steps.append(new_step)
        elif hook_point == "final":
            # After last task call
            new_step.depends = [steps[-1].name] if steps else []
            steps.append(new_step)

        return steps
```

## CLI Commands

### New Hook Commands

```python
@cli.group()
def hooks():
    """Hook system commands."""
    pass


@hooks.command("llm-eval")
@click.option("--prompt", required=True, help="Prompt to run")
@click.option("--runner", default="claude", help="LLM runner to use")
@click.option("--model", help="Model to use")
@click.option("--timeout", type=int, default=120, help="Timeout in seconds")
@click.option("--output-format", type=click.Choice(["json", "text"]), default="json")
def hooks_llm_eval(prompt: str, runner: str, model: str | None, timeout: int, output_format: str):
    """Run an LLM evaluation and output structured result.

    This command is typically called by hook-injected steps, not directly by users.
    """
    from agent_arborist.hooks.steps import LLMEvalStep

    step = LLMEvalStep(prompt=prompt, runner=runner, model=model, timeout=timeout)

    # Build minimal context (variables already substituted)
    ctx = StepContext(
        task_id=os.environ.get("ARBORIST_TASK_ID"),
        spec_id=os.environ.get("ARBORIST_SPEC_ID", ""),
        worktree_path=Path(os.environ.get("ARBORIST_WORKTREE", ".")),
        branch_name=os.environ.get("ARBORIST_BRANCH", ""),
        parent_branch=os.environ.get("ARBORIST_PARENT_BRANCH", ""),
        arborist_home=get_arborist_home(),
    )

    result = step.execute(ctx)

    if output_format == "json":
        print(result.to_json())
    else:
        print(f"Score: {result.score}")
        print(f"Summary: {result.summary}")


@hooks.command("quality-check")
@click.option("--command", required=True, help="Command to run")
@click.option("--min-score", type=float, default=0.0, help="Minimum passing score")
@click.option("--extraction", type=click.Choice(["json_path", "regex", "exit_code"]), default="exit_code")
@click.option("--extraction-pattern", help="Pattern for extraction (json path or regex)")
def hooks_quality_check(command: str, min_score: float, extraction: str, extraction_pattern: str | None):
    """Run a quality check command and extract score.

    This command is typically called by hook-injected steps, not directly by users.
    """
    from agent_arborist.hooks.steps import QualityCheckStep

    step = QualityCheckStep(
        command=command,
        min_score=min_score,
        score_extraction={"type": extraction, "pattern": extraction_pattern},
    )

    ctx = StepContext(...)  # Similar to above
    result = step.execute(ctx)

    print(result.to_json())


@hooks.command("list")
@click.pass_context
def hooks_list(ctx: click.Context):
    """List configured hooks."""
    arborist_home = ctx.obj.get("arborist_home")
    config = get_config(arborist_home=arborist_home)

    if not config.hooks.enabled:
        console.print("[dim]Hooks are disabled[/dim]")
        return

    console.print("[bold]Step Definitions:[/bold]")
    for name, step_def in config.hooks.step_definitions.items():
        console.print(f"  {name}: {step_def.type}")

    console.print("\n[bold]Injections:[/bold]")
    for hook_point, injections in config.hooks.injections.items():
        console.print(f"  {hook_point}:")
        for inj in injections:
            step_name = inj.step or f"inline:{inj.type}"
            tasks = ", ".join(inj.tasks) if inj.tasks != ["*"] else "all"
            console.print(f"    - {step_name} (tasks: {tasks})")


@hooks.command("validate")
@click.pass_context
def hooks_validate(ctx: click.Context):
    """Validate hooks configuration."""
    arborist_home = ctx.obj.get("arborist_home")
    config = get_config(arborist_home=arborist_home)

    try:
        config.hooks.validate()
        console.print("[green]Hooks configuration is valid[/green]")
    except ConfigValidationError as e:
        console.print(f"[red]Validation error:[/red] {e}")
        raise SystemExit(1)
```

## Testing Strategy

### Unit Tests

```python
# tests/unit/test_hooks_config.py

def test_hooks_config_disabled_by_default():
    """Hooks should be disabled by default."""
    config = ArboristConfig()
    assert config.hooks.enabled is False


def test_hooks_config_from_dict():
    """Test parsing hooks config from dictionary."""
    data = {
        "hooks": {
            "enabled": True,
            "step_definitions": {
                "quality": {"type": "llm_eval", "prompt": "Evaluate..."}
            },
            "injections": {
                "post_task": [{"step": "quality", "tasks": ["*"]}]
            }
        }
    }
    config = ArboristConfig.from_dict(data)
    assert config.hooks.enabled is True
    assert "quality" in config.hooks.step_definitions


def test_hooks_config_validation_invalid_hook_point():
    """Test validation catches invalid hook points."""
    config = HooksConfig(
        enabled=True,
        injections={"invalid_point": []}
    )
    with pytest.raises(ConfigValidationError, match="Invalid hook point"):
        config.validate()


def test_hooks_config_validation_unknown_step_reference():
    """Test validation catches unknown step references."""
    config = HooksConfig(
        enabled=True,
        injections={"post_task": [HookInjection(step="nonexistent")]}
    )
    with pytest.raises(ConfigValidationError, match="Unknown step"):
        config.validate()


# tests/unit/test_hooks_steps.py

def test_llm_eval_step_prompt_substitution():
    """Test variable substitution in prompts."""
    step = LLMEvalStep(prompt="Evaluate {{task_id}} in {{worktree_path}}")
    ctx = StepContext(
        task_id="T001",
        worktree_path=Path("/path/to/worktree"),
        ...
    )
    resolved = substitute_variables(step.prompt, ctx)
    assert "T001" in resolved
    assert "/path/to/worktree" in resolved


def test_shell_step_execution(mocker):
    """Test shell step executes command."""
    mocker.patch("subprocess.run", return_value=Mock(
        returncode=0, stdout="OK", stderr=""
    ))
    step = ShellStep(command="echo test")
    result = step.execute(StepContext(...))
    assert result.success is True


def test_quality_check_json_path_extraction():
    """Test JSON path score extraction."""
    step = QualityCheckStep(
        command="echo '{\"coverage\": 85.5}'",
        score_extraction={"type": "json_path", "path": "$.coverage"}
    )
    # ... test implementation


# tests/unit/test_hooks_prompts.py

def test_prompt_loader_from_file(tmp_path):
    """Test loading prompt from file."""
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "test.md").write_text("Test prompt for {{task_id}}")

    loader = PromptLoader(prompts_dir)
    prompt = loader.load({"prompt_file": "test.md"})
    assert "Test prompt" in prompt


def test_prompt_loader_inline_text():
    """Test inline prompt text."""
    loader = PromptLoader(Path("/nonexistent"))
    prompt = loader.load({"prompt": "Inline prompt"})
    assert prompt == "Inline prompt"


def test_prompt_loader_multiline_array():
    """Test multiline prompt as array."""
    loader = PromptLoader(Path("/nonexistent"))
    prompt = loader.load({"prompt": ["Line 1", "Line 2", "Line 3"]})
    assert prompt == "Line 1\nLine 2\nLine 3"


# tests/unit/test_hooks_injector.py

def test_injector_task_filter_wildcard():
    """Test wildcard task filter matches all."""
    injector = HookInjector(...)
    injection = HookInjection(tasks=["*"])
    assert injector._matches_task_filter("T001", injection) is True
    assert injector._matches_task_filter("T999", injection) is True


def test_injector_task_filter_explicit_list():
    """Test explicit task list."""
    injection = HookInjection(tasks=["T001", "T002"])
    assert injector._matches_task_filter("T001", injection) is True
    assert injector._matches_task_filter("T003", injection) is False


def test_injector_task_filter_pattern():
    """Test glob pattern matching."""
    injection = HookInjection(tasks=["T00[1-3]"])
    assert injector._matches_task_filter("T001", injection) is True
    assert injector._matches_task_filter("T005", injection) is False


def test_injector_task_exclude():
    """Test task exclusion."""
    injection = HookInjection(tasks=["*"], tasks_exclude=["T001"])
    assert injector._matches_task_filter("T001", injection) is False
    assert injector._matches_task_filter("T002", injection) is True
```

### Integration Tests

```python
# tests/integration/test_hooks_dag_build.py

def test_dag_build_without_hooks():
    """Test DAG builds correctly when hooks disabled."""
    config = ArboristConfig()
    assert config.hooks.enabled is False

    dag_config = DagConfig(name="test", arborist_config=config)
    builder = SubDagBuilder(dag_config)
    bundle = builder.build(spec, task_tree)

    # Verify no hook steps injected
    for subdag in bundle.subdags:
        step_names = [s.name for s in subdag.steps]
        assert not any("hook" in name for name in step_names)


def test_dag_build_with_post_task_hook():
    """Test DAG builds with post_task hook injection."""
    config = ArboristConfig.from_dict({
        "hooks": {
            "enabled": True,
            "step_definitions": {
                "quality": {"type": "shell", "command": "echo quality"}
            },
            "injections": {
                "post_task": [{"step": "quality", "tasks": ["*"], "after": "post-merge"}]
            }
        }
    })

    dag_config = DagConfig(name="test", arborist_config=config)
    builder = SubDagBuilder(dag_config)
    bundle = builder.build(spec, task_tree)

    # Verify hook step was injected after post-merge
    for subdag in bundle.subdags:
        step_names = [s.name for s in subdag.steps]
        post_merge_idx = step_names.index("post-merge")
        assert "hook-quality" in step_names[post_merge_idx + 1]


def test_dag_build_with_selective_task_hooks():
    """Test hooks only apply to specified tasks."""
    config = ArboristConfig.from_dict({
        "hooks": {
            "enabled": True,
            "injections": {
                "post_task": [{
                    "type": "shell",
                    "command": "echo selective",
                    "tasks": ["T001"]
                }]
            }
        }
    })

    # ... build and verify T001 has hook, T002 doesn't


def test_dag_build_with_final_hook():
    """Test final hook injection at DAG level."""
    config = ArboristConfig.from_dict({
        "hooks": {
            "enabled": True,
            "injections": {
                "final": [{
                    "type": "shell",
                    "command": "echo cleanup"
                }]
            }
        }
    })

    dag_config = DagConfig(name="test", arborist_config=config)
    builder = SubDagBuilder(dag_config)
    bundle = builder.build(spec, task_tree)

    # Verify hook is last step in root DAG
    root_step_names = [s.name for s in bundle.root.steps]
    assert root_step_names[-1].startswith("hook-")


# tests/integration/test_hooks_config_merge.py

def test_hooks_config_merge_global_and_project():
    """Test hooks config merges correctly from global and project."""
    # Create global config with some hooks
    global_config = ArboristConfig.from_dict({
        "hooks": {
            "enabled": True,
            "step_definitions": {
                "global_check": {"type": "shell", "command": "echo global"}
            }
        }
    })

    # Create project config with additional hooks
    project_config = ArboristConfig.from_dict({
        "hooks": {
            "step_definitions": {
                "project_check": {"type": "shell", "command": "echo project"}
            },
            "injections": {
                "post_task": [{"step": "global_check"}, {"step": "project_check"}]
            }
        }
    })

    merged = merge_configs(global_config, project_config)

    assert "global_check" in merged.hooks.step_definitions
    assert "project_check" in merged.hooks.step_definitions


# tests/integration/test_hooks_e2e_mock.py

def test_hooks_e2e_full_flow_mocked(tmp_path, mocker):
    """E2E test with mocked LLM runner."""
    # Mock the runner to return a predictable response
    mocker.patch("agent_arborist.runner.get_runner", return_value=MockRunner())

    # Create test spec directory
    spec_dir = tmp_path / "specs" / "001-test"
    spec_dir.mkdir(parents=True)
    (spec_dir / "tasks.md").write_text("""
# Test Spec
## T001 First Task
- [ ] Do something
""")

    # Create hooks config
    arborist_home = tmp_path / ".arborist"
    arborist_home.mkdir()
    (arborist_home / "config.json").write_text(json.dumps({
        "hooks": {
            "enabled": True,
            "injections": {
                "post_task": [{
                    "type": "llm_eval",
                    "prompt": "Rate this code",
                    "tasks": ["*"]
                }]
            }
        }
    }))

    # Run dag-build
    result = CliRunner().invoke(cli, [
        "--arborist-home", str(arborist_home),
        "spec", "--spec", "001-test",
        "dag-build", str(spec_dir), "--no-ai", "--dry-run"
    ])

    assert result.exit_code == 0
    assert "hook-llm-eval" in result.output
```

### E2E Test with Claude Code

```python
# tests/e2e/test_hooks_e2e_claude.py

import pytest
import subprocess
import shutil

# Skip if claude not available
pytestmark = pytest.mark.skipif(
    shutil.which("claude") is None,
    reason="Claude CLI not available"
)


@pytest.fixture
def test_repo(tmp_path):
    """Create a minimal test repo for E2E testing."""
    repo = tmp_path / "test-repo"
    repo.mkdir()

    # Initialize git
    subprocess.run(["git", "init"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)

    # Create initial commit
    (repo / "README.md").write_text("# Test Repo")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo, check=True)

    # Create spec
    spec_dir = repo / "specs" / "001-test"
    spec_dir.mkdir(parents=True)
    (spec_dir / "tasks.md").write_text("""
# Test Feature

## Tasks

### T001 Add hello function
Create a simple hello world function in hello.py

### T002 Add tests
Add tests for the hello function
""")

    # Create .arborist with hooks config
    arborist_home = repo / ".arborist"
    arborist_home.mkdir()
    prompts_dir = arborist_home / "prompts"
    prompts_dir.mkdir()

    # Create prompt file
    (prompts_dir / "code_review.md").write_text("""
# Code Review

Review the code changes and provide feedback.

Evaluate:
1. Code correctness
2. Style consistency
3. Potential issues

Output a score from 0-100 and a brief summary.

```json
{"score": <number>, "summary": "<summary>"}
```
""")

    # Create config with hooks
    (arborist_home / "config.json").write_text(json.dumps({
        "hooks": {
            "enabled": True,
            "prompts_dir": "prompts",
            "step_definitions": {
                "code_review": {
                    "type": "llm_eval",
                    "prompt_file": "code_review.md",
                    "runner": "claude",
                    "model": "haiku",
                    "timeout": 60
                }
            },
            "injections": {
                "post_task": [{
                    "step": "code_review",
                    "tasks": ["*"],
                    "after": "post-merge"
                }]
            }
        }
    }, indent=2))

    return repo


@pytest.mark.e2e
@pytest.mark.slow
def test_hooks_e2e_with_claude(test_repo):
    """E2E test running hooks with actual Claude CLI.

    This test:
    1. Creates a test repo with hooks configured
    2. Builds a DAG with hooks enabled
    3. Verifies hook steps are in the generated DAG
    4. Runs the hooks llm-eval command directly to verify it works
    """
    from click.testing import CliRunner
    from agent_arborist.cli import cli

    runner = CliRunner()

    # Build DAG with hooks
    result = runner.invoke(cli, [
        "--arborist-home", str(test_repo / ".arborist"),
        "spec", "--spec", "001-test",
        "dag-build", str(test_repo / "specs" / "001-test"),
        "--no-ai", "--dry-run", "--show"
    ], env={"HOME": str(test_repo.parent)})

    assert result.exit_code == 0, f"dag-build failed: {result.output}"

    # Verify hook steps are present
    assert "hook-code-review" in result.output or "code_review" in result.output

    # Test the llm-eval command directly
    eval_result = runner.invoke(cli, [
        "hooks", "llm-eval",
        "--prompt", "Say 'test successful' and output: {\"score\": 100, \"summary\": \"test\"}",
        "--runner", "claude",
        "--model", "haiku",
        "--timeout", "30"
    ])

    # This actually calls Claude - may take a few seconds
    assert eval_result.exit_code == 0, f"llm-eval failed: {eval_result.output}"

    # Verify JSON output
    output_data = json.loads(eval_result.output)
    assert "score" in output_data
    assert "summary" in output_data
    assert output_data["success"] is True


@pytest.mark.e2e
@pytest.mark.slow
def test_hooks_shell_step_e2e(test_repo):
    """E2E test for shell step execution."""
    # Update config with shell hook
    config_path = test_repo / ".arborist" / "config.json"
    config_path.write_text(json.dumps({
        "hooks": {
            "enabled": True,
            "injections": {
                "post_task": [{
                    "type": "shell",
                    "command": "echo 'Hook executed for {{task_id}}' && date",
                    "tasks": ["*"]
                }]
            }
        }
    }, indent=2))

    from click.testing import CliRunner
    from agent_arborist.cli import cli

    runner = CliRunner()

    # Build DAG
    result = runner.invoke(cli, [
        "--arborist-home", str(test_repo / ".arborist"),
        "spec", "--spec", "001-test",
        "dag-build", str(test_repo / "specs" / "001-test"),
        "--no-ai", "--dry-run", "--show"
    ])

    assert result.exit_code == 0
    # Shell command should be in the DAG
    assert "echo 'Hook executed" in result.output
```

## Implementation Phases

### Phase 1: Core Infrastructure (3-4 days)

1. **HooksConfig dataclass** - Add to config.py
2. **Config parsing and validation** - from_dict, validate
3. **Prompt loader** - File loading, variable substitution
4. **Step types base** - StepResultBase extensions
5. **Unit tests** - Config parsing, validation, prompt loading

**Deliverables:**
- `src/agent_arborist/hooks/__init__.py`
- `src/agent_arborist/hooks/config.py` (moved to main config.py integration)
- `src/agent_arborist/hooks/prompt_loader.py`
- Updated `src/agent_arborist/config.py` with HooksConfig
- Updated `src/agent_arborist/step_results.py` with hook results
- `tests/unit/test_hooks_config.py`
- `tests/unit/test_hooks_prompts.py`

### Phase 2: Step Implementations (2-3 days)

1. **Shell step** - Command execution
2. **LLM eval step** - Runner integration, output parsing
3. **Quality check step** - Score extraction methods
4. **Custom Python step** - Class loading, interface
5. **Unit tests** - Each step type

**Deliverables:**
- `src/agent_arborist/hooks/steps.py`
- `src/agent_arborist/hooks/registry.py` (for custom Python steps)
- `tests/unit/test_hooks_steps.py`

### Phase 3: Hook Injector (2-3 days)

1. **HookInjector class** - Core injection logic
2. **Task filtering** - Wildcard, patterns, exclusions
3. **Step positioning** - after/before anchors
4. **Diagnostics** - Summary output
5. **Integration tests** - Injection scenarios

**Deliverables:**
- `src/agent_arborist/hooks/injector.py`
- `src/agent_arborist/hooks/base.py` (StepContext, etc.)
- `tests/unit/test_hooks_injector.py`
- `tests/integration/test_hooks_dag_build.py`

### Phase 4: DAG Builder Integration (1-2 days)

1. **SubDagBuilder updates** - Post-processing phase
2. **CLI integration** - Hooks respected in dag-build
3. **Integration tests** - Full DAG generation

**Deliverables:**
- Updated `src/agent_arborist/dag_builder.py`
- `tests/integration/test_hooks_config_merge.py`

### Phase 5: CLI Commands (1-2 days)

1. **hooks llm-eval** - LLM evaluation command
2. **hooks quality-check** - Quality check command
3. **hooks list** - List configured hooks
4. **hooks validate** - Validate configuration

**Deliverables:**
- Updated `src/agent_arborist/cli.py`
- CLI help text and documentation

### Phase 6: E2E Testing (2-3 days)

1. **Mock E2E tests** - Full flow with mocked runners
2. **Claude E2E test** - Real Claude CLI integration
3. **Test fixtures** - Sample repos, configs, prompts

**Deliverables:**
- `tests/e2e/test_hooks_e2e_claude.py`
- `tests/integration/test_hooks_e2e_mock.py`
- Test fixtures in `tests/fixtures/hooks/`

### Phase 7: Documentation (1 day)

1. **User guide** - How to configure hooks
2. **Examples** - Common patterns
3. **API reference** - Step types, config options

**Deliverables:**
- `docs/hooks-guide.md`

## Summary

This revised design provides:

- **Full configuration via JSON** - No Python required for standard use cases
- **Built-in step types** - `llm_eval`, `shell`, `quality_check`, `python`
- **Prompt library** - Reusable prompts in `.arborist/prompts/`
- **Variable substitution** - Dynamic values like `{{task_id}}`
- **Post-AI phase** - Hooks applied after DAG generation, not during
- **Integrated config** - Part of ArboristConfig with standard precedence
- **Comprehensive testing** - Unit, integration, and E2E with Claude

The architecture cleanly separates:
- **Step definitions**: What to execute (reusable)
- **Injections**: When/where to inject (contextual)
- **Prompts**: External files or inline text

This enables the use case of "general-purpose LLM-based test reports" with configurable prompts while maintaining extensibility for advanced Python-based custom steps.
