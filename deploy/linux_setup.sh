#!/bin/bash
# Linux/macOS Deployment Script for CourtListener Citation Validation MCP

set -e  # Exit on error

echo ""
echo "=== CourtListener Citation Validation MCP - Linux/macOS Setup ==="
echo ""

# Color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1"; }
log_info()    { echo -e "${CYAN}[INFO]${NC} $1"; }

# Resolve script and project directories
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Source validation helpers
source "$SCRIPT_DIR/validation_helpers.sh"

# ============================================================================
# SECTION 1: Install uv
# ============================================================================

log_info "uv will handle Python installation automatically"
echo ""

if ! command -v uv &> /dev/null; then
    log_info "uv not found — installing uv package manager..."

    if curl -LsSf https://astral.sh/uv/install.sh | sh; then
        # Add uv to PATH for this session
        export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

        if command -v uv &> /dev/null; then
            log_success "uv installed successfully: $(uv --version)"
        else
            log_error "uv installed but not on PATH. Add ~/.local/bin to your PATH and re-run."
            log_info "  export PATH=\"\$HOME/.local/bin:\$PATH\""
            exit 1
        fi
    else
        log_error "Failed to install uv automatically"
        log_info "Install manually: curl -LsSf https://astral.sh/uv/install.sh | sh"
        exit 1
    fi
else
    log_success "uv found: $(uv --version)"
fi

# ============================================================================
# SECTION 2: Install dependencies
# ============================================================================

echo ""
log_info "Installing project dependencies with uv..."
cd "$PROJECT_DIR"

if uv sync; then
    log_success "Dependencies installed successfully"
else
    log_error "Failed to install dependencies"
    exit 1
fi

# ============================================================================
# SECTION 3: Verify installation
# ============================================================================

log_info "Verifying installation..."
if uv run courtlistener-mcp --help &> /dev/null 2>&1; then
    log_success "Entry point verified: courtlistener-mcp"
elif uv run python -c "import courtlistener_mcp" &> /dev/null 2>&1; then
    log_success "Package import verified — run with: uv run courtlistener-mcp"
else
    log_warning "Could not verify installation (may still work)"
    log_info "You can run the server with: uv run courtlistener-mcp"
fi

# ============================================================================
# SECTION 4: API Token Configuration
# ============================================================================

echo ""
echo -e "${CYAN}API Token Configuration${NC}"
echo ""
log_info "CourtListener requires one API token (no optional keys)."
log_info "Get your free token at: https://www.courtlistener.com/sign-in/"
echo ""

# Prompt with validation and existing-token detection
CL_API_TOKEN=$(prompt_and_validate_token)
if [[ -z "$CL_API_TOKEN" ]]; then
    log_error "Failed to obtain a valid CourtListener API token — aborting"
    exit 1
fi

log_success "API token validated"

# ============================================================================
# SECTION 5: Store token via Python secure storage
# ============================================================================

echo ""
log_info "Storing token in secure storage..."

# Pass token via environment variable (avoids command-line exposure)
export _CL_TOKEN_SETUP="$CL_API_TOKEN"

STORE_RESULT=$(cd "$PROJECT_DIR" && uv run python << 'EOF'
import os, sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / 'src'))

try:
    from courtlistener_mcp.shared.secure_storage import store_api_token
    token = os.environ.get('_CL_TOKEN_SETUP', '')
    if not token:
        print('ERROR: No token provided')
        sys.exit(1)
    success = store_api_token(token)
    print('SUCCESS' if success else 'FAILED')
except Exception as e:
    print(f'ERROR: {e}')
    sys.exit(1)
EOF
)

unset _CL_TOKEN_SETUP

if [[ "$STORE_RESULT" == "SUCCESS" ]]; then
    log_success "Token stored successfully"
    log_info "  Primary location:  keyring (Secret Service / macOS Keychain)"
    log_info "  Fallback location: ~/.courtlistener_api_token"

    # Set restrictive permissions on the fallback file if it was created
    if [ -f "$HOME/.courtlistener_api_token" ]; then
        set_secure_file_permissions "$HOME/.courtlistener_api_token"
    fi
else
    # Fall back to writing the token file directly with correct permissions
    log_warning "Python storage returned: $STORE_RESULT"
    log_info "Falling back to direct file storage..."

    printf '%s' "$CL_API_TOKEN" > "$HOME/.courtlistener_api_token"
    set_secure_file_permissions "$HOME/.courtlistener_api_token"
    log_success "Token written to ~/.courtlistener_api_token (permissions: 600)"
    log_info "Set COURTLISTENER_API_TOKEN env var as an alternative if this file is not picked up"
