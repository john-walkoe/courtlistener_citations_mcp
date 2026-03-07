"""
CourtListener Citation Validation MCP Server

FastMCP 3.0 server with 6 citation validation tools + guidance.
Supports STDIO (Claude Desktop/Code) and Streamable HTTP (CoPilot Studio).
MCP Apps extension provides interactive UI for citation validation results.
"""

import asyncio
import functools
import json
import os
from typing import Annotated, Any, Optional

import httpx
from fastmcp import FastMCP, Context
from fastmcp.exceptions import ToolError
from pydantic import Field
from starlette.responses import JSONResponse

from .api.client import CourtListenerClient
from .errors import AuthenticationError
from .config.api_constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, OPINION_URL_TEMPLATE
from .config.log_config import setup_logging
from .config.settings import get_settings
from .config.tool_guidance import SERVER_INSTRUCTIONS, get_guidance_section
from .shared.safe_logger import get_safe_logger
from .ui.citation_view import CITATION_VIEW_HTML

setup_logging(log_level=os.getenv("LOG_LEVEL", "INFO"))
logger = get_safe_logger(__name__)

# =============================================================================
# SERVER INITIALIZATION
# =============================================================================

mcp = FastMCP(
    name="CourtListener Citation Validation MCP",
    instructions=SERVER_INSTRUCTIONS,
    version="1.0.0",
)

# Register prompt templates
from .prompts import register_prompts  # noqa: E402
register_prompts(mcp)

# =============================================================================
# MCP APPS - UI RESOURCE
# =============================================================================

CITATION_VIEW_URI = "ui://courtlistener-mcp/citation-results.html"


@mcp.resource(
    CITATION_VIEW_URI,
    mime_type="text/html;profile=mcp-app",
    meta={"ui": {"csp": {"resourceDomains": ["https://cdn.jsdelivr.net"]}}},
)
def citation_view_resource() -> str:
    """Interactive citation validation results view (MCP Apps)."""
    return CITATION_VIEW_HTML


# Lazy-initialized client
_client: Optional[CourtListenerClient] = None
_client_lock: Optional[asyncio.Lock] = None
_settings = None


def _get_client_lock() -> asyncio.Lock:
    """Get or create the client initialization lock (lazy so it's bound to the running loop)."""
    global _client_lock
    if _client_lock is None:
        _client_lock = asyncio.Lock()
    return _client_lock


def _get_settings():
    global _settings
    if _settings is None:
        _settings = get_settings()
    return _settings


async def _get_client(ctx: Optional[Context] = None) -> CourtListenerClient:
    """
    Get or create the API client. Uses elicitation to request token if missing.

    Args:
        ctx: FastMCP context for elicitation support

    Returns:
        Configured CourtListenerClient

    Raises:
        ToolError: If no API token is available
    """
    global _client

    settings = _get_settings()
    token = settings.get_api_token()

    if not token and ctx:
        try:
            result = await ctx.elicit(
                "CourtListener API token is required.\n"
                "Get a free token at: https://www.courtlistener.com/sign-in/\n"
                "Enter your API token:",
                response_type=str,
            )
            if result.action == "accept" and result.data:
                token = result.data.strip()
                # Try to store via DPAPI for future sessions
                try:
                    from .shared.secure_storage import store_api_token
                    store_api_token(token)
                except Exception:
                    pass
                settings.courtlistener_api_token = token
        except Exception as e:
            logger.debug(f"Elicitation not supported by client: {e}")

    if not token:
        raise ToolError(
            "CourtListener API token not configured. Set COURTLISTENER_API_TOKEN "
            "environment variable or run deploy/windows_setup.ps1 for DPAPI storage."
        )

    async with _get_client_lock():
        if _client is None:
            _client = CourtListenerClient(token=token)

    return _client


def _format_results(data: Any) -> str:
    """Format API response data as readable JSON string."""
    if isinstance(data, str):
        return data
    return json.dumps(data, indent=2, default=str)


def _empty_response(summary: str, hint: str = "") -> str:
    """Standardized empty-results response."""
    result: dict[str, Any] = {"summary": summary, "results": []}
    if hint:
        result["hint"] = hint
    return json.dumps(result, indent=2)


