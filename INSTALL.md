# CourtListener Citation Validation MCP — Installation Guide

Step-by-step setup for the CourtListener Citation Validation MCP on Windows and Linux/macOS.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Start — Windows](#quick-start--windows)
- [Quick Start — Linux / macOS](#quick-start--linuxmacos)
- [API Token](#api-token)
- [Claude Desktop / Claude Code Configuration](#claude-desktop--claude-code-configuration)
- [Verify Installation](#verify-installation)
- [Manage API Keys (Windows)](#manage-api-keys-windows)
- [Docker / HTTP Mode](#docker--http-mode)
- [n8n Integration](#n8n-integration)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Python 3.11+ | Managed automatically by `uv` |
| [uv](https://docs.astral.sh/uv/) | Python package manager — installed by setup scripts |
| CourtListener API token | Free — [sign up here](https://www.courtlistener.com/sign-in/) |
| Claude Desktop or Claude Code | For MCP integration |

**uv is required.** The setup scripts install it automatically if not present.

---

## Quick Start — Windows

1. Clone or download the repository:
   ```powershell
   git clone https://github.com/john-walkoe/courtlistener_citations_mcp.git
   cd courtlistener_citations_mcp
   ```

2. Run the Windows setup script (PowerShell — right-click → Run as Administrator not required):
   ```powershell
   .\deploy\windows_setup.ps1
   ```

3. The script will:
   - Install `uv` if not present
   - Install Python dependencies with `uv sync`
   - Prompt for your CourtListener API token (stored securely)
   - Ask about transport mode (STDIO or HTTP)
   - Optionally configure Claude Desktop or Claude Code

---

## Quick Start — Linux / macOS

1. Clone or download the repository:
   ```bash
   git clone https://github.com/john-walkoe/courtlistener_citations_mcp.git
   cd courtlistener_citations_mcp
   ```

2. Make the setup script executable and run it:
   ```bash
   chmod +x deploy/linux_setup.sh
   ./deploy/linux_setup.sh
   ```

3. The script will:
   - Install `uv` if not present (via `curl -LsSf https://astral.sh/uv/install.sh | sh`)
   - Install Python dependencies with `uv sync`
   - Prompt for your CourtListener API token (stored in keyring or `~/.courtlistener_api_token`)
   - Ask about transport mode (STDIO or HTTP)
   - Optionally configure Claude Desktop or Claude Code

---

## API Token

### Getting Your Token

1. Sign up or log in at [https://www.courtlistener.com/sign-in/](https://www.courtlistener.com/sign-in/)
2. Navigate to your profile → Account
3. Select "Developer Tools"
4. Select "Your API Token"
5. Copy the 40-character hex token (e.g., `a1b2c3d4e5f6...`)

**Token format:** Exactly 40 characters, lowercase hex only (`a-f`, `0-9`).

**Screenshot — CourtListener API Token Page:**

![CourtListener API Token](documentation_photos\install_courtlistener_token_page.jpg)

### Token Storage

**Windows (preferred):**

- Primary: Windows Credential Manager (`CourtListener MCP:API_TOKEN`)
- Fallback: DPAPI-encrypted file at `~/.courtlistener_api_token`

**Linux / macOS:**
- Primary: keyring (Secret Service on Linux, Keychain on macOS)
- Fallback: plaintext file at `~/.courtlistener_api_token` with `chmod 600` permissions

**Docker / Remote:** Use `COURTLISTENER_API_TOKEN` environment variable (see [Docker section](#docker--http-mode)).

The token is **never stored in the MCP config file** — it is loaded at runtime from secure storage.

---

## Claude Desktop / Claude Code Configuration

### STDIO Mode (Recommended)

STDIO is the recommended installation method. It supports the **interactive MCP App panel** — color-coded citation cards render inline in Claude Desktop with no Docker required. DPAPI/Windows Credential Manager secure token storage is STDIO-only (Windows).

Add to your Claude config (`~/.claude.json` for Claude Code, or `~/.config/Claude/claude_desktop_config.json` for Claude Desktop):

**Windows:**
```json
{
  "mcpServers": {
    "courtlistener_citations": {
      "command": "uv",
      "args": [
        "--directory",
        "C:/Users/YOUR_USERNAME/courtlistener_citations_mcp",
        "run",
        "courtlistener-mcp"
      ]
    }
  }
}
```

**Linux / macOS:**
```json
{
  "mcpServers": {
    "courtlistener_citations": {
      "command": "uv",
      "args": [
        "--directory",
        "/home/YOUR_USERNAME/courtlistener_citations_mcp",
        "run",
        "courtlistener-mcp"
      ]
    }
  }
}
```

**Screenshot — Claude Code Config File:**
> 📷 `documentation_photos/install_claude_code_config.png`

### HTTP Mode (via mcp-remote)

If running in HTTP mode (e.g., Docker or remote server), use `npx mcp-remote`:

```json
{
  "mcpServers": {
    "courtlistener_citations": {
      "command": "npx",
      "args": [
        "mcp-remote",
        "http://localhost:8000/mcp"
      ]
    }
  }
}
```

**After updating config:** Restart Claude Desktop or Claude Code to load the MCP.

```
claude mcp list
```

Should show `courtlistener_citations` in the list.

---

## Verify Installation

### 1. Test the entry point

```bash
uv run courtlistener-mcp --help
```

### 2. Test from Claude

After restarting Claude, ask:

```
Use courtlistener_get_guidance with section="overview"
```

Expected: A text response explaining the MCP tools and use cases.

### 3. Test citation validation

```
Use courtlistener_validate_citations on this text: 134 S. Ct. 2347
```

Expected: Status 200, Alice Corp. v. CLS Bank Int'l.

### 4. Test local extraction (no API needed)

```
Use courtlistener_extract_citations on: Alice Corp. v. CLS Bank Int'l, 573 U.S. 208 (2014)
```

Expected: 1 case citation extracted, no API call required.

---

## Manage API Keys (Windows)

The `manage_api_keys.ps1` script provides a menu to manage all API keys.

```powershell
.\deploy\manage_api_keys.ps1
```

**Menu options:**

```
============================================================
  CourtListener Citation Validation MCP — API Key Manager
============================================================

  1. Update CourtListener API token
  2. Update OpenAI API key        (optional)
  3. Update Mistral API key       (optional)
  4. Test all configured keys
  5. Remove a key
  6. Migrate CourtListener token  (file → Credential Manager)
  7. Show key format requirements
  8. Exit

Enter your choice (1-8):
```

**Actions:**

| Option | Description |
|--------|-------------|
| 1 | Set or replace the required CourtListener token |
| 2 | Set optional OpenAI key (for OCR / Chat endpoint use) |
| 3 | Set optional Mistral key (for OCR / Chat endpoint use) |
| 4 | Live test — makes an HTTP call to `api.courtlistener.com` |
| 5 | Remove any stored key |
| 6 | Migrate CL token from file-based DPAPI to Credential Manager |
| 7 | Display all format requirements |
| 8 | Exit |

**Screenshot — Key Test Results:**
> 📷 `documentation_photos/install_key_test_results.png`

### Key Format Requirements

```
CourtListener API Token (required):
  Format: 40 lowercase hex characters (a-f, 0-9)
  Example: a1b2c3d4e5f67890abcdef1234567890abcdef12
  Get it:  https://www.courtlistener.com/sign-in/

OpenAI API Key (optional — for OCR / Chat endpoint use):
  Format: sk- followed by alphanumeric characters (min 20 total)
  Ollama: Use "ollama" or "ollama:modelname" for local Ollama instances
  Example: sk-proj-abc123...
  Ollama:  ollama  OR  ollama:llama3.2

Mistral API Key (optional — for OCR / Chat endpoint use):
  Format: 32 alphanumeric characters (A-Z, a-z, 0-9)
  Example: AbCdEfGh1234567890IjKlMn01234567
```

---

## Docker / HTTP Mode

HTTP mode is suitable for CoPilot Studio, n8n, remote clients, or multi-user deployments.

### Setup

1. Create a `.env` file in the project root:
   ```bash
   # .env
   COURTLISTENER_API_TOKEN=your_40_char_hex_token_here
   ```

2. Start the server:
   ```bash
   docker compose up -d
   ```

3. Verify:
   ```bash
   curl http://localhost:8000/health
   ```
   Expected: `{"status": "ok"}`

### MCP Endpoint

```
http://localhost:8000/mcp
```

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `COURTLISTENER_API_TOKEN` | Yes | — | API token (required for Docker — no keyring/DPAPI) |
| `TRANSPORT` | No | `stdio` | Set to `http` for HTTP mode |
| `HOST` | No | `0.0.0.0` | HTTP server bind address |
| `PORT` | No | `8000` | HTTP server port |
| `LOG_LEVEL` | No | `INFO` | Logging level |
| `CORS_ORIGINS` | No | `http://localhost:8080,http://127.0.0.1:8080` | Comma-separated list of allowed CORS origins (HTTP mode only). Add your reverse proxy or gateway URL here. |

### Dev Tunnel (Windows — for remote access)

> ⚠️ **Corporate & Regulatory Policy Notice:** Dev tunnels create a publicly accessible endpoint for your local server. Before using this feature, consult your organization's IT security policy and bar association ethics rules regarding client data confidentiality. Many law firms prohibit this type of network bypass on managed devices. **Do not use on corporate/managed hardware without IT approval.** For production use, deploy behind a properly secured reverse proxy instead.

To expose the local HTTP server via a dev tunnel:

```powershell
.\deploy\start_devtunnel.ps1
```

```powershell
.\deploy\cleanup_devtunnels.ps1
```

---

## Troubleshooting

### MCP server not listed in `claude mcp list`

1. Check the config file location:
   - Claude Code: `~/.claude.json`
   - Claude Desktop: `~/.config/Claude/claude_desktop_config.json`
2. Verify the `courtlistener_citations` key exists in `mcpServers`
3. Restart Claude Desktop or Claude Code
4. Re-run `windows_setup.ps1` or `linux_setup.sh` to reconfigure

### "No API token found" error

1. **Windows:** Run `.\deploy\manage_api_keys.ps1` → option 4 (Test) to check status
2. **Linux:** Check `~/.courtlistener_api_token` exists and has content
3. **Docker:** Verify `.env` file has `COURTLISTENER_API_TOKEN=...`
4. Set env var directly: `set COURTLISTENER_API_TOKEN=your_token` (Windows) or `export COURTLISTENER_API_TOKEN=your_token` (Linux)

### validate_citations returns 404 for a known citation

This is expected for some cases — it is not a bug:

- **Alice Corp. 573 U.S. 208** — U.S. Reports indexing is incomplete; use `134 S. Ct. 2347` or let the fallback chain find it via `search_cases`
- **Very recent SCOTUS opinions** — may not yet be indexed in U.S. Reports
- **State court opinions** — CourtListener coverage varies by state and time period

The 3-tool fallback chain handles most real cases. True 404s after all three tools = likely hallucination.

See: `courtlistener_get_guidance` with `section="limitations"` for full coverage details.

### uv command not found

```bash
# Linux / macOS
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

# Or reinstall:
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```powershell
# Windows — check if uv is in PATH
where uv

# Or reinstall via PowerShell
irm https://astral.sh/uv/install.ps1 | iex
```

### HTTP 403 from CourtListener API

You are using API v3. Only v4 works. The MCP always uses v4 (`/api/rest/v4/`). If you see 403, check your token is valid by running the key test:

```powershell
.\deploy\manage_api_keys.ps1  # Option 4: Test all keys
```

### Rate limit errors (429)

- **General:** 5,000 requests/hour — retry after 1 hour
- **Citation-lookup:** 60 valid citations/minute — reduce batch size or add delay
- **Large documents:** Auto-chunked at 64,000 chars — do not split manually

### Docker container can't access Windows Credential Manager

Expected. Docker runs Linux and cannot access Windows Credential Manager or DPAPI. Always use `COURTLISTENER_API_TOKEN` environment variable in `.env` for Docker deployments.

### eyecite ImportError

```bash
uv sync
```

This reinstalls all dependencies including eyecite. If the problem persists:

```bash
uv pip install eyecite>=2.7.6
```

---

## Available Tools (7)

| Tool | Type | Description |
|------|------|-------------|
| `courtlistener_extract_citations` | Local (eyecite) | Extract all citation types — no API, instant |
| `courtlistener_validate_citations` | API | Primary citation validation (POST `/citation-lookup/`) |
| `courtlistener_search_cases` | API | Search by case name — 404 fallback |
| `courtlistener_lookup_citation` | API | Direct reporter lookup — last resort |
| `courtlistener_get_cluster` | API | Full case details and CourtListener URL |
| `courtlistener_search_clusters` | API | Filtered opinion cluster search |
| `courtlistener_get_guidance` | Local | Workflow help, risk levels, tool reference |

---

## Security Notes

- API token is **not** stored in the Claude config file
- Token loaded at runtime from Windows Credential Manager / keyring / file-based DPAPI
- Config files are set to `chmod 600` (owner-only) on Linux/macOS
- Tokens are never logged or included in error messages
- Optional OpenAI/Mistral keys stored as DPAPI-encrypted files on Windows
- Rate limiting prevents unintentional API abuse
