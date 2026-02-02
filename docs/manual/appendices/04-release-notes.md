# Release Notes

Version history and changes for Agent Arborist.

## Version 0.1.0 (Current)

### 🎉 Initial Release

Initial public release of Agent Arborist.

### Major Features

- **AI-Driven Workflow Generation**: Generate task specifications from natural language descriptions using Claude and OpenAI models
- **DAGU Integration**: Automatic generation of DAGU workflow configurations
- **Flexible Runner Support**: Support for Claude, OpenAI, and custom AI runners
- **Container Execution**: Run workflows in isolated Docker/podman containers
- **Hooks System**: Customizable workflow lifecycle hooks
- **Git Worktree Isolation**: Isolated execution environments preventing conflicts
- **Complete CLI**: Full command-line interface with orchestration capabilities

### CLI Commands

- `generate-task-spec` - Generate task specifications
- `generate-dagu` - Generate DAGU configurations
- `run-dagu` - Execute DAGU workflows
- `orchestrate` - End-to-end workflow orchestration
- `version` - Version information

### Configuration

- YAML-based configuration system
- Environment-specific configurations
- Timeout settings per operation
- Custom path configuration
- Security options for containers

### Documentation

- Comprehensive user manual (8 parts, 31 sections)
- API reference documentation
- CLI reference
- Configuration reference
- Troubleshooting guide
- FAQ

### Components

- **Config Module**: Load and validate YAML configurations
- **Runner Module**: AI provider integrations
- **DAGU Module**: DAGU configuration generation and execution
- **Hooks Module**: Workflow customization hooks
- **Container Module**: Container execution support
- **Workflow Module**: Workflow orchestration

### Testing

- Unit tests for all core modules
- Integration tests for workflow execution
- Mock runner for testing without API costs
- Fixtures for test configurations

### Known Limitations

- Limited to Claude and OpenAI models (custom runners required for others)
- DAGU dependency for workflow execution
- Limited Kubernetes support
- No built-in monitoring dashboards
- No advanced scheduling features beyond DAGU's capabilities

### Breaking Changes

None (initial release)

### Upgrades

None (initial release)

---

## Future Roadmap

### Version 0.2.0 (Planned)

### Planned Features

- Enhanced scheduling capabilities
- Kubernetes native execution
- Advanced monitoring and observability
- Workflow templates library
- Visual workflow editor
- Performance metrics dashboard

### Improvements

- Additional AI provider support
- Optimized runner caching
- Enhanced error messages
- Improved documentation

---

## Migration Guides

### No migrations needed for current version

This is the initial release. Migration guides will be added for future versions.

---

## Changelog Format

Release notes follow this format:

### 🎉 Major Version Changes
### ✨ New Features
### 🐛 Bug Fixes
### 💥 Breaking Changes
### 📚 Documentation
### 🧪 Testing
### ⚡ Performance
### 🔧 Maintenance

---

## Release Process

Releases follow this process:

1. **Feature Development**: Features developed on feature branches
2. **Testing**: Comprehensive testing and review
3. **Documentation**: Documentation updated
4. **Version Bump**: Semantic version bump in `pyproject.toml`
5. **Release Tag**: Git tag created
6. **Publish**: Published to PyPI
7. **GitHub Release**: Release notes added to GitHub

---

## Support Policy

### Supported Versions

| Version | Status | Support Until |
|---------|--------|---------------|
| 0.1.0   | Current | Until 0.2.0 release |

### Maintenance

- **Bug fixes**: Most recent version
- **Security updates**: All supported versions
- **Feature updates**: Current version only

---

## Bug Reports

Report bugs on GitHub Issues with:
- Version number
- Environment details
- Reproduction steps
- Expected vs actual behavior

**Link:** [GitHub Issues](https://github.com/your-org/agent-arborist/issues)

---

## Feature Requests

Suggest features on GitHub Discussions or Issues:

1. Check if feature already exists
2. Provide detailed description
3. Explain use case
4. Include examples if helpful

**Link:** [GitHub Discussions](https://github.com/your-org/agent-arborist/discussions)

---

## Acknowledgments

### Contributors

- [Your Name] - Initial development

### Libraries and Tools

- **Click** - CLI framework
- **PyYAML** - YAML parsing
- **DAGU** - Workflow execution
- **Anthropic Claude** - AI model
- **OpenAI GPT** - AI model

---

## Version History Summary

| Version | Date | Notes |
|---------|------|-------|
| 0.1.0 | TBD | Initial release |

---

## Related Documentation

- [Quick Start](../01-getting-started/03-quick-start.md)
- [Best Practices](../07-advanced-topics/04-best-practices.md)
- [Contributing](./03-contributing.md)