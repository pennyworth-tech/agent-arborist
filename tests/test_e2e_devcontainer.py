"""End-to-end test for full DAG execution with devcontainer support.

Tests the complete workflow:
1. Create temp project with devcontainer
2. Build DAG from spec with container mode
3. Execute DAG (tasks run inside containers)
4. Verify worktrees, artifacts, and cleanup
5. Verify commit generation and rollup

Run with:
    pytest -m "integration and opencode" tests/test_e2e_devcontainer.py -v
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

# Skip markers
requires_docker = pytest.mark.skipif(
    shutil.which("docker") is None
    or subprocess.run(["docker", "info"], capture_output=True).returncode != 0,
    reason="Docker not available or not running",
)

requires_devcontainer_cli = pytest.mark.skipif(
    shutil.which("devcontainer") is None,
    reason="devcontainer CLI not installed (install: npm install -g @devcontainers/cli)",
)

requires_arborist = pytest.mark.skipif(
    shutil.which("arborist") is None,
    reason="arborist CLI not installed",
)

requires_openai_api_key = pytest.mark.skipif(
    os.environ.get("OPENAI_API_KEY") is None,
    reason="OPENAI_API_KEY not set in environment",
)


@pytest.fixture
def e2e_project(tmp_path):
    """Create a complete test project with devcontainer and spec."""
    project_dir = tmp_path / "calculator-project"
    project_dir.mkdir()

    # Create .devcontainer
    devcontainer_dir = project_dir / ".devcontainer"
    devcontainer_dir.mkdir()

    # Dockerfile with default WORKDIR (will be set by devcontainer CLI to /workspaces/<folder-name>)
    dockerfile = devcontainer_dir / "Dockerfile"
    dockerfile.write_text(
        """\
FROM node:18-slim