def _handle_client_errors(func):
    """Convert client-layer exceptions to user-friendly ToolErrors."""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except AuthenticationError:
            global _client
            _client = None  # Force re-creation with fresh token on next call
            raise
        except ToolError:
            raise  # Already user-friendly (includes our custom errors)
        except ValueError as e:
            raise ToolError(str(e))
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status == 401:
                raise ToolError(
                    "API token invalid or expired. "
                    "Get a new token at: https://www.courtlistener.com/sign-in/"
                )
            if status == 403:
                raise ToolError("API token lacks permission for this endpoint.")
            if status == 404:
                raise ToolError("Requested resource not found on CourtListener.")
            raise ToolError(f"CourtListener API error (HTTP {status}). Try again later.")
        except httpx.TimeoutException:
            raise ToolError(
                "CourtListener API timed out. Try again or use a smaller query."
            )
        except httpx.RequestError as e:
            raise ToolError(f"Cannot reach CourtListener API: {type(e).__name__}")
    return wrapper


def _build_courtlistener_url(cluster_id: int, case_name: str = "") -> str:
    """Build a CourtListener opinion URL from cluster ID."""
    slug = case_name.lower().replace(" ", "-").replace(".", "")[:80] if case_name else ""
    return OPINION_URL_TEMPLATE.format(cluster_id=cluster_id, slug=slug)


def _enrich_citation_result(r: dict[str, Any]) -> dict[str, Any]:
    """Add courtlistener_url / search_url to a raw citation-lookup result."""
    status = r.get("status")
    clusters = r.get("clusters", [])
    if status == 200 and clusters:
        c = clusters[0]
        cluster_id = c.get("id", "")
        case_name = c.get("case_name", "")
        r["courtlistener_url"] = (
            f"https://www.courtlistener.com{c['absolute_url']}"
            if c.get("absolute_url")
            else _build_courtlistener_url(cluster_id, case_name)
        )
        r["cluster_id"] = cluster_id
    elif status == 300 and clusters:
        # Ambiguous — attach URLs for all candidates
        for c in clusters:
            cluster_id = c.get("id", "")
            c["courtlistener_url"] = (
                f"https://www.courtlistener.com{c['absolute_url']}"
                if c.get("absolute_url")
                else _build_courtlistener_url(cluster_id, c.get("case_name", ""))
            )
    elif status == 404:
        # Construct a CourtListener search URL for manual verification
        citation_str = r.get("citation", "")
        import urllib.parse
        query = urllib.parse.quote_plus(citation_str)
        r["search_url"] = f"https://www.courtlistener.com/?q={query}&type=o"
    return r


def _extract_case_summary(result: dict[str, Any]) -> dict[str, Any]:
    """Extract a concise case summary from a search result."""
    cluster_id = result.get("cluster_id", "")
    case_name = result.get("caseName", result.get("case_name", "Unknown"))
    return {
        "case_name": case_name,
        "citation": result.get("citation", []),
        "court": result.get("court", result.get("court_id", "")),
        "date_filed": result.get("dateFiled", result.get("date_filed", "")),
        "cluster_id": cluster_id,
        "docket_number": result.get("docketNumber", result.get("docket_number", "")),
        "status": result.get("status", ""),
        "courtlistener_url": (
            f"https://www.courtlistener.com{result['absolute_url']}"
            if result.get("absolute_url")
            else _build_courtlistener_url(cluster_id, case_name)
        ),
    }


# =============================================================================
# TOOL: validate_citations (PRIMARY)
# =============================================================================

