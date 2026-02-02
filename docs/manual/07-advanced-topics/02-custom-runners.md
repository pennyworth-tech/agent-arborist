# Custom Runners

Agent Arborist supports custom AI runners, allowing you to integrate with internal AI services, custom APIs, or local LLM deployments.

## Overview

The runner interface is defined in [`src/agent_arborist/runner.py`](../../src/agent_arborist/runner.py) and provides a contract for generating task specifications and DAGU configurations.

## Runner Interface

### Base Runner Class

All runners extend the base `Runner` class:

```python
from abc import ABC, abstractmethod
from typing import Dict, Any

class Runner(ABC):
    """Base class for AI runners."""
    
    @abstractmethod
    def generate_task_spec(self, description: str, **kwargs) -> str:
        """Generate a task specification from a description."""
        pass
    
    @abstractmethod
    def generate_dagu_config(self, spec: str, **kwargs) -> str:
        """Generate a DAGU configuration from a task spec."""
        pass
```

## Creating a Custom Runner

### Step 1: Define the Runner Class

Create a new Python file, e.g., `src/agent_arborist/runners/custom.py`:

```python
from agent_arborist.runner import Runner
from typing import Dict, Any

class CustomRunner(Runner):
    """Custom AI runner implementation."""
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the custom runner.
        
        Args:
            config: Runner configuration
        """
        self.config = config
        self.api_key = config.get('api_key')
        self.endpoint = config.get('endpoint')
    
    def generate_task_spec(self, description: str, **kwargs) -> str:
        """
        Generate a task specification.
        
        Args:
            description: Natural language description
            
        Returns:
            YAML task specification
        """
        # Call your custom AI service
        response = self._call_ai_service(description)
        
        # Format as YAML
        spec = self._format_as_yaml(response)
        
        return spec
    
    def generate_dagu_config(self, spec: str, **kwargs) -> str:
        """
        Generate a DAGU configuration.
        
        Args:
            spec: Task specification in YAML format
            
        Returns:
            YAML DAGU configuration
        """
        # Parse spec
        parsed_spec = self._parse_spec(spec)
        
        # Generate DAGU config
        dagu_config = self._generate_dagu(parsed_spec)
        
        return dagu_config
    
    def _call_ai_service(self, description: str) -> Dict[str, Any]:
        """Call the custom AI service."""
        # Implement your AI service call here
        import requests
        
        response = requests.post(
            self.endpoint,
            headers={'Authorization': f'Bearer {self.api_key}'},
            json={'prompt': description}
        )
        
        response.raise_for_status()
        return response.json()
    
    def _format_as_yaml(self, response: Dict[str, Any]) -> str:
        """Format response as YAML."""
        import yaml
        
        spec = {
            'name': response.get('name', 'custom-task'),
            'description': response.get('description', ''),
            'steps': response.get('steps', [])
        }
        
        return yaml.dump(spec, default_flow_style=False)
    
    def _parse_spec(self, spec: str) -> Dict[str, Any]:
        """Parse YAML specification."""
        import yaml
        return yaml.safe_load(spec)
    
    def _generate_dagu(self, spec: Dict[str, Any]) -> str:
        """Generate DAGU configuration from spec."""
        import yaml
        
        dagu = {
            'name': spec['name'],
            'description': spec['description'],
            'tasks': [
                {
                    'name': step['name'],
                    'command': step['command'],
                    'depends_on': step.get('depends_on', [])
                }
                for step in spec['steps']
            ]
        }
        
        return yaml.dump(dagu, default_flow_style=False)
```

### Step 2: Register the Runner

Register your custom runner in [`src/agent_arborist/config.py`](../../src/agent_arborist/config.py):

```python
from agent_arborist.runners.custom import CustomRunner

VALID_RUNNERS = ["claude", "openai", "mock", "custom"]

RUNNER_CLASSES = {
    "claude": ClaudeRunner,
    "openai": OpenAIRunner,
    "mock": MockRunner,
    "custom": CustomRunner,
}
```

### Step 3: Configure the Runner

Add your runner to `agent-arborist.yaml`:

```yaml
# agent-arborist.yaml
runner: custom

custom:
  api_key: ${CUSTOM_API_KEY}
  endpoint: https://api.custom-service.com/v1/generate
```

