"""
CourtListener MCP Prompt Templates

Pre-canned workflows that guide Claude through citation validation tasks.
Each prompt provides a complete, parameterized execution plan for a common
use case, embedding the 3-tool fallback chain, output format, and risk
assessment logic.

Available Prompts:
- validate_legal_brief: Full citation validation of a legal document with
  3-tool fallback chain, link generation, and risk assessment report.
"""


def register_prompts(mcp_server):
    """Register all prompts with the MCP server.

    Called from main.py after the mcp object is created.

    Args:
        mcp_server: The FastMCP server instance
    """
    global mcp
    mcp = mcp_server

    from . import validate_legal_brief  # noqa: F401


__all__ = ["register_prompts"]
