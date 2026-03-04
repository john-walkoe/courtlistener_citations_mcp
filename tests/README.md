# Test Suite

This directory contains all automated tests for the CourtListener Citation Validation MCP Server. The suite covers the full tool stack: local eyecite extraction, API client behavior, secure storage, log sanitization, and MCP server integration.

## Test Results (136 tests, 100% passing)

```
tests/integration/test_mcp_tools.py      15 tests  ✅
tests/unit/test_client.py                34 tests  ✅
tests/unit/test_extract_citations.py     36 tests  ✅
tests/unit/test_log_sanitizer.py         27 tests  ✅
tests/unit/test_secure_storage.py        24 tests  ✅
─────────────────────────────────────────────────
Total:                                  136 tests  ✅
```

## Available Tools Under Test (7 Tools)

### Discovery Tool (Local — No API)
- **`courtlistener_extract_citations`** — Extracts all citation types locally via eyecite (no API key, no rate limits)

### Citation Validation Tools (3-Tool Fallback Chain)
- **`courtlistener_validate_citations`** — Primary citation validation via CourtListener `/citation-lookup/`
- **`courtlistener_search_cases`** — Fallback search by case name when citation returns 404
- **`courtlistener_lookup_citation`** — Last resort direct reporter citation lookup

### Supporting Tools
- **`courtlistener_get_cluster`** — Fetch full case details and CourtListener URLs by cluster ID
- **`courtlistener_search_clusters`** — Search opinion clusters with filters
- **`courtlistener_citations_get_guidance`** — Sectioned workflow guidance (no API call)

## Test Structure

```
tests/
├── conftest.py                    # Shared fixtures (api_client, sample responses, global reset)
├── unit/
│   ├── test_client.py             # API client: rate limiting, chunking, throttle parsing,
│   │                              #   HTTP errors, citation validation, security logging
│   ├── test_extract_citations.py  # eyecite extraction: all citation types, id/supra resolution,
│   │                              #   empty text guard, async JSON return
│   ├── test_log_sanitizer.py      # Token masking, ANSI/injection filtering, truncation,
│   │                              #   header sanitization, JSON sanitization
│   └── test_secure_storage.py     # Keyring get/store/delete, DPAPI fallback, migration,
│                                  #   file permissions, token validation
└── integration/
    └── test_mcp_tools.py          # _handle_client_errors decorator, client reset on auth
                                   #   failure, concurrent init single-instance guarantee
```

## Running Tests

### Run All Tests (Recommended)

```bash
uv run pytest tests/
```

### Run with Verbose Output

```bash
uv run pytest tests/ -v
```

### Run Specific Test File

```bash
uv run pytest tests/unit/test_client.py -v
uv run pytest tests/unit/test_extract_citations.py -v
uv run pytest tests/unit/test_log_sanitizer.py -v
uv run pytest tests/unit/test_secure_storage.py -v
uv run pytest tests/integration/test_mcp_tools.py -v
```

### Run a Specific Test Class or Test

```bash
# Run a full test class
uv run pytest tests/unit/test_client.py::TestRateLimiter -v

# Run a single test
uv run pytest tests/unit/test_extract_citations.py::TestCaseCitations::test_multiple_case_citations -v
```

### Run with Coverage Report

```bash
uv run pytest tests/ --cov=courtlistener_mcp --cov-report=term-missing
```

## Test File Reference

### `tests/unit/test_client.py` — API Client (34 tests)

Tests the `CourtListenerClient` HTTP layer including all rate limiting, retry, and validation logic.

| Class | Tests | What It Covers |
|-------|-------|----------------|
| `TestRateLimiter` | 3 | Token bucket: initial capacity, no-sleep on available tokens, throttle on empty bucket |
| `TestChunkText` | 5 | Text splitting: no-op for short text, sentence boundary, space fallback, empty string, max chunk length |
| `TestParseThrottleWait` | 4 | 429 parsing: `wait_until` ISO-8601 field, `Retry-After` header, default fallback, minimum 1-second floor |
| `TestValidateSearchParams` | 6 | Search validation: valid/invalid date formats, oversized query, `None` params, boundary length |
| `TestClientRequest` | 7 | HTTP layer: 200 success, 401/403 raise auth error, 404 raises not-found, 500 retry then succeed, 500 exhaust retries, 429 retry |
| `TestValidateCitations` | 5 | Citation endpoint: blank/whitespace text returns empty, oversized text rejected, success path, large text auto-chunked |
| `TestSecurityLogging` | 4 | Security log: 401/403/429 write to `security` logger, module-level logger defined |