## Advanced Runner Features

### 1. Async Support

Implement async operations for better performance:

```python
import asyncio
from typing import AsyncIterator

class AsyncCustomRunner(Runner):
    """Async custom runner implementation."""
    
    async def generate_task_spec_async(self, 
                                        description: str,
                                        **kwargs) -> str:
        """Async task spec generation."""
        response = await self._call_ai_service_async(description)
        return self._format_as_yaml(response)
    
    async def _call_ai_service_async(self, 
                                      description: str) -> Dict[str, Any]:
        """Async AI service call using aiohttp."""
        import aiohttp
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.endpoint,
                headers={'Authorization': f'Bearer {self.api_key}'},
                json={'prompt': description}
            ) as response:
                response.raise_for_status()
                return await response.json()
```

### 2. Streaming Support

Support streaming responses:

```python
from typing import AsyncIterator

class StreamingRunner(Runner):
    """Runner with streaming support."""
    
    async def generate_task_spec_streaming(
        self, description: str, **kwargs
    ) -> AsyncIterator[str]:
        """Generate task spec with streaming."""
        stream = self._stream_ai_response(description)
        
        buffer = ""
        async for chunk in stream:
            buffer += chunk
            if '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                yield line
        
        if buffer:
            yield buffer
```

### 3. Retry Logic

Implement retry mechanisms:

```python
import time
from functools import wraps

def retry(max_attempts: int = 3, delay: float = 1.0):
    """Decorator for retry logic."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_attempts - 1:
                        time.sleep(delay * (2 ** attempt))
            raise last_error
        return wrapper
    return decorator

class RetryRunner(Runner):
    """Runner with built-in retry logic."""
    
    @retry(max_attempts=3, delay=2.0)
    def generate_task_spec(self, description: str, **kwargs) -> str:
        """Generate with retry logic."""
        return self._call_ai_service(description)
```

### 4. Caching Support

Implement caching to reduce API calls:

```python
import hashlib
import json
from pathlib import Path

class CachingRunner(Runner):
    """Runner with caching support."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.cache_dir = Path(config.get('cache_dir', '.cache/runner'))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def generate_task_spec(self, description: str, **kwargs) -> str:
        """Generate with caching."""
        cache_key = self._get_cache_key(description)
        cache_file = self.cache_dir / cache_key
        
        if cache_file.exists():
            with open(cache_file, 'r') as f:
                return f.read()
        
        result = self._call_ai_service(description)
        
        with open(cache_file, 'w') as f:
            f.write(result)
        
        return result
    
    def _get_cache_key(self, description: str) -> str:
        """Generate cache key from description."""
        hash_obj = hashlib.sha256(description.encode())
        return f"task_spec_{hash_obj.hexdigest()[:16]}.yaml"
```

## Runner Comparison

| Runner Type | Complexity | Use Case | Pros | Cons |
|-------------|-----------|----------|------|------|
| Built-in | Low | General purpose | Easy to use, supported | Limited to available models |
| Custom API | Medium | Internal services | Custom logic, privacy | Maintenance overhead |
| Local LLM | High | On-premise | No API costs, privacy | Resource intensive |
| Hybrid | High | Complex workflows | Flexibility | Complex setup |

## Example Use Cases

### 1. Internal AI Service

```python
class InternalAIRunner(Runner):
    """Runner for internal AI service."""
    
    def __init__(self, config: Dict[str, Any]):
        self.service_url = config['service_url']
        self.auth_token = config['auth_token']
    
    def generate_task_spec(self, description: str, **kwargs) -> str:
        """Spec generation for internal service."""
        response = requests.post(
            f"{self.service_url}/generate",
            headers={'Authorization': f'Bearer {self.auth_token}'},
            json={
                'type': 'task_spec',
                'prompt': description
            }
        )
        return response.json()['output']
```

### 2. Local LLM

```python
class LocalLLMRunner(Runner):
    """Runner for local LLM (Ollama)."""
    
    def generate_task_spec(self, description: str, **kwargs) -> str:
        """Spec generation using local LLM."""
        response = requests.post(
            'http://localhost:11434/api/generate',
            json={
                'model': self.config['model'],
                'prompt': description,
                'stream': False
            }
        )
        return response.json()['response']
```