fi

# Clear token from shell variable
CL_API_TOKEN=""

# ============================================================================
# SECTION 6: Transport Mode Selection
# ============================================================================

echo ""
echo -e "${CYAN}Transport Mode${NC}"
echo ""
echo "  [1] STDIO (recommended) — direct process, used by Claude Desktop / Claude Code"
echo "  [2] HTTP  — Streamable HTTP on localhost (Docker, CoPilot Studio, remote clients)"
echo ""
read -p "Enter choice (1 or 2, default is 1): " TRANSPORT_CHOICE
TRANSPORT_CHOICE=${TRANSPORT_CHOICE:-1}

USE_HTTP=false
HTTP_PORT="8000"

if [[ "$TRANSPORT_CHOICE" == "2" ]]; then
    USE_HTTP=true
    read -p "HTTP port (default: 8000): " PORT_INPUT
    if [[ -n "$PORT_INPUT" ]]; then
        HTTP_PORT="$PORT_INPUT"
    fi
    log_success "Transport: HTTP on port $HTTP_PORT"
    log_info "  MCP endpoint: http://localhost:$HTTP_PORT/mcp"
else
    log_success "Transport: STDIO (default)"
fi

# ============================================================================
# SECTION 7: Claude Desktop / Claude Code Configuration
# ============================================================================

echo ""
echo -e "${CYAN}Claude Desktop / Claude Code Configuration${NC}"
echo ""

read -p "Would you like to configure Claude integration? (Y/n): " CONFIGURE_CLAUDE
CONFIGURE_CLAUDE=${CONFIGURE_CLAUDE:-Y}

if [[ "$CONFIGURE_CLAUDE" =~ ^[Yy]$ ]]; then

    # Detect config location
    # Claude Code: ~/.claude.json  |  Claude Desktop: ~/.config/Claude/claude_desktop_config.json
    if [ -f "$HOME/.claude.json" ]; then
        CLAUDE_CONFIG_FILE="$HOME/.claude.json"
        CLAUDE_CONFIG_DIR="$HOME"
        log_info "Detected Claude Code config: $CLAUDE_CONFIG_FILE"
    else
        CLAUDE_CONFIG_DIR="$HOME/.config/Claude"
        CLAUDE_CONFIG_FILE="$CLAUDE_CONFIG_DIR/claude_desktop_config.json"
        log_info "Using Claude Desktop config: $CLAUDE_CONFIG_FILE"
    fi

    # Create config directory if needed (skip if it's $HOME itself)
    if [ ! -d "$CLAUDE_CONFIG_DIR" ] && [ "$CLAUDE_CONFIG_DIR" != "$HOME" ]; then
        mkdir -p "$CLAUDE_CONFIG_DIR"
        log_success "Created config directory: $CLAUDE_CONFIG_DIR"
    fi

    if [ "$CLAUDE_CONFIG_DIR" != "$HOME" ]; then
        set_secure_directory_permissions "$CLAUDE_CONFIG_DIR"
    fi

    # Build the server JSON block based on transport mode
    if [[ "$USE_HTTP" == true ]]; then
        SERVER_BLOCK=$(cat << JSONEOF
    "courtlistener_citations": {
      "command": "npx",
      "args": [
        "mcp-remote",
        "http://localhost:${HTTP_PORT}/mcp/"
      ]
    }
JSONEOF
)
    else
        SERVER_BLOCK=$(cat << JSONEOF
    "courtlistener_citations": {
      "command": "uv",
      "args": [
        "--directory",
        "${PROJECT_DIR}",
        "run",
        "courtlistener-mcp"
      ]
    }
JSONEOF
)
    fi

    if [ -f "$CLAUDE_CONFIG_FILE" ]; then
        log_info "Existing config found — merging CourtListener MCP configuration..."

        BACKUP_FILE="${CLAUDE_CONFIG_FILE}.backup_$(date +%Y%m%d_%H%M%S)"
        cp "$CLAUDE_CONFIG_FILE" "$BACKUP_FILE"
        log_info "Backup created: $BACKUP_FILE"

        # Use Python to safely merge JSON (preserves all existing servers)
        MERGE_RESULT=$(cd "$PROJECT_DIR" && uv run python << PYEOF
import json, sys

config_file = '$CLAUDE_CONFIG_FILE'

try:
    with open(config_file, 'r') as f:
        config = json.load(f)
except json.JSONDecodeError as e:
    print(f'ERROR: JSON parse failed: {e}')
    sys.exit(1)

if 'mcpServers' not in config:
    config['mcpServers'] = {}

if '$USE_HTTP' == 'true':
    config['mcpServers']['courtlistener_citations'] = {
        'command': 'npx',
        'args': ['mcp-remote', 'http://localhost:$HTTP_PORT/mcp/']
    }
else:
    config['mcpServers']['courtlistener_citations'] = {
        'command': 'uv',
        'args': ['--directory', '$PROJECT_DIR', 'run', 'courtlistener-mcp']
    }

with open(config_file, 'w') as f:
    json.dump(config, f, indent=2)

print('SUCCESS')
PYEOF
)

        if [[ "$MERGE_RESULT" == "SUCCESS" ]]; then
            log_success "Configuration merged — existing MCP servers preserved"
        else
            log_error "Merge failed: $MERGE_RESULT"
            log_info "Please add the following manually to $CLAUDE_CONFIG_FILE:"
            echo ""
            echo '  "mcpServers": {'
            echo "$SERVER_BLOCK"
            echo '  }'
            exit 1
        fi

    else
        # Create a new config file
        log_info "Creating new Claude config file..."

        cat > "$CLAUDE_CONFIG_FILE" << CFGEOF
{
  "mcpServers": {
${SERVER_BLOCK}
  }
}
CFGEOF
        log_success "Created: $CLAUDE_CONFIG_FILE"
    fi

    # Secure the config file
    if [ -f "$CLAUDE_CONFIG_FILE" ]; then
        set_secure_file_permissions "$CLAUDE_CONFIG_FILE"
    fi

    log_success "Claude integration configured!"
    echo ""
    log_info "Security notes:"
    log_info "  - API token is NOT stored in the config file"
    log_info "  - Token loaded at runtime from keyring / ~/.courtlistener_api_token"
    log_info "  - Config file permissions: 600 (owner read/write only)"

