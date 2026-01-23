"""
Multi-provider integration tests for DAG generation.

Tests DAG generation across different AI providers:
- claude CLI: Claude models (opus, sonnet, haiku)
- gemini CLI: Google Gemini models
- opencode CLI: zai, cerebras, minimax models

These tests are non-deterministic and require the respective CLI tools.
Run with: pytest tests/test_dag_generator_providers.py -v -m provider

To run a specific provider:
    pytest tests/test_dag_generator_providers.py -v -k "claude"
    pytest tests/test_dag_generator_providers.py -v -k "gemini"
    pytest tests/test_dag_generator_providers.py -v -k "zai"
    pytest tests/test_dag_generator_providers.py -v -k "cerebras"
    pytest tests/test_dag_generator_providers.py -v -k "minimax"
"""

import pytest
import yaml
from pathlib import Path

from agent_arborist.dag_generator import DagGenerator
from agent_arborist.runner import (
    Runner,
    ClaudeRunner,
    GeminiRunner,
    OpencodeRunner,
    get_runner,
)


# Mark all tests as provider tests (flaky, require external services)
pytestmark = [
    pytest.mark.provider,
    pytest.mark.flaky,
]


# Provider configurations: (runner_type, model, display_name)
PROVIDER_CONFIGS = [
    ("claude", "opus", "Claude Opus"),
    ("claude", "sonnet", "Claude Sonnet"),
    ("claude", "haiku", "Claude Haiku"),
    ("gemini", "gemini-2.5-flash", "Gemini 2.5 Flash"),
    ("opencode", "zai-coding-plan/glm-4.7", "ZAI GLM 4.7"),
    ("opencode", "cerebras/zai-glm-4.7", "Cerebras GLM 4.7"),
    ("opencode", "minimax-coding-plan/MiniMax-M2.1", "MiniMax M2.1"),
]


