"""Integration tests for hooks system.

Tests the full hooks workflow including:
- Hook injection into generated DAGs
- Variable substitution in real contexts
- CLI hooks commands with real config files
"""

import json
import os
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_arborist.cli import main
from agent_arborist.config import ArboristConfig, HooksConfig, HookInjection, StepDefinition
from agent_arborist.dag_builder import DagConfig, SequentialDagBuilder


class TestHooksWithDagBuilder:
    """Test hook injection with the real DAG builder."""

    @pytest.fixture
    def git_repo_with_spec_and_hooks(self, tmp_path):
        """Create a temp git repo with a spec directory and hooks config."""
        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        subprocess.run(["git", "init"], capture_output=True, check=True)
        readme = tmp_path / "README.md"
        readme.write_text("# Test\n")
        subprocess.run(["git", "add", "."], capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            capture_output=True,
            check=True,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "Test",
                "GIT_AUTHOR_EMAIL": "test@test.com",
                "GIT_COMMITTER_NAME": "Test",
                "GIT_COMMITTER_EMAIL": "test@test.com",
            },
        )

        # Create arborist directory structure
        arborist_dir = tmp_path / ".arborist"
        arborist_dir.mkdir()

        # Create spec directory with task file (markdown format)
        spec_dir = tmp_path / "specs" / "test-spec"
        spec_dir.mkdir(parents=True)
        task_file = spec_dir / "tasks.md"
        task_file.write_text("""# Tasks: Test Project

**Project**: Test project
**Total Tasks**: 2

## Phase 1: Setup

- [ ] T001 Create project directory
- [ ] T002 Add requirements file

**Checkpoint**: Ready

---

## Dependencies

```
T001 → T002
```
""")

        yield tmp_path
        os.chdir(original_cwd)

    @pytest.mark.skip(reason="Hooks injection not yet implemented in jj DAG builder")
    def test_dag_build_with_hooks_enabled(self, git_repo_with_spec_and_hooks):
        """Test that hooks are injected into a built DAG."""
        tmp_path = git_repo_with_spec_and_hooks

        # Create config with hooks
        config = {
            "hooks": {
                "enabled": True,
                "step_definitions": {
                    "lint_check": {
                        "type": "shell",
                        "command": "echo 'Linting...'"
                    }
                },
                "injections": {
                    "post_task": [
                        {"step": "lint_check", "tasks": ["*"]}
                    ]
                }
            }
        }
        (tmp_path / ".arborist" / "config.json").write_text(json.dumps(config))

        spec_dir = tmp_path / "specs" / "test-spec"
        runner = CliRunner()
        result = runner.invoke(main, [
            "spec", "dag-build",
            str(spec_dir),
            "--dry-run",
            "--no-ai"
        ])

        # Should succeed
        assert result.exit_code == 0, f"Exit code {result.exit_code}: {result.output}"
        # The output should be YAML containing the hook step
        assert "hook_post_task_lint_check_T001" in result.output or "lint_check" in result.output.lower()

    def test_dag_build_hooks_disabled(self, git_repo_with_spec_and_hooks):
        """Test that hooks are not injected when disabled."""
        tmp_path = git_repo_with_spec_and_hooks

        # Create config with hooks disabled
        config = {
            "hooks": {
                "enabled": False,
                "step_definitions": {
                    "lint_check": {
                        "type": "shell",
                        "command": "echo 'Linting...'"
                    }
                },
                "injections": {
                    "post_task": [
                        {"step": "lint_check", "tasks": ["*"]}
                    ]
                }
            }
        }
        (tmp_path / ".arborist" / "config.json").write_text(json.dumps(config))

        spec_dir = tmp_path / "specs" / "test-spec"
        runner = CliRunner()
        result = runner.invoke(main, [
            "spec", "dag-build",
            str(spec_dir),
            "--dry-run",
            "--no-ai"
        ])

        # Should succeed
        assert result.exit_code == 0, f"Exit code {result.exit_code}: {result.output}"
        # The output should NOT contain the hook step
        assert "hook_post_task_lint_check" not in result.output