@mcp.tool(
    name="courtlistener_validate_citations",
    annotations={
        "title": "CourtListener Validate Citations",
        "readOnlyHint": True,
        "openWorldHint": True,
    },
    meta={"ui": {"resourceUri": CITATION_VIEW_URI}},
)
@_handle_client_errors
async def validate_citations(
    ctx: Context,
    text: Annotated[str, "Full document text containing legal citations to validate"],
) -> str:
    """
    Extract and validate all legal citations from document text.

    Uses CourtListener's eyecite-based citation parser to find and validate
    citations. This is the PRIMARY tool for citation validation.

    TIP: Run courtlistener_extract_citations first (free, local, no API) to get
    a full census of ALL citation types — including statutes, law journals, id.,
    and supra that this tool silently skips.

    Returns validation status per citation:
    - 200: Citation found and valid
    - 300: Ambiguous citation (multiple matches)
    - 400: Invalid reporter (not a real citation)
    - 404: Citation NOT found (potential hallucination)
    - 429: Overflow (>250 citations in request, not looked up)

    IMPORTANT - URLs are pre-built in results:
    - status 200/300: courtlistener_url is directly in each cluster object — use it as 🔗 link
    - status 404: search_url is pre-built for manual lookup — present it as 🔗 link
    - NEVER use web search to verify citations — CourtListener is the sole authoritative source
    - A 404 result means SUSPECT regardless of what external sources say — present it as ⚠️ SUSPECT
    - DO NOT override a 404 result with information from Wikipedia, Westlaw, or any web source

    RATE LIMIT STRATEGY — the throttle is 60 *valid* citations per minute
    (not 60 requests). A document with 60 real citations consumes the entire
    minute's quota in one call. To avoid long waits:
    - For SHORT documents (1–2 pages, few citations): call once, done.
    - For MEDIUM documents (up to ~50 pages / 64,000 chars): still one call;
      the client auto-chunks at the 64,000-char boundary.
    - For LONG documents or MANY citations: split by section/paragraph and
      call courtlistener_validate_citations once per section rather than
      passing the entire document. This spreads citations across multiple
      minutes and avoids hitting the 60/min ceiling, which causes the API to
      throttle and makes every subsequent call wait up to 60 seconds.
    - Per-request hard limits (enforced by API, cannot be changed):
        • 64,000 chars max per request (~50 pages)
        • 250 citations max per request (overflow silently gets status 429)
    """
    client = await _get_client(ctx)

    text_len = len(text)
    await ctx.info(
        f"Validating citations from {text_len:,} chars of text..."
    )
    results = await client.validate_citations(text)

    if not results:
        return _empty_response(
            "No citations found in the provided text.",
            "Eyecite found no formal citations. Extract case names manually from "
            "the text (e.g., 'Alice Corp v. CLS Bank'), then use courtlistener_search_cases(case_name=...) for each.",
        )

    valid_count = sum(1 for r in results if r.get("status") == 200)
    not_found_count = sum(1 for r in results if r.get("status") == 404)
    ambiguous_count = sum(1 for r in results if r.get("status") == 300)

    # Enrich each result with courtlistener_url (200/300) or search_url (404)
    enriched = [_enrich_citation_result(r) for r in results]

    output: dict[str, Any] = {
        "total_citations": len(enriched),
        "valid": valid_count,
        "ambiguous": ambiguous_count,
        "invalid_reporter": sum(1 for r in enriched if r.get("status") == 400),
        "not_found": not_found_count,
        "overflow": sum(1 for r in enriched if r.get("status") == 429),
        "citations": enriched,
    }

    # Build workflow guidance based on results
    next_steps = []
    if valid_count > 0:
        next_steps.append(
            "200: courtlistener_url is already in the result — use it as 🔗 link. "
            "Check case_name matches the document (MISMATCH = suspect citation)."
        )
    if not_found_count > 0:
        next_steps.append(
            f"404 ({not_found_count}): use courtlistener_search_cases(case_name=..., court=...) as fallback. "
            "search_url is pre-built in each 404 result for manual lookup if all tools fail."
        )
    if ambiguous_count > 0:
        next_steps.append(
            "300: courtlistener_url is in each cluster — pick best match, present with 🔗 link."
        )
    if not next_steps:
        next_steps.append("Format results per courtlistener_citations_get_guidance(section='response_format')")

    output["guidance"] = {"next_steps": next_steps}

    return _format_results(output)


# =============================================================================
# TOOL: lookup_citation
# =============================================================================

