"""Tests for CLI commands."""

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from agent_arborist.cli import main
from agent_arborist.checks import DependencyStatus
from agent_arborist.home import ARBORIST_DIR_NAME, DAGU_DIR_NAME, DAGU_HOME_ENV_VAR


class TestVersionCommand:
    def test_version_output(self):
        runner = CliRunner()
        result = runner.invoke(main, ["version"])
        assert result.exit_code == 0
        assert "agent-arborist" in result.output
        assert "0.1.0" in result.output

    @patch("agent_arborist.cli.check_runtimes")
    @patch("agent_arborist.cli.check_dagu")
    def test_version_with_check(self, mock_dagu, mock_runtimes):
        mock_dagu.return_value = DependencyStatus(
            name="dagu",
            installed=True,
            version="1.30.3",
            path="/usr/bin/dagu",
            min_version="1.30.3",
        )
        mock_runtimes.return_value = [
            DependencyStatus(name="claude", installed=True, version="1.0.0", path="/usr/bin/claude"),
            DependencyStatus(name="opencode", installed=False),
            DependencyStatus(name="gemini", installed=False),
        ]

        runner = CliRunner()
        result = runner.invoke(main, ["version", "--check"])
        assert result.exit_code == 0
        assert "agent-arborist" in result.output
        assert "dagu" in result.output


class TestDoctorCommand:
    def test_doctor_group_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["doctor", "--help"])
        assert result.exit_code == 0
        assert "check-runner" in result.output

    @patch("agent_arborist.cli.check_runtimes")
    @patch("agent_arborist.cli.check_dagu")
    def test_doctor_all_ok(self, mock_dagu, mock_runtimes):
        mock_dagu.return_value = DependencyStatus(
            name="dagu",
            installed=True,
            version="1.30.3",
            path="/usr/bin/dagu",
            min_version="1.30.3",
        )
        mock_runtimes.return_value = [
            DependencyStatus(name="claude", installed=True, version="1.0.0", path="/usr/bin/claude"),
            DependencyStatus(name="opencode", installed=False),
            DependencyStatus(name="gemini", installed=False),
        ]

        runner = CliRunner()
        result = runner.invoke(main, ["doctor"])
        assert result.exit_code == 0
        assert "All dependencies OK" in result.output

    @patch("agent_arborist.cli.check_runtimes")
    @patch("agent_arborist.cli.check_dagu")
    def test_doctor_dagu_missing(self, mock_dagu, mock_runtimes):
        mock_dagu.return_value = DependencyStatus(
            name="dagu",
            installed=False,
            min_version="1.30.3",
            error="dagu not found in PATH",
        )
        mock_runtimes.return_value = [
            DependencyStatus(name="claude", installed=True, version="1.0.0", path="/usr/bin/claude"),
            DependencyStatus(name="opencode", installed=False),
            DependencyStatus(name="gemini", installed=False),
        ]

        runner = CliRunner()
        result = runner.invoke(main, ["doctor"])
        assert result.exit_code == 1
        assert "missing or outdated" in result.output

    @patch("agent_arborist.cli.check_runtimes")
    @patch("agent_arborist.cli.check_dagu")
    def test_doctor_no_runtimes(self, mock_dagu, mock_runtimes):
        mock_dagu.return_value = DependencyStatus(
            name="dagu",
            installed=True,
            version="1.30.3",
            path="/usr/bin/dagu",
            min_version="1.30.3",
        )
        mock_runtimes.return_value = [
            DependencyStatus(name="claude", installed=False),
            DependencyStatus(name="opencode", installed=False),
            DependencyStatus(name="gemini", installed=False),
        ]

        runner = CliRunner()
        result = runner.invoke(main, ["doctor"])
        assert result.exit_code == 1
        assert "At least one runtime" in result.output


