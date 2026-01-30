# Test Fixture: DevContainer with All AI Runners
# Used by arborist integration tests to verify multi-runner support
# Includes: Claude Code, OpenCode, Gemini CLI
FROM mcr.microsoft.com/devcontainers/base:debian12

ENV DEBIAN_FRONTEND=noninteractive

# Install system packages
RUN apt-get update && apt-get install -y \
    curl wget git build-essential \
    python3 python3-pip python3-venv \
    tmux pkg-config libssl-dev \
    ca-certificates gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install GitHub CLI
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

# Switch to root for global installations
USER root
RUN bash -c '. /home/vscode/.nvm/nvm.sh && ln -sf $(which node) /usr/local/bin/node && ln -sf $(which npm) /usr/local/bin/npm'

# Install all three AI runner CLIs globally
RUN bash -c '. /home/vscode/.nvm/nvm.sh && npm install -g \
    @anthropic-ai/claude-code \
    opencode-ai \
    @google/gemini-cli'

# Create global symlinks
RUN bash -c '. /home/vscode/.nvm/nvm.sh && \
    ln -sf $(which claude) /usr/local/bin/claude && \
    ln -sf $(which opencode) /usr/local/bin/opencode && \
    ln -sf $(which gemini) /usr/local/bin/gemini'

# Configure as vscode user
USER vscode
RUN git config --global --add safe.directory '*' \
    && git config --global --add safe.directory '/workspaces' \
    && git config --global --add safe.directory '/workspaces/*' \
    && git config --global --add safe.directory '/workspace'

# Shell configuration
RUN echo '' >> /home/vscode/.bashrc \
    && echo '# Load nvm' >> /home/vscode/.bashrc \
    && echo 'export NVM_DIR="$HOME/.nvm"' >> /home/vscode/.bashrc \
    && echo '[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"' >> /home/vscode/.bashrc

WORKDIR /workspaces
RUN echo "✅ Test fixture ready with Claude Code, OpenCode, and Gemini CLI"