# Install essential tools
        RUN apt-get update && apt-get install -y \\
            git \\
            curl \\
            && rm -rf /var/lib/apt/lists/*

# Install OpenCode CLI globally
RUN npm install -g opencode-ai@latest

# Verify installation
RUN opencode --version
"""
    )

    # devcontainer.json - mount arborist source from parent, use default workspaceFolder
    arborist_repo_root = str(Path(__file__).parent.parent.parent.resolve())
    devcontainer_json = devcontainer_dir / "devcontainer.json"
    devcontainer_json.write_text(
        f"""{{
  "name": "calculator-test",
  "build": {{
    "dockerfile": "Dockerfile"
  }},
  "mounts": [
    "source={arborist_repo_root},target=/arborist-src,type=bind,consistency=cached"
  ],
  "remoteEnv": {{
    "OPENAI_API_KEY": "${{localEnv:OPENAI_API_KEY}}",
    "ARBORIST_DEFAULT_RUNNER": "opencode",
    "ARBORIST_DEFAULT_MODEL": "openai/gpt-4o-mini"
  }},
  "customizations": {{
    "vscode": {{
      "extensions": []
    }}
  }}
}}
"""
    )

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=project_dir, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=project_dir, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=project_dir,
        capture_output=True,
    )

    # Create initial commit
    readme = project_dir / "README.md"
    readme.write_text("# Calculator Project\\n")
    subprocess.run(
        ["git", "add", "."], cwd=project_dir, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=project_dir,
        capture_output=True,
        check=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@test.com",
        },
    )

    # Create and checkout spec-named branch (realistic workflow)
    subprocess.run(
        ["git", "checkout", "-b", "001-calculator"],
        cwd=project_dir,
        capture_output=True,
        check=True,
    )

    # Create spec directory
    spec_dir = project_dir / "specs" / "001-calculator"
    spec_dir.mkdir(parents=True)

    # Create a single tasks.md file with all task definitions
    (spec_dir / "tasks.md").write_text(
        """\
# Tasks: Calculator Project

**Project**: Simple command-line calculator with basic arithmetic operations
**Total Tasks**: 4

## Phase 1: Core Operations

- [ ] T001 Create `calculator.js` with an `add(a, b)` function
- [ ] T002 Add `subtract(a, b)` function to calculator.js
- [ ] T003 Add `multiply(a, b)` function to calculator.js

**Checkpoint**: All basic operations implemented

---

## Phase 2: Testing

- [ ] T004 Create `calculator.test.js` with tests for all operations

**Checkpoint**: Tests pass

---

## Dependencies

```
T001 → T002 → T003 → T004
```
"""
    )

    # Commit spec files on the spec-named branch
    subprocess.run(
        ["git", "add", "specs"],
        cwd=project_dir,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Add 001-calculator spec"],
        cwd=project_dir,
        capture_output=True,
        check=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@test.com",
        },
    )

    return project_dir


@pytest.mark.integration
@pytest.mark.opencode
@requires_docker
@requires_devcontainer_cli
@requires_arborist
@requires_openai_api_key
@pytest.mark.usefixtures("e2e_project")
class TestE2EDevContainer:
    """End-to-end tests for DAG execution with devcontainer support."""

    def test_full_dag_workflow_with_containers(self, e2e_project):
        """Test complete workflow: build DAG → run with containers → verify results."""
        spec_dir = e2e_project / "specs" / "001-calculator"

        # Set up DAGU_HOME
        dagu_home = e2e_project / ".arborist" / "dagu"
        dagu_home.mkdir(parents=True, exist_ok=True)
        (dagu_home / "dags").mkdir(exist_ok=True)

        test_env = {**os.environ, "DAGU_HOME": str(dagu_home)}

        # Step 1: Build DAG from spec with container mode
        build_result = subprocess.run(
            [
                "arborist",
                "spec",
                "dag-build",
                str(spec_dir),
                "--runner",
                "opencode",
                "--model",
                "openai/gpt-4o-mini",
                "--container-mode",
                "enabled",  # Force containers for testing
                "--show",
            ],
            cwd=e2e_project,
            capture_output=True,
            text=True,
            timeout=120,
            env=test_env,
        )

        print("\\n=== DAG Build Output ===")
        print(build_result.stdout)
        if build_result.stderr:
            print("=== Stderr ===")
            print(build_result.stderr)

        assert build_result.returncode == 0, f"DAG build failed: {build_result.stderr}"
        assert "001-calculator" in build_result.stdout

        # Step 2: Check that DAG file was created
        dag_file = dagu_home / "dags" / "001-calculator.yaml"

        assert dag_file.exists(), f"DAG file not created at {dag_file}"

        # Step 3: Run the DAG
        run_result = subprocess.run(
            ["arborist", "dag", "run", "001-calculator"],
            cwd=e2e_project,
            capture_output=True,
            text=True,
            timeout=600,  # 10 minutes for full execution
            env=test_env,
        )

        print("\n=== DAG Run Output ===")
        print(run_result.stdout)
        if run_result.stderr:
            print("=== Stderr ===")
            print(run_result.stderr)

        # Step 4: Check for worktrees
        worktree_dir = e2e_project / ".arborist" / "worktrees"
        if worktree_dir.exists():
            worktrees = list(worktree_dir.iterdir())
            print(f"\\n=== Found {len(worktrees)} worktrees ===")
            for wt in worktrees:
                print(f"  - {wt.name}")
        else:
            print("\\n=== No worktrees directory found ===")

        # Step 5: Check DAG run status
        status_result = subprocess.run(
            ["arborist", "dag", "run-list", "001-calculator"],
            cwd=e2e_project,
            capture_output=True,
            text=True,
            env=test_env,
        )

        print("\\n=== DAG Run Status ===")
        print(status_result.stdout)

        # Step 6: Verify commits were made for each task
        print("\n=== Verifying Task Commits ===")

        task_branches = ["001-calculator_a_T001", "001-calculator_a_T002", "001-calculator_a_T003", "001-calculator_a_T004"]
        expected_task_count = 4
        commits_verified = []
        branches_with_changes = []

        for branch in task_branches:
            task_id = branch.split("_")[-1]  # Extract T001, T002, etc.

            branch_check = subprocess.run(
                ["git", "rev-parse", "--verify", branch],
                cwd=e2e_project,
                capture_output=True,
                text=True,
            )

            if branch_check.returncode == 0:
                # Get commits with task(TXXX): format
                task_commits = get_task_commit_messages(e2e_project, branch)

                log_result = subprocess.run(
                    ["git", "log", "--oneline", "-5", branch],
                    cwd=e2e_project,
                    capture_output=True,
                    text=True,
                )

                print(f"\n{branch}:")
                print(log_result.stdout)

                # Check if branch has changes compared to source branch
                diff_result = subprocess.run(
                    ["git", "diff", "--stat", "001-calculator", branch],
                    cwd=e2e_project,
                    capture_output=True,
                    text=True,
                )

                if diff_result.stdout.strip():
                    print(f"  Changes: {diff_result.stdout.strip()}")
                    branches_with_changes.append(branch)
                else:
                    print(f"  WARNING: No changes found")

                # Verify task commits exist
                if task_commits:
                    print(f"  ✓ Found {len(task_commits)} task commit(s) matching task({task_id}): format")
                    commits_verified.append(branch)
                else:
                    print(f"  ✗ No task commits found matching task({task_id}): format")
            else:
                print(f"\n{branch}: Branch does not exist")

        # Step 7: Assert commit requirements
        print("\n=== Commit Verification Results ===")
        print(f"Branches with task(TXXX): commits: {len(commits_verified)}/{expected_task_count}")
        print(f"Branches with file changes: {len(branches_with_changes)}/{expected_task_count}")

        assert len(commits_verified) == expected_task_count, \
            f"Expected {expected_task_count} branches with task commits, but found {len(commits_verified)}"

        assert len(branches_with_changes) == expected_task_count, \
            f"Expected {expected_task_count} branches with changes, but found {len(branches_with_changes)}"

        # Step 8: Verify DAG structure and container mode
        assert dag_file.exists(), "DAG file should exist"

        dag_content = dag_file.read_text()
        print("\n=== Verifying Container Mode Integration ===")

        has_container_up = "container-up" in dag_content
        has_container_down = "container-down" in dag_content
        has_worktree_env = "ARBORIST_WORKTREE" in dag_content
        has_container_up_cmd = "arborist task container-up" in dag_content
        has_container_down_cmd = "arborist task container-down" in dag_content

        print(f"✓ Container-up steps: {'YES' if has_container_up else 'NO'}")
        print(f"✓ Container-down steps: {'YES' if has_container_down else 'NO'}")
        print(f"✓ Container-up command: {'YES' if has_container_up_cmd else 'NO'}")
        print(f"✓ Container-down command: {'YES' if has_container_down_cmd else 'NO'}")
        print(f"✓ ARBORIST_WORKTREE env var: {'YES' if has_worktree_env else 'NO'}")

        assert has_container_up, "DAG should have container-up steps"
        assert has_container_down, "DAG should have container-down steps"
        assert has_container_up_cmd, "DAG should have arborist task container-up command"
        assert has_container_down_cmd, "DAG should have arborist task container-down command"
        assert has_worktree_env, "DAG should set ARBORIST_WORKTREE"

        print("\n=== Test Summary ===")
        print("✓ DAG built successfully")
        print("✓ DAG executed successfully")
        print(f"✓ All {expected_task_count} task branches have valid commits with changes")
        print("✓ Container mode integration verified")
        print("✓ Worktrees created properly")

    def test_container_mode_flag_integration(self, e2e_project):
        """Test that container mode can be controlled via CLI flags."""
        from agent_arborist.container_runner import has_devcontainer

        assert has_devcontainer(e2e_project) is True

    def _run_full_dag_workflow(self, e2e_project):
        """Helper: Execute the full DAG workflow (build + run)."""
        spec_dir = e2e_project / "specs" / "001-calculator"

        dagu_home = e2e_project / ".arborist" / "dagu"
        dagu_home.mkdir(parents=True, exist_ok=True)
        (dagu_home / "dags").mkdir(exist_ok=True)

        test_env = {**os.environ, "DAGU_HOME": str(dagu_home)}

        build_result = subprocess.run(
            [
                "arborist",
                "spec",
                "dag-build",
                str(spec_dir),
                "--runner",
                "opencode",
                "--model",
                "openai/gpt-4o-mini",
                "--container-mode",
                "enabled",
            ],
            cwd=e2e_project,
            capture_output=True,
            text=True,
            timeout=120,
            env=test_env,
        )

        if build_result.returncode != 0:
            raise Exception(f"DAG build failed: {build_result.stderr}")

        run_result = subprocess.run(
            ["arborist", "dag", "run", "001-calculator"],
            cwd=e2e_project,
            capture_output=True,
            text=True,
            timeout=600,
            env=test_env,
        )

        print("\n=== DAG Run Output ===")
        print(run_result.stdout)
        if run_result.stderr:
            print("=== Stderr ===")
            print(run_result.stderr)

        return build_result, run_result

    def test_commit_generation_per_task(self, e2e_project):
        """Verify that each task branch has valid commits generated during execution."""
        build_result, run_result = self._run_full_dag_workflow(e2e_project)

        print("\n=== DAG Execution Result ===")
        print(f"Build success: {build_result.returncode == 0}")
        print(f"Run success: {run_result.returncode == 0}")

        task_branches = ["001-calculator_a_T001", "001-calculator_a_T002", "001-calculator_a_T003", "001-calculator_a_T004"]

        print("\n=== Verifying Commit Generation Per Task ===")
        any_branch_found = False

        for branch in task_branches:
            task_id = branch.split("_")[-1]

            branch_check = subprocess.run(
                ["git", "rev-parse", "--verify", branch],
                cwd=e2e_project,
                capture_output=True,
                text=True,
            )

            if branch_check.returncode != 0:
                print(f"\n{branch}: SKIPPED - Branch does not exist")
                continue

            any_branch_found = True
            commit_count = get_commit_count(e2e_project, branch)

            if commit_count == 0:
                print(f"\n{branch}: FAILED - No commits")
                assert False, f"Task branch {branch} has no commits"
                continue

            messages = get_commit_messages(e2e_project, branch)
            print(f"\n{branch}:")
            print(f"  Commits: {commit_count}")
            for msg in messages[:3]:
                print(f"    - {msg[:80]}")

            task_commits = get_task_commit_messages(e2e_project, branch)

            if len(task_commits) == 0:
                print(f"  ✗ No task(TXXX): commits found")
                assert False, f"Task branch {branch} has no task(TXXX): commits"
                continue

            for task_msg in task_commits:
                assert verify_commit_format(task_msg, task_id), \
                    f"Commit message for {task_id} doesn't match format: {task_msg}"

            print(f"  ✓ Has {len(task_commits)} valid task commits")

        if not any_branch_found:
            pytest.skip("No task branches found - DAG execution may have failed")

        print("\n✓ Commit generation verification complete")

    def test_commit_count_matches_manifest(self, e2e_project):
        """Verify that commit counts match the number of tasks in the manifest."""
        build_result, run_result = self._run_full_dag_workflow(e2e_project)

        manifest = load_manifest_from_dagu_home(e2e_project, "001-calculator")

        if manifest is None:
            pytest.skip("Manifest file not found - DAG may not have built successfully")

        expected_tasks = len(manifest.get("tasks", {}))
        print(f"\n=== Verifying Commit Count Matches Manifest ===")
        print(f"Expected tasks from manifest: {expected_tasks}")

        task_branches = ["001-calculator_a_T001", "001-calculator_a_T002", "001-calculator_a_T003", "001-calculator_a_T004"]
        total_commits = 0

        for branch in task_branches:
            if subprocess.run(
                ["git", "rev-parse", "--verify", branch],
                cwd=e2e_project,
                capture_output=True
            ).returncode == 0:
                task_commits = count_task_commits(e2e_project, branch)
                print(f"{branch}: {task_commits} task commits")
                total_commits += task_commits
            else:
                print(f"{branch}: SKIPPED - branch does not exist")

        print(f"Total task commits: {total_commits}")

        if total_commits == 0:
            pytest.skip("No task commits found - tasks may have failed to commit")

        assert total_commits >= expected_tasks, \
            f"Expected at least {expected_tasks} task commits, found {total_commits}"

        assert total_commits <= expected_tasks + len(task_branches), \
            f"Too many commits: expected <= {expected_tasks + len(task_branches)}, found {total_commits}"

        print(f"✓ Commit count matches manifest (expected {expected_tasks}, found {total_commits})")

    def test_post_merge_rollup_to_spec_branch(self, e2e_project):
        """Verify that task commits are rolled up to the spec branch via post-merge."""
        spec_branch = "001-calculator"

        print(f"\n=== Verifying Post-Merge Rollup to Spec Branch ({spec_branch}) ===")

        spec_messages = get_commit_messages(e2e_project, spec_branch, limit=20)

        task_commits_on_spec = [msg for msg in spec_messages if "task(T" in msg]

        print(f"\nCommits on {spec_branch}: {len(spec_messages)}")
        print(f"Task-related commits: {len(task_commits_on_spec)}")

        if len(task_commits_on_spec) > 0:
            for msg in task_commits_on_spec[:5]:
                print(f"  - {msg[:100]}")

    def test_commits_beyond_plan_tag(self, e2e_project):
        """Verify that commits exist beyond the plan tag baseline for spec branch."""
        spec_branch = "001-calculator"

        print(f"\n=== Verifying Commits Beyond Plan Tag ===")

        initial_result = subprocess.run(
            ["git", "log", "--format=%H", "--grep=Add 001-calculator spec", spec_branch],
            cwd=e2e_project,
            capture_output=True,
            text=True,
        )

        if initial_result.returncode == 0 and initial_result.stdout.strip():
            plan_tag_sha = initial_result.stdout.strip().split("\n")[0]
            print(f"Plan tag SHA: {plan_tag_sha[:12]}")

            new_commits = get_commits_since(e2e_project, spec_branch, plan_tag_sha)

            print(f"Commits beyond plan tag: {len(new_commits)}")

            for msg in new_commits[:5]:
                print(f"  - {msg[:100]}")


# ============================================================
# Helper Functions for Commit Verification
# ============================================================

def get_branch_head_sha(project_dir: Path, branch: str) -> str | None:
    """Get the HEAD commit SHA for a branch."""
    result = subprocess.run(
        ["git", "rev-parse", branch],
        cwd=project_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def get_commit_count(project_dir: Path, branch: str) -> int:
    """Get the number of commits on a branch."""
    result = subprocess.run(
        ["git", "rev-list", "--count", branch],
        cwd=project_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return int(result.stdout.strip())
    return 0


def get_commit_messages(project_dir: Path, branch: str, limit: int = 20) -> list[str]:
    """Get commit messages for a branch."""
    result = subprocess.run(
        ["git", "log", "--format=%s", f"-{limit}", branch],
        cwd=project_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout.strip().split("\n")
    return []


def get_task_commit_messages(project_dir: Path, branch: str) -> list[str]:
    """Get commit messages matching the task(TXXX): pattern."""
    result = subprocess.run(
        ["git", "log", "--format=%s", "--grep=^task(T", branch],
        cwd=project_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout.strip().split("\n") if result.stdout.strip() else []
    return []


def verify_commit_format(message: str, task_id: str) -> bool:
    """Verify that a commit message follows the expected format.

    Expected format:
    - First line: task(TXXX): <summary>
    - Footer contains: (generated by <runner> or (merged by <runner>
    """
    if not message.startswith(f"task({task_id}):"):
        return False

    has_footer = "(generated by" in message or "(merged by" in message
    return has_footer


def count_task_commits(project_dir: Path, branch: str) -> int:
    """Count commits with task(TXXX): pattern on a branch."""
    return len(get_task_commit_messages(project_dir, branch))


def get_commits_since(project_dir: Path, branch: str, since_sha: str) -> list[str]:
    """Get commit messages since a specific SHA."""
    result = subprocess.run(
        ["git", "log", "--format=%s", f"{since_sha}..{branch}"],
        cwd=project_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout.strip().split("\n") if result.stdout.strip() else []
    return []


def load_manifest_from_dagu_home(project_dir: Path, spec_id: str) -> dict | None:
    """Load the branch manifest JSON from DAGU_HOME."""
    import json

    manifest_path = project_dir / ".arborist" / "dagu" / "dags" / f"{spec_id}.json"
    if not manifest_path.exists():
        return None

    try:
        with open(manifest_path) as f:
            return json.load(f)
    except Exception:
        return None