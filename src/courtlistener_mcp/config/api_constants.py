"""
API Configuration Constants

Single source of truth for all configuration values.
No magic numbers anywhere in the codebase.
"""

# =============================================================================
# COURTLISTENER API
# =============================================================================

API_BASE_URL = "https://www.courtlistener.com/api/rest/v4"
"""CourtListener REST API v4 base URL"""

OPINION_URL_TEMPLATE = "https://www.courtlistener.com/opinion/{cluster_id}/{slug}/"
"""Template for CourtListener opinion URLs"""

# =============================================================================
# CONNECTION POOL
# =============================================================================

DEFAULT_MAX_CONNECTIONS = 20
"""Maximum total connections across all hosts"""

DEFAULT_MAX_KEEPALIVE_CONNECTIONS = 5
"""Maximum persistent keep-alive connections"""

DEFAULT_KEEPALIVE_EXPIRY_SECONDS = 5.0
"""Idle timeout for keep-alive connections"""

# =============================================================================
# TIMEOUTS
# =============================================================================

DEFAULT_TIMEOUT_SECONDS = 30
"""Default HTTP request timeout in seconds"""

CITATION_VALIDATION_TIMEOUT_SECONDS = 60
"""Extended timeout for citation validation (processes full documents)"""

# =============================================================================
# RATE LIMITING
# =============================================================================

RATE_LIMIT_REQUESTS_PER_HOUR = 5000
"""CourtListener authenticated user rate limit (requests/hour)"""

RATE_LIMIT_BURST_PER_MINUTE = 83
"""General API burst rate (requests/minute). 83 = floor(5000/60) keeps sustained
traffic at ~4,980/hr, safely under the documented 5,000/hr cap."""

CITATION_RATE_LIMIT_PER_MINUTE = 60
"""Citation-lookup endpoint throttle: 60 valid citations per minute"""

CITATION_MAX_PER_REQUEST = 250
"""Maximum citations looked up per single request (overflow gets 429 status)"""

CITATION_MAX_TEXT_LENGTH = 64000
"""Maximum text length for citation-lookup requests (chars, ~50 pages)"""

# =============================================================================
# SEARCH & PAGINATION
# =============================================================================

DEFAULT_PAGE_SIZE = 20
"""Default number of results per page"""

MAX_PAGE_SIZE = 100
"""Maximum results per page (API constraint)"""

MIN_PAGE_SIZE = 1
"""Minimum results per page"""

MAX_QUERY_LENGTH = 2000
"""Maximum combined query string length (characters)"""

MAX_VALIDATE_TEXT_LENGTH = 500_000
"""Maximum text input length for validate_citations (chars, ~390 pages)"""

# =============================================================================
# RETRY CONFIGURATION
# =============================================================================

DEFAULT_MAX_RETRIES = 3
"""Maximum retry attempts for recoverable errors"""

DEFAULT_RETRY_DELAY_SECONDS = 1.0
"""Base delay between retry attempts (exponential backoff)"""

RETRY_BACKOFF_FACTOR = 2.0
"""Multiplier for exponential backoff"""

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
"""HTTP status codes that trigger retry"""

# =============================================================================
# SECURITY & CRYPTOGRAPHY
# =============================================================================

DPAPI_ENTROPY_BYTES = 32
"""Cryptographically secure entropy size for DPAPI encryption (256 bits)"""

DPAPI_DESCRIPTION = "CourtListener MCP API Token"
"""Description stored with DPAPI-encrypted data"""

# =============================================================================
# STORAGE PATHS
# =============================================================================

SECURE_STORAGE_FILENAME = ".courtlistener_api_token"
"""Filename for DPAPI-encrypted API token (stored in user home directory)"""