@pytest.fixture
def fixtures_dir():
    """Path to test fixtures."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def hello_world_spec(fixtures_dir):
    """Hello world task spec content."""
    return (fixtures_dir / "tasks-hello-world.md").read_text()


@pytest.fixture
def calculator_spec(fixtures_dir):
    """Calculator task spec content."""
    return (fixtures_dir / "tasks-calculator.md").read_text()


def create_runner(runner_type: str, model: str | None = None) -> Runner:
    """Create a runner with optional model specification."""
    if runner_type == "claude":
        return ClaudeRunner(model=model)
    elif runner_type == "gemini":
        return GeminiRunner(model=model)
    elif runner_type == "opencode":
        return OpencodeRunner(model=model)
    else:
        raise ValueError(f"Unknown runner type: {runner_type}")


def is_runner_available(runner_type: str) -> bool:
    """Check if a runner is available."""
    try:
        runner = create_runner(runner_type)
        return runner.is_available()
    except Exception:
        return False


def assert_valid_multi_doc_yaml(yaml_content: str, min_docs: int = 1) -> list[dict]:
    """Assert YAML is valid multi-document and return parsed documents."""
    assert yaml_content is not None, "YAML content should not be None"

    try:
        documents = list(yaml.safe_load_all(yaml_content))
    except yaml.YAMLError as e:
        pytest.fail(f"Invalid YAML: {e}")

    # Filter out None documents (empty documents in multi-doc)
    documents = [d for d in documents if d is not None]

    assert len(documents) >= min_docs, (
        f"Expected at least {min_docs} document(s), got {len(documents)}"
    )

    return documents


def assert_dag_structure(dag: dict, is_root: bool = False):
    """Assert a DAG document has valid structure."""
    assert isinstance(dag, dict), "DAG should be a dictionary"
    assert "name" in dag, "DAG should have 'name' field"
    assert "steps" in dag, "DAG should have 'steps' field"
    assert isinstance(dag["steps"], list), "Steps should be a list"
    assert len(dag["steps"]) >= 1, "DAG should have at least one step"

    if is_root:
        # Root should typically have env with ARBORIST_MANIFEST
        if "env" in dag:
            env_str = str(dag["env"])
            # Soft check - AI may format env differently
            if "ARBORIST_MANIFEST" not in env_str:
                print(f"Note: Root env missing ARBORIST_MANIFEST: {dag['env']}")


class TestRunnerWithModel:
    """Tests for runner model parameter support."""

    def test_claude_runner_accepts_model(self):
        """Test ClaudeRunner accepts model parameter."""
        runner = ClaudeRunner(model="opus")
        assert runner.model == "opus"

    def test_claude_runner_default_model(self):
        """Test ClaudeRunner has sensible default."""
        runner = ClaudeRunner()
        assert runner.model is None or isinstance(runner.model, str)

    def test_gemini_runner_accepts_model(self):
        """Test GeminiRunner accepts model parameter."""
        runner = GeminiRunner(model="gemini-2.5-flash")
        assert runner.model == "gemini-2.5-flash"

    def test_gemini_runner_default_model(self):
        """Test GeminiRunner has sensible default."""
        runner = GeminiRunner()
        assert runner.model is None or isinstance(runner.model, str)

    def test_opencode_runner_accepts_model(self):
        """Test OpencodeRunner accepts model parameter."""
        runner = OpencodeRunner(model="zai-coding-plan/glm-4.7")
        assert runner.model == "zai-coding-plan/glm-4.7"

    def test_opencode_runner_default_model(self):
        """Test OpencodeRunner has sensible default."""
        runner = OpencodeRunner()
        assert runner.model is None or isinstance(runner.model, str)

    def test_get_runner_with_model(self):
        """Test get_runner supports model parameter."""
        runner = get_runner("claude", model="sonnet")
        assert isinstance(runner, ClaudeRunner)
        assert runner.model == "sonnet"

        runner = get_runner("gemini", model="gemini-2.5-pro")
        assert isinstance(runner, GeminiRunner)
        assert runner.model == "gemini-2.5-pro"

        runner = get_runner("opencode", model="cerebras/zai-glm-4.7")
        assert isinstance(runner, OpencodeRunner)
        assert runner.model == "cerebras/zai-glm-4.7"


class TestClaudeOpusProvider:
    """Tests for Claude Opus provider DAG generation."""

    @pytest.fixture
    def runner(self):
        """Create Claude Opus runner."""
        return ClaudeRunner(model="opus")

    @pytest.mark.skipif(
        not is_runner_available("claude"),
        reason="claude CLI not available"
    )
    def test_claude_opus_generates_valid_yaml(self, runner, hello_world_spec):
        """Test Claude Opus generates valid multi-document YAML."""
        generator = DagGenerator(runner=runner)
        result = generator.generate(hello_world_spec, "hello-world", timeout=180)

        assert result.success, f"Generation failed: {result.error}\nRaw: {result.raw_output}"

        documents = assert_valid_multi_doc_yaml(result.yaml_content)
        assert_dag_structure(documents[0], is_root=True)

    @pytest.mark.skipif(
        not is_runner_available("claude"),
        reason="claude CLI not available"
    )
    def test_claude_opus_generates_subdags(self, runner, hello_world_spec):
        """Test Claude Opus generates subdags for tasks."""
        generator = DagGenerator(runner=runner)
        result = generator.generate(hello_world_spec, "hello-world", timeout=180)

        assert result.success, f"Generation failed: {result.error}"

        documents = assert_valid_multi_doc_yaml(result.yaml_content, min_docs=2)

        for doc in documents:
            assert_dag_structure(doc)


class TestClaudeSonnetProvider:
    """Tests for Claude Sonnet provider DAG generation."""

    @pytest.fixture
    def runner(self):
        """Create Claude Sonnet runner."""
        return ClaudeRunner(model="sonnet")

    @pytest.mark.skipif(
        not is_runner_available("claude"),
        reason="claude CLI not available"
    )
    def test_claude_sonnet_generates_valid_yaml(self, runner, hello_world_spec):
        """Test Claude Sonnet generates valid multi-document YAML."""
        generator = DagGenerator(runner=runner)
        result = generator.generate(hello_world_spec, "hello-world", timeout=180)

        assert result.success, f"Generation failed: {result.error}\nRaw: {result.raw_output}"

        documents = assert_valid_multi_doc_yaml(result.yaml_content)
        assert_dag_structure(documents[0], is_root=True)

    @pytest.mark.skipif(
        not is_runner_available("claude"),
        reason="claude CLI not available"
    )
    def test_claude_sonnet_generates_subdags(self, runner, hello_world_spec):
        """Test Claude Sonnet generates subdags for tasks."""
        generator = DagGenerator(runner=runner)
        result = generator.generate(hello_world_spec, "hello-world", timeout=180)

        assert result.success, f"Generation failed: {result.error}"

        documents = assert_valid_multi_doc_yaml(result.yaml_content, min_docs=2)

        for doc in documents:
            assert_dag_structure(doc)


class TestClaudeHaikuProvider:
    """Tests for Claude Haiku provider DAG generation."""

    @pytest.fixture
    def runner(self):
        """Create Claude Haiku runner."""
        return ClaudeRunner(model="haiku")

    @pytest.mark.skipif(
        not is_runner_available("claude"),
        reason="claude CLI not available"
    )
    def test_claude_haiku_generates_valid_yaml(self, runner, hello_world_spec):
        """Test Claude Haiku generates valid multi-document YAML."""
        generator = DagGenerator(runner=runner)
        result = generator.generate(hello_world_spec, "hello-world", timeout=180)

        assert result.success, f"Generation failed: {result.error}\nRaw: {result.raw_output}"

        documents = assert_valid_multi_doc_yaml(result.yaml_content)
        assert_dag_structure(documents[0], is_root=True)

    @pytest.mark.skipif(
        not is_runner_available("claude"),
        reason="claude CLI not available"
    )
    def test_claude_haiku_generates_subdags(self, runner, hello_world_spec):
        """Test Claude Haiku generates subdags for tasks."""
        generator = DagGenerator(runner=runner)
        result = generator.generate(hello_world_spec, "hello-world", timeout=180)

        assert result.success, f"Generation failed: {result.error}"

        documents = assert_valid_multi_doc_yaml(result.yaml_content, min_docs=2)

        for doc in documents:
            assert_dag_structure(doc)


class TestGeminiProvider:
    """Tests for Gemini provider DAG generation."""

    @pytest.fixture
    def runner(self):
        """Create Gemini runner."""
        return GeminiRunner(model="gemini-2.5-flash")

    @pytest.mark.skipif(
        not is_runner_available("gemini"),
        reason="gemini CLI not available"
    )
    def test_gemini_generates_valid_yaml(self, runner, hello_world_spec):
        """Test Gemini generates valid multi-document YAML."""
        generator = DagGenerator(runner=runner)
        result = generator.generate(hello_world_spec, "hello-world", timeout=180)

        assert result.success, f"Generation failed: {result.error}\nRaw: {result.raw_output}"

        documents = assert_valid_multi_doc_yaml(result.yaml_content)
        assert_dag_structure(documents[0], is_root=True)

    @pytest.mark.skipif(
        not is_runner_available("gemini"),
        reason="gemini CLI not available"
    )
    def test_gemini_generates_subdags(self, runner, hello_world_spec):
        """Test Gemini generates subdags for tasks."""
        generator = DagGenerator(runner=runner)
        result = generator.generate(hello_world_spec, "hello-world", timeout=180)

        assert result.success, f"Generation failed: {result.error}"

        documents = assert_valid_multi_doc_yaml(result.yaml_content, min_docs=2)

        # Should have root + subdags
        for doc in documents:
            assert_dag_structure(doc)


class TestZaiProvider:
    """Tests for ZAI (zai-coding-plan/glm-4.7) provider DAG generation."""

    @pytest.fixture
    def runner(self):
        """Create ZAI runner via opencode."""
        return OpencodeRunner(model="zai-coding-plan/glm-4.7")

    @pytest.mark.skipif(
        not is_runner_available("opencode"),
        reason="opencode CLI not available"
    )
    def test_zai_generates_valid_yaml(self, runner, hello_world_spec):
        """Test ZAI generates valid multi-document YAML."""
        generator = DagGenerator(runner=runner)
        result = generator.generate(hello_world_spec, "hello-world", timeout=180)

        assert result.success, f"Generation failed: {result.error}\nRaw: {result.raw_output}"

        documents = assert_valid_multi_doc_yaml(result.yaml_content)
        assert_dag_structure(documents[0], is_root=True)

    @pytest.mark.skipif(
        not is_runner_available("opencode"),
        reason="opencode CLI not available"
    )
    def test_zai_generates_subdags(self, runner, hello_world_spec):
        """Test ZAI generates subdags for tasks."""
        generator = DagGenerator(runner=runner)
        result = generator.generate(hello_world_spec, "hello-world", timeout=180)

        assert result.success, f"Generation failed: {result.error}"

        documents = assert_valid_multi_doc_yaml(result.yaml_content, min_docs=2)

        for doc in documents:
            assert_dag_structure(doc)


class TestCerebrasProvider:
    """Tests for Cerebras (cerebras/zai-glm-4.7) provider DAG generation."""

    @pytest.fixture
    def runner(self):
        """Create Cerebras runner via opencode."""
        return OpencodeRunner(model="cerebras/zai-glm-4.7")

    @pytest.mark.skipif(
        not is_runner_available("opencode"),
        reason="opencode CLI not available"
    )
    def test_cerebras_generates_valid_yaml(self, runner, hello_world_spec):
        """Test Cerebras generates valid multi-document YAML."""
        generator = DagGenerator(runner=runner)
        result = generator.generate(hello_world_spec, "hello-world", timeout=180)

        assert result.success, f"Generation failed: {result.error}\nRaw: {result.raw_output}"

        documents = assert_valid_multi_doc_yaml(result.yaml_content)
        assert_dag_structure(documents[0], is_root=True)

    @pytest.mark.skipif(
        not is_runner_available("opencode"),
        reason="opencode CLI not available"
    )
    def test_cerebras_generates_subdags(self, runner, hello_world_spec):
        """Test Cerebras generates subdags for tasks."""
        generator = DagGenerator(runner=runner)
        result = generator.generate(hello_world_spec, "hello-world", timeout=180)

        assert result.success, f"Generation failed: {result.error}"

        documents = assert_valid_multi_doc_yaml(result.yaml_content, min_docs=2)

        for doc in documents:
            assert_dag_structure(doc)


class TestMinimaxProvider:
    """Tests for MiniMax (minimax-coding-plan/MiniMax-M2.1) provider DAG generation."""

    @pytest.fixture
    def runner(self):
        """Create MiniMax runner via opencode."""
        return OpencodeRunner(model="minimax-coding-plan/MiniMax-M2.1")

    @pytest.mark.skipif(
        not is_runner_available("opencode"),
        reason="opencode CLI not available"
    )
    def test_minimax_generates_valid_yaml(self, runner, hello_world_spec):
        """Test MiniMax generates valid multi-document YAML."""
        generator = DagGenerator(runner=runner)
        result = generator.generate(hello_world_spec, "hello-world", timeout=180)

        assert result.success, f"Generation failed: {result.error}\nRaw: {result.raw_output}"

        documents = assert_valid_multi_doc_yaml(result.yaml_content)
        assert_dag_structure(documents[0], is_root=True)

    @pytest.mark.skipif(
        not is_runner_available("opencode"),
        reason="opencode CLI not available"
    )
    def test_minimax_generates_subdags(self, runner, hello_world_spec):
        """Test MiniMax generates subdags for tasks."""
        generator = DagGenerator(runner=runner)
        result = generator.generate(hello_world_spec, "hello-world", timeout=180)

        assert result.success, f"Generation failed: {result.error}"

        documents = assert_valid_multi_doc_yaml(result.yaml_content, min_docs=2)

        for doc in documents:
            assert_dag_structure(doc)


class TestAllProvidersParameterized:
    """Parameterized tests across all providers."""

    @pytest.mark.parametrize(
        "runner_type,model,display_name",
        PROVIDER_CONFIGS,
        ids=[c[2] for c in PROVIDER_CONFIGS],
    )
    def test_provider_generates_valid_dag(
        self, runner_type, model, display_name, hello_world_spec
    ):
        """Test each provider generates valid DAG structure."""
        if not is_runner_available(runner_type):
            pytest.skip(f"{runner_type} CLI not available")

        runner = create_runner(runner_type, model)
        generator = DagGenerator(runner=runner)
        result = generator.generate(hello_world_spec, "hello-world", timeout=180)

        assert result.success, (
            f"[{display_name}] Generation failed: {result.error}\n"
            f"Raw output: {result.raw_output}"
        )

        documents = assert_valid_multi_doc_yaml(result.yaml_content)
        assert_dag_structure(documents[0], is_root=True)

        print(f"\n[{display_name}] Generated {len(documents)} documents")

    @pytest.mark.parametrize(
        "runner_type,model,display_name",
        PROVIDER_CONFIGS,
        ids=[c[2] for c in PROVIDER_CONFIGS],
    )
    def test_provider_handles_complex_spec(
        self, runner_type, model, display_name, calculator_spec
    ):
        """Test each provider handles complex task specs."""
        if not is_runner_available(runner_type):
            pytest.skip(f"{runner_type} CLI not available")

        runner = create_runner(runner_type, model)
        generator = DagGenerator(runner=runner)
        result = generator.generate(calculator_spec, "calculator", timeout=180)

        assert result.success, (
            f"[{display_name}] Generation failed: {result.error}\n"
            f"Raw output: {result.raw_output}"
        )

        documents = assert_valid_multi_doc_yaml(result.yaml_content, min_docs=2)

        # Should have multiple subdags for calculator spec
        print(f"\n[{display_name}] Generated {len(documents)} documents for calculator")
        for doc in documents:
            print(f"  - {doc.get('name', 'unnamed')}: {len(doc.get('steps', []))} steps")
