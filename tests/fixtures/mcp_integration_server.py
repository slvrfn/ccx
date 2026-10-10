"""Test-only launcher for the real Python facade and staged, locked Node adapters."""

import os
from pathlib import Path

from ccx.runtime import mcp_server

if __name__ == "__main__":
    runtime = Path(os.environ["CCX_TEST_JS_DIR"])
    mcp_server.UPSTREAM = runtime / "upstream.mjs"
    mcp_server.INCREMENTAL = runtime / "incremental.mjs"
    mcp_server.mcp.run(transport="stdio")
