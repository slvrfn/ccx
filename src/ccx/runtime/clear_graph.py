"""Explicitly confirmed graph deletion; never reached through auto-allowed MCP tools."""

import os
import shutil

from ccx.graph.output import require_owned
from ccx.io import safe_child
from ccx.runtime.state import lock, root

if __name__ == "__main__":
    with lock():
        output = safe_child(root(), os.environ["CCX_GRAPH_OUT"])
        if output.exists():
            require_owned(output)
            shutil.rmtree(output)