class TestHooksVariableSubstitution:
    """Test variable substitution in hooks."""

    @pytest.fixture
    def git_repo(self, tmp_path):
        """Create a minimal git repo for hooks testing."""
        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        subprocess.run(["git", "init"], capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], capture_output=True)
        (tmp_path / "README.md").write_text("# Test\n")
        subprocess.run(["git", "add", "."], capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], capture_output=True, check=True)
        arborist_dir = tmp_path / ".arborist"
        arborist_dir.mkdir()
        yield tmp_path
        os.chdir(original_cwd)

    def test_shell_command_with_variables(self, git_repo):
        """Test that variables are substituted in shell commands."""
        runner = CliRunner()
        result = runner.invoke(main, [
            "hooks", "run",
            "--type", "shell",
            "--command", "echo 'Task: {{task_id}}'",
            "--task", "T001"
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        # Variable should be substituted
        assert "T001" in data["stdout"]

    def test_shell_command_without_task(self, git_repo):
        """Test shell command without task context still works."""
        runner = CliRunner()
        result = runner.invoke(main, [
            "hooks", "run",
            "--type", "shell",
            "--command", "echo 'No task context'"
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "No task context" in data["stdout"]


class TestHooksConfigIntegration:
    """Test hooks configuration loading and validation."""

    def test_hooks_config_from_file(self, tmp_path, monkeypatch):
        """Test loading hooks config from a real file."""
        arborist_dir = tmp_path / ".arborist"
        arborist_dir.mkdir()

        # Create a comprehensive hooks config
        config = {
            "hooks": {
                "enabled": True,
                "prompts_dir": "prompts",
                "step_definitions": {
                    "code_review": {
                        "type": "llm_eval",
                        "prompt": "Review this code for quality"
                    },
                    "run_tests": {
                        "type": "shell",
                        "command": "npm test"
                    },
                    "coverage_check": {
                        "type": "quality_check",
                        "command": "npm run coverage",
                        "min_score": 0.80
                    }
                },
                "injections": {
                    "pre_task": [
                        {"step": "run_tests", "tasks": ["*"]}
                    ],
                    "post_task": [
                        {"step": "code_review", "tasks": ["T001", "T002"]},
                        {"step": "coverage_check", "tasks": ["*"]}
                    ]
                }
            }
        }
        (arborist_dir / "config.json").write_text(json.dumps(config))

        monkeypatch.chdir(tmp_path)
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)

        # Validate using CLI
        runner = CliRunner()
        result = runner.invoke(main, ["hooks", "validate"])

        assert result.exit_code == 0
        assert "✓" in result.output

    def test_hooks_config_with_invalid_step_reference(self, tmp_path, monkeypatch):
        """Test that invalid step references are caught during validation."""
        arborist_dir = tmp_path / ".arborist"
        arborist_dir.mkdir()

        # Create config with invalid step reference
        config = {
            "hooks": {
                "enabled": True,
                "step_definitions": {
                    "lint_check": {
                        "type": "shell",
                        "command": "npm run lint"
                    }
                },
                "injections": {
                    "post_task": [
                        {"step": "nonexistent_step", "tasks": ["*"]}
                    ]
                }
            }
        }
        (arborist_dir / "config.json").write_text(json.dumps(config))

        monkeypatch.chdir(tmp_path)
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)

        # Validate using CLI - should fail or warn
        runner = CliRunner()
        result = runner.invoke(main, ["hooks", "validate"])

        # Validation should indicate an issue
        assert result.exit_code != 0 or "nonexistent" in result.output.lower()


class TestHooksPromptLoading:
    """Test prompt loading from files."""

    def test_prompt_file_loading(self, tmp_path, monkeypatch):
        """Test that prompts can be loaded from files."""
        arborist_dir = tmp_path / ".arborist"
        arborist_dir.mkdir()

        # Create prompts directory
        prompts_dir = arborist_dir / "prompts"
        prompts_dir.mkdir()

        # Create a prompt file
        prompt_content = """Review the following code changes:

Task: {{task_id}}
Branch: {{branch_name}}

Please analyze:
1. Code quality
2. Potential bugs
3. Style consistency

Provide a score from 0-100 and a brief summary.
"""
        (prompts_dir / "code_review.md").write_text(prompt_content)

        # Create config referencing the prompt file
        config = {
            "hooks": {
                "enabled": True,
                "step_definitions": {
                    "code_review": {
                        "type": "llm_eval",
                        "prompt_file": "code_review.md"
                    }
                },
                "injections": {
                    "post_task": [
                        {"step": "code_review", "tasks": ["*"]}
                    ]
                }
            }
        }
        (arborist_dir / "config.json").write_text(json.dumps(config))

        monkeypatch.chdir(tmp_path)
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)

        # Validate - prompt file should be found
        runner = CliRunner()
        result = runner.invoke(main, ["hooks", "validate"])

        assert result.exit_code == 0
        assert "✓" in result.output


class TestHooksTaskFiltering:
    """Test task filtering with patterns."""

    def test_glob_pattern_matching(self):
        """Test that glob patterns work for task filtering."""
        from agent_arborist.hooks.injector import HookInjector, InjectorConfig
        from agent_arborist.config import HooksConfig, HookInjection, StepDefinition

        hooks_config = HooksConfig(
            enabled=True,
            step_definitions={
                "test": StepDefinition(type="shell", command="echo test")
            },
            injections={
                "post_task": [
                    HookInjection(step="test", tasks=["T00*"])
                ]
            }
        )

        config = InjectorConfig(
            hooks_config=hooks_config,
            spec_id="test-spec",
            arborist_home=Path("/tmp")
        )

        injector = HookInjector(config)

        # Test pattern matching
        injection = hooks_config.injections["post_task"][0]
        assert injector._task_matches("T001", injection) is True
        assert injector._task_matches("T002", injection) is True
        assert injector._task_matches("T100", injection) is False

    def test_exclude_pattern(self):
        """Test that exclude patterns work."""
        from agent_arborist.hooks.injector import HookInjector, InjectorConfig
        from agent_arborist.config import HooksConfig, HookInjection, StepDefinition

        hooks_config = HooksConfig(
            enabled=True,
            step_definitions={
                "test": StepDefinition(type="shell", command="echo test")
            },
            injections={
                "post_task": [
                    HookInjection(step="test", tasks=["*"], tasks_exclude=["T002"])
                ]
            }
        )

        config = InjectorConfig(
            hooks_config=hooks_config,
            spec_id="test-spec",
            arborist_home=Path("/tmp")
        )

        injector = HookInjector(config)

        # Test exclude
        injection = hooks_config.injections["post_task"][0]
        assert injector._task_matches("T001", injection) is True
        assert injector._task_matches("T002", injection) is False
        assert injector._task_matches("T003", injection) is True


class TestHooksE2EWorkflow:
    """End-to-end test of the hooks workflow."""

    @pytest.fixture
    def git_repo_for_workflow(self, tmp_path):
        """Create a temp git repo for E2E workflow testing."""
        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        subprocess.run(["git", "init"], capture_output=True, check=True)
        readme = tmp_path / "README.md"
        readme.write_text("# Test\n")
        subprocess.run(["git", "add", "."], capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            capture_output=True,
            check=True,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "Test",
                "GIT_AUTHOR_EMAIL": "test@test.com",
                "GIT_COMMITTER_NAME": "Test",
                "GIT_COMMITTER_EMAIL": "test@test.com",
            },
        )

        # Setup
        arborist_dir = tmp_path / ".arborist"
        arborist_dir.mkdir()
        dagu_dir = arborist_dir / "dagu" / "dags"
        dagu_dir.mkdir(parents=True)

        # Create hooks config with shell step
        config = {
            "hooks": {
                "enabled": True,
                "step_definitions": {
                    "log_task": {
                        "type": "shell",
                        "command": "echo 'Processing task {{task_id}}'"
                    }
                },
                "injections": {
                    "pre_task": [
                        {"step": "log_task", "tasks": ["*"]}
                    ]
                }
            }
        }
        (arborist_dir / "config.json").write_text(json.dumps(config))

        # Create spec directory with markdown task file
        spec_dir = tmp_path / "specs" / "workflow-test"
        spec_dir.mkdir(parents=True)
        task_file = spec_dir / "tasks.md"
        task_file.write_text("""# Tasks: Workflow Test

**Project**: Workflow test
**Total Tasks**: 2

## Phase 1: Tasks

- [ ] T001 First Task
- [ ] T002 Second Task

**Checkpoint**: Ready

---

## Dependencies

```
T001 → T002
```
""")

        yield tmp_path
        os.chdir(original_cwd)

    def test_complete_hooks_workflow(self, git_repo_for_workflow):
        """Test complete workflow: config -> build -> run hook."""
        tmp_path = git_repo_for_workflow
        spec_dir = tmp_path / "specs" / "workflow-test"

        runner = CliRunner()

        # Step 1: Validate hooks config
        result = runner.invoke(main, ["hooks", "validate"])
        assert result.exit_code == 0
        assert "✓" in result.output

        # Step 2: List hooks
        result = runner.invoke(main, ["hooks", "list"])
        assert result.exit_code == 0
        assert "log_task" in result.output
        assert "pre_task" in result.output

        # Step 3: Build DAG with hooks
        result = runner.invoke(main, [
            "spec", "dag-build",
            str(spec_dir),
            "--dry-run",
            "--no-ai"
        ])
        assert result.exit_code == 0, f"Exit code {result.exit_code}: {result.output}"

        # Step 4: Run hook step directly
        result = runner.invoke(main, [
            "hooks", "run",
            "--type", "shell",
            "--command", "echo 'Processing task T001'",
            "--task", "T001"
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["success"] is True
        assert "Processing task T001" in data["stdout"]

    def test_hooks_with_quality_gate(self, tmp_path, monkeypatch):
        """Test hooks as quality gates that can fail the build."""
        arborist_dir = tmp_path / ".arborist"
        arborist_dir.mkdir()

        # Create config with quality check
        config = {
            "hooks": {
                "enabled": True,
                "step_definitions": {
                    "quality_gate": {
                        "type": "quality_check",
                        "command": "echo '75%'",
                        "min_score": 0.80,
                        "fail_on_threshold": True
                    }
                },
                "injections": {
                    "post_task": [
                        {"step": "quality_gate", "tasks": ["*"]}
                    ]
                }
            }
        }
        (arborist_dir / "config.json").write_text(json.dumps(config))

        monkeypatch.chdir(tmp_path)
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)

        runner = CliRunner()

        # Run quality check - should fail (75% < 80%)
        result = runner.invoke(main, [
            "hooks", "run",
            "--type", "quality_check",
            "--command", "echo '75%'",
            "--min-score", "0.80"
        ])

        assert result.exit_code == 1  # Should fail
        data = json.loads(result.output)
        assert data["success"] is False
        assert data["score"] == 0.75
        assert data["passed"] is False
