# Glossary

Definitions and explanations of Agent Arborist terminology.

## A

### Agent Arborist
The AI-powered task specification and workflow orchestration tool that generates task specifications from natural language descriptions and creates executable workflows using DAGU.

### Anthropic Claude
Anthropic's AI family of models used as one of the supported runners in Agent Arborist, particularly the Claude 3.5 Sonnet model for high-quality task specification generation.

**Code Reference:** [`src/agent_arborist/runner.py:ClaudeRunner`](../../src/agent_arborist/runner.py)

## B

### Base Runner
The abstract base class that all AI runner implementations extend, providing a common interface for generating task specifications and DAGU configurations.

**Code Reference:** [`src/agent_arborist/runner.py:Runner`](../../src/agent_arborist/runner.py)

## C

### Claude Runner
The Anthropic Claude-based AI runner implementation, used for generating task specifications and DAGU configurations using Claude models.

### CLI (Command-Line Interface)
The command-line tool for interacting with Agent Arborist, providing commands like `generate-task-spec`, `generate-dagu`, `run-dagu`, and `orchestrate`.

**Code Reference:** [`src/agent_arborist/cli.py`](../../src/agent_arborist/cli.py)

### Configuration
The YAML file (`agent-arborist.yaml`) that defines settings for Agent Arborist, including runner selection, timeouts, paths, and other options.

**Code Reference:** [`src/agent_arborist/config.py`](../../src/agent_arborist/config.py)

### Container
An isolated execution environment using Docker or podman, providing reproducible execution for workflows. Containers can be configured with specific images, resources, mounts, and security settings.

### Container Runtime
The software that executes containers, either Docker or podman. Agent Arborist supports automatic detection or explicit selection of the runtime.

## D

### DAG (Directed Acyclic Graph)
A graph structure where edges represent dependencies and there are no cycles. DAGU workflows are represented as DAGs where tasks are nodes and dependencies are edges.

### DAGU
An open-source workflow tool that Agent Arborist uses to execute workflows. DAGU provides a CLI, web UI, and scheduler for managing workflows.

### DAGU Configuration
The YAML file that defines a DAGU workflow, including task definitions, dependencies, schedules, and other execution parameters.

**Code Reference:** [`src/agent_arborist/dagu.py`](../../src/agent_arborist/dagu.py)

## E

### Environment Variable
A system-wide variable that can override configuration values, typically used for secrets or environment-specific settings (e.g., `AGENT_ARBORIST_RUNNER`, `API_KEY`).

### Execution Phase
One of the phases in the orchestration lifecycle, including task spec generation, DAGU generation, and workflow execution.

## F

### Fan-in/Fan-out
A workflow pattern where a single task splits into multiple parallel tasks (fan-out) that later converge back into a single task (fan-in), commonly used for distributed processing.

## G

### Git Worktree
A Git feature that allows multiple working trees for the same repository, used by Agent Arborist to isolate workflow execution in separate directories without conflicts.

### Generate DAGU (command)
The CLI command that generates a DAGU workflow configuration from a task specification file.

**Code Reference:** [`src/agent_arborist/cli.py:generate_dagu()`](../../src/agent_arborist/cli.py#L45)

### Generate Task Spec (command)
The CLI command that generates a task specification from a natural language description.

**Code Reference:** [`src/agent_arborist/cli.py:generate_task_spec()`](../../src/agent_arborist/cli.py#L18)

## H

### Hook
A custom script or command that executes at specific points in the workflow lifecycle, used to customize behavior, validate content, send notifications, or integrate with external systems.

**Code Reference:** [`src/agent_arborist/hooks.py`](../../src/agent_arborist/hooks.py)

### Hook Phase
A specific point in the workflow lifecycle where hooks can execute: `pre_generation`, `post_spec`, `post_dagu`, `pre_execution`, `post_execution`.

## I

### Input
The natural language description provided to Agent Arborist to generate a task specification or workflow.

## M

### Mock Runner
A testing runner that returns predefined responses without making API calls, used for development and testing without incurring costs.

**Code Reference:** [`src/agent_arborist/runner.py:MockRunner`](../../src/agent_arborist/runner.py)

### Model Configuration
Settings that specify which AI model to use for different operations (task spec generation, DAGU generation). Each runner (Claude, OpenAI) has its own model configuration.

**Code Reference:** [`src/agent_arborist/config.py:ModelConfig`](../../src/agent_arborist/config.py#L34)

## O

### OpenAI Runner
The OpenAI GPT-based AI runner implementation, used for generating task specifications and DAGU configurations using OpenAI models.

### Orchestrate (command)
The CLI command that executes the complete workflow from description to execution: generates a task spec, creates a DAGU configuration, and runs the workflow.

**Code Reference:** [`src/agent_arborist/cli.py:orchestrate()`](../../src/agent_arborist/cli.py#L99)

### Orchestration
The process of managing the complete workflow lifecycle, including task spec generation, DAGU configuration, and workflow execution.

## P

### Parallel Workflow
A workflow pattern where multiple tasks execute simultaneously, useful for independent operations that can run concurrently.

### Paths Configuration
Configuration settings that specify directory locations for specifications, DAGs, outputs, worktrees, and temporary files.

**Code Reference:** [`src/agent_arborist/config.py:PathsConfig`](../../src/agent_arborist/config.py)

### Podman
An alternative container runtime to Docker that Agent Arborist supports for executing workflows in containers.

## R

### Runner
An AI service integration that generates task specifications and DAGU configurations. Runners include Claude, OpenAI, Mock, and custom implementations.

**Code Reference:** [`src/agent_arborist/runner.py`](../../src/agent_arborist/runner.py)

### Run DAGU (command)
The CLI command that executes a DAGU workflow configuration, managing Git worktrees and task execution.

**Code Reference:** [`src/agent_arborist/cli.py:run_dagu()`](../../src/agent_arborist/cli.py#L72)

## S

### Spec (Specification)
A YAML file that defines a workflow with task names, commands, descriptions, dependencies, and other metadata. Generated by AI runners from natural language descriptions.

### Spec Directory
The directory where task specification files are stored, configurable via the `paths.spec_dir` setting (default: `spec/`).

## T

### Task
A single unit of work in a workflow, defined by a name, command, description, and optional dependencies and retry settings.

### Task Specification
The complete definition of a workflow or task, including all steps, commands, dependencies, and metadata, generated from a natural language description.

### Timeout
The maximum time allowed for operation before it is cancelled. Timeouts can be configured separately for spec generation, DAGU generation, and workflow execution.

**Code Reference:** [`src/agent_arborist/config.py:TimeoutsConfig`](../../src/agent_arborist/config.py)

## V

## W

### Workflow
A sequence of tasks defined in a DAGU configuration, executed based on dependencies. Workflows can be linear, parallel, conditional, or complex multi-stage pipelines.

### Workflow Generation
The process of generating executable workflows from task specifications, creating DAGU configurations that define tasks and their dependencies.

### Workflow Orchestration
Managing the execution of workflows, including setup, monitoring, error handling, and cleanup.

### Worktree
A Git working tree created for isolated workflow execution, preventing conflicts when running multiple workflows in parallel.

**Code Reference:** [`src/agent_arborist/worktree.py`](../../src/agent_arborist/worktree.py)

### Worktree Directory
The directory where Git worktrees are created for workflow execution, configurable via the `git.worktree_dir` setting (default: `work/`).

## Y

### YAML
The configuration format used for Agent Arborist configuration files, task specifications, and DAGU configurations. YAML provides a human-readable format for structured data.