**Expected output:**
```
tests/unit/test_client.py::TestRateLimiter::test_rate_limiter_has_full_tokens_initially PASSED
...
34 passed in 0.Xs
```

---

### `tests/unit/test_extract_citations.py` — eyecite Local Extraction (36 tests)

Tests the `courtlistener_extract_citations` tool and the underlying `_extract_citations_sync` helper. All tests run without any API call.

| Class | Tests | What It Covers |
|-------|-------|----------------|
| `TestCaseCitations` | 9 | Case citation extraction, reporter/volume/page/text metadata, plaintiff metadata, year parsing, multiple citations, Federal Circuit format |
| `TestStatutoryCitations` | 4 | Statutory citation extraction, text field, note field, not included in case_citations list |
| `TestJournalCitations` | 2 | Law journal citation extraction, note field |
| `TestIdSupraCitations` | 5 | `id.` citation extraction, text field, antecedent resolution, reporter in antecedent, pin cite |
| `TestSummaryStructure` | 9 | Summary keys, result sections, total equals sum of parts, empty text returns zeros, no-citation text, guidance next_steps, guidance references validate_citations, guidance mentions statute limit, empty text guidance message |
| `TestMixedDocument` | 4 | Mixed document: case citations found, statutory citation found, id. citation found, total is sum |
| `TestExtractCitationsAsyncTool` | 3 | ImportError raises ToolError, returns JSON string, logs info with char count |

**Key behaviors tested:**
- Empty string guard: `eyecite` raises `ValueError` on `""` — the tool returns a zero-count result instead of crashing
- `id.` antecedent resolution: resolves to the preceding full case citation within the same text chunk
- No `__wrapped__` on this tool — tests call `await extract_citations(ctx, text)` directly (tool is not decorated with `@_handle_client_errors`)

**Expected output:**
```
tests/unit/test_extract_citations.py::TestCaseCitations::test_extracts_case_citation PASSED
...
36 passed in 0.Xs
```

---

### `tests/unit/test_log_sanitizer.py` — Log Sanitization (27 tests)

Tests the `LogSanitizer` and `SafeLogger` components that prevent sensitive data from appearing in log output.

| Class | Tests | What It Covers |
|-------|-------|----------------|
| `TestTokenMasking` | 3 | Masks `Authorization: Token <hex>`, bare 40-char hex tokens, verifies token not in output |
| `TestControlCharacters` | 4 | Strips null byte, SOH, BEL, multiple control chars |
| `TestAnsiEscapeSequences` | 2 | Filters ANSI escape sequences, removes escape byte |
| `TestLogInjectionPrevention` | 3 | Prevents `\n`, `\r`, `\r\n` injection in log messages |
| `TestStringTruncation` | 3 | Truncates long strings, passes short strings unchanged, respects custom max_length |
| `TestSanitizeHeaders` | 4 | Removes `Authorization` header, removes `X-Api-Key` header, does not mutate original dict, preserves safe headers |
| `TestSanitizeForJson` | 5 | Handles dict, list, nested dict, `None` values, numeric values |
| `TestEdgeCases` | 3 | Empty string, non-string input, safe unicode content |

**Key behavior:** The security logger (`logging.getLogger("security")`) has `propagate=False`. Tests that assert on security log output must attach a handler directly to `logging.getLogger("security")`, not use `caplog`.

**Expected output:**
```
tests/unit/test_log_sanitizer.py::TestTokenMasking::test_masks_courtlistener_api_token PASSED
...
27 passed in 0.Xs
```

---

### `tests/unit/test_secure_storage.py` — Secure Token Storage (24 tests)

Tests the `keyring` Credential Manager layer and DPAPI file fallback for storing and retrieving the CourtListener API token.

| Class | Tests | What It Covers |
|-------|-------|----------------|
| `TestGetTokenFromKeyring` | 5 | Returns `None` on ImportError/OSError/RuntimeError, returns token on success, returns `None` when `get_password` returns `None` |
| `TestStoreTokenInKeyring` | 4 | Returns `False` on OSError/RuntimeError/ImportError, returns `True` on success |
| `TestDeleteTokenFromKeyring` | 3 | Returns `False` on OSError/RuntimeError, returns `True` on success |
| `TestRestrictFilePermissions` | 4 | Silent on subprocess error, silent on OSError, POSIX uses `chmod`, POSIX silent on OSError |
| `TestMigrateFileToKeyring` | 3 | Silent on ImportError/OSError, stores when file token present |
| `TestStoreApiToken` | 5 | Rejects empty string, rejects whitespace, strips and stores, falls back to file when keyring fails, returns `False` when both fail |

