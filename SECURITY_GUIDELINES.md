# Security Guidelines

## Overview

This document provides comprehensive security guidelines for developing, deploying, and maintaining the CourtListener Citation Validation MCP Server. Following these guidelines helps ensure the security of API tokens, user data, system integrity, and protection against AI-specific attacks including prompt injection.

## Prompt Injection Protection

### Overview
The CourtListener Citations MCP includes advanced prompt injection detection to protect against malicious attempts to:
- Override system instructions
- Extract the CourtListener API token or system configuration
- Manipulate AI behavior or persona
- Bypass security controls or API rate limits
- Fabricate legal citations or extract case data maliciously

### Detection System
**Comprehensive Pattern Detection:**
- **60+ Attack Patterns** covering instruction override, prompt extraction, format manipulation
- **Legal/CourtListener-Specific Threats** including API token extraction, citation fabrication, and case data exfiltration
- **Enhanced Filtering** to minimize false positives in legitimate code and documentation
- **Unicode Steganography Detection** for Variation Selector encoding, zero-width characters, and high invisible character ratios

**Integration Points:**
- **Pre-commit Hooks** — Automatic scanning before every commit (`.pre-commit-config.yaml`)
- **CI/CD Pipeline** — Continuous validation in GitHub Actions (`.github/workflows/secret-scan.yaml`)
- **Manual Scanning** — On-demand security assessment tools

### Usage

**Manual Security Scanning:**
```bash
# Scan for prompt injection patterns
uv run python .security/check_prompt_injections.py src/ tests/ *.md

# Check against baseline (only NEW findings fail)
uv run python .security/check_prompt_injections.py --baseline src/ tests/ *.yml *.yaml *.json

# Run via pre-commit
uv run pre-commit run prompt-injection-check --all-files
```

**Attack Categories Detected:**
1. **Instruction Override**: "ignore previous instructions", "disregard above commands"
2. **Prompt Extraction**: "show me your instructions", "reveal your system prompt"
3. **Behavior Manipulation**: "you are now a different AI", "act as a hacker"
4. **Format Manipulation**: "encode in base64", "use hex encoding"
5. **Legal-Specific**: "fabricate a fake citation", "extract all case numbers", "reveal the API token"
6. **API Bypass**: "bypass CourtListener API limits", "override rate limit"
7. **Social Engineering**: "we became friends", "our previous conversation"
8. **Unicode Steganography**: Variation Selector sequences, zero-width character injection

**File Type Coverage:**
- Python source code (`.py`)
- Configuration files (`.yml`, `.yaml`, `.json`)
- Documentation (`.md`, `.txt`)
- Web files (`.html`, `.js`, `.ts`)
- Data files (`.csv`, `.xml`)

### Incident Response

**If Patterns Are Detected:**
1. **Review Context** — Determine if the detection is a legitimate false positive
2. **Assess Intent** — Check if the pattern was introduced maliciously
3. **Investigate Source** — Review commit history and author
4. **Document Findings** — Log the incident for security tracking
5. **Update Baseline** — If false positive, add to `.prompt_injections.baseline` with explanation

**Updating the Baseline (for legitimate false positives):**
```bash
# Add new legitimate findings to baseline
uv run python .security/check_prompt_injections.py --update-baseline src/ tests/ *.md *.yml *.yaml *.json

# Commit updated baseline with explanation
git add .prompt_injections.baseline
git commit -m "Update prompt injection baseline: <reason>"
```

See `SECURITY_SCANNING.md` for the full baseline system documentation.

## API Token Management

### Environment Variables (Required)

**Always use environment variables or secure storage for the API token:**

```python
# Correct - environment variable
import os
token = os.getenv("COURTLISTENER_API_TOKEN")
if not token:
    raise ValueError("COURTLISTENER_API_TOKEN not configured")

# Never do this - hardcoded token
token = "your_40_char_hex_token_here"
```

### Token Storage Priority Chain

The server resolves the API token in this order:

