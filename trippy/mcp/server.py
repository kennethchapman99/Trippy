"""Trippy Google Tools MCP server.

Exposes Gmail, Google Sheets, and Google Drive as MCP tools so the Hermes
agent can call them as first-class tool invocations rather than Python imports.

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

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "trippy-google-tools",
    instructions=(
        "Google Workspace tools for the Trippy travel concierge. "
        "Use these to read Gmail confirmations, manage Google Sheets trip records, "
        "and search Google Drive for past trip files."
    ),
)

register_gmail_tools(mcp)
register_sheets_tools(mcp)
register_drive_tools(mcp)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    mcp.run()


if __name__ == "__main__":
    main()