class TestSpecBranchCommands:
    """Tests for spec branch commands."""

    def test_spec_branch_create_all_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["spec", "branch-create-all", "--help"])
        assert result.exit_code == 0
        assert "manifest" in result.output.lower()

    def test_spec_branch_create_all_requires_manifest(self):
        """branch-create-all requires ARBORIST_MANIFEST env var."""
        runner = CliRunner()
        result = runner.invoke(main, ["spec", "branch-create-all"])
        assert result.exit_code != 0
        assert "ARBORIST_MANIFEST environment variable not set" in result.output

    def test_spec_branch_cleanup_all_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["spec", "branch-cleanup-all", "--help"])
        assert result.exit_code == 0
        assert "--force" in result.output

    def test_spec_branch_cleanup_all_requires_manifest(self):
        """branch-cleanup-all requires ARBORIST_MANIFEST env var."""
        runner = CliRunner()
        result = runner.invoke(main, ["spec", "branch-cleanup-all"])
        assert result.exit_code != 0
        assert "ARBORIST_MANIFEST environment variable not set" in result.output


class TestTaskCommands:
    def test_task_group_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["task", "--help"])
        assert result.exit_code == 0
        assert "sync" in result.output
        assert "run" in result.output
        assert "test" in result.output
        assert "merge" in result.output
        assert "cleanup" in result.output
        assert "status" in result.output

    def test_task_sync_requires_manifest(self):
        """sync requires ARBORIST_MANIFEST env var."""
        runner = CliRunner()
        result = runner.invoke(main, ["task", "sync", "T001"])
        assert result.exit_code != 0
        assert "ARBORIST_MANIFEST environment variable not set" in result.output

    def test_task_run_requires_manifest(self):
        """run requires ARBORIST_MANIFEST env var."""
        runner = CliRunner()
        result = runner.invoke(main, ["task", "run", "T001"])
        assert result.exit_code != 0
        assert "ARBORIST_MANIFEST environment variable not set" in result.output

    def test_task_status_requires_spec(self):
        """status requires a spec to be available (via context or --spec)."""
        runner = CliRunner()
        result = runner.invoke(main, ["task", "status"])
        assert result.exit_code != 0
        assert "No spec available" in result.output

    def test_task_test_requires_manifest(self):
        """test requires ARBORIST_MANIFEST env var."""
        runner = CliRunner()
        result = runner.invoke(main, ["task", "test", "T001"])
        assert result.exit_code != 0
        assert "ARBORIST_MANIFEST environment variable not set" in result.output

    def test_task_merge_requires_manifest(self):
        """merge requires ARBORIST_MANIFEST env var."""
        runner = CliRunner()
        result = runner.invoke(main, ["task", "merge", "T001"])
        assert result.exit_code != 0
        assert "ARBORIST_MANIFEST environment variable not set" in result.output

    def test_task_cleanup_requires_manifest(self):
        """cleanup requires ARBORIST_MANIFEST env var."""
        runner = CliRunner()
        result = runner.invoke(main, ["task", "cleanup", "T001"])
        assert result.exit_code != 0
        assert "ARBORIST_MANIFEST environment variable not set" in result.output


class TestSpecCommands:
    def test_spec_group_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["spec", "--help"])
        assert result.exit_code == 0
        assert "whoami" in result.output

    @patch("agent_arborist.cli.detect_spec_from_git")
    def test_spec_whoami_found(self, mock_detect):
        from agent_arborist.spec import SpecInfo

        mock_detect.return_value = SpecInfo(
            spec_id="002",
            name="my-feature",
            source="git",
            branch="002-my-feature",
        )

        runner = CliRunner()
        result = runner.invoke(main, ["spec", "whoami"])
        assert result.exit_code == 0
        assert "002-my-feature" in result.output
        assert "git" in result.output

    @patch("agent_arborist.cli.detect_spec_from_git")
    def test_spec_whoami_not_found(self, mock_detect):
        from agent_arborist.spec import SpecInfo

        mock_detect.return_value = SpecInfo(
            error="Branch 'main' does not contain spec pattern",
            source="git",
            branch="main",
        )

        runner = CliRunner()
        result = runner.invoke(main, ["spec", "whoami"])
        assert result.exit_code == 0
        assert "Not detected" in result.output
        assert "--spec" in result.output or "-s" in result.output


