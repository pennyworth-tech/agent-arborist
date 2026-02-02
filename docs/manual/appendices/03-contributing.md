# Contributing

How to contribute to Agent Arborist.

## Overview

We welcome contributions! This guide covers development setup, contribution guidelines, and the pull request process.

## Ways to Contribute

- 🐛 **Report bugs**: Found an issue? Let us know!
- 📝 **Improve docs**: Help make documentation clearer
- ✨ **Add features**: Submit new features
- 🧪 **Add tests**: Improve test coverage
- 🎨 **UI/UX**: Improve user experience

## Development Setup

### Prerequisites

- Python 3.11+
- Git
- Docker (optional)
- Poetry or pip

### Setting Up Development Environment

1. **Fork the repository:**
   ```bash
   # On GitHub, click "Fork" button
   ```

2. **Clone your fork:**
   ```bash
   git clone https://github.com/YOUR_USERNAME/agent-arborist.git
   cd agent-arborist
   ```

3. **Install development dependencies:**
   ```bash
   # Using Poetry (recommended)
   poetry install --with dev

   # Or using pip
   pip install -e ".[dev]"
   ```

4. **Set up pre-commit hooks:**
   ```bash
   pre-commit install
   ```

5. **Create a branch:**
   ```bash
   git checkout -b feature/my-feature
   ```

## Code Style

### Python Code