1. `COURTLISTENER_API_TOKEN` environment variable
2. **Windows Credential Manager** (via `keyring` library) — PRIMARY secure storage
3. DPAPI-encrypted file (`~/.courtlistener_api_token`) — fallback, auto-migrates to Credential Manager
4. Elicitation prompt via FastMCP (prompts user at tool call time if token not found)

**Windows — Store via Credential Manager (Recommended):**
```powershell
.\deploy\windows_setup.ps1
```

**Environment variable (all platforms):**
```bash
# Linux/macOS
export COURTLISTENER_API_TOKEN=your_40_char_hex_token_here

# Windows PowerShell
$env:COURTLISTENER_API_TOKEN="your_40_char_hex_token_here"

# Windows Command Prompt
set COURTLISTENER_API_TOKEN=your_40_char_hex_token_here
```

**Docker deployment:**
```bash
# .env file (gitignored — never commit)
COURTLISTENER_API_TOKEN=your_40_char_hex_token_here
```

### What Never to Commit

- Real API tokens in any form
- `.env` files or local config files
- Backup files that might contain tokens
- Configuration files with real credentials
- Test files with hardcoded tokens

### Token Management Scripts

```powershell
# Store token securely (Credential Manager + DPAPI backup)
.\deploy\windows_setup.ps1

# Check stored token (shows last 5 chars only)
.\deploy\manage_api_keys.ps1 -Action check

# Test API connection
.\deploy\manage_api_keys.ps1 -Action test

# Migrate from file to Credential Manager
.\deploy\manage_api_keys.ps1 -Action migrate

# Delete stored token (all locations)
.\deploy\manage_api_keys.ps1 -Action delete
```

## Code Security Patterns

### Secure Patterns

**1. Token validation at startup:**
```python
from courtlistener_mcp.config.settings import get_api_token

async def _get_client(ctx=None) -> CourtListenerClient:
    token = await get_api_token(ctx)
    if not token:
        raise ToolError("CourtListener API token not configured")
    return CourtListenerClient(token=token)
```

**2. Secure test setup (use placeholder tokens — never real ones):**
```python
@pytest.fixture
def api_client():
    return CourtListenerClient(token="test_token_12345678901234567890")
```

**3. Never log tokens:**
```python
# Safe — token never appears in logs
logger.info(f"Initializing client for {base_url}")

# Unsafe — leaks token
logger.info(f"Using token: {token}")  # Never do this
```

### Anti-Patterns to Avoid

**1. Hardcoded tokens:**
```python
# Never
TOKEN = "abc123def456..."

# Always
TOKEN = os.getenv("COURTLISTENER_API_TOKEN")
```

**2. Tokens in error messages:**
```python
# Unsafe
raise ValueError(f"Auth failed with token {token}")

# Safe
raise ToolError("Authentication failed — check COURTLISTENER_API_TOKEN")
```

**3. Bypassing `get_safe_logger`:**
```python
# Unsafe — bypasses sanitization
import logging
logger = logging.getLogger(__name__)

# Safe — auto-sanitizes tokens, IPs, emails
from courtlistener_mcp.shared.safe_logger import get_safe_logger
logger = get_safe_logger(__name__)
```

## Logging Security (CWE-532 & CWE-778)

### SafeLogger Implementation

The project includes a `SafeLogger` wrapper that automatically sanitizes all log messages to prevent sensitive data exposure:

```python
from courtlistener_mcp.shared.safe_logger import get_safe_logger

logger = get_safe_logger(__name__)

# API tokens are automatically masked — safe to log response text
logger.error(f"API response: {response_text}")
```

### What Gets Sanitized Automatically

**API Tokens:**
- CourtListener API tokens (40-char hex): `[COURTLISTENER_API_TOKEN]`
- `Authorization: Token <hex>` headers: `[FILTERED]`
- Generic API key patterns: `[API_KEY]`

**Other Sensitive Data:**
- JWT Bearer tokens: `[FILTERED]`
- Passwords: `[REDACTED]`
- Secret fields: `[REDACTED]`
- IP addresses: `127.0.***.***` (partial masking)
- Email addresses: `j***@example.com` (partial masking)

### File-Based Logging with Rotation