@mcp.tool(
    name="courtlistener_lookup_citation",
    annotations={
        "title": "CourtListener Lookup Citation",
        "readOnlyHint": True,
        "openWorldHint": True,
    },
)
@_handle_client_errors
async def lookup_citation(
    ctx: Context,
    citation: Annotated[str, "Legal citation string (e.g., '573 U.S. 208', '134 S. Ct. 2347')"],
    page_size: Annotated[int, Field(ge=1, le=MAX_PAGE_SIZE, description="Results per page")] = DEFAULT_PAGE_SIZE,
) -> str:
    """
    Look up a case by its reporter citation.

    Searches CourtListener for cases matching the given citation.
    Supports U.S. Reports, Federal Reporter, Federal Supplement,
    Supreme Court Reporter, and state reporter formats.

    Use as LAST RESORT after courtlistener_validate_citations and courtlistener_search_cases.
    """
    client = await _get_client(ctx)

    await ctx.info(f"Looking up citation: {citation}")
    result = await client.lookup_citation(citation, page_size=page_size)

    raw_results = result.get("results", [])
    if not raw_results:
        return _empty_response(
            f"No cases found for citation: {citation}",
            "This is the LAST RESORT tool. If courtlistener_validate_citations and courtlistener_search_cases also failed, "
            "mark this citation as NOT FOUND (likely hallucination).",
        )

    cases = [_extract_case_summary(r) for r in raw_results]

    return json.dumps({
        "summary": f"Found {len(cases)} case(s) for citation: {citation}",
        "results": cases,
        "guidance": {
            "next_steps": [
                "Check case_name for MISMATCH, format as ⚠️ PARTIAL MATCH",
                "courtlistener_get_cluster(cluster_id) for full details + URL",
            ],
        },
    }, indent=2)


# =============================================================================
# TOOL: search_cases (FALLBACK)
# =============================================================================

@mcp.tool(
    name="courtlistener_search_cases",
    annotations={
        "title": "CourtListener Search Cases",
        "readOnlyHint": True,
        "openWorldHint": True,
    },
)
@_handle_client_errors
async def search_cases(
    ctx: Context,
    query: Annotated[Optional[str], "Full-text search query"] = None,
    case_name: Annotated[Optional[str], "Case name to search for (e.g., 'Alice Corp v CLS Bank')"] = None,
    court: Annotated[Optional[str], "Court identifier (e.g., 'scotus', 'ca1', 'cafc', 'dcd')"] = None,
    citation: Annotated[Optional[str], "Citation to filter by"] = None,
    date_filed_after: Annotated[Optional[str], "Filter: filed after date (YYYY-MM-DD)"] = None,
    date_filed_before: Annotated[Optional[str], "Filter: filed before date (YYYY-MM-DD)"] = None,
    precedential_status: Annotated[Optional[str], "Filter: Published, Unpublished, Errata"] = None,
    page: Annotated[int, "Page number (1-based)"] = 1,
    page_size: Annotated[int, Field(ge=1, le=MAX_PAGE_SIZE, description="Results per page")] = DEFAULT_PAGE_SIZE,
) -> str:
    """
    Search for cases by name, court, date, or full-text query.

    This is the FALLBACK tool when courtlistener_validate_citations returns 404.
    Search optimization tips:
    - Remove "Inc.", "LLC", "Corp." if first search fails
    - Try first party name only (e.g., "Alice" instead of "Alice Corp")
    - Always include court parameter when known for faster results

    Common court identifiers:
    - scotus: Supreme Court
    - cafc: Federal Circuit
    - ca1-ca11: Circuit Courts
    - cadc: DC Circuit
    """
    if not any([query, case_name, court, citation]):
        raise ToolError("At least one search parameter is required (query, case_name, court, or citation)")

    client = await _get_client(ctx)

    search_desc = " | ".join(
        f"{k}={v}" for k, v in [
            ("case_name", case_name), ("court", court),
            ("query", query), ("citation", citation),
        ] if v
    )
    await ctx.info(f"Searching cases: {search_desc}")

    result = await client.search_cases(
        query=query,
        case_name=case_name,
        court=court,
        citation=citation,
        date_filed_after=date_filed_after,
        date_filed_before=date_filed_before,
        precedential_status=precedential_status,
        page=page,
        page_size=page_size,
    )

    raw_results = result.get("results", [])
    cases = [_extract_case_summary(r) for r in raw_results]

    count = result.get("count", len(cases))

    # Build guidance based on whether results were found
    if cases:
        guidance = {
            "next_steps": [
                "Check case_name for MISMATCH, format as ⚠️ PARTIAL MATCH",
                "courtlistener_get_cluster(cluster_id) for full details + URL",
            ],
        }
    else:
        guidance = {
            "next_steps": [
                "Simplify: remove Inc/LLC/Corp, try first party name only",
                "Try without court filter, then courtlistener_lookup_citation(citation=...)",
                "If all 3 tools fail → ❌ NOT FOUND (likely hallucination)",
            ],
        }

    return json.dumps({
        "summary": f"Found {count} case(s)",
        "page": page,
        "page_size": page_size,
        "total_count": count,
        "results": cases,
        "search_parameters": {
            k: v for k, v in {
                "query": query, "case_name": case_name, "court": court,
                "citation": citation, "date_filed_after": date_filed_after,
                "date_filed_before": date_filed_before,
            }.items() if v
        },
        "guidance": guidance,
    }, indent=2)


