"""Trippy MCP server.

Exposes Google Workspace tools and Trippy domain tools so Hermes can call them
as first-class tool invocations rather than Python imports.

Run with:
    python -m trippy.mcp.server
Or via the Claude Code / Hermes MCP config (see mcp_config.json).

Transport: stdio (default for local Hermes integration)
"""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

from trippy.mcp.drive_tools import register_drive_tools
from trippy.mcp.gmail_tools import register_gmail_tools
from trippy.mcp.sheets_tools import register_sheets_tools
from trippy.mcp.trippy_tools import register_trippy_tools

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "trippy-tools",
    instructions=(
        "Tools for the Trippy travel concierge. Use Google Workspace tools to read "
        "Gmail confirmations, manage Google Sheets trip records, and search Drive. "
        "Use Trippy domain tools for canonical trip state, shortlists, sheet sync, "
        "friction audits, and review-gated learning proposals."
    ),
)

register_gmail_tools(mcp)
register_sheets_tools(mcp)
register_drive_tools(mcp)
register_trippy_tools(mcp)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    mcp.run()


if __name__ == "__main__":
    main()