**Expected output:**
```
tests/unit/test_secure_storage.py::TestGetTokenFromKeyring::test_get_token_from_keyring_returns_none_on_import_error PASSED
...
24 passed in 0.Xs
```

---

### `tests/integration/test_mcp_tools.py` — MCP Server Integration (15 tests)

Tests the MCP server layer: the `_handle_client_errors` decorator, client lifecycle (reset on auth failure), and concurrent initialization safety.

| Class | Tests | What It Covers |
|-------|-------|----------------|
| `TestHandleClientErrors` | 9 | Passes through `ToolError`, converts `ValueError`/timeout/`RequestError`/401/403/404/5xx to `ToolError`, returns value on success |
| `TestClientResetOnAuthError` | 3 | Auth error resets `_client` to `None`, non-auth `ToolError` does not reset, plain `ToolError` does not reset |
| `TestConcurrentClientInit` | 3 | Concurrent calls create exactly one client instance (async lock), raises `ToolError` without token, returns existing client when already initialized |

**Expected output:**
```
tests/integration/test_mcp_tools.py::TestHandleClientErrors::test_handle_client_errors_passes_through_tool_error PASSED
...
15 passed in 0.Xs
```

---

### `tests/conftest.py` — Shared Fixtures

Provides pytest fixtures shared across all test files:

| Fixture | Scope | Returns |
|---------|-------|---------|
| `api_client` | function | `CourtListenerClient` with `token="test_token_12345678901234567890"` |
| `sample_citation_response` | function | Bare list with one 200 result (Alice Corp.) and one 404 result |
| `sample_search_response` | function | Search response dict with `count=1`, Alice Corp. result |
| `reset_global_client` | function (autouse) | Resets `_client = None` before and after each test for isolation |

## API Token for Tests

**No real CourtListener API token is required to run the test suite.** All tests use mocked HTTP responses (`respx` library) or test placeholder tokens (`"test_token_12345678901234567890"`).

If you want to run live integration tests against the real CourtListener API, set the environment variable:
```bash
export COURTLISTENER_API_TOKEN=your_40_char_hex_token_here
```

Live API calls are not part of the automated test suite — use the MCP tools directly in Claude to test against the real API.

## Prerequisites

```bash
# Install all dev dependencies
uv pip install -e ".[dev]"

# Or with pip
pip install -e ".[dev]"
```

**Required dev dependencies** (from `pyproject.toml [dev]`):
- `pytest` — test runner
- `pytest-asyncio` — async test support
- `pytest-cov` — coverage reporting
- `respx` — httpx request mocking
- `anyio` — async utilities

## Gotchas and Known Behaviors

### Security Logger and `caplog`

The `security` logger has `propagate=False` (intentional — keeps security events out of the root logger). Tests that assert on security log messages must attach a handler directly:

```python
import logging

def test_security_event():
    records = []
    handler = logging.StreamHandler()
    handler.emit = lambda r: records.append(r)
    logging.getLogger("security").addHandler(handler)
    # ... trigger the event ...
    assert any("expected message" in r.getMessage() for r in records)
```

### `extract_citations` Has No `__wrapped__`

`courtlistener_extract_citations` is not decorated with `@_handle_client_errors` (which uses `functools.wraps` and sets `__wrapped__`). Call the tool directly in tests:

```python
# Correct
result = await extract_citations(ctx, text="...")

# Wrong — extract_citations has no __wrapped__
result = await extract_citations.__wrapped__(ctx, text="...")
```

### eyecite Raises `ValueError` on Empty String

`get_citations("")` raises `ValueError: Both markup_text and plain_text are empty`. The tool guards against this and returns a zero-count result. Tests for empty/whitespace text verify this behavior:

```python
result = await extract_citations(ctx, text="")
data = json.loads(result)
assert data["summary"]["total"] == 0
```

### Global `_client` Reset Between Tests

`conftest.py` has an autouse fixture (`reset_global_client`) that resets the module-level `_client` variable to `None` before and after every test. This prevents test pollution from singleton client state.