else
    log_info "Skipping Claude configuration"
    log_info "Add the following to your mcpServers config manually:"
    echo ""
    if [[ "$USE_HTTP" == true ]]; then
        cat << MANUALEOF
  "courtlistener_citations": {
    "command": "npx",
    "args": ["mcp-remote", "http://localhost:${HTTP_PORT}/mcp/"]
  }
MANUALEOF
    else
        cat << MANUALEOF
  "courtlistener_citations": {
    "command": "uv",
    "args": ["--directory", "${PROJECT_DIR}", "run", "courtlistener-mcp"]
  }
MANUALEOF
    fi
    echo ""
fi

# ============================================================================
# SECTION 8: Final Summary
# ============================================================================

echo ""
log_success "Linux/macOS setup complete!"
log_warning "Restart Claude Desktop / Claude Code to load the MCP server"
echo ""
log_info "Configuration Summary:"
log_success "  API Token:    Stored in secure storage (not in config file)"
log_success "  Dependencies: Installed via uv"
log_success "  Entry point:  uv run courtlistener-mcp"
log_success "  Project:      $PROJECT_DIR"

if [[ "$USE_HTTP" == true ]]; then
    log_success "  Transport:    HTTP on port $HTTP_PORT"
    log_info   "  Start server: TRANSPORT=http PORT=$HTTP_PORT uv run courtlistener-mcp"
    log_info   "  MCP endpoint: http://localhost:$HTTP_PORT/mcp"
else
    log_success "  Transport:    STDIO (direct process)"
fi

echo ""
log_info "Available Tools (7):"
log_info "  Citation Validation (3-tool fallback chain):"
log_info "    - extract_citations   (local, no API, eyecite)"
log_info "    - validate_citations  (primary — CourtListener API)"
log_info "    - search_cases        (fallback — search by case name)"
log_info "    - lookup_citation     (last resort — direct citation lookup)"
log_info "  Case Details:"
log_info "    - get_cluster         (full case details & CourtListener URLs)"
log_info "    - search_clusters     (filtered opinion cluster search)"
log_info "  Guidance:"
log_info "    - get_guidance        (workflow help & risk assessment)"
echo ""
log_info "Quick test:"
echo "  uv run courtlistener-mcp"
echo ""
log_info "Verify MCP is registered:"
echo "  claude mcp list"
echo ""
log_info "Test with Claude:"
echo "  Ask: 'Use get_guidance to learn about CourtListener MCP'"
echo "  Ask: 'Use validate_citations on this text: 573 U.S. 208 (2014)'"
echo ""
echo -e "${GREEN}=== Setup Complete! ===${NC}"
echo ""
