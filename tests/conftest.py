"""
Shared pytest fixtures for the CourtListener MCP test suite.
"""

import asyncio
import pytest

from courtlistener_mcp.api.client import CourtListenerClient


# ---------------------------------------------------------------------------
# Client fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def api_client() -> CourtListenerClient:
    """A CourtListenerClient pre-configured with a test token."""
    return CourtListenerClient(token="test_token_12345678901234567890")


# ---------------------------------------------------------------------------
# Sample API response fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_citation_response() -> list:
    """
    Bare citation-lookup response list with one 200 and one 404 result.
    Matches the actual API format: a bare list (not wrapped in {results: []}).
    """
    return [
        {
            "citation": "573 U.S. 208",
            "status": 200,
            "clusters": [
                {
                    "id": 2679558,
                    "case_name": "Alice Corp. v. CLS Bank International",
                    "absolute_url": "/opinion/2679558/alice-corp-v-cls-bank/",
                }
            ],
            "start_index": 0,
            "end_index": 12,
        },
        {
            "citation": "999 F.3d 999",
            "status": 404,
            "clusters": [],
            "start_index": 50,
            "end_index": 62,
        },
    ]


@pytest.fixture
def sample_search_response() -> dict:
    """Search API response with count=1 and one Alice Corp result."""
    return {
        "count": 1,
        "next": None,
        "previous": None,
        "results": [
            {
                "cluster_id": 2679558,
                "caseName": "Alice Corp. v. CLS Bank International",
                "citation": ["573 U.S. 208"],
                "court": "scotus",
                "court_id": "scotus",
                "dateFiled": "2014-06-19",
                "docketNumber": "13-298",
                "status": "Published",
                "absolute_url": "/opinion/2679558/alice-corp-v-cls-bank/",
            }
        ],
    }


# ---------------------------------------------------------------------------
# Global-state reset fixture
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_main_globals():
    """
    Reset the lazy-initialized globals in courtlistener_mcp.main before and
    after every test so tests are fully isolated.
    """
    import courtlistener_mcp.main as main_module

    # --- setup: reset to known-clean state ---
    main_module._client = None
    main_module._client_lock = None
    main_module._settings = None

    yield

    # --- teardown: reset again to avoid polluting later tests ---
    main_module._client = None
    main_module._client_lock = None
    main_module._settings = None