- Follow [PEP 8](https://pep8.org/)
- Use 4 spaces for indentation
- Max line length: 100 characters
- Use type hints

**Example:**
```python
from typing import Dict, List, Optional

def generate_task_spec(
    description: str,
    timeout: int = 300
) -> Optional[TaskSpec]:
    """
    Generate a task specification.
    
    Args:
        description: Task description
        timeout: Timeout in seconds
        
    Returns:
        Task specification or None if failed
    """
    if not description:
        return None
    
    try:
        spec = _generate_spec(description, timeout)
        return TaskSpec(**spec)
    except Exception as e:
        log.error(f"Failed to generate spec: {e}")
        return None
```

### YAML Configuration

- Use 2 spaces for indentation
- Use descriptive comments
- Keep configurations simple

**Example:**
```yaml
# Configuration for production environment
runner: claude
timeouts:
  # Task spec generation timeout (5 minutes)
  generate_task_spec: 300
```

### Documentation

- Use clear, concise language
- Provide examples
- Include diagrams when helpful
- Link to related sections

**Markdown style:**
```markdown
## Feature Name

Description of the feature.

### Usage

```bash
agent-arborist command --option value
```

### Configuration

```yaml
key: value
```

**See also:** [Related section](link)
```

## Running Tests

### Run all tests:

```bash
pytest tests/
```

### Run specific tests:

```bash
# Run specific test file
pytest tests/test_config.py

# Run specific test
pytest tests/test_config.py::test_load_config

# Run with coverage
pytest --cov=agent_arborist tests/
```

### Run linters:

```bash
# Python linting
ruff check src/

# Type checking
mypy src/

# YAML linting
yamllint agent-arborist.yaml
```

### Format code:

```bash
# Black formatter
black src/

# Ruff formatter
ruff format src/
```

## Project Structure

```
agent-arborist/
├── src/
│   └── agent_arborist/
│       ├── cli.py              # CLI interface
│       ├── config.py           # Configuration
│       ├── runner.py           # Runner base & impls
│       ├── dagu.py             # DAGU integration
│       ├── hooks.py            # Hooks system
│       ├── container.py        # Container support
│       ├── workflow.py         # Workflow management
│       └── models.py           # Data models
├── tests/
│   ├── test_config.py          # Config tests
│   ├── test_runner.py          # Runner tests
│   ├── test_dagu.py            # DAGU tests
│   └── fixtures/               # Test fixtures
├── docs/
│   ├── agent-arborist.md       # Design doc
│   └── manual/                 # User manual
├── pyproject.toml              # Project config
└── README.md                   # Project README
```

## Adding New Features

### Step 1: Create Issue

- Check if feature already exists
- Create feature request on GitHub
- Get feedback from maintainers

### Step 2: Design

- Document design decisions
- Consider backward compatibility
- Plan for testing

### Step 3: Implementation

1. Write code following style guide
2. Add type hints
3. Include docstrings
4. Write tests

### Step 4: Testing

```bash
# Add new test file
touch tests/test_my_feature.py

# Write tests
# pytest tests/test_my_feature.py

# Ensure all tests pass
pytest tests/
```

### Step 5: Documentation

- Update user manual
- Add examples
- Update API reference
- Add diagrams if helpful

### Step 6: Commit

```bash
git add .
git commit -m "Add my feature: description"

# Use conventional commits
# feat: add new feature
# fix: fix bug
# docs: update documentation
# test: add tests
# chore: maintenance
```

## Pull Request Process

### 1. Push your changes:

```bash
git push origin feature/my-feature
```

### 2. Create Pull Request:

- Title: `feat: Add my feature`
- Description: Explain changes, include screenshots
- Link to related issues

### 3. PR Requirements:

- [ ] Tests added/updated
- [ ] Documentation updated
- [ ] Code follows style guide
- [ ] All checks pass

### 4. Review Process:

- Automatic CI checks run
- Maintainers review code
- Request changes if needed
- Approval required before merge

### 5. Merge:

- Squash and merge for clean history
- Maintainers merge
- CI creates release with your changes

## Bug Reporting

### Before Reporting:

1. **Search existing issues**
2. **Check troubleshooting guide** in user manual
3. **Try latest version**

### Good Bug Report:

```markdown
## Description
Brief description of the bug

## Steps to Reproduce
1. Run command: `agent-arborist orchestrate "Test"`
2. Observe error

## Expected Behavior
What should happen

## Actual Behavior
What actually happened

## Environment
- OS: Ubuntu 22.04
- Python: 3.11.5
- Agent Arborist: v0.1.0

## Logs/Error Messages
```
Error message here
```

## Additional Context
Any other relevant information
```

## Documentation Guidelines

### User Manual

- Keep it simple and user-focused
- Provide code examples
- Use diagrams for complex topics
- Link to code with deep links

**Example:**
```markdown
## Feature Name

Description of feature.

### Usage

```bash
agent-arborist command --option value
```

### Configuration

```yaml
key: value
```

**Code reference:** [`src/agent_arborist/config.py:key`](../../src/agent_arborist/config.py#L25)

### See Also
- [Related section](../related/section.md)
```

### API Reference

- Document all public APIs
- Include type information
- Provide usage examples
- Note stability level

**Example:**
```markdown
### `generate_task_spec(description, **kwargs)` 🟢

Generate task specification.

**Parameters:**
- `description` (str): Task description
- `timeout` (int): Timeout in seconds (default: 300)

**Returns:** `str` - YAML specification

**Raises:**
- `RunnerError`: If runner fails
- `TimeoutError`: If timeout exceeded

**Example:**
```python
spec = runner.generate_task_spec("Build pipeline")
```
```

## Release Process

### Version Bumping

Follow [Semantic Versioning](https://semver.org/):
- **Major**: Breaking changes
- **Minor**: New features (backward compatible)
- **Patch**: Bug fixes (backward compatible)

### Release Checklist:

- [ ] Update version in `pyproject.toml`
- [ ] Update CHANGELOG.md
- [ ] Update documentation
- [ ] Tag release
- [ ] Build and publish
- [ ] Create GitHub release

### Example:

```bash
# Bump version
sed -i 's/version = "0.1.0"/version = "0.2.0"/' pyproject.toml

# Update changelog
# Build and publish
poetry build
poetry publish

# Tag and push
git tag v0.2.0
git push origin v0.2.0
```

## Community Guidelines

### Code of Conduct

- Be respectful
- Be inclusive
- Provide constructive feedback
- Assume good intentions

### Communication Channels

- **GitHub Issues**: Bug reports, feature requests
- **GitHub Discussions**: Questions, ideas
- **Pull Requests**: Code contributions
- **Slack/Discord**: Real-time conversation (if available)

### Getting Help

- Check documentation first
- Search existing issues
- Ask in Discussions
- Be patient with responses

## Recognitions

Contributors are recognized in:
- [CONTRIBUTORS.md](../../CONTRIBUTORS.md) - List of contributors
- [CHANGELOG.md](../../CHANGELOG.md) - Feature credits
- GitHub Releases - Release notes

### Contributors File Format

```markdown
# Contributors

 alphabetical_order

- **[Name]** ([@username]) - Description
  - PR #123: Feature description
  - PR #456: Bug fix
```

## Resources

### Internal

- [`README.md`](../../README.md) - Project overview
- [`CONTRIBUTING.md`](../../CONTRIBUTING.md) - This file
- [`docs/agent-arborist.md`](../../docs/agent-arborist.md) - Design document

### External

- [PEP 8](https://pep8.org/) - Python style guide
- [Semantic Versioning](https://semver.org/) - Versioning
- [Conventional Commits](https://www.conventionalcommits.org/) - Commit format

## Contact

- ** GitHub**: [agent-arborist](https://github.com/your-org/agent-arborist)
- **Issues**: [GitHub Issues](https://github.com/your-org/agent-arborist/issues)
- **Discussions**: [GitHub Discussions](https://github.com/your-org/agent-arborist/discussions)

## Thank You! 🎉

Thank you for contributing to Agent Arborist! Your contributions make this project better for everyone.