# =============================================================================
# TOOL: get_cluster
# =============================================================================

@mcp.tool(
    name="courtlistener_get_cluster",
    annotations={
        "title": "CourtListener Get Case Cluster",
        "readOnlyHint": True,
        "openWorldHint": True,
    },
)
@_handle_client_errors
async def get_cluster(
    ctx: Context,
    cluster_id: Annotated[int, "CourtListener cluster ID (from opinion URLs like /opinion/2679558/)"],
    include_opinions: Annotated[bool, "Include full opinion text (set false for faster metadata-only)"] = False,
) -> str:
    """
    Get detailed information about a specific opinion cluster.

    A cluster groups all opinions from a single court decision
    (majority, dissent, concurrence). Use the cluster_id from
    search_cases or lookup_citation results.

    Cluster IDs come from CourtListener URLs:
    /opinion/2679558/alice-corp-v-cls-bank/ -> cluster_id = 2679558

    Returns:
        cluster_id, case_name, courtlistener_url, court, date_filed,
        docket_id, citations (parallel reporter strings), precedential_status,
        citation_count, judges, nature_of_suit, syllabus (first 500 chars).

        citation_count: how many later opinions cite this case in CourtListener.
          Use as a hallucination signal in combination with date_filed — a
          supposedly landmark case with citation_count=0 warrants extra scrutiny,
          but only if date_filed is more than ~12 months ago. Recent decisions
          naturally have low counts regardless of importance.

        If include_opinions=True, also returns opinions[] with:
          id, type (majority/dissent/concurrence), author, text_excerpt
          (first 500 chars from html_with_citations, which has citations
          pre-linked with CourtListener opinion IDs in data-id attributes).
    """
    client = await _get_client(ctx)

    await ctx.info(f"Fetching cluster {cluster_id}...")
    result = await client.get_cluster(cluster_id, include_opinions=include_opinions)

    case_name = result.get("case_name", result.get("caseName", ""))
    absolute_url = result.get("absolute_url", "")

    output = {
        "cluster_id": cluster_id,
        "case_name": case_name,
        "courtlistener_url": (
            f"https://www.courtlistener.com{absolute_url}"
            if absolute_url
            else _build_courtlistener_url(cluster_id, case_name)
        ),
        "court": result.get("court", result.get("court_id", "")),
        "date_filed": result.get("date_filed", ""),
        "docket_id": result.get("docket_id", ""),
        "citations": [
            f"{c.get('volume', '')} {c.get('reporter', '')} {c.get('page', '')}"
            for c in result.get("citations", [])
            if isinstance(c, dict)
        ],
        "precedential_status": result.get("precedential_status", ""),
        "citation_count": result.get("citation_count"),
        "judges": result.get("judges", ""),
        "nature_of_suit": result.get("nature_of_suit", ""),
        "syllabus": result.get("syllabus", "")[:500] if result.get("syllabus") else "",
    }

    if include_opinions and result.get("fetched_opinions"):
        output["opinions"] = [
            {
                "id": op.get("id"),
                "type": op.get("type", ""),
                "author": op.get("author", ""),
                "text_excerpt": (op.get("html_with_citations") or op.get("plain_text") or op.get("html") or "")[:500],
            }
            for op in result["fetched_opinions"]
        ]

    output["guidance"] = {
        "next_steps": [
            "Confirm case_name matches document → ✅/⚠️ MISMATCH",
            "Include courtlistener_url as 🔗 link in response",
            "citation_count=0 on a major case >1yr old → ⚠️ flag for extra scrutiny (recent decisions always have low counts)",
        ],
    }

    return _format_results(output)


