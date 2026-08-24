import logging
import os
import sys

from mcp.server.fastmcp import FastMCP

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    stream=sys.stderr,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

mcp = FastMCP("gemma-mcp")