class TestCheckRunnerCommand:
    @patch("agent_arborist.cli.get_runner")
    def test_check_runner_success(self, mock_get_runner):
        from agent_arborist.runner import RunResult

        mock_runner = mock_get_runner.return_value
        mock_runner.is_available.return_value = True
        mock_runner.command = "claude"
        mock_runner.run.return_value = RunResult(
            success=True,
            output="Why did the programmer quit? Because he didn't get arrays!",
            exit_code=0,
        )

        runner = CliRunner()
        result = runner.invoke(main, ["doctor", "check-runner"])
        assert result.exit_code == 0
        assert "OK" in result.output
        assert "arrays" in result.output

    @patch("agent_arborist.cli.get_runner")
    def test_check_runner_not_found(self, mock_get_runner):
        mock_runner = mock_get_runner.return_value
        mock_runner.is_available.return_value = False

        runner = CliRunner()
        result = runner.invoke(main, ["doctor", "check-runner"])
        assert result.exit_code == 1
        assert "FAIL" in result.output
        assert "not found" in result.output

    @patch("agent_arborist.cli.get_runner")
    def test_check_runner_execution_failure(self, mock_get_runner):
        from agent_arborist.runner import RunResult

        mock_runner = mock_get_runner.return_value
        mock_runner.is_available.return_value = True
        mock_runner.command = "claude"
        mock_runner.run.return_value = RunResult(
            success=False,
            output="",
            error="Timeout after 30 seconds",
            exit_code=-1,
        )

        runner = CliRunner()
        result = runner.invoke(main, ["doctor", "check-runner"])
        assert result.exit_code != 0
        assert "FAIL" in result.output
        assert "Timeout" in result.output

    @patch("agent_arborist.cli.get_runner")
    def test_check_runner_with_runner_option(self, mock_get_runner):
        from agent_arborist.runner import RunResult

        mock_runner = mock_get_runner.return_value
        mock_runner.is_available.return_value = True
        mock_runner.command = "opencode"
        mock_runner.run.return_value = RunResult(
            success=True,
            output="A joke from opencode",
            exit_code=0,
        )

        runner = CliRunner()
        result = runner.invoke(main, ["doctor", "check-runner", "--runner", "opencode"])
        assert result.exit_code == 0
        mock_get_runner.assert_called_with("opencode")

    def test_check_runner_invalid_runner(self):
        runner = CliRunner()
        result = runner.invoke(main, ["doctor", "check-runner", "--runner", "invalid"])
        assert result.exit_code != 0


class TestCheckDaguCommand:
    @patch("shutil.which")
    def test_check_dagu_not_found(self, mock_which):
        mock_which.return_value = None

        runner = CliRunner()
        result = runner.invoke(main, ["doctor", "check-dagu"])
        assert result.exit_code == 1
        assert "not found" in result.output

    @patch("subprocess.run")
    @patch("shutil.which")
    def test_check_dagu_version_fails(self, mock_which, mock_run):
        mock_which.return_value = "/usr/bin/dagu"
        mock_run.return_value = subprocess.CompletedProcess(
            args=["dagu", "version"],
            returncode=1,
            stdout="",
            stderr="error",
        )

        runner = CliRunner()
        result = runner.invoke(main, ["doctor", "check-dagu"])
        assert result.exit_code == 1
        assert "Could not get dagu version" in result.output

    @patch("subprocess.run")
    @patch("shutil.which")
    def test_check_dagu_success(self, mock_which, mock_run):
        mock_which.return_value = "/usr/bin/dagu"

        def run_side_effect(args, **kwargs):
            if "version" in args:
                return subprocess.CompletedProcess(
                    args=args, returncode=0, stdout="", stderr="1.30.3"
                )
            elif "dry" in args:
                return subprocess.CompletedProcess(
                    args=args, returncode=0, stdout="Succeeded", stderr=""
                )
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

        mock_run.side_effect = run_side_effect

        runner = CliRunner()
        result = runner.invoke(main, ["doctor", "check-dagu"])
        assert result.exit_code == 0
        assert "1.30.3" in result.output
        assert "All dagu checks passed" in result.output

    @patch("subprocess.run")
    @patch("shutil.which")
    def test_check_dagu_dry_run_fails(self, mock_which, mock_run):
        mock_which.return_value = "/usr/bin/dagu"

        def run_side_effect(args, **kwargs):
            if "version" in args:
                return subprocess.CompletedProcess(
                    args=args, returncode=0, stdout="", stderr="1.30.3"
                )
            elif "dry" in args:
                return subprocess.CompletedProcess(
                    args=args, returncode=1, stdout="", stderr="DAG execution failed"
                )
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

        mock_run.side_effect = run_side_effect

        runner = CliRunner()
        result = runner.invoke(main, ["doctor", "check-dagu"])
        assert result.exit_code == 1
        assert "dry run failed" in result.output


