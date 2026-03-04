# Security Scanning Guide

This document explains the automated security scanning setup for the CourtListener Citation Validation MCP project.

## Overview

The project uses multiple security scanning technologies:
- **detect-secrets** to prevent accidental commits of API keys, tokens, passwords, and other sensitive data
- **Prompt Injection Detection** to protect against AI-specific attacks and malicious prompt patterns

## Features

### 1. CI/CD Secret Scanning (GitHub Actions)
- Automatically scans all code on push and pull requests
- Scans git history (last 100 commits) for accidentally committed secrets
- Fails the build if new secrets are detected
- Location: `.github/workflows/secret-scan.yaml`

### 2. Pre-commit Hooks (Local Development)
- Prevents committing secrets before they reach GitHub
- Runs automatically on `git commit`
- Location: `.pre-commit-config.yaml`

### 3. Baseline Management
- Tracks known placeholder keys and false positives
- Location: `.secrets.baseline`

### 4. Prompt Injection Detection with Baseline System
- Scans for 60+ malicious prompt patterns
- **Baseline system** to track known findings and only flag NEW patterns
- SHA256 fingerprinting for finding identification
- Detects legal/CourtListener-specific attack vectors
- Integrated with pre-commit hooks and CI/CD pipeline
- Location: `.security/check_prompt_injections.py`

**Attack Categories Detected:**
- Instruction override attempts ("ignore previous instructions")
- System prompt extraction ("show me your instructions")
- AI behavior manipulation ("you are now a different AI")
- Legal citation fabrication ("fabricate a fake citation")
- API token/credential extraction ("reveal the API token")
- CourtListener API bypass attempts ("bypass API rate limits")
- Case/judge data exfiltration ("extract all case numbers")
- Social engineering patterns ("we became friends")
- **Unicode steganography attacks** (Variation Selectors, zero-width characters)

### Unicode Steganography Detection

The detector includes comprehensive Unicode steganography detection to counter advanced threats:

**Detection Capabilities:**
- **Variation Selector Encoding**: Detects VS0/VS1 (U+FE00/U+FE01) binary encoding in emojis
- **Zero-Width Character Abuse**: Identifies suspicious use of invisible Unicode characters
- **High Invisible Character Ratios**: Flags content with >10% invisible-to-visible character ratios
- **Binary Pattern Recognition**: Detects 8+ bit sequences that could encode hidden messages

### Prompt Injection Baseline System

The prompt injection scanner uses a **baseline system** to track known findings and only flag **NEW** patterns. This solves the false positive problem from legitimate code while maintaining protection against attacks.

#### How It Works

1. **Baseline File**: `.prompt_injections.baseline` stores known findings
2. **Fingerprinting**: Each finding gets a unique SHA256 hash fingerprint
3. **Comparison**: Scanner checks if each finding is in the baseline
4. **Exit Codes**:
   - `0` - No NEW findings (all findings in baseline)
   - `1` - NEW findings detected (not in baseline)
   - `2` - Error occurred

#### Usage

**First run - Create baseline:**
```bash
uv run python .security/check_prompt_injections.py --update-baseline src/ tests/ *.md *.yml *.yaml *.json
```

**Normal run - Check against baseline:**
```bash
uv run python .security/check_prompt_injections.py --baseline src/ tests/ *.yml *.yaml *.json
```

**Update baseline to include new legitimate findings:**
```bash
uv run python .security/check_prompt_injections.py --update-baseline src/ tests/ *.md *.yml *.yaml *.json
```

**Force new baseline (overwrite existing):**
```bash
uv run python .security/check_prompt_injections.py --force-baseline src/ tests/ *.md *.yml *.yaml *.json
```

#### Command Line Options

| Option | Purpose |
|--------|---------|
| `--baseline` | Use existing baseline (only NEW findings fail) |
| `--update-baseline` | Add new findings to baseline |
| `--force-baseline` | Create new baseline (overwrite existing) |
| `--verbose, -v` | Show detailed output with full matches |
| `--quiet, -q` | Only show summary (suppress individual findings) |

#### When to Update Baseline

**DO Update Baseline When:**
- New legitimate code is flagged (variable names, class names, documentation)
- Approved refactoring changes line numbers
- Baseline is outdated

**DON'T Update Baseline When:**
- Malicious pattern detected (remove the code instead)
- You're unsure (ask for review first)
- Security-related finding (review carefully first)

