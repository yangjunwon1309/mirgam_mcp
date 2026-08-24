"""Streamable-HTTP FastMCP entry point.

Register further tools by adding modules under app/tools and importing them in
app.tools. Keep tools self-contained and read-only by default.
"""

from __future__ import annotations

import os

from .mcp_app import mcp
from . import tools  # noqa: F401  Registers decorated tools.


def main() -> None:
    mcp.settings.host = os.getenv("MCP_HTTP_HOST", "127.0.0.1")
    mcp.settings.port = int(os.getenv("MCP_HTTP_PORT", "8765"))
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()