# =============================================================================
# TOOL: search_clusters
# =============================================================================

@mcp.tool(
    name="courtlistener_search_clusters",
    annotations={
        "title": "CourtListener Search Clusters",
        "readOnlyHint": True,
        "openWorldHint": True,
    },
)
@_handle_client_errors
async def search_clusters(
    ctx: Context,
    case_name: Annotated[Optional[str], "Case name to search"] = None,
    court: Annotated[Optional[str], "Court identifier (e.g., 'scotus', 'cafc')"] = None,
    docket_number: Annotated[Optional[str], "Docket number (combine with court)"] = None,
    judge: Annotated[Optional[str], "Judge name"] = None,
    citation: Annotated[Optional[str], "Citation to search"] = None,
    date_filed_after: Annotated[Optional[str], "Filed after date (YYYY-MM-DD)"] = None,
    date_filed_before: Annotated[Optional[str], "Filed before date (YYYY-MM-DD)"] = None,
    page: Annotated[int, "Page number"] = 1,
    page_size: Annotated[int, Field(ge=1, le=MAX_PAGE_SIZE, description="Results per page")] = DEFAULT_PAGE_SIZE,
) -> str:
    """
    Search opinion clusters with filters.

    A cluster groups all opinions from a single court decision.
    Always include 'court' parameter for faster queries.
    Docket numbers require court (they're not unique across courts).
    """
    if not any([case_name, court, docket_number, judge, citation]):
        raise ToolError("At least one search parameter required")

    client = await _get_client(ctx)

    await ctx.info("Searching opinion clusters...")
    result = await client.search_clusters(
        case_name=case_name,
        court=court,
        docket_number=docket_number,
        judge=judge,
        citation=citation,
        date_filed_after=date_filed_after,
        date_filed_before=date_filed_before,
        page=page,
        page_size=page_size,
    )

    raw_results = result.get("results", [])
    clusters = [_extract_case_summary(r) for r in raw_results]
    count = result.get("count", len(clusters))

    if clusters:
        guidance = {
            "next_steps": [
                "courtlistener_get_cluster(cluster_id) for full details + URL",
            ],
        }
    else:
        guidance = {
            "next_steps": [
                "Broaden: remove suffixes or drop court filter",
            ],
        }

    return json.dumps({
        "summary": f"Found {count} cluster(s)",
        "page": page,
        "total_count": count,
        "results": clusters,
        "guidance": guidance,
    }, indent=2)


# =============================================================================
# TOOL: extract_citations (LOCAL - no API call)
# =============================================================================