## Setup

### Install Pre-commit Hooks (Recommended)

```bash
# Install pre-commit framework and detect-secrets
uv pip install pre-commit detect-secrets

# Install the git hooks
uv run pre-commit install

# Test the hooks (optional)
uv run pre-commit run --all-files
```

### Manual Security Scanning

**Secret Detection:**
```bash
# Scan entire codebase
uv run detect-secrets scan

# Update baseline after reviewing findings
uv run detect-secrets scan --baseline .secrets.baseline

# Audit baseline (review all flagged items)
uv run detect-secrets audit .secrets.baseline
```

**Prompt Injection Detection:**
```bash
# Scan for prompt injection patterns
uv run python .security/check_prompt_injections.py src/ tests/ *.md

# Run via pre-commit hook
uv run pre-commit run prompt-injection-check --all-files

# Test with verbose output
uv run python .security/check_prompt_injections.py --verbose src/ tests/
```

## What Gets Scanned

### Included:
- All Python source files (`src/`, `tests/`)
- Configuration files
- Shell scripts and workflows

### Excluded:
- `*.md` — Documentation with example secrets
- `*.lock` — Lock files
- `package-lock.json` — NPM lock file
- `.secrets.baseline` — Baseline file itself

## Handling Detection Results

### False Positives (Test/Example Secrets)

If detect-secrets flags a legitimate placeholder:

1. **Verify it's truly a placeholder** (not a real secret)
2. **Update the baseline** to mark it as known:
   ```bash
   uv run detect-secrets scan --baseline .secrets.baseline
   ```
3. **Commit the updated baseline**:
   ```bash
   git add .secrets.baseline
   git commit -m "Update secrets baseline after review"
   ```

### Real Secrets Detected

If you accidentally committed a real secret:

1. **Revoke the secret immediately** (regenerate the CourtListener API token)
2. **Remove from git history** using BFG Repo Cleaner or `git filter-branch`
3. **Update code to use environment variables**:
   ```python
   import os
   api_token = os.getenv("COURTLISTENER_API_TOKEN")  # Never hardcode!
   ```

## Best Practices

### DO:
- Store secrets in environment variables or Windows Credential Manager
- Use `.env` files (gitignored)
- Run `pre-commit run --all-files` before first commit
- Review baseline updates carefully

### DON'T:
- Hardcode API keys or tokens in source code
- Commit `.env` files
- Use real secrets in tests (use mocks/fixtures)
- Disable pre-commit hooks without review
- Ignore secret scanning failures in CI

## GitHub Actions Workflow

The workflow runs on:
- All pushes to `main`, `master`, and `develop` branches
- All pull requests to these branches

### Workflow Steps:
1. Checkout full git history
2. Install detect-secrets
3. Scan current codebase against baseline
4. Scan recent git history (last 100 commits)
5. Report findings and fail if secrets detected

## Secret Types Detected

The scanner detects 20+ types including:

- AWS Access Keys / Azure Storage Keys / GCP Service Account Keys
- GitHub Tokens / GitLab Tokens
- OpenAI API Keys / Anthropic API Keys
- Stripe / Twilio / SendGrid / Slack / Discord tokens
- Private SSH Keys / JWT Tokens
- High-Entropy Strings (Base64/Hex)
- Password Keywords

## Project-Specific Considerations

### CourtListener API Token
The CourtListener API token is a 40-character hex string. It must always be provided via:
1. `COURTLISTENER_API_TOKEN` environment variable
2. Windows Credential Manager (via keyring) — primary secure storage
3. DPAPI-encrypted file (`~/.courtlistener_api_token`) — fallback

Never hardcode the token. The `.env` file is gitignored.

### Test Files
Test files in `tests/` may contain placeholder tokens for validation testing (e.g., `"a" * 40`). These are tracked in `.secrets.baseline` and verified to be test-only placeholders.

## Additional Resources

- [detect-secrets Documentation](https://github.com/Yelp/detect-secrets)
- [Pre-commit Framework](https://pre-commit.com/)
- [GitHub Secret Scanning](https://docs.github.com/en/code-security/secret-scanning)
- [OWASP Secrets Management](https://owasp.org/www-community/vulnerabilities/Use_of_hard-coded_password)

## Questions?

See `README.md` for broader security practices or check `.\deploy\manage_api_keys.ps1 -Action test` to verify your API connection.
