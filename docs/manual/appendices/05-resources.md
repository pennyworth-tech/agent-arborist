# Resources

Additional resources, tools, and links related to Agent Arborist.

## Official Resources

### Documentation

- **User Manual** - Main documentation for Agent Arborist
- **API Reference** - Python API documentation
- **CLI Reference** - Command-line interface reference
- **Design Document** - [agent-arborist.md](../../docs/agent-arborist.md)

### Code

- **GitHub Repository** - [https://github.com/your-org/agent-arborist](https://github.com/your-org/agent-arborist)
- **Source Code** - All code available under license
- **Issues** - Bug reports and feature requests
- **Pull Requests** - Contribution reviews

### Packages

- **PyPI Package** - [https://pypi.org/project/agent-arborist](https://pypi.org/project/agent-arborist)
- **Installation**: `pip install agent-arborist`

## Related Tools and Projects

### Workflow Orchestration

#### DAGU
- **Website**: [https://dagu.dev](https://dagu.dev)
- **Description**: Lightweight workflow engine used by Agent Arborist
- **Documentation**: [https://dagu.dev/docs](https://dagu.dev/docs)
- **GitHub**: [https://github.com/dagu-dev/dagu](https://github.com/dagu-dev/dagu)

#### Apache Airflow
- **Website**: [https://airflow.apache.org](https://airflow.apache.org)
- **Description**: Popular workflow orchestration platform
- **Use**: For advanced scheduling and monitoring needs

#### Prefect
- **Website**: [https://prefect.io](https://prefect.io)
- **Description**: Modern workflow orchestration
- **Use**: For more flexible workflow definitions

### AI and LLM Tools

#### Anthropic Claude
- **Website**: [https://www.anthropic.com/claude](https://www.anthropic.com/claude)
- **API Docs**: [https://docs.anthropic.com](https://docs.anthropic.com)
- **Use**: High-quality task specification generation

#### OpenAI
- **Website**: [https://openai.com](https://openai.com)
- **API Docs**: [https://platform.openai.com/docs](https://platform.openai.com/docs)
- **Use**: Generative AI for task specs

#### Ollama
- **Website**: [https://ollama.ai](https://ollama.ai)
- **Description**: Run LLMs locally
- **Use**: For custom local runners

### Container Technologies

#### Docker
- **Website**: [https://www.docker.com](https://www.docker.com)
- **Documentation**: [https://docs.docker.com](https://docs.docker.com)
- **Use**: Container execution and isolation

#### Podman
- **Website**: [https://podman.io](https://podman.io)
- **Documentation**: [https://docs.podman.io](https://docs.podman.io)
- **Use**: Docker alternative for containers

## Learning Resources

### Python

- **PEP 8** - Python style guide
- **Type Hints** - Python typing documentation
- **Click** - CLI framework docs

### Workflow Orchestration

- **DAG Concepts** - Directed Acyclic Graph overview
- **Workflow Patterns** - Common workflow design patterns
- **DAGU Tutorial** - Get started with DAGU

### AI and LLMs

- **Prompt Engineering** - How to write good prompts
- **Model Selection** - Choosing the right model
- **Token Management** - Understanding token usage and costs

## Community

### GitHub

- **Repository**: [agent-arborist](https://github.com/your-org/agent-arborist)
- **Issues**: [https://github.com/your-org/agent-arborist/issues](https://github.com/your-org/agent-arborist/issues)
- **Discussions**: [https://github.com/your-org/agent-arborist/discussions](https://github.com/your-org/agent-arborist/discussions)
- **Pull Requests**: [https://github.com/your-org/agent-arborist/pulls](https://github.com/your-org/agent-arborist/pulls)

### Social Media

- **Twitter**: Follow updates (placeholder link)
- **LinkedIn**: Connect (placeholder link)
- **Blog**: Development updates (placeholder link)

### Support

- **Troubleshooting**: [Appendix 01 - Troubleshooting](./01-troubleshooting.md)
- **FAQ**: [Appendix 02 - FAQ](./02-faq.md)
- **Email**: support@example.com (placeholder)

## Development Tools

### Testing

- **pytest** - Testing framework
- **pytest-cov** - Coverage reporting
- **mypy** - Type checking
- **ruff** - Linting and formatting

### Documentation

- **Sphinx** - Documentation generation
- **MkDocs** - Static site generator
- **Mermaid** - Diagram generation

### CI/CD

- **GitHub Actions** - Automated workflows
- **pre-commit** - Git hooks
- **Poetry** - Dependency management

## Best Practices

### Workflow Design

- **Keep workflows modular**: Single responsibility per workflow
- **Use clear naming**: Descriptive task and workflow names
- **Document dependencies**: Clear task dependency graphs
- **Test thoroughly**: Mock runners for testing

**See:** [Best Practices](../07-advanced-topics/04-best-practices.md)

### Security

- **Never commit secrets**: Use environment variables
- **Use read-only containers**: Minimize attack surface
- **Validate inputs**: Check all external inputs
- **Review configs**: Regular security audits

**See:** [Security](../07-advanced-topics/04-best-practices.md#security-best-practices)

### Performance

- **Use caching**: Cache generated specs
- **Parallelize**: Use parallel task execution
- **Optimize resources**: Set appropriate limits
- **Monitor usage**: Track resource consumption

## Examples and Templates

### Example Workflows

- [Data ETL Pipeline](../01-getting-started/03-quick-start.md)
- [Machine Learning Pipeline](../02-core-concepts/01-specs-and-tasks.md)
- [CI/CD Workflow](../05-hooks-system/04-hooks-examples.md)

### Configurations

- [Development Config](../03-configuration/04-test-configuration.md)
- [Production Config](../06-container-support/02-container-configuration.md)
- [Minimal Config](../03-configuration/01-configuration-system.md)

### Hooks

- [Validation Hooks](../05-hooks-system/04-hooks-examples.md)
- [Notification Hooks](../05-hooks-system/04-hooks-examples.md)
- [Archival Hooks](../05-hooks-system/04-hooks-examples.md)

## Troubleshooting Resources

### Common Issues

- [Configuration errors](./01-troubleshooting.md#configuration-issues)
- [Runner errors](./01-troubleshooting.md#runner-issues)
- [Workflow errors](./01-troubleshooting.md#workflow-execution-issues)
- [Container errors](./01-troubleshooting.md#container-issues)

### Debugging Tools

-Verbose logging** - Enable detailed logs
- Dry run mode** - Test without execution
- Configuration validation** - Check config syntax

## Integration Guides

### CI/CD Integration

- **GitHub Actions**: [Example in FAQ](./02-faq.md#can-i-integrate-with-github-actions)
- **GitLab CI**: [Example in Test Configuration](../03-configuration/04-test-configuration.md)
- **Pre-commit Hooks**: Custom validation

### Cloud Platforms

- **AWS**: S3 archival, Lambda tasks
- **GCP**: Cloud Storage, Cloud Functions
- **Azure**: Blob Storage, Functions

### Monitoring

- **Prometheus**: Metrics collection
- **Datadog**: APM and monitoring
- **Grafana**: Dashboards

## Books and Articles

### Workflow Orchestration

- *Designing Data-Intensive Applications* - Martin Kleppmann
- *Building Microservices* - Sam Newman
- *Data Engineering with Python* - Paul Crickard

### AI/ML

- *Designing Machine Learning Systems* - Chip Huyen
- *The Hundred-Page Machine Learning Book* - Andriy Burkov

### DevOps

- *The Phoenix Project* - Gene Kim et al.
- *Site Reliability Engineering* - Google SRE

## Conferences and Events

- **KubeCon** - Kubernetes and cloud native
- **PyCon** - Python development
- **AI conferences** - Latest AI research and applications

## License and Legal

- **License**: [MIT License](../../LICENSE)
- **Code of Conduct**: [CODE_OF_CONDUCT.md](../../CODE_OF_CONDUCT.md)
- **Contributing**: [Contributing](./03-contributing.md)

## Quick Links

**Getting Started:**
- [Quick Start](../01-getting-started/03-quick-start.md)
- [Installation](../../README.md#installation)

**Documentation:**
- [User Manual](../00-introduction/00-welcome.md)
- [Reference](../08-reference/README.md)

**Support:**
- [Troubleshooting](./01-troubleshooting.md)
- [FAQ](./02-faq.md)
- [GitHub Issues](https://github.com/your-org/agent-arborist/issues)

**Community:**
- [Contributing](./03-contributing.md)
- [Discussions](https://github.com/your-org/agent-arborist/discussions)

---

## Feedback

Have a resource you'd like to add? Open a PR or an issue on GitHub!