def _extract_citations_sync(text: str) -> dict:
    """
    Synchronous eyecite extraction — runs in thread pool via asyncio.to_thread.

    Extracts ALL citation types: case, statutory, law journal, id., supra, unknown.
    Pure local processing; no network calls, no API key required.
    """
    from eyecite import get_citations, resolve_citations
    from eyecite.models import (
        FullCaseCitation, FullLawCitation, FullJournalCitation,
        IdCitation, SupraCitation, UnknownCitation,
    )

    if not text or not text.strip():
        return {
            "summary": {
                "total": 0, "case_citations": 0, "statutory_citations": 0,
                "law_journal_citations": 0, "id_citations": 0,
                "supra_citations": 0, "unknown_citations": 0,
            },
            "case_citations": [], "statutory_citations": [], "law_journal_citations": [],
            "id_citations": [], "supra_citations": [], "unknown_citations": [],
            "guidance": {"next_steps": ["No citations found in text"]},
        }

    found = get_citations(text)
    resolved = resolve_citations(found)

    # Map citation object id -> antecedent text for Id./Supra resolution
    antecedent_map: dict[int, str] = {}
    for resource, cit_list in resolved.items():
        try:
            ant_text = resource.citation.matched_text()
        except Exception:
            ant_text = ""
        for cit in cit_list:
            if isinstance(cit, (IdCitation, SupraCitation)):
                antecedent_map[id(cit)] = ant_text

    case_cits: list[dict] = []
    statutory_cits: list[dict] = []
    journal_cits: list[dict] = []
    id_cits: list[dict] = []
    supra_cits: list[dict] = []
    unknown_cits: list[dict] = []

    for cit in found:
        m = getattr(cit, "metadata", None)
        g = getattr(cit, "groups", {}) or {}
        text_repr = cit.matched_text()

        if isinstance(cit, FullCaseCitation):
            entry: dict[str, Any] = {
                "text": text_repr,
                "reporter": g.get("reporter", ""),
                "volume": g.get("volume", ""),
                "page": g.get("page", ""),
            }
            if m:
                for attr in ("plaintiff", "defendant", "year", "court"):
                    val = getattr(m, attr, None)
                    if val is not None:
                        entry[attr] = val
            case_cits.append(entry)

        elif isinstance(cit, FullLawCitation):
            entry = {
                "text": text_repr,
                "reporter": g.get("reporter", ""),
                "title": g.get("title", ""),
                "section": g.get("section", ""),
                "note": "Statutes not validated — no CourtListener database available",
            }
            statutory_cits.append({k: v for k, v in entry.items() if v})

        elif isinstance(cit, FullJournalCitation):
            entry = {
                "text": text_repr,
                "reporter": g.get("reporter", ""),
                "volume": g.get("volume", ""),
                "page": g.get("page", ""),
                "note": "Law journal citations not validated — no CourtListener database available",
            }
            if m:
                yr = getattr(m, "year", None)
                if yr is not None:
                    entry["year"] = yr
            journal_cits.append(entry)

        elif isinstance(cit, IdCitation):
            entry = {"text": text_repr}
            if m:
                pin = getattr(m, "pin_cite", None)
                if pin:
                    entry["pin_cite"] = pin
            ant = antecedent_map.get(id(cit))
            if ant:
                entry["resolves_to"] = ant
            id_cits.append(entry)

        elif isinstance(cit, SupraCitation):
            entry = {"text": text_repr}
            if m:
                guess = getattr(m, "antecedent_guess", None)
                pin = getattr(m, "pin_cite", None)
                if guess:
                    entry["antecedent_guess"] = guess
                if pin:
                    entry["pin_cite"] = pin
            ant = antecedent_map.get(id(cit))
            if ant:
                entry["resolves_to"] = ant
            supra_cits.append(entry)

        elif isinstance(cit, UnknownCitation):
            unknown_cits.append({"text": text_repr})

    # Build guidance
    next_steps = []
    if case_cits:
        next_steps.append(
            f"{len(case_cits)} case citation(s) found → call courtlistener_validate_citations(text) "
            "to validate against CourtListener"
        )
    if statutory_cits:
        next_steps.append(
            f"{len(statutory_cits)} statutory citation(s) extracted — "
            "cannot be validated (not in CourtListener database)"
        )
    if journal_cits:
        next_steps.append(
            f"{len(journal_cits)} law journal citation(s) extracted — cannot be validated"
        )
    total_unresolved = (
        sum(1 for c in id_cits if "resolves_to" not in c)
        + sum(1 for c in supra_cits if "resolves_to" not in c)
    )
    if total_unresolved:
        next_steps.append(
            f"{total_unresolved} id./supra citation(s) could not be resolved to an antecedent "
            "(antecedent may appear in preceding text not included in this chunk)"
        )
    if not next_steps:
        next_steps.append("No citations found in text")

    return {
        "summary": {
            "total": len(found),
            "case_citations": len(case_cits),
            "statutory_citations": len(statutory_cits),
            "law_journal_citations": len(journal_cits),
            "id_citations": len(id_cits),
            "supra_citations": len(supra_cits),
            "unknown_citations": len(unknown_cits),
        },
        "case_citations": case_cits,
        "statutory_citations": statutory_cits,
        "law_journal_citations": journal_cits,
        "id_citations": id_cits,
        "supra_citations": supra_cits,
        "unknown_citations": unknown_cits,
        "guidance": {"next_steps": next_steps},
    }