@pytest.fixture
def git_repo(tmp_path):
    """Create a temporary git repository."""
    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    subprocess.run(["git", "init"], capture_output=True, check=True)
    readme = tmp_path / "README.md"
    readme.write_text("# Test\n")
    subprocess.run(["git", "add", "."], capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
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
    yield tmp_path
    os.chdir(original_cwd)


@pytest.fixture
def non_git_dir(tmp_path):
    """Create a temporary directory that is not a git repo."""
    original_cwd = os.getcwd()
    # Create a subdirectory to ensure we're not in a git repo
    test_dir = tmp_path / "not_git"
    test_dir.mkdir()
    os.chdir(test_dir)
    yield test_dir
    os.chdir(original_cwd)


class TestInitCommand:
    def test_init_creates_arborist_directory(self, git_repo):
        runner = CliRunner()
        result = runner.invoke(main, ["init"])
        assert result.exit_code == 0
        assert "Initialized" in result.output

        arborist_dir = git_repo / ARBORIST_DIR_NAME
        assert arborist_dir.is_dir()

    def test_init_adds_to_gitignore(self, git_repo):
        runner = CliRunner()
        result = runner.invoke(main, ["init"])
        assert result.exit_code == 0

        gitignore = git_repo / ".gitignore"
        assert gitignore.exists()
        content = gitignore.read_text()
        assert f"{ARBORIST_DIR_NAME}/" in content

    def test_init_fails_outside_git_repo(self, non_git_dir):
        runner = CliRunner()
        result = runner.invoke(main, ["init"])
        assert result.exit_code == 1
        assert "git repository" in result.output.lower()

    def test_init_fails_if_already_initialized(self, git_repo):
        # First init
        runner = CliRunner()
        result = runner.invoke(main, ["init"])
        assert result.exit_code == 0

        # Second init should fail
        result = runner.invoke(main, ["init"])
        assert result.exit_code == 1
        assert "already initialized" in result.output.lower()

    def test_init_shows_path_in_output(self, git_repo):
        runner = CliRunner()
        result = runner.invoke(main, ["init"])
        assert result.exit_code == 0
        assert ARBORIST_DIR_NAME in result.output

    def test_init_creates_dagu_subdirectory(self, git_repo):
        runner = CliRunner()
        result = runner.invoke(main, ["init"])
        assert result.exit_code == 0

        dagu_dir = git_repo / ARBORIST_DIR_NAME / DAGU_DIR_NAME
        assert dagu_dir.is_dir()

    def test_init_creates_dagu_dags_subdirectory(self, git_repo):
        runner = CliRunner()
        result = runner.invoke(main, ["init"])
        assert result.exit_code == 0

        dags_dir = git_repo / ARBORIST_DIR_NAME / DAGU_DIR_NAME / "dags"
        assert dags_dir.is_dir()


class TestDaguHomeEnvVar:
    def test_dagu_home_set_when_initialized(self, git_repo):
        # First initialize
        runner = CliRunner()
        result = runner.invoke(main, ["init"])
        assert result.exit_code == 0

        # Run any command and check env var is set
        # We use version as a simple command
        result = runner.invoke(main, ["version"])
        assert result.exit_code == 0

        # Check the env var was set
        expected_dagu_home = str(git_repo / ARBORIST_DIR_NAME / DAGU_DIR_NAME)
        assert os.environ.get(DAGU_HOME_ENV_VAR) == expected_dagu_home

    def test_dagu_home_not_set_when_not_initialized(self, git_repo, monkeypatch):
        # Ensure env var is not set
        monkeypatch.delenv(DAGU_HOME_ENV_VAR, raising=False)

        runner = CliRunner()
        result = runner.invoke(main, ["version"])
        assert result.exit_code == 0

        # DAGU_HOME should not be set since we didn't init
        assert os.environ.get(DAGU_HOME_ENV_VAR) is None


# -----------------------------------------------------------------------------
# Spec DAG commands
# -----------------------------------------------------------------------------


class TestSpecDagCommands:
    def test_spec_group_has_dag_commands(self):
        runner = CliRunner()
        result = runner.invoke(main, ["spec", "--help"])
        assert result.exit_code == 0
        assert "dag-build" in result.output
        assert "dag-show" in result.output

    def test_spec_dag_build_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["spec", "dag-build", "--help"])
        assert result.exit_code == 0
        assert "DIRECTORY" in result.output
        assert "--dry-run" in result.output
        assert "--runner" in result.output


