import logging
import os
import sys

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    stream=sys.stderr,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# The API reaches this container through Docker DNS as http://mcp:8765/mcp.
# Streamable HTTP rejects non-localhost Host headers by default as a DNS-rebinding
# defence, so explicitly allow only the Docker service and local development use.
mcp = FastMCP(
    "gemma-mcp",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["mcp:8765", "localhost:8765", "127.0.0.1:8765"],
    ),
)
