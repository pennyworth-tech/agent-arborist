# Minimal OpenCode DevContainer for Testing
FROM node:18-slim

# Install essential tools
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install OpenCode CLI globally
# Using npm package: opencode-ai
RUN npm install -g opencode-ai@latest

# Verify installation
RUN opencode --version

# Set working directory
WORKDIR /workspace

# Git configuration will be done in postCreateCommand
# to ensure correct workspace path