class TestDagBuild:
    @pytest.fixture
    def git_repo_with_spec(self, tmp_path):
        """Create a temp git repo with a spec directory."""
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

        # Create spec directory with task file
        spec_dir = tmp_path / "specs" / "test-spec"
        spec_dir.mkdir(parents=True)
        task_file = spec_dir / "tasks.md"
        task_file.write_text("""# Tasks: Test Project

**Project**: Test project
**Total Tasks**: 3

## Phase 1: Setup

- [ ] T001 Create project directory
- [ ] T002 Add requirements file
- [ ] T003 Create main module

**Checkpoint**: Ready

---

## Dependencies

```
T001 → T002 → T003
```
""")

        yield tmp_path
        os.chdir(original_cwd)

    def test_dag_build_dry_run(self, git_repo_with_spec):
        runner = CliRunner()
        spec_dir = git_repo_with_spec / "specs" / "test-spec"

        result = runner.invoke(main, ["spec", "dag-build", str(spec_dir), "--dry-run", "--no-ai"])

        assert result.exit_code == 0
        # Name is derived from directory name (with dashes converted to underscores)
        assert "name: test_spec" in result.output
        assert "T001" in result.output
        assert "T002" in result.output
        assert "T003" in result.output

    def test_dag_build_with_output(self, git_repo_with_spec, tmp_path):
        runner = CliRunner()
        spec_dir = git_repo_with_spec / "specs" / "test-spec"
        output_file = tmp_path / "output.yaml"

        result = runner.invoke(
            main, ["spec", "dag-build", str(spec_dir), "-o", str(output_file), "--no-ai"]
        )

        assert result.exit_code == 0
        assert output_file.exists()
        content = output_file.read_text()
        assert "T001" in content
        assert "depends:" in content

    def test_dag_build_to_dagu_home(self, git_repo_with_spec, monkeypatch):
        # Initialize arborist first
        runner = CliRunner()
        result = runner.invoke(main, ["init"])
        assert result.exit_code == 0

        spec_dir = git_repo_with_spec / "specs" / "test-spec"

        result = runner.invoke(main, ["spec", "dag-build", str(spec_dir), "--no-ai"])

        assert result.exit_code == 0
        assert "DAG written to:" in result.output

        # Verify file was created in dagu home
        dagu_home = git_repo_with_spec / ".arborist" / "dagu" / "dags"
        dag_files = list(dagu_home.glob("*.yaml"))
        assert len(dag_files) == 1

    def test_dag_build_no_directory_no_spec(self, non_git_dir):
        runner = CliRunner()
        result = runner.invoke(main, ["spec", "dag-build"])

        assert result.exit_code == 1
        assert "No spec" in result.output or "Error" in result.output

    def test_dag_build_nonexistent_directory(self, git_repo):
        runner = CliRunner()
        result = runner.invoke(main, ["spec", "dag-build", "/nonexistent/path"])

        # Click validates path exists
        assert result.exit_code != 0

    def test_dag_build_step_names_under_40_chars(self, git_repo_with_spec):
        """Ensure all step names are under 40 chars for dagu compatibility."""
        runner = CliRunner()
        spec_dir = git_repo_with_spec / "specs" / "test-spec"

        result = runner.invoke(main, ["spec", "dag-build", str(spec_dir), "--dry-run", "--no-ai"])

        assert result.exit_code == 0

        # Parse the YAML output and check step names
        import yaml
        # Find the YAML content (skip the status messages)
        lines = result.output.split("\n")
        yaml_start = next(i for i, line in enumerate(lines) if line.startswith("name:"))
        yaml_content = "\n".join(lines[yaml_start:])
        dag = yaml.safe_load(yaml_content)

        for step in dag["steps"]:
            assert len(step["name"]) <= 40, f"Step name too long: {step['name']}"

    def test_dag_build_with_show(self, git_repo_with_spec, tmp_path):
        """Test --show flag displays YAML after writing."""
        runner = CliRunner()
        spec_dir = git_repo_with_spec / "specs" / "test-spec"
        output_file = tmp_path / "output.yaml"

        result = runner.invoke(
            main, ["spec", "dag-build", str(spec_dir), "-o", str(output_file), "--show", "--no-ai"]
        )

        assert result.exit_code == 0
        assert "DAG written to:" in result.output
        # YAML content should appear after the write message
        assert "steps:" in result.output
        assert "T001" in result.output