### 3. Multi-Model Runner

```python
class MultiModelRunner(Runner):
    """Runner that uses multiple models."""
    
    def generate_task_spec(self, description: str, **kwargs) -> str:
        """Route to appropriate model."""
        complexity = self._estimate_complexity(description)
        
        if complexity == 'high':
            return self._use_model('gpt-4', description)
        elif complexity == 'medium':
            return self._use_model('claude-3-sonnet', description)
        else:
            return self._use_model('gpt-3.5-turbo', description)
    
    def _estimate_complexity(self, description: str) -> str:
        """Estimate task complexity."""
        # Simple heuristic
        if len(description) > 500:
            return 'high'
        elif len(description) > 200:
            return 'medium'
        return 'low'
```

## Best Practices

### 1. Error Handling

```python
def generate_task_spec(self, description: str, **kwargs) -> str:
    """Generate with proper error handling."""
    try:
        response = self._call_ai_service(description)
    except requests.RequestException as e:
        raise RunnerError(f"API request failed: {e}")
    except ValueError as e:
        raise RunnerError(f"Invalid response format: {e}")
    
    if not self._validate_response(response):
        raise RunnerError("Invalid task specification")
    
    return self._format_as_yaml(response)
```

### 2. Logging

```python
import logging

logger = logging.getLogger(__name__)

def generate_task_spec(self, description: str, **kwargs) -> str:
    """Generate with logging."""
    logger.info(f"Generating task spec: {description[:50]}...")
    
    try:
        result = self._call_ai_service(description)
        logger.info("Task spec generated successfully")
        return result
    except Exception as e:
        logger.error(f"Failed to generate task spec: {e}")
        raise
```

### 3. Configuration Validation

```python
def __init__(self, config: Dict[str, Any]):
    """Initialize with validation."""
    required_fields = ['api_key', 'endpoint']
    
    for field in required_fields:
        if field not in config:
            raise ValueError(f"Missing required field: {field}")
    
    self.api_key = config['api_key']
    self.endpoint = config['endpoint']
```

### 4. Rate Limiting

```python
import time
from collections import defaultdict

class RateLimitingRunner(Runner):
    """Runner with rate limiting."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.rate_limit = config.get('rate_limit', 10)  # requests per minute
        self.request_times = []
    
    def _check_rate_limit(self):
        """Check if within rate limit."""
        now = time.time()
        self.request_times = [t for t in self.request_times if now - t < 60]
        
        if len(self.request_times) >= self.rate_limit:
            sleep_time = 60 - (now - self.request_times[0])
            time.sleep(sleep_time)
            self.request_times = []
        
        self.request_times.append(now)
```

## Testing Custom Runners

```python
import pytest
from agent_arborist.runners.custom import CustomRunner

# Tests in tests/test_custom_runner.py

def test_custom_runner_init():
    """Test runner initialization."""
    config = {
        'api_key': 'test-key',
        'endpoint': 'https://api.test.com'
    }
    runner = CustomRunner(config)
    
    assert runner.api_key == 'test-key'
    assert runner.endpoint == 'https://api.test.com'

@pytest.fixture
def mock_ai_service(mocker):
    """Mock AI service."""
    return mocker.patch('requests.post')

def test_generate_task_spec(mock_ai_service):
    """Test task spec generation."""
    mock_ai_service.return_value.json.return_value = {
        'name': 'test-task',
        'description': 'Test description',
        'steps': [{}]
    }
    
    config = {'api_key': 'test', 'endpoint': 'https://test.com'}
    runner = CustomRunner(config)
    
    result = runner.generate_task_spec("Test description")
    
    assert 'name: test-task' in result
    assert 'description: Test description' in result
```

## Code References

- Runner base class: [`src/agent_arborist/runner.py:Runner`](../../src/agent_arborist/runner.py)
- Configuration schema: [`src/agent_arborist/config.py:VALID_RUNNERS`](../../src/agent_arborist/config.py#L22)
- Runner tests: [`tests/test_runner.py`](../../tests/test_runner.py)

## Next Steps

- Explore [Workflows and Dependencies](./03-workflows-and-dependencies.md)
- Review [Best Practices](./04-best-practices.md)