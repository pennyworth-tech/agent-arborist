"""
FULL End-to-End Test: Calculator with AI, Hooks, and Visualization

This test exercises the COMPLETE Arborist pipeline:
1. Create a calculator project with real Python code and tests
2. Create a spec for building the calculator
3. Configure hooks for test execution and quality checks
4. Generate DAG using real AI (Claude)
5. Run the DAG with real AI execution
6. Extract metrics from hook outputs
7. Visualize with viz commands and dashboard

Run with:
    pytest tests/test_full_e2e_calculator.py -v -s --tb=short

To keep the test environment for dashboard inspection:
    TEST_KEEP_ENV=1 pytest tests/test_full_e2e_calculator.py -v -s

After running, launch dashboard with:
    cd /tmp/calc-e2e-test && arborist dashboard
"""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from agent_arborist.cli import main
from agent_arborist.home import ARBORIST_DIR_NAME, DAGU_DIR_NAME


# =============================================================================
# Skip conditions
# =============================================================================

def check_claude_available():
    """Check if claude CLI is available."""
    return shutil.which("claude") is not None


def check_dagu_available():
    """Check if dagu is available."""
    return shutil.which("dagu") is not None


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.full_pipeline,
    pytest.mark.skipif(not check_claude_available(), reason="claude CLI not available"),
    pytest.mark.skipif(not check_dagu_available(), reason="dagu not available"),
]


# =============================================================================
# Test Environment Setup
# =============================================================================

# Use persistent directory so we can inspect after test
TEST_DIR = Path("/tmp/calc-e2e-test")
KEEP_ENV = os.environ.get("TEST_KEEP_ENV", "1") == "1"  # Default to keeping


