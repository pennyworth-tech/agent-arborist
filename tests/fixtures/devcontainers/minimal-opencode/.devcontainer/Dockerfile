# Minimal OpenCode DevContainer for Testing
FROM node:18-slim

# Install essential tools including Python
RUN apt-get update && apt-get install -y \
    git \
    curl \
    python3 \
    python3-pip \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Install OpenCode CLI globally
# Using npm package: opencode-ai
RUN npm install -g opencode-ai@latest

# Verify opencode installation
RUN opencode --version

# Set working directory
WORKDIR /workspace

# Git configuration will be done in postCreateCommand
# Arborist will be installed from local source in postCreateCommand