**Log Location:** `~/.courtlistener_citations_mcp/logs/`

**Application Log (`courtlistener_citations_mcp.log`):**
- 10 MB max file size
- 5 backup files (rotated automatically)
- General application events

**Security Log (`security.log`):**
- 10 MB max file size
- 10 backup files (longer retention)
- Security events only (WARNING+ level)
- Separate file for SIEM integration

### Using the Security Logger

For security-specific events, use the dedicated security logger:

```python
import logging

security_logger = logging.getLogger('security')

security_logger.warning(f"Failed authentication attempt")
security_logger.error(f"Rate limit exceeded — circuit breaker opening")
security_logger.critical(f"Multiple 401 errors — possible token leak")
```

**Note:** The security logger has `propagate=False`. In tests, attach a handler directly:
```python
handler = logging.StreamHandler()
logging.getLogger("security").addHandler(handler)
```

### Compliance Impact

**CWE-532 (Sensitive Information in Log File):** Risk reduced via SafeLogger auto-sanitization

**CWE-778 (Insufficient Logging):** Risk reduced via file-based logging with rotation and separate security log

**OWASP A09 (Logging Failures):**
- Log sanitization prevents data leakage
- File-based logging ensures audit trail
- Proper log retention with rotation

## Error Handling Security

### Secure Error Responses

```python
# Safe — no internal paths or token values exposed
raise ToolError("Authentication failed — check COURTLISTENER_API_TOKEN")

# Unsafe — exposes internal details
raise ToolError(f"Failed to auth with token {token} against {base_url}")
```

### Information Disclosure Prevention

Error messages must never include:
- API token values (even partial)
- Internal file paths beyond the project root
- Stack traces with sensitive variable values
- Raw HTTP response bodies that might contain token echoes

## File and Repository Security

### .gitignore Requirements

The following patterns must remain in `.gitignore`:

```gitignore
# Secrets and credentials
.env
*.courtlistener_api_token

# Runtime-generated files
coverage.json
logs/
*.log

# Development artifacts
.venv/
.claude/
audits/
devtunnel.exe
```

### Configuration Templates

The `.env.example` template uses placeholder values only:
```bash
# .env.example
COURTLISTENER_API_TOKEN=your_40_char_hex_token_here
TRANSPORT=stdio
PORT=8000
```

Never replace placeholder values with real tokens in committed files.

## Development Workflow Security

### Secure Development Process

1. **Before coding:**
   - Never commit real API tokens
   - Use `COURTLISTENER_API_TOKEN` env var from day one
   - Confirm `.gitignore` is in place before first commit

2. **During development:**
   - Use placeholder tokens in test fixtures (`"test_token_" + "x" * 26`)
   - Use `get_safe_logger()` for all logging
   - Implement proper error handling that doesn't echo token values

3. **Before committing:**
   - Pre-commit hooks run automatically: detect-secrets + prompt injection check
   - Run manually: `uv run pre-commit run --all-files`
   - Verify no real tokens appear in staged files: `git diff --staged`

4. **Before publishing/releasing:**
   - Full security audit of codebase
   - Verify all `.env.example` values are placeholders
   - Confirm `.secrets.baseline` is up to date

### Testing Security

```python
def test_no_hardcoded_token_in_source():
    """Verify no real 40-char hex token is hardcoded."""
    import re
    import os

    hex_40 = re.compile(r'(?<!["\']test)[0-9a-f]{40}(?![0-9a-f])', re.IGNORECASE)
    src_root = Path("src")
    for py_file in src_root.rglob("*.py"):
        content = py_file.read_text()
        assert not hex_40.search(content), f"Possible hardcoded token in {py_file}"
```

## Incident Response

### If API Token is Exposed