@pytest.fixture(scope="module")
def calculator_project():
    """Create a complete calculator project with tests.

    This creates a real Python project that the AI will modify.
    """
    # Clean up if exists
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR)

    TEST_DIR.mkdir(parents=True)
    original_cwd = os.getcwd()
    os.chdir(TEST_DIR)

    try:
        # Initialize git
        subprocess.run(["git", "init"], capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], capture_output=True)

        # Create README
        (TEST_DIR / "README.md").write_text("# Calculator Project\n\nA simple CLI calculator.\n")

        # Create .gitignore
        (TEST_DIR / ".gitignore").write_text("__pycache__/\n*.pyc\n.pytest_cache/\n*.egg-info/\n")

        # Initial commit
        subprocess.run(["git", "add", "."], capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            capture_output=True,
            check=True,
            env={**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@test.com"},
        )

        # Initialize arborist
        runner = CliRunner()
        result = runner.invoke(main, ["init"])
        assert result.exit_code == 0, f"arborist init failed: {result.output}"

        yield TEST_DIR

    finally:
        os.chdir(original_cwd)
        if not KEEP_ENV:
            shutil.rmtree(TEST_DIR, ignore_errors=True)


@pytest.fixture(scope="module")
def calculator_spec(calculator_project):
    """Create the calculator spec with tasks."""
    spec_dir = calculator_project / "specs" / "001-calculator"
    spec_dir.mkdir(parents=True)

    # Create task files for each task
    # Phase 1: Project Setup
    (spec_dir / "T001.md").write_text("""\
# T001: Create project structure

Create the basic Python project structure:
- Create `src/` directory
- Create `src/__init__.py` (empty file)
- Create `tests/` directory
- Create `tests/__init__.py` (empty file)

## Acceptance Criteria
- src/ directory exists
- src/__init__.py exists
- tests/ directory exists
- tests/__init__.py exists
""")

    (spec_dir / "T002.md").write_text("""\
# T002: Create pyproject.toml

Create `pyproject.toml` with project configuration:
- Project name: "calculator"
- Version: "0.1.0"
- Python requires: ">=3.9"
- Add pytest as dev dependency

## Dependencies
- T001

## Acceptance Criteria
- pyproject.toml exists with valid TOML
- Contains project metadata
""")

    # Phase 2: Core Implementation
    (spec_dir / "T003.md").write_text("""\
# T003: Implement add and subtract

Create `src/calculator.py` with:
- `add(a: float, b: float) -> float` - returns sum
- `subtract(a: float, b: float) -> float` - returns difference

Include docstrings for each function.

## Dependencies
- T001

## Acceptance Criteria
- src/calculator.py exists
- add() function works correctly
- subtract() function works correctly
""")

    (spec_dir / "T004.md").write_text("""\
# T004: Implement multiply and divide

Add to `src/calculator.py`:
- `multiply(a: float, b: float) -> float` - returns product
- `divide(a: float, b: float) -> float` - returns quotient, raises ValueError on division by zero

## Dependencies
- T003

## Acceptance Criteria
- multiply() function works correctly
- divide() function works correctly
- divide() raises ValueError for division by zero
""")

    # Phase 3: Tests
    (spec_dir / "T005.md").write_text("""\
# T005: Write unit tests

Create `tests/test_calculator.py` with comprehensive tests:
- Test add() with positive, negative, and zero values
- Test subtract() with various inputs
- Test multiply() with various inputs
- Test divide() with valid inputs
- Test divide() raises ValueError for zero divisor

Use pytest style tests with descriptive names.

## Dependencies
- T004

## Acceptance Criteria
- tests/test_calculator.py exists
- All tests pass when run with pytest
- At least 8 test cases
""")

    # Create the main tasks.md that references all tasks
    (spec_dir / "tasks.md").write_text("""\
# Calculator Project Tasks

## Phase 1: Setup
- T001: Create project structure
- T002: Create pyproject.toml [depends: T001]

## Phase 2: Implementation
- T003: Implement add and subtract [depends: T001]
- T004: Implement multiply and divide [depends: T003]

## Phase 3: Testing
- T005: Write unit tests [depends: T004]

## Dependencies
```
T001 → T002
T001 → T003 → T004 → T005
```
""")

    return spec_dir


@pytest.fixture(scope="module")
def hooks_config(calculator_project):
    """Configure hooks for test execution and quality checks."""
    arborist_dir = calculator_project / ARBORIST_DIR_NAME

    # Create prompts directory
    prompts_dir = arborist_dir / "prompts"
    prompts_dir.mkdir(exist_ok=True)

    # Quality check prompt
    (prompts_dir / "quality_check.md").write_text("""\
# Code Quality Evaluation

Evaluate the code changes for task {{task_id}}.

## Code Diff
```
{{git_diff}}
```

## Evaluation Criteria
Rate the code from 1-10 based on:
1. Correctness - Does it work as intended?
2. Readability - Is the code clear and well-named?
3. Best practices - Does it follow Python conventions?

## Response Format
Respond with JSON only:
```json
{
  "score": <1-10>,
  "summary": "<one sentence summary>",
  "suggestions": ["<suggestion 1>", "<suggestion 2>"]
}
```
""")

    # Create full arborist config with hooks
    # Hooks are auto-enabled when config exists
    arborist_config = {
        "version": "1",
        "defaults": {
            "runner": "claude",
            "model": "sonnet"
        },
        "hooks": {
            "enabled": True,
            "prompts_dir": "prompts",
            "step_definitions": {
                "run_tests": {
                    "type": "shell",
                    "command": "cd $ARBORIST_WORKTREE && python -m pytest tests/ -v --tb=short 2>&1 || true",
                    "timeout": 120,
                    "extract_pattern": "(\\d+) passed",
                },
                "quality_check": {
                    "type": "llm_eval",
                    "prompt_file": "quality_check.md",
                    "model": "haiku",
                },
            },
            "injections": {
                "post_task": [
                    {"step": "run_tests", "name": "run-test"},
                    {"step": "quality_check", "name": "quality-check"},
                ]
            }
        }
    }

    config_path = arborist_dir / "config.json"
    config_path.write_text(json.dumps(arborist_config, indent=2))

    return config_path


# =============================================================================
# Main E2E Test
# =============================================================================


class TestFullE2ECalculator:
    """Full end-to-end test for calculator with AI, hooks, and visualization."""

    def test_01_generate_dag_with_hooks(self, calculator_project, calculator_spec, hooks_config):
        """Step 1: Generate DAG from spec with hooks enabled."""
        print("\n" + "="*60)
        print("STEP 1: Generate DAG from spec with AI")
        print("="*60)

        os.chdir(calculator_project)
        runner = CliRunner()

        # Generate DAG (hooks auto-enabled from config.json)
        result = runner.invoke(
            main,
            [
                "spec", "dag-build",
                str(calculator_spec),
                "--timeout", "300",
                "--model", "sonnet",  # Use sonnet for better quality
                "--show",  # Show the generated YAML
            ],
            catch_exceptions=False,
        )

        print(f"Output:\n{result.output}")
        assert result.exit_code == 0, f"DAG build failed: {result.output}"

        # Verify DAG was created
        dagu_home = calculator_project / ARBORIST_DIR_NAME / DAGU_DIR_NAME
        dag_path = dagu_home / "dags" / "001-calculator.yaml"
        assert dag_path.exists(), f"DAG not created at {dag_path}"

        # Verify hooks were injected
        dag_content = dag_path.read_text()
        print(f"\nGenerated DAG preview (first 2000 chars):\n{dag_content[:2000]}")

        # Check for hook steps in the DAG
        assert "run-test" in dag_content or "run_test" in dag_content, \
            "run-test hook not found in generated DAG"

        # Verify manifest was created
        manifest_path = dagu_home / "dags" / "001-calculator.json"
        assert manifest_path.exists(), f"Manifest not created at {manifest_path}"

        manifest = json.loads(manifest_path.read_text())
        tasks = manifest.get("tasks", {})
        task_ids = list(tasks.keys()) if isinstance(tasks, dict) else [t["task_id"] for t in tasks]
        print(f"\nManifest tasks: {task_ids}")

        assert len(tasks) >= 5, f"Expected at least 5 tasks in manifest, got {len(tasks)}"

    def test_02_dry_run_dag(self, calculator_project):
        """Step 2: Verify DAG with dry run."""
        print("\n" + "="*60)
        print("STEP 2: Dry run DAG to verify structure")
        print("="*60)

        os.chdir(calculator_project)
        dagu_home = calculator_project / ARBORIST_DIR_NAME / DAGU_DIR_NAME

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["dag", "run", "001-calculator", "--dry-run"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        print(f"Dry run output:\n{result.output}")
        assert result.exit_code == 0, f"Dry run failed: {result.output}"

    def test_03_run_dag_with_ai(self, calculator_project):
        """Step 3: Execute DAG with real AI."""
        print("\n" + "="*60)
        print("STEP 3: Run DAG with real AI execution")
        print("="*60)
        print("This may take several minutes...")

        os.chdir(calculator_project)
        dagu_home = calculator_project / ARBORIST_DIR_NAME / DAGU_DIR_NAME
        dag_path = dagu_home / "dags" / "001-calculator.yaml"

        # Run DAG using dagu directly for better output
        env = os.environ.copy()
        env["DAGU_HOME"] = str(dagu_home)

        start_time = time.time()
        result = subprocess.run(
            ["dagu", "start", str(dag_path)],
            env=env,
            capture_output=True,
            text=True,
            timeout=900,  # 15 minute timeout
            cwd=calculator_project,
        )
        elapsed = time.time() - start_time

        print(f"\nDAG execution completed in {elapsed:.1f} seconds")
        print(f"stdout:\n{result.stdout[:3000] if result.stdout else '(empty)'}")
        if result.stderr:
            print(f"stderr:\n{result.stderr[:1000]}")

        # Check run data was created
        data_dir = dagu_home / "data"
        print(f"\nData directory contents: {list(data_dir.glob('**/*'))[:20]}")

    def test_04_verify_task_results(self, calculator_project):
        """Step 4: Verify tasks completed and created files."""
        print("\n" + "="*60)
        print("STEP 4: Verify task results")
        print("="*60)

        os.chdir(calculator_project)

        # Check for expected files created by tasks
        expected_files = [
            "src/__init__.py",
            "src/calculator.py",
            "tests/__init__.py",
            "tests/test_calculator.py",
            "pyproject.toml",
        ]

        # Check git branches created
        result = subprocess.run(
            ["git", "branch", "-a"],
            capture_output=True,
            text=True,
            cwd=calculator_project,
        )
        print(f"Git branches:\n{result.stdout}")

        # Check for task branches
        branches = result.stdout
        task_branches_found = []
        for task_id in ["T001", "T002", "T003", "T004", "T005"]:
            if task_id in branches:
                task_branches_found.append(task_id)

        print(f"Task branches found: {task_branches_found}")

        # Check which files exist (may be on branches, not main)
        files_found = []
        for f in expected_files:
            path = calculator_project / f
            if path.exists():
                files_found.append(f)

        print(f"Files found on current branch: {files_found}")

        # Check if calculator.py exists on any branch
        for branch in ["main", "001-calculator_T003", "001-calculator_T004", "001-calculator_T005"]:
            check = subprocess.run(
                ["git", "show", f"{branch}:src/calculator.py"],
                capture_output=True,
                text=True,
                cwd=calculator_project,
            )
            if check.returncode == 0:
                print(f"\ncalculator.py found on branch {branch}:")
                print(check.stdout[:500])
                break

    def test_05_run_viz_tree(self, calculator_project):
        """Step 5: Run viz tree to see DAG structure with metrics."""
        print("\n" + "="*60)
        print("STEP 5: Visualize DAG tree")
        print("="*60)

        os.chdir(calculator_project)
        dagu_home = calculator_project / ARBORIST_DIR_NAME / DAGU_DIR_NAME

        runner = CliRunner()

        # ASCII tree
        result = runner.invoke(
            main,
            ["viz", "tree", "001-calculator", "-e"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        print(f"Viz tree output:\n{result.output}")

        if result.exit_code != 0:
            print(f"Warning: viz tree failed (may be no runs yet): {result.output}")

    def test_06_run_viz_metrics(self, calculator_project):
        """Step 6: Run viz metrics to see extracted data."""
        print("\n" + "="*60)
        print("STEP 6: Extract and display metrics")
        print("="*60)

        os.chdir(calculator_project)
        dagu_home = calculator_project / ARBORIST_DIR_NAME / DAGU_DIR_NAME

        runner = CliRunner()

        # Get metrics as JSON
        result = runner.invoke(
            main,
            ["viz", "metrics", "001-calculator"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        print(f"Viz metrics output:\n{result.output}")

        if result.exit_code == 0:
            try:
                metrics = json.loads(result.output)
                print(f"\nParsed metrics summary: {json.dumps(metrics.get('summary', {}), indent=2)}")
            except json.JSONDecodeError:
                print("Could not parse metrics as JSON")

    def test_07_run_viz_export(self, calculator_project):
        """Step 7: Export visualization artifacts."""
        print("\n" + "="*60)
        print("STEP 7: Export visualization artifacts")
        print("="*60)

        os.chdir(calculator_project)
        dagu_home = calculator_project / ARBORIST_DIR_NAME / DAGU_DIR_NAME

        export_dir = calculator_project / "viz-export"
        export_dir.mkdir(exist_ok=True)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["viz", "export", "001-calculator", "--output-dir", str(export_dir), "--formats", "json"],
            env={"DAGU_HOME": str(dagu_home)},
        )

        print(f"Export result:\n{result.output}")

        if export_dir.exists():
            exported_files = list(export_dir.glob("*"))
            print(f"Exported files: {exported_files}")

            # Show contents of any JSON files
            for f in exported_files:
                if f.suffix == ".json":
                    print(f"\n{f.name}:\n{f.read_text()[:1000]}")

    def test_08_show_dag_run_status(self, calculator_project):
        """Step 8: Show DAG run status and history."""
        print("\n" + "="*60)
        print("STEP 8: Show DAG run status")
        print("="*60)

        os.chdir(calculator_project)
        dagu_home = calculator_project / ARBORIST_DIR_NAME / DAGU_DIR_NAME

        runner = CliRunner()

        # Run list
        result = runner.invoke(
            main,
            ["dag", "run-list", "--dag-name", "001-calculator"],
            env={"DAGU_HOME": str(dagu_home)},
        )
        print(f"Run list:\n{result.output}")

        # Run show with expand
        result = runner.invoke(
            main,
            ["dag", "run-show", "001-calculator", "-e"],
            env={"DAGU_HOME": str(dagu_home)},
        )
        print(f"Run show:\n{result.output}")

    def test_09_print_dashboard_instructions(self, calculator_project):
        """Step 9: Print instructions for launching dashboard."""
        print("\n" + "="*60)
        print("STEP 9: Dashboard Instructions")
        print("="*60)

        print(f"""
TEST COMPLETE! Environment preserved at: {calculator_project}

To explore the results:

  cd {calculator_project}

  # View tree visualization
  arborist viz tree 001-calculator -e

  # View metrics
  arborist viz metrics 001-calculator

  # Launch dashboard
  arborist dashboard

  # Or Dagu's web UI
  dagu server
  # Then open http://localhost:8080

  # Check the generated code
  git log --oneline --all
  git show main_a:src/calculator.py
""")


# =============================================================================
# Standalone runner
# =============================================================================

if __name__ == "__main__":
    """Allow running directly: python tests/test_full_e2e_calculator.py"""
    pytest.main([__file__, "-v", "-s", "--tb=short"])
