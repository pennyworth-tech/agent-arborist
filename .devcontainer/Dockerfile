# Simplified DevContainer for Agent Arborist
# Supports both ARM64 (Apple Silicon) and x64 architectures
# Installs only essential CLI tools: Claude Code, OpenCode, Gemini
FROM mcr.microsoft.com/devcontainers/base:debian12

# Avoid interactive prompts during installation
ENV DEBIAN_FRONTEND=noninteractive

# Install system packages in one layer
RUN apt-get update && apt-get install -y \
    # Core development tools
    curl wget git build-essential \
    # Python and dependencies
    python3 python3-pip python3-venv \
    # Terminal multiplexer
    tmux \
    # SSL/TLS support
    pkg-config libssl-dev \
    # Utilities
    ca-certificates gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install GitHub CLI (official method)
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && apt-get update \
    && apt-get install -y gh \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js via nvm as vscode user
USER vscode
ENV NVM_DIR="/home/vscode/.nvm"
RUN curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash \
    && . "$NVM_DIR/nvm.sh" \
    && nvm install --lts \
    && nvm alias default lts/* \
    && nvm use default
ENV PATH="${NVM_DIR}/versions/node/v$(cat ${NVM_DIR}/alias/default 2>/dev/null || echo 'v20.11.0')/bin:${PATH}"

# Switch back to root for global npm package installations
USER root

# Ensure node is available globally (create symlinks)
RUN bash -c '. /home/vscode/.nvm/nvm.sh && ln -sf $(which node) /usr/local/bin/node && ln -sf $(which npm) /usr/local/bin/npm'

# Install npm global packages: Claude Code, OpenCode, Gemini CLI
RUN bash -c '. /home/vscode/.nvm/nvm.sh && npm install -g \
    @anthropic-ai/claude-code \
    opencode-ai \
    @google/gemini-cli'

# Create symlinks for globally installed CLIs
RUN bash -c '. /home/vscode/.nvm/nvm.sh && \
    ln -sf $(which claude) /usr/local/bin/claude && \
    ln -sf $(which opencode) /usr/local/bin/opencode && \
    ln -sf $(which gemini) /usr/local/bin/gemini'

# Switch to vscode user for remaining configurations
USER vscode

# Configure Git safe directories
RUN git config --global --add safe.directory '*' \
    && git config --global --add safe.directory '/workspaces' \
    && git config --global --add safe.directory '/workspaces/*' \
    && git config --global --add safe.directory '/workspace'

# Create shell alias for Claude Code in bashrc
RUN echo '' >> /home/vscode/.bashrc \
    && echo '# Claude Code bypass permissions shortcut' >> /home/vscode/.bashrc \
    && echo 'dsp() { claude --dangerously-skip-permissions "$@"; }' >> /home/vscode/.bashrc \
    && echo '' >> /home/vscode/.bashrc \
    && echo '# Add local bin to PATH' >> /home/vscode/.bashrc \
    && echo 'export PATH="$HOME/.local/bin:$PATH"' >> /home/vscode/.bashrc \
    && echo '' >> /home/vscode/.bashrc \
    && echo '# Load nvm' >> /home/vscode/.bashrc \
    && echo 'export NVM_DIR="$HOME/.nvm"' >> /home/vscode/.bashrc \
    && echo '[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"' >> /home/vscode/.bashrc

# Create shell alias in zshrc if it exists
RUN if [ -f /home/vscode/.zshrc ]; then \
        echo '' >> /home/vscode/.zshrc \
        && echo '# Claude Code bypass permissions shortcut' >> /home/vscode/.zshrc \
        && echo 'dsp() { claude --dangerously-skip-permissions "$@"; }' >> /home/vscode/.zshrc \
        && echo '' >> /home/vscode/.zshrc \
        && echo '# Load nvm' >> /home/vscode/.zshrc \
        && echo 'export NVM_DIR="$HOME/.nvm"' >> /home/vscode/.zshrc \
        && echo '[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"' >> /home/vscode/.zshrc; \
    fi

# Set working directory
WORKDIR /workspaces

# Final message
RUN echo "✅ Agent Arborist DevContainer ready!" \
    && echo "🔧 Installed: Claude Code, OpenCode, Gemini CLI"