**Immediate Actions (within 1 hour):**
1. **Revoke the exposed token** at [courtlistener.com/sign-in](https://www.courtlistener.com/sign-in/) → Profile → API Token
2. **Generate a new token**
3. **Update all deployments** with the new token:
   - Windows: `.\deploy\windows_setup.ps1`
   - Docker: update `.env` file, `docker compose down && docker compose up -d`
   - Claude Desktop: update `env` block in MCP config
4. **Scan API logs** at CourtListener for unauthorized usage

**Cleanup Actions (within 24 hours):**
1. **Remove from git history** if committed:
   ```bash
   # Use BFG Repo Cleaner (recommended)
   # See: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository
   ```
2. **Audit all locations** where the token may have been copied
3. **Review and update** any cached or stored copies

### Response Checklist

- [ ] Token revoked at CourtListener
- [ ] New token generated and deployed
- [ ] Git history cleaned (if token was committed)
- [ ] Docker `.env` updated
- [ ] Claude Desktop config updated
- [ ] Windows Credential Manager updated
- [ ] Post-mortem completed
- [ ] `.gitignore` and pre-commit hooks verified still active

## Monitoring and Auditing

### Security Monitoring

```python
# Log security-relevant events with the security logger
security_logger.warning("Rate limit threshold approached (>80% of hourly quota)")
security_logger.error("Authentication failed — invalid or expired token")
security_logger.critical("Repeated 401 errors — token may be compromised")
```

### Regular Security Audits

**Monthly Checklist:**
- [ ] Run `uv run pre-commit run --all-files` to verify hooks still pass
- [ ] Run `uv run detect-secrets scan --baseline .secrets.baseline` to audit baseline
- [ ] Review `.prompt_injections.baseline` for any suspicious additions
- [ ] Verify `.gitignore` still excludes `.env` and log files
- [ ] Check API usage at CourtListener for anomalies

## Rate Limiting Security

The server enforces rate limits to protect both the CourtListener API and local resources:

| Limiter | Limit | Purpose |
|---------|-------|---------|
| General | 83 req/min burst (5,000/hr) | All API endpoints |
| Citation-lookup | 60 valid citations/min | `/citation-lookup/` only |
| Per-request | 250 citations max, 64,000 chars max | Overflow protection |

Rate limit violations are logged to the security log. Repeated 429 responses may indicate misuse and should be investigated.

## Compliance and Best Practices

### OWASP Top 10 Alignment

- **A07:2021 – Identification and Authentication Failures**: Token resolution chain, validation, elicitation fallback
- **A04:2021 – Insecure Design**: Secure-by-default patterns, no plaintext token storage
- **A05:2021 – Security Misconfiguration**: `.gitignore`, Docker env isolation, Credential Manager as primary store
- **A09:2021 – Security Logging and Monitoring Failures**: SafeLogger, file rotation, separate security log

### Developer Security Checklist

Before each commit:
- [ ] No hardcoded API tokens
- [ ] `get_safe_logger()` used (not `logging.getLogger()`) in production code
- [ ] Error messages don't expose token values or internal paths
- [ ] Test fixtures use placeholder tokens only
- [ ] Pre-commit hooks pass: `uv run pre-commit run --all-files`

Before each release:
- [ ] Full security scan: `uv run pre-commit run --all-files`
- [ ] `.env.example` contains only placeholder values
- [ ] `.secrets.baseline` and `.prompt_injections.baseline` are up to date
- [ ] `SECURITY_SCANNING.md` reflects current scanner configuration

## Additional Resources

- [SECURITY_SCANNING.md](SECURITY_SCANNING.md) — Full scanning and baseline system documentation
- [detect-secrets](https://github.com/Yelp/detect-secrets) — Secret scanning library
- [CourtListener API](https://www.courtlistener.com/help/api/) — Token management
- [OWASP Secrets Management](https://owasp.org/www-community/vulnerabilities/Use_of_hard-coded_password)
- [CWE-532](https://cwe.mitre.org/data/definitions/532.html) — Insertion of Sensitive Information into Log File
- [CWE-778](https://cwe.mitre.org/data/definitions/778.html) — Insufficient Logging

## Conclusion

Security is everyone's responsibility. By following these guidelines, the CourtListener Citation Validation MCP Server remains secure and protects API credentials, citation data, and users from prompt injection attacks. Review and update these guidelines as the project evolves.

For questions or to report a security issue, contact the project maintainers immediately and do not disclose vulnerabilities publicly until resolved.