@mcp.tool(
    name="courtlistener_extract_citations",
    annotations={
        "title": "CourtListener Extract Citations",
        "readOnlyHint": True,
        "openWorldHint": False,
    },
)
async def extract_citations(
    ctx: Context,
    text: Annotated[str, "Document text to extract citations from"],
) -> str:
    """
    Extract ALL legal citation types from document text using eyecite (local, no API).

    Runs entirely locally — no CourtListener API call, no rate limits, no API key needed.
    Use this BEFORE validate_citations to discover what's in a document.

    Returns categorized citations:
    - case_citations: Reporter citations (e.g., "573 U.S. 208") → validate with validate_citations
    - statutory_citations: Statutes (e.g., "42 U.S.C. § 1983") → cannot be CourtListener-validated
    - law_journal_citations: Journal articles (e.g., "128 Harv. L. Rev. 1") → cannot be validated
    - id_citations: "Id." / "Id. at X" back-references with resolved antecedent
    - supra_citations: "supra" back-references with resolved antecedent
    - unknown_citations: Unrecognized citation-like strings

    WORKFLOW:
    1. courtlistener_extract_citations(text) → get full census of citation types
    2. courtlistener_validate_citations(text) → validate case citations against CourtListener
    3. courtlistener_search_cases / courtlistener_lookup_citation → fallback for any 404 results

    NOTE: CourtListener's courtlistener_validate_citations silently drops statutes, law journals,
    id., and supra citations. Use courtlistener_extract_citations first to capture the complete
    citation inventory before validation.
    """
    await ctx.info(f"Extracting citations from {len(text):,} chars (local, no API)...")

    try:
        result = await asyncio.to_thread(_extract_citations_sync, text)
    except ImportError as e:
        raise ToolError(f"eyecite library not available: {e}. Run: pip install eyecite")

    return _format_results(result)


# =============================================================================
# TOOL: get_guidance
# =============================================================================

@mcp.tool(
    name="courtlistener_citations_get_guidance",
    annotations={
        "title": "CourtListener Citations Get Guidance",
        "readOnlyHint": True,
        "openWorldHint": False,
    },
)
async def get_guidance(
    section: Annotated[str, "Guidance section: overview, workflow, response_format, hallucination_patterns, edge_cases, risk_assessment, limitations"] = "overview",
) -> str:
    """
    Get contextual guidance for using CourtListener citation validation tools.

    Sections available:
    - overview: What this MCP does, tool list, quick reference chart
    - workflow: Discovery + 3-tool fallback chain with decision chart
    - response_format: Visual symbols and response structure (✅⚠️❌🔗)
    - hallucination_patterns: AI hallucination detection patterns and examples
    - edge_cases: Special handling (SCOTUS parallel citations, state courts, etc.)
    - risk_assessment: How to interpret validation results
    - limitations: CourtListener coverage gaps and false negatives

    Legacy section names (citation_workflow, fallback_chain, step_by_step_workflow,
    tools, link_generation, citation_patterns) are still accepted via aliases.
    """
    return get_guidance_section(section)


# =============================================================================
# HEALTH CHECK (HTTP mode)
# =============================================================================

@mcp.custom_route("/health", methods=["GET"])
async def health_check(request):
    """Health check endpoint for load balancers and monitoring."""
    return JSONResponse({"status": "healthy"})


# =============================================================================
# ASGI APP (for Docker/Uvicorn deployment)
# =============================================================================

from starlette.middleware.cors import CORSMiddleware
from .shared.http_rate_limit import InboundRateLimitMiddleware

app = CORSMiddleware(
    InboundRateLimitMiddleware(mcp.http_app(path="/mcp"), max_requests=60, window_seconds=60),
    allow_origins=["http://localhost:8080", "http://127.0.0.1:8080"],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Mcp-Session-Id"],
)


# =============================================================================
# ENTRY POINTS
# =============================================================================

def run_server():
    """CLI entry point. Transport controlled by TRANSPORT env var."""
    settings = _get_settings()
    transport = settings.transport.lower()

    if transport == "http":
        logger.info(f"Starting HTTP server on {settings.host}:{settings.port}")
        mcp.run(
            transport="http",
            host=settings.host,
            port=settings.port,
        )
    else:
        logger.info("Starting STDIO server")
        mcp.run()


if __name__ == "__main__":
    run_server()