class TestDagShow:
    @pytest.fixture
    def git_repo_with_dag(self, tmp_path):
        """Create a temp git repo with a built DAG."""
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

        # Initialize arborist
        cli_runner = CliRunner()
        cli_runner.invoke(main, ["init"])

        # Create a DAG file directly
        dags_dir = tmp_path / ".arborist" / "dagu" / "dags"
        dag_file = dags_dir / "test-dag.yaml"
        dag_file.write_text("""name: test_dag
description: Test DAG
steps:
  - name: step1
    command: echo step1
  - name: step2
    command: echo step2
    depends: [step1]
  - name: step3
    command: echo step3
    depends: [step1]
  - name: step4
    command: echo step4
    depends: [step2, step3]
""")

        yield tmp_path
        os.chdir(original_cwd)

    def test_dag_show_summary(self, git_repo_with_dag):
        runner = CliRunner()
        result = runner.invoke(main, ["spec", "dag-show", "test-dag"])

        assert result.exit_code == 0
        assert "test_dag" in result.output
        assert "Steps:" in result.output
        assert "step1" in result.output
        assert "step4" in result.output

    def test_dag_show_deps(self, git_repo_with_dag):
        runner = CliRunner()
        result = runner.invoke(main, ["spec", "dag-show", "test-dag", "--deps"])

        assert result.exit_code == 0
        assert "step2" in result.output
        assert "← step1" in result.output

    def test_dag_show_blocking(self, git_repo_with_dag):
        runner = CliRunner()
        result = runner.invoke(main, ["spec", "dag-show", "test-dag", "--blocking"])

        assert result.exit_code == 0
        assert "step1" in result.output
        assert "→ step2" in result.output
        assert "→ step3" in result.output

    def test_dag_show_yaml(self, git_repo_with_dag):
        runner = CliRunner()
        result = runner.invoke(main, ["spec", "dag-show", "test-dag", "--yaml"])

        assert result.exit_code == 0
        assert "name: test_dag" in result.output
        assert "step2" in result.output
        assert "depends:" in result.output

    def test_dag_show_not_found(self, git_repo_with_dag):
        runner = CliRunner()
        result = runner.invoke(main, ["spec", "dag-show", "nonexistent"])

        assert result.exit_code == 1
        assert "not found" in result.output
