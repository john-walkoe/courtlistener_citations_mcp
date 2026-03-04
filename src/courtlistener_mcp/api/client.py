"""
CourtListener API Client

Async HTTP client for CourtListener REST API v4.
Features: connection pooling, rate limiting, retry with exponential backoff.

Citation-lookup endpoint specifics (per official docs):
  - Throttle: 60 valid citations per minute
  - Max 250 citations looked up per request (overflow gets 429 status)
  - Max 64,000 characters per text request (~50 pages)
  - Uses form-encoded POST (not JSON)
  - Returns bare list (not wrapped in {results: [...]})
  - On rate limit: returns HTTP 429 with wait_until ISO-8601 datetime
"""

import asyncio
from datetime import datetime, timezone
import re
import time
from typing import Any, Optional

import httpx

from ..config.api_constants import (
    API_BASE_URL,
    CITATION_MAX_TEXT_LENGTH,
    CITATION_RATE_LIMIT_PER_MINUTE,
    CITATION_VALIDATION_TIMEOUT_SECONDS,
    DEFAULT_MAX_CONNECTIONS,
    DEFAULT_MAX_KEEPALIVE_CONNECTIONS,
    DEFAULT_MAX_RETRIES,
    DEFAULT_PAGE_SIZE,
    DEFAULT_RETRY_DELAY_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    MAX_PAGE_SIZE,
    MAX_QUERY_LENGTH,
    MAX_VALIDATE_TEXT_LENGTH,
    RATE_LIMIT_BURST_PER_MINUTE,
    RETRY_BACKOFF_FACTOR,
    RETRYABLE_STATUS_CODES,
)
from ..errors import AuthenticationError, NotFoundError, RateLimitError
from ..shared.safe_logger import get_safe_logger

import logging

logger = get_safe_logger(__name__)
security_logger = logging.getLogger("security")


def _chunk_text(text: str, max_length: int) -> list[str]:
    """Split text into chunks at sentence boundaries, respecting max length."""
    chunks: list[str] = []
    remaining = text

    while len(remaining) > max_length:
        # Find last sentence boundary before the limit
        cut = remaining[:max_length].rfind(". ")
        if cut == -1 or cut < max_length // 2:
            # No good sentence boundary - cut at last space
            cut = remaining[:max_length].rfind(" ")
        if cut == -1:
            cut = max_length

        chunks.append(remaining[: cut + 1])
        remaining = remaining[cut + 1 :]

    if remaining.strip():
        chunks.append(remaining)

    return chunks


def _parse_throttle_wait(response: httpx.Response) -> float:
    """Parse wait time from a 429 throttle response.

    The citation-lookup API returns a JSON body with a `wait_until` key
    containing an ISO-8601 datetime. Falls back to Retry-After header
    or a default 60-second wait.
    """
    try:
        body = response.json()
        wait_until = body.get("wait_until") or body.get("detail", "")
        if "wait_until" in body:
            dt = datetime.fromisoformat(wait_until.replace("Z", "+00:00"))
            delta = (dt - datetime.now(timezone.utc)).total_seconds()
            return max(1.0, delta)
    except (ValueError, KeyError, TypeError):
        pass

    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return max(1.0, float(retry_after))
        except ValueError:
            pass

    return 60.0


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_search_params(
    query: str | None = None,
    date_filed_after: str | None = None,
    date_filed_before: str | None = None,
) -> None:
    """Validate common search parameters before sending to the API."""
    if query and len(query) > MAX_QUERY_LENGTH:
        raise ValueError(f"Query exceeds {MAX_QUERY_LENGTH} characters")
    for name, val in [("date_filed_after", date_filed_after), ("date_filed_before", date_filed_before)]:
        if val and not _DATE_RE.match(val):
            raise ValueError(f"{name} must be YYYY-MM-DD format")


class RateLimiter:
    """Simple token bucket rate limiter."""

    def __init__(self, max_per_minute: int = RATE_LIMIT_BURST_PER_MINUTE):
        self._max_per_minute = max_per_minute
        self._tokens = float(max_per_minute)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a request token is available."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(
                self._max_per_minute,
                self._tokens + elapsed * (self._max_per_minute / 60.0),
            )
            self._last_refill = now

            if self._tokens < 1.0:
                wait_time = (1.0 - self._tokens) / (self._max_per_minute / 60.0)
                await asyncio.sleep(wait_time)
                self._tokens = 0.0
            else:
                self._tokens -= 1.0


