# CourtListener Citation Validation MCP Server

A Model Context Protocol (MCP) server for validating legal citations against the [CourtListener](https://www.courtlistener.com/) database. Its primary use case is detecting AI-generated **hallucinated citations** in legal briefs and documents. Uses a local [eyecite](https://github.com/freelawproject/eyecite) pass to inventory all citation types first, then a 3-tool fallback chain against the CourtListener API for case citation validation.

[![Platform Support](https://img.shields.io/badge/platform-Linux%20%7C%20Windows-blue.svg)]()
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)]()
[![API](https://img.shields.io/badge/API-CourtListener%20REST%20v4-green.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Quick Start

### Docker (Recommended)

Docker is the recommended installation method. It includes the **interactive MCP App panel** — color-coded citation cards with clickable CourtListener links rendered inline in Claude Desktop.

**Prerequisites:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine)

```bash
# 1. Clone the repo
git clone https://github.com/john-walkoe/courtlistener_citations_mcp.git
cd courtlistener_citations_mcp

# 2. Create a .env file with your CourtListener API token
#    (free token at https://www.courtlistener.com/sign-in/)
echo COURTLISTENER_API_TOKEN=your_40_char_hex_token_here > .env

# 3. Start the server
docker compose up -d

# Verify it's running
curl http://localhost:8000/health
```

**Claude Desktop config** (`%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "courtlistener_citations": {
      "command": "npx",
      "args": ["mcp-remote", "http://localhost:8000/mcp"]
    }
  }
}
```

> The `.env` file is gitignored. Never commit it. See `.env.example` for reference.

---

### Windows STDIO Install

> **Note:** STDIO mode works fully for citation validation. However, the **interactive MCP App panel does not currently render in Claude Desktop via STDIO** — you will get text results only. Use Docker mode above for the full visual panel experience. DPAPI/Credential Manager secure storage is Windows STDIO only.

**Run PowerShell as Administrator**, then:

```powershell
# Navigate to your user profile
cd $env:USERPROFILE

# If git is installed:
git clone https://github.com/john-walkoe/courtlistener_citations_mcp.git
cd courtlistener_citations_mcp

# If git is NOT installed:
# Download and extract the repository to C:\Users\YOUR_USERNAME\courtlistener_citations_mcp
# Then navigate to the folder:
# cd C:\Users\YOUR_USERNAME\courtlistener_citations_mcp

# The script detects if uv is installed and if it is not it will install uv - https://docs.astral.sh/uv

# Run setup script (sets execution policy for this session only):
Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Scope Process
.\deploy\windows_setup.ps1
```

The PowerShell script will:

- Check for and auto-install uv (via winget or PowerShell script)
- Install dependencies and create virtual environment
- Prompt for CourtListener API token (free at [courtlistener.com/sign-in](https://www.courtlistener.com/sign-in/))
- Store API token securely using Windows DPAPI encryption
- Ask to choose transport mode (STDIO or HTTP)
- Ask if you want Claude Desktop integration configured
- Offer secure configuration method (recommended) or traditional method (token in plain text in the MCP JSON file)
- Backup and automatically merge with existing Claude Desktop config (preserves other MCP servers)
- Provide installation summary and next steps

### Claude Desktop Configuration - Manual Install

**STDIO mode** (no MCP App panel in Claude Desktop — text results only):

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
      ],
      "env": {
        "COURTLISTENER_API_TOKEN": "your_40_char_hex_token_here"
      }
    }
  }
}
```

**HTTP mode (via mcp-remote):**

```json
{
  "mcpServers": {
    "courtlistener_citations": {
      "command": "npx",
      "args": [
        "mcp-remote",
        "http://localhost:8000/mcp/"
      ]
    }
  }
}
```

> **Note:** When using secure storage (Windows), the `env` block can be omitted entirely - the token is loaded automatically from Windows Credential Manager (or the DPAPI-encrypted file fallback) at runtime.

**Claude Code — Docker/HTTP mode (via mcp-remote, no dev tunnel):**

Add to `.claude.json` in your project root or `~/.claude.json` globally:

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

> Requires the Docker container to be running (`docker compose up -d`) and the `.env` file to contain `COURTLISTENER_API_TOKEN`. No token is needed in the JSON config itself — the container handles auth internally.

## Key Features

- **Local Citation Extraction** - [eyecite](https://github.com/freelawproject/eyecite) library inventories all citation types (case, statute, law journal, id., supra) locally before any API call — no API key, no rate limits, instant
- **Citation Validation** - 7-tool workflow detects hallucinated citations: local discovery first, then 3-tool fallback chain against CourtListener API
- **Dual Transport** - STDIO (Claude Desktop/Code) and Streamable HTTP (Docker, CoPilot Studio, remote clients)
- **MCP Apps UI** - Interactive citation validation results panel with color-coded cards and CourtListener links. **Requires Docker/HTTP mode** (`npx mcp-remote`). STDIO mode in Claude Desktop does not currently render the panel (text results still work).
- **Secure API Key Storage** - Windows DPAPI encryption for API tokens (no plain text in config files)
- **Elicitation Support** - Prompts for API token at runtime if not configured (FastMCP 3.0)
- **Tool Search Optimization** - Server instructions guide Claude to efficiently discover tools on-demand
- **SafeLogger with Auto-Sanitization** - Automatically masks API tokens, passwords, and sensitive data in all log messages
- **File-Based Logging with Rotation** - Persistent audit trail with 10MB rotation in `~/.courtlistener_citations_mcp/logs/`
- **Rate Limiting** - Dual token-bucket limiters: 83 req/min general (≤5,000/hr), 60 valid-citations/min for citation-lookup; automatic `wait_until` parsing on 429 responses
- **Cross-Platform** - Works on Linux and Windows (DPAPI on Windows, env var fallback on Linux)

### Workflow Design

**User requests:**

- *"Check if these citations in my brief are real"*
- *"Validate the citations in this legal document"*
- *"Look up Alice Corp v. CLS Bank and verify its citation"*
- *"Find Supreme Court cases about patent eligibility from 2014"*

**LLM performs the 4-step workflow:**

**Step 0: courtlistener_extract_citations (DISCOVERY)** - Runs eyecite locally to inventory ALL citation types in the document — case, statutory, law journal, id., supra. Free (no API), instant, no rate limits.

**Step 1: courtlistener_validate_citations (PRIMARY)** - Validate all case citations against CourtListener API using the eyecite parser

**Step 2: courtlistener_search_cases (FALLBACK)** - For any citations returning 404, search by case name to verify the case exists

**Step 3: courtlistener_lookup_citation (LAST RESORT)** - Direct reporter citation lookup when other methods fail

## Available Tools (7)

### Citation Discovery Tool (Local — No API)

| Tool | Purpose | Use Case |
|------|---------|----------|
| `courtlistener_extract_citations` | Extract all citation types locally via eyecite | **STEP 0** - Full census before API calls; identifies case, statute, journal, id., supra |

### Citation Validation Tools (3-Tool Fallback Chain)

| Tool | Purpose | Use Case |
|------|---------|----------|
| `courtlistener_validate_citations` | Extract & validate all case citations from text | **PRIMARY** - Paste full document text |
| `courtlistener_search_cases` | Search by case name, court, date, query | **FALLBACK** - When citation returns 404 |
| `courtlistener_lookup_citation` | Direct reporter citation lookup | **LAST RESORT** - Direct citation search |

### Supporting Tools

| Tool | Purpose | Use Case |
|------|---------|----------|
| `courtlistener_get_cluster` | Get full case details and CourtListener URLs | Deep dive into a specific case |
| `courtlistener_search_clusters` | Search opinion clusters with filters | Filtered search by judge, court, docket |
| `courtlistener_citations_get_guidance` | Workflow guidance and documentation (no API call) | Help with workflows and risk assessment |

### Tool Search Optimization (Claude Code v2.1.7+)

This MCP supports Claude Code's built-in tool search optimization, reducing context window usage through dynamic tool discovery.

**Always-Available Tools** (loaded immediately):
1. `courtlistener_extract_citations` - Local citation discovery (eyecite, no API)
2. `courtlistener_validate_citations` - Primary citation validation
3. `courtlistener_citations_get_guidance` - Workflow guidance and documentation
4. `courtlistener_search_cases` - Fallback search by case name

**Discovered On-Demand:**
5. `courtlistener_get_cluster` - Case details and CourtListener URLs
6. `courtlistener_search_clusters` - Filtered cluster search
7. `courtlistener_lookup_citation` - Direct citation lookup

### Guidance Sections

Use `courtlistener_citations_get_guidance(section)` with these sections:

| Section | When to Use |
|---------|-------------|
| `overview` | What this MCP does and quick-start workflow |
| `workflow` | Full discovery + 3-tool fallback chain explained |
| `response_format` | How to format results with ✅⚠️❌ symbols |
| `hallucination_patterns` | Common AI hallucination detection patterns |
| `edge_cases` | SCOTUS parallel citations, state courts, unpublished opinions |
| `risk_assessment` | How to interpret validation results |
| `limitations` | CourtListener coverage gaps and false negatives |

## Transport Modes

| Mode | Use Case | MCP App Panel | Secure Token Storage | Configuration |
|------|----------|--------------|---------------------|---------------|
| **HTTP (Docker)** | Claude Desktop, CoPilot Studio, web clients | ✅ Full panel | `.env` file | `TRANSPORT=http` via docker-compose |
| **STDIO** | Claude Desktop, Claude Code | ❌ Not rendered (text only) | Windows Credential Manager + DPAPI (Windows only) | Default |

> **MCP App panel** renders interactive color-coded citation cards inline in Claude Desktop when using HTTP/Docker mode via `npx mcp-remote`. STDIO mode negotiates the capability but Claude Desktop does not yet render panels for STDIO transport.

> **DPAPI / Windows Credential Manager** secure storage is only available in STDIO mode on Windows. Docker containers run Linux and cannot access Windows Credential Manager — use a `.env` file instead.

### Running in HTTP Mode

```bash
# Direct
set TRANSPORT=http
set PORT=8000
courtlistener-mcp

# Via uvicorn
uvicorn courtlistener_mcp.main:app --host 0.0.0.0 --port 8000

# Via Docker
docker compose up -d
# MCP endpoint: http://localhost:8000/mcp
# Health check: http://localhost:8000/health
```

#### Docker: API Token via .env file

Docker containers run Linux and cannot access Windows Credential Manager or DPAPI. The token **must** be provided via a `.env` file in the project root:

```bash
# .env (only this one variable is needed — TRANSPORT, HOST, PORT are hardcoded in docker-compose.yml)
COURTLISTENER_API_TOKEN=your_40_char_hex_token_here
```

> **Note:** The `.env` file is gitignored. Never commit it. The `.env.example` template is provided for reference.

### Dev Tunnel for CoPilot Studio / Claude.ai

For external access (CoPilot Studio, Claude.ai), use the dev tunnel launcher script. It starts the HTTP server locally and creates a [Microsoft Dev Tunnel](https://learn.microsoft.com/en-us/azure/developer/dev-tunnels/) to expose it publicly.

**Prerequisites:** `devtunnel.exe` ([download](https://aka.ms/devtunnels)) and `devtunnel user login`

```powershell
# Temporary tunnel (URL changes each time)
.\deploy\start_devtunnel.ps1

# Custom port
.\deploy\start_devtunnel.ps1 -Port 8889

# Persistent tunnel (URL stays the same across restarts)
.\deploy\start_devtunnel.ps1 -Persistent
```

The script will:
- Ask whether the server is running in Docker or local Python
- Ask which port (defaults to 8000)
- Verify Docker container health (Docker mode) or start Python server (local mode)
- Auto-download `devtunnel.exe` if not found, and add Windows Firewall rules automatically (requires Admin)
- Create a dev tunnel with anonymous access
- Display the public MCP endpoint URL (`https://<tunnel>.devtunnels.ms/mcp`)
- On Ctrl+C: clean up the tunnel; leave Docker running (or stop the Python process)

Use the displayed tunnel URL as your MCP endpoint in CoPilot Studio or Claude.ai.

#### Example: Working Script Output (Docker mode)

```
=== CourtListener MCP - Dev Tunnel Launcher ===

[OK] devtunnel: C:\Users\...\courtlistener_citations_mcp\devtunnel.exe
[OK] Firewall rule exists for devtunnel.exe
[OK] Logged in as john@walkoe.com using Microsoft.
How is the MCP server running?
  [1] Docker (already running via 'docker compose up -d')
  [2] Local Python (start it now via uv/venv)

Enter choice (1 or 2, default is 1): 1

Port the server is/will run on (default: 8000):

[INFO] Docker mode - checking container health on port 8000...
[OK] Docker container healthy at http://localhost:8000
     Health: http://localhost:8000/health
     MCP:    http://localhost:8000/mcp

[INFO] Starting temporary dev tunnel on port 8000...

========================================
 Tunnel is starting...
 Look for the URL below (*.devtunnels.ms)
 Your MCP endpoint will be:
   <tunnel-url>/mcp

 For CoPilot Studio or Claude.ai, use:
   https://<tunnel-subdomain>.devtunnels.ms/mcp

 Press Ctrl+C to stop tunnel and server
========================================

Hosting port: 8000
Connect via browser: https://3tgxrktm.usw3.devtunnels.ms:8000, https://3tgxrktm-8000.usw3.devtunnels.ms
Inspect network activity: https://3tgxrktm-8000-inspect.usw3.devtunnels.ms

Ready to accept connections for tunnel: quick-pond-mprv3rk.usw3
```

**MCP endpoint:** `https://3tgxrktm-8000.usw3.devtunnels.ms/mcp`

> **Note:** Temporary tunnel URLs change every run. Use `-Persistent` for a stable URL across restarts.

#### Firewall & Network: Lessons Learned

Getting devtunnel working on a hardened network required clearing multiple independent layers. If your tunnel fails with a connection timeout to `global.rel.tunnels.api.visualstudio.com:443`, work through this checklist:

**1. Windows Firewall**
The script automatically checks and adds outbound/inbound rules for `devtunnel.exe`. Run PowerShell as Administrator on the first run so it can create the rules. Verify with:
```powershell
Get-NetFirewallApplicationFilter -Program "C:\path\to\devtunnel.exe"
```

**2. Pi-hole / DNS sinkhole**
If you run Pi-hole or similar DNS blocking, add these to your allowlist:
- `(\.|^)devtunnels\.ms$`
- `(\.|^)visualstudio\.com$`
- `(\.|^)microsoftonline\.com$`
- `(\.|^)live\.com$`

**3. pfBlockerNG (pfSense)**
The devtunnel relay uses Microsoft Azure US West IPs (`20.125.0.0/16`). If pfBlockerNG is blocking outbound traffic, add `20.125.0.0/16` to your **Firewall > pfBlockerNG > IP > IPv4 Whitelist_Only_Outbound** list and click **Update**.

**4. Snort / Suricata IPS**
If Snort or Suricata is in blocking mode, the relay IP may get added to the `snort2c` block table after the first failed connection attempt. Two fixes required:
- Add the relay subnet to your Snort **Pass List** (prevents future blocks)
- Flush the existing block table entry — from pfSense **Diagnostics > Command Prompt**:
  ```bash
  pfctl -t snort2c -T flush
  ```
  Note: stopping Snort does NOT flush the pf table — you must flush manually.

**5. Test connectivity before running the script**
```powershell
Test-NetConnection global.rel.tunnels.api.visualstudio.com -Port 443
# TcpTestSucceeded : True  <-- required before devtunnel will work
```

## Rate Limits & Performance Expectations

### CourtListener API Limits

| Limit | Value | Scope |
|-------|-------|-------|
| General requests | **5,000 / hour** | All endpoints |
| Citation-lookup throttle | **60 *valid* citations / minute** | `/citation-lookup/` only |
| Citations per request | **250 max** | `/citation-lookup/` only |
| Text per request | **64,000 chars (~50 pages)** | `/citation-lookup/` only |

> **Key distinction:** the 60/min throttle counts *valid* citations (status 200 or 300), not requests. A single brief with 60 real cases consumes the entire minute's quota in one call. Invalid reporters and 404s do not count against the limit.

### How the Server Enforces Limits

The client uses two token-bucket rate limiters:

- **General limiter** — 83 requests/minute burst (`floor(5000 ÷ 60)`), keeping sustained throughput safely under the 5,000/hr cap
- **Citation limiter** — 60 citations/minute, matching the CourtListener throttle exactly

When the API returns HTTP 429, the response includes a `wait_until` ISO-8601 timestamp. The client parses that and waits precisely the right amount of time before retrying — no guessing, no wasted sleep.

### Performance Expectations for Large Documents

**The tool docstring is read by the LLM before it writes the tool call.** The `courtlistener_validate_citations` docstring contains explicit guidance on how to handle documents with many citations — when to call once vs. when to split by section. This means:

- **Short brief (few citations):** LLM calls once, results in a few seconds. No noticeable overhead.
- **Long document (many citations):** The LLM will spend a moment *thinking* about the docstring guidance before writing the tool call — planning how to split the document to avoid burning the 60/min quota in one shot. This pre-call reasoning adds a few seconds of visible "thinking" time but prevents a forced 60-second API wait mid-validation.
- **Dense citation document (>60 valid citations):** If not split, the API will throttle after 60 valid citations and the client will pause until the wait_until window expires. Splitting by section eliminates this pause entirely.

In short: slightly longer time before the first tool call → much shorter total wall-clock time for large documents.

---

## CourtListener API

### Getting an API Token

1. Visit [courtlistener.com/sign-in](https://www.courtlistener.com/sign-in/)
2. Create a free account
3. Go to your profile settings to find your API token
4. Tokens are 40-character hex strings

### Critical: API Version

- **API v4** is current. v3 returns 403 Forbidden on all data endpoints.
- Base URL: `https://www.courtlistener.com/api/rest/v4`
- Auth header: `Authorization: Token {token}` (NOT `Bearer`)
- Must include `User-Agent` header

### Key Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/citation-lookup/` | POST | Validate citations from text (eyecite) |
| `/search/?type=o` | GET | Search opinions by name, court, citation |
| `/clusters/{id}/` | GET | Get opinion cluster details |

### Common Court Identifiers

| ID | Court |
|----|-------|
| `scotus` | Supreme Court |
| `cafc` | Federal Circuit |
| `ca1` - `ca11` | Circuit Courts 1-11 |
| `cadc` | DC Circuit |
| `dcd` | District of Columbia |

## API Token Management

### Token Resolution Priority

1. `COURTLISTENER_API_TOKEN` environment variable ← **Docker / all platforms**
2. **Windows Credential Manager** (via `keyring` library) ← **Windows STDIO only**
3. DPAPI-encrypted file (`~/.courtlistener_api_token`) ← **Windows STDIO fallback** (auto-migrated to Credential Manager on first access)
4. Elicitation prompt (asks user at tool call time via FastMCP) ← STDIO only

> **Docker users:** Only option 1 applies. Set `COURTLISTENER_API_TOKEN` in your `.env` file. Options 2–4 require a native Windows process and are not available inside a Linux container.

### PowerShell Management

```powershell
# Store token securely (Credential Manager + DPAPI backup)
.\deploy\windows_setup.ps1

# Check stored token
.\deploy\manage_api_keys.ps1 -Action check

# Test API connection
.\deploy\manage_api_keys.ps1 -Action test

# Delete stored token
.\deploy\manage_api_keys.ps1 -Action delete
```

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `COURTLISTENER_API_TOKEN` | Yes* | None | API token (*or use DPAPI storage) |
| `TRANSPORT` | No | `stdio` | Transport mode: `stdio` or `http` |
| `HOST` | No | `0.0.0.0` | HTTP server bind address |
| `PORT` | No | `8000` | HTTP server port |
| `LOG_LEVEL` | No | `INFO` | Logging level |

## Cross-MCP Integration

This MCP is designed to complement other legal research MCP servers:

### Related MCP Servers

| MCP Server | Purpose | GitHub Repository |
|------------|---------|-------------------|
| **CourtListener Citation Validation** | Citation validation & hallucination detection | [courtlistener_citations_mcp](https://github.com/john-walkoe/courtlistener_citations_mcp.git) |
| **USPTO Patent File Wrapper (PFW)** | Patent prosecution history & documents | [uspto_pfw_mcp](https://github.com/john-walkoe/uspto_pfw_mcp.git) |
| **USPTO Patent Trial and Appeal Board (PTAB)** | Post-grant challenges (IPR/PGR/CBM) | [uspto_ptab_mcp](https://github.com/john-walkoe/uspto_ptab_mcp.git) |
| **USPTO Final Petition Decisions (FPD)** | Petition decisions during prosecution | [uspto_fpd_mcp](https://github.com/john-walkoe/uspto_fpd_mcp.git) |
| **USPTO Enriched Citation** | AI-extracted citation intelligence from Office Actions | [uspto_enriched_citation_mcp](https://github.com/john-walkoe/uspto_enriched_citation_mcp.git) |
| **Pinecone Assistant MCP** | Patent law knowledge base (MPEP, examination guidance) | [pinecone_assistant_mcp](https://github.com/john-walkoe/pinecone_assistant_mcp.git) |
| **Pinecone RAG MCP** | Patent law knowledge base with custom embeddings | [pinecone_rag_mcp](https://github.com/john-walkoe/pinecone_rag_mcp.git) |

### Integration Patterns

- **CourtListener + PFW**: Validate patent case citations, then pull prosecution documents for cited cases
- **CourtListener + PTAB**: Verify PTAB decision citations in legal briefs, cross-reference with trial records
- **CourtListener + Pinecone**: Research MPEP guidance on legal standards, then validate supporting case citations

## Project Structure

```
courtlistener_citations_mcp/
├── pyproject.toml                     # FastMCP 3.0 beta 2, httpx, pydantic-settings
├── .env.example                       # Template for env vars
├── Dockerfile                         # Python 3.11-slim, STDIO default (HTTP via TRANSPORT=http)
├── docker-compose.yml                 # Single service, port 8000
├── CLAUDE.md                          # Claude Code guidance
├── README.md                          # This file
├── src/
│   └── courtlistener_mcp/
│       ├── __init__.py
│       ├── __main__.py                # python -m courtlistener_mcp
│       ├── main.py                    # FastMCP server + 7 tools + health check + MCP Apps
│       ├── api/
│       │   └── client.py             # CourtListenerClient (httpx async, rate limiting, retry)
│       ├── config/
│       │   ├── settings.py           # Pydantic settings + Credential Manager + DPAPI fallback
│       │   ├── api_constants.py      # No magic numbers
│       │   ├── tool_guidance.py      # Sectioned guidance (7 sections, 80-95% token reduction)
│       │   └── log_config.py         # File-based logging with rotation
│       ├── shared/
│       │   ├── dpapi_crypto.py       # DPAPI encryption (Windows only)
│       │   ├── secure_storage.py     # Unified API token storage
│       │   ├── log_sanitizer.py      # Automatic sensitive data sanitization
│       │   └── safe_logger.py        # SafeLogger with auto-sanitization
│       ├── prompts/
│       │   ├── __init__.py
│       │   └── validate_legal_brief.py  # Full citation audit prompt (Step 0 + 3-tool chain)
│       └── ui/
│           └── citation_view.py      # MCP Apps interactive citation results UI
├── skill/
│   └── courtlistener-citation-validator/
│       └── SKILL.md                  # Claude Code skill: validate citations in legal documents
├── deploy/
│   ├── windows_setup.ps1             # Full Windows deployment (uv, venv, token, Claude Desktop)
│   ├── manage_api_keys.ps1           # Token management (check/test/delete)
│   └── start_devtunnel.ps1           # Dev tunnel launcher for CoPilot Studio / Claude.ai
└── tests/
    ├── conftest.py                    # Shared fixtures (api_client, sample responses, global reset)
    ├── unit/
    │   ├── test_client.py             # RateLimiter, chunking, throttle parsing, HTTP errors,
    │   │                              #   citation validation, security logging
    │   ├── test_extract_citations.py  # eyecite extraction: all citation types, id/supra resolution,
    │   │                              #   empty text guard, async JSON return
    │   ├── test_log_sanitizer.py      # Token masking, ANSI/injection filtering, truncation
    │   └── test_secure_storage.py     # Keyring exception handling, token storage/migration
    └── integration/
        └── test_mcp_tools.py          # _handle_client_errors, client reset on auth failure,
                                       #   concurrent init single-instance guarantee

Runtime Generated Files (not in repo):
~/.courtlistener_citations_mcp/
├── logs/
│   ├── courtlistener_citations_mcp.log  # Application logs (10MB rotation, 5 backups)
│   └── security.log                  # Security events (10MB rotation, 10 backups)
└── .courtlistener_api_token          # Encrypted API token (DPAPI, Windows only)
```

## Troubleshooting

### Common Issues

#### API Token Issues
- **Symptom:** `ToolError: CourtListener API token not configured`
- **Solution:** Set `COURTLISTENER_API_TOKEN` env var, run `.\deploy\windows_setup.ps1`, or let elicitation prompt you

#### Docker: Token Not Found / Blank Token Warning
- **Symptom:** `The "COURTLISTENER_API_TOKEN" variable is not set. Defaulting to a blank string.` in `docker compose up` output
- **Cause:** Docker containers run Linux — Windows Credential Manager and DPAPI are not available inside the container
- **Solution:** Create a `.env` file in the project root containing `COURTLISTENER_API_TOKEN=your_token`, then `docker compose down && docker compose up -d`

#### Docker: Port Already Allocated
- **Symptom:** `Bind for 0.0.0.0:8000 failed: port is already allocated`
- **Cause:** Another container (e.g., graphiti-mcp) is using port 8000
- **Solution:** Stop the conflicting container first (`docker stop <name>`), then `docker compose up -d` — do not use `docker start` on a previously-failed container as it won't get the port binding

#### API v3 vs v4
- **Symptom:** 403 Forbidden on all data endpoints
- **Cause:** Using API v3 URL instead of v4
- **Solution:** Ensure base URL is `https://www.courtlistener.com/api/rest/v4`

#### Auth Header Format
- **Symptom:** 401 Unauthorized
- **Cause:** Using `Bearer` instead of `Token`
- **Solution:** Auth header must be `Authorization: Token {key}` (NOT `Bearer {key}`)

#### Citation-Lookup Returns Empty
- **Symptom:** Citation exists but returns no results
- **Cause:** Supreme Court cases may be indexed under different reporters (e.g., "573 U.S. 208" may not match but "134 S. Ct. 2347" does)
- **Solution:** This is why the fallback chain exists - use `courtlistener_search_cases` with the case name

#### MCP Server Won't Start
- **Cause:** Missing dependencies or incorrect paths
- **Solution:** Re-run setup script, restart all PowerShell windows, restart Claude Desktop and verify configuration

#### Virtual Environment Issues (Windows Setup)
- **Symptom:** "No pyvenv.cfg file" errors during `windows_setup.ps1`
- **Cause:** Claude Desktop locks `.venv` files when running
- **Solution:**
  1. Close Claude Desktop completely before running setup script
  2. Remove `.venv` folder: `Remove-Item ./.venv -Force -Recurse -ErrorAction SilentlyContinue`
  3. Run `.\deploy\windows_setup.ps1` again

#### Resetting MCP Installation

```powershell
# Navigate to the project directory
cd C:\Users\YOUR_USERNAME\courtlistener_citations_mcp

# Remove Python cache directories
Get-ChildItem -Path ./src -Directory -Recurse -Force | Where-Object { $_.Name -eq '__pycache__' } | Remove-Item -Recurse -Force

# Remove virtual environment
if (Test-Path ".venv") {
    Remove-Item ./.venv -Force -Recurse -ErrorAction SilentlyContinue
}

# Now you can run the setup script again
.\deploy\windows_setup.ps1
```

## Security & Production Readiness

### Security Features
- **Windows Credential Manager + DPAPI** - API tokens stored in Windows Credential Manager (via `keyring`) as the primary secure store, with a DPAPI-encrypted file fallback (user-specific encryption + 256-bit entropy). Tokens are automatically migrated from file to Credential Manager on first access.
- **SafeLogger with Auto-Sanitization** - Automatically masks 40-char hex tokens, `Token <hex>` auth headers, passwords, IPs, and emails in all log messages (CWE-532)
- **File-Based Logging with Rotation** - Persistent audit trail with 10MB rotation, separate security logs with 10 backups (CWE-778)
- **Environment variable tokens** - No hardcoded credentials anywhere in codebase
- **Tokens never logged** - API tokens never included in error messages or log output
- **`User-Agent` header** - Identifies the MCP to CourtListener
- **Rate limiting** - Dual token-bucket limiters (83 req/min general, 60 valid-citations/min for citation-lookup) prevent API abuse and stay within CourtListener's 5,000/hr cap

### Error Handling
- **Retry with exponential backoff** - 3 attempts for transient failures (429, 5xx)
- **Smart retry strategy** - Doesn't retry authentication errors or client errors (4xx)
- **Graceful fallback** - DPAPI unavailable on Linux? Falls back to env var (no crash)
- **Connection pooling** - httpx async client with keep-alive for performance

## Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## License

MIT License

## Disclaimer

**THIS SOFTWARE IS PROVIDED "AS IS" AND WITHOUT WARRANTY OF ANY KIND.**

**Independent Project Notice**: This is an independent personal project and is not affiliated with, endorsed by, or sponsored by Free Law Project or CourtListener.

The author makes no representations or warranties, express or implied, including but not limited to:

- **Accuracy & AI-Generated Content**: No guarantee of data accuracy, completeness, or fitness for any purpose. Users are specifically cautioned that outputs generated or assisted by Artificial Intelligence (AI) components may be inaccurate, incomplete, fictionalized, or represent "hallucinations" by the AI model. This tool helps *detect* such hallucinations but cannot guarantee 100% detection.
- **Availability**: CourtListener API dependencies may cause service interruptions.
- **Legal Advice**: This tool provides data access and processing only, not legal counsel. All results must be independently verified, critically analyzed, and professionally judged by qualified legal professionals.
- **Coverage Gaps**: CourtListener does not index every case. A citation returning 404 does NOT definitively mean it is fabricated - it may simply not be in the database. Always use the fallback chain and exercise professional judgment.
- **Commercial Use**: Users must verify CourtListener terms of service for commercial applications.

**LIMITATION OF LIABILITY:** Under no circumstances shall the author be liable for any direct, indirect, incidental, special, or consequential damages arising from use of this software, even if advised of the possibility of such damages.

### USER RESPONSIBILITY

- **Independent Verification**: All outputs MUST be thoroughly reviewed, independently verified, and corrected by a human prior to any reliance, action, or submission to any court or entity.
- **Professional Judgment**: This tool is a supplement, not a substitute, for your own professional judgment and expertise.
- **Security**: Maintain secure handling of API credentials.
- **Testing**: Test thoroughly before production use.

**By using this software, you acknowledge that you have read this disclaimer and agree to use the software at your own risk, accepting full responsibility for all outcomes.**

> **Note for Legal Professionals:** While this tool validates citations against the CourtListener database, a "valid" result only confirms the citation exists in CourtListener's index - it does not verify that the citation supports the legal proposition for which it is cited. Professional analysis is always required.

## Related Links

- [CourtListener](https://www.courtlistener.com/) - Free legal research platform by Free Law Project
- [CourtListener API Documentation](https://www.courtlistener.com/help/api/)
- [Free Law Project](https://free.law/) - Non-profit operating CourtListener
- [Model Context Protocol](https://modelcontextprotocol.io)
- [Claude](https://claude.ai)
- [uv Package Manager](https://github.com/astral-sh/uv)

## Support This Project

If you find this CourtListener Citation Validation MCP Server useful, please consider supporting the development!

[![Donate with PayPal](https://www.paypalobjects.com/en_US/i/btn/btn_donateCC_LG.gif)](https://paypal.me/walkoe)

Your support helps maintain and improve this open-source tool. Thank you!

## Acknowledgments

- [Free Law Project](https://free.law/) for operating CourtListener and providing the REST API
- [eyecite](https://github.com/freelawproject/eyecite) (Free Law Project) for the local citation extraction library used in `courtlistener_extract_citations`
- [blakeox/courtlistener-mcp](https://github.com/blakeox/courtlistener-mcp) — prior CourtListener MCP implementation; some architectural patterns and tool design informed by this work
- [JamesANZ/us-legal-mcp](https://github.com/JamesANZ/us-legal-mcp) — US legal research MCP; citation validation workflow concepts referenced during design
- [Model Context Protocol](https://modelcontextprotocol.io/) for the MCP specification
- **[Claude Code](https://claude.ai/code)** for development assistance, architectural guidance, and documentation
- **[Claude Desktop](https://claude.ai)** for additional development support and testing

---

**Questions?** Review the troubleshooting section above, use `courtlistener_citations_get_guidance(section='overview')` for workflow help, or check `.\deploy\manage_api_keys.ps1 -Action test` to verify your API connection.