class CourtListenerClient:
    """Async client for CourtListener REST API v4."""

    def __init__(self, token: str):
        self._token = token
        self._rate_limiter = RateLimiter()
        self._citation_rate_limiter = RateLimiter(
            max_per_minute=CITATION_RATE_LIMIT_PER_MINUTE
        )
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the httpx async client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=API_BASE_URL,
                headers={
                    "Authorization": f"Token {self._token}",
                    "Accept": "application/json",
                    "User-Agent": "CourtListener-MCP/1.0",
                },
                timeout=DEFAULT_TIMEOUT_SECONDS,
                limits=httpx.Limits(
                    max_connections=DEFAULT_MAX_CONNECTIONS,
                    max_keepalive_connections=DEFAULT_MAX_KEEPALIVE_CONNECTIONS,
                ),
                follow_redirects=False,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
        json_data: Optional[dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> dict[str, Any]:
        """
        Make an API request with rate limiting and retry.

        Args:
            method: HTTP method (GET, POST)
            path: API path (relative to base URL)
            params: Query parameters
            json_data: JSON body for POST requests
            timeout: Override default timeout

        Returns:
            Parsed JSON response

        Raises:
            httpx.HTTPStatusError: On non-retryable HTTP errors
            httpx.TimeoutException: On timeout after all retries
        """
        await self._rate_limiter.acquire()
        client = await self._get_client()

        last_error: Optional[Exception] = None

        for attempt in range(DEFAULT_MAX_RETRIES):
            try:
                kwargs: dict[str, Any] = {}
                if params:
                    kwargs["params"] = {
                        k: v for k, v in params.items() if v is not None
                    }
                if json_data:
                    kwargs["json"] = json_data
                if timeout:
                    kwargs["timeout"] = timeout

                response = await client.request(method, path, **kwargs)

                if response.status_code in RETRYABLE_STATUS_CODES:
                    delay = DEFAULT_RETRY_DELAY_SECONDS * (
                        RETRY_BACKOFF_FACTOR ** attempt
                    )
                    if response.status_code == 429:
                        delay = max(delay, _parse_throttle_wait(response))

                    logger.warning(
                        f"Retryable status {response.status_code} on {path}, "
                        f"attempt {attempt + 1}/{DEFAULT_MAX_RETRIES}, "
                        f"waiting {delay:.1f}s"
                    )
                    await asyncio.sleep(delay)
                    continue

                if response.status_code == 401:
                    security_logger.warning(
                        "Authentication failure: CourtListener API token invalid or expired (HTTP 401)"
                    )
                    raise AuthenticationError(
                        "CourtListener API token is invalid or expired. "
                        "Get a new token at: https://www.courtlistener.com/sign-in/"
                    )
                if response.status_code == 403:
                    security_logger.warning(
                        "Authentication failure: API token lacks permission for this endpoint (HTTP 403)"
                    )
                    raise AuthenticationError(
                        "API token lacks permission for this endpoint."
                    )
                if response.status_code == 404:
                    raise NotFoundError(f"Resource not found: {path}")

                response.raise_for_status()
                return response.json()

            except httpx.TimeoutException as e:
                last_error = e
                if attempt < DEFAULT_MAX_RETRIES - 1:
                    delay = DEFAULT_RETRY_DELAY_SECONDS * (
                        RETRY_BACKOFF_FACTOR ** attempt
                    )
                    logger.warning(
                        f"Timeout on {path}, attempt {attempt + 1}, "
                        f"retrying in {delay:.1f}s"
                    )
                    await asyncio.sleep(delay)
            except httpx.HTTPStatusError:
                raise
            except httpx.RequestError as e:
                last_error = e
                if attempt < DEFAULT_MAX_RETRIES - 1:
                    await asyncio.sleep(
                        DEFAULT_RETRY_DELAY_SECONDS * (RETRY_BACKOFF_FACTOR ** attempt)
                    )

        if last_error:
            raise last_error
        raise RuntimeError(f"All {DEFAULT_MAX_RETRIES} retries exhausted for {path}")

    # =========================================================================
    # CITATION TOOLS
    # =========================================================================

    async def validate_citations(self, text: str) -> list[dict[str, Any]]:
        """
        Extract and validate citations from document text via /citation-lookup/.

        Per CourtListener docs:
          - Uses form-encoded POST with 'text' field
          - Returns bare list of citation objects
          - Status codes per citation: 200 (found), 300 (ambiguous),
            400 (bad reporter), 404 (not found), 429 (overflow)
          - Throttle: 60 valid citations per minute (API-enforced)
          - Max 250 citations per request (overflow gets status 429)
          - Max 64,000 chars per request (~50 pages)

        Large texts are automatically chunked into separate requests.
        HTTP 429 throttle responses are handled with wait_until parsing.

        Args:
            text: Full document text containing legal citations

        Returns:
            List of citation validation results with status codes
        """
        if not text or not text.strip():
            return []

        if len(text) > MAX_VALIDATE_TEXT_LENGTH:
            raise ValueError(
                f"Text exceeds maximum of {MAX_VALIDATE_TEXT_LENGTH:,} characters. "
                "Split into smaller documents."
            )

        # Chunk text if it exceeds the API limit
        if len(text) <= CITATION_MAX_TEXT_LENGTH:
            chunks = [text]
        else:
            chunks = _chunk_text(text, CITATION_MAX_TEXT_LENGTH)
            logger.info(
                f"Text ({len(text)} chars) split into {len(chunks)} chunks "
                f"(limit: {CITATION_MAX_TEXT_LENGTH})"
            )

        all_results: list[dict[str, Any]] = []
        offset = 0

        for chunk in chunks:
            # Citation-specific rate limiter (60 citations/min)
            await self._citation_rate_limiter.acquire()

            results = await self._citation_lookup_request(chunk)

            # Adjust indices for chunked requests
            if offset > 0:
                for r in results:
                    r["start_index"] = r.get("start_index", 0) + offset
                    r["end_index"] = r.get("end_index", 0) + offset

            # Log overflow citations (status 429 = exceeded 250 per request)
            overflow = [r for r in results if r.get("status") == 429]
            if overflow:
                logger.info(
                    f"{len(overflow)} citation(s) exceeded 250 per-request limit "
                    f"(returned with status 429)"
                )

            all_results.extend(results)
            offset += len(chunk)

        return all_results

    async def _citation_lookup_request(
        self, text: str
    ) -> list[dict[str, Any]]:
        """Send a single citation-lookup POST request.

        Uses form-encoded body (not JSON) per CourtListener docs.
        Handles HTTP 429 throttle with automatic wait and retry.
        Retries on timeout with exponential backoff.
        """
        client = await self._get_client()
        await self._rate_limiter.acquire()

        for attempt in range(DEFAULT_MAX_RETRIES):
            try:
                response = await client.post(
                    "/citation-lookup/",
                    data={"text": text},
                    timeout=CITATION_VALIDATION_TIMEOUT_SECONDS,
                )
            except httpx.TimeoutException:
                if attempt < DEFAULT_MAX_RETRIES - 1:
                    delay = DEFAULT_RETRY_DELAY_SECONDS * (
                        RETRY_BACKOFF_FACTOR ** attempt
                    )
                    logger.warning(
                        f"Citation lookup timeout, attempt {attempt + 1}, "
                        f"retrying in {delay:.1f}s"
                    )
                    await asyncio.sleep(delay)
                    continue
                raise  # Let decorator handle on final attempt

            if response.status_code == 429:
                wait = _parse_throttle_wait(response)
                security_logger.warning(
                    f"Rate limit exceeded: Citation API throttle, wait={wait:.0f}s "
                    f"(attempt {attempt + 1}/{DEFAULT_MAX_RETRIES})"
                )
                logger.warning(
                    f"Citation rate limit hit, waiting {wait:.0f}s "
                    f"(attempt {attempt + 1}/{DEFAULT_MAX_RETRIES})"
                )
                await asyncio.sleep(wait)
                continue

            response.raise_for_status()
            result = response.json()
            return result if isinstance(result, list) else []

        raise RateLimitError(
            "CourtListener rate limit exceeded after retries. "
            "Wait 60 seconds and try again with a smaller document."
        )

    async def lookup_citation(
        self,
        citation: str,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        """
        Look up a case by reporter citation.

        Args:
            citation: Legal citation string (e.g., "573 U.S. 208")
            page_size: Number of results to return

        Returns:
            Search results matching the citation
        """
        return await self._request(
            "GET",
            "/search/",
            params={
                "type": "o",
                "citation": citation,
                "page_size": min(page_size, MAX_PAGE_SIZE),
            },
        )

    async def search_cases(
        self,
        query: Optional[str] = None,
        case_name: Optional[str] = None,
        court: Optional[str] = None,
        citation: Optional[str] = None,
        date_filed_after: Optional[str] = None,
        date_filed_before: Optional[str] = None,
        precedential_status: Optional[str] = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        """
        Search for cases with various filters.

        Args:
            query: Full-text search query
            case_name: Filter by case name
            court: Court identifier (e.g., "scotus", "ca1", "cafc")
            citation: Citation filter
            date_filed_after: Filter by filing date (YYYY-MM-DD)
            date_filed_before: Filter by filing date (YYYY-MM-DD)
            precedential_status: Filter by status (Published, Unpublished, etc.)
            page: Page number (1-based)
            page_size: Results per page

        Returns:
            Search results with pagination info
        """
        _validate_search_params(
            query=query or case_name,
            date_filed_after=date_filed_after,
            date_filed_before=date_filed_before,
        )

        params: dict[str, Any] = {
            "type": "o",
            "page_size": min(page_size, MAX_PAGE_SIZE),
        }
        if page > 1:
            params["page"] = page
        if query:
            params["q"] = query
        if case_name:
            params["case_name"] = case_name
        if court:
            params["court"] = court
        if citation:
            params["citation"] = citation
        if date_filed_after:
            params["filed_after"] = date_filed_after
        if date_filed_before:
            params["filed_before"] = date_filed_before
        if precedential_status:
            params["stat_Published"] = (
                "on" if precedential_status == "Published" else ""
            )

        return await self._request("GET", "/search/", params=params)

    async def get_cluster(
        self,
        cluster_id: int,
        include_opinions: bool = True,
    ) -> dict[str, Any]:
        """
        Get detailed information about a specific opinion cluster.

        Args:
            cluster_id: CourtListener cluster ID
            include_opinions: Whether to include full opinion text

        Returns:
            Cluster details with metadata and optionally opinions
        """
        result = await self._request("GET", f"/clusters/{cluster_id}/")

        if include_opinions and "sub_opinions" in result:
            opinions = []
            for opinion_url in result.get("sub_opinions", []):
                try:
                    opinion_id = opinion_url.rstrip("/").split("/")[-1]
                    opinion = await self._request(
                        "GET", f"/opinions/{opinion_id}/"
                    )
                    opinions.append(opinion)
                except (httpx.HTTPStatusError, httpx.RequestError) as e:
                    logger.warning(f"Failed to fetch opinion {opinion_url}: {e}")
            result["fetched_opinions"] = opinions

        return result

    async def search_clusters(
        self,
        case_name: Optional[str] = None,
        court: Optional[str] = None,
        docket_number: Optional[str] = None,
        judge: Optional[str] = None,
        citation: Optional[str] = None,
        date_filed_after: Optional[str] = None,
        date_filed_before: Optional[str] = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        """
        Search opinion clusters with filters.

        Args:
            case_name: Filter by case name
            court: Court identifier
            docket_number: Docket number
            judge: Judge name
            citation: Citation filter
            date_filed_after: Filter by date (YYYY-MM-DD)
            date_filed_before: Filter by date (YYYY-MM-DD)
            page: Page number
            page_size: Results per page

        Returns:
            Search results with cluster information
        """
        _validate_search_params(
            query=case_name,
            date_filed_after=date_filed_after,
            date_filed_before=date_filed_before,
        )

        params: dict[str, Any] = {
            "type": "o",
            "page_size": min(page_size, MAX_PAGE_SIZE),
        }
        if page > 1:
            params["page"] = page
        if case_name:
            params["case_name"] = case_name
        if court:
            params["court"] = court
        if docket_number:
            params["docket_number"] = docket_number
        if judge:
            params["judge"] = judge
        if citation:
            params["citation"] = citation
        if date_filed_after:
            params["filed_after"] = date_filed_after
        if date_filed_before:
            params["filed_before"] = date_filed_before

        return await self._request("GET", "/search/", params=params)
