"""Single graph writer, honors configurable output and code-only operation."""

import argparse
import json
import os

from ccx.graph.output import claim_output
from ccx.graph.status import graph_status
from ccx.io import safe_child
from ccx.process import SubprocessRunner
from ccx.runtime.state import lock, root


def build(full: bool = False) -> dict[str, object]:
    directory = safe_child(root(), os.environ["CCX_GRAPH_OUT"])
    semantic = os.environ.get("CCX_GRAPH_SEMANTIC", "false") == "true"
    with lock():
        claim_output(directory)
        # extract's cache gate provides incremental semantic extraction. update is
        # code-only in Graphify 0.9.83 and does not accept --out; GRAPHIFY_OUT does.
        if full or semantic or not (directory / "graph.json").exists():
            args = ["graphify", "extract", str(root()), "--out", str(directory)]
            if full:
                args.append("--force")
            args += ["--backend", "openai"] if semantic else ["--code-only"]
        else:
            args = ["graphify", "update", str(root())]
        env = dict(os.environ)
        env["GRAPHIFY_OUT"] = str(directory)
        env["OPENAI_BASE_URL"] = os.environ["CCX_INFERENCE_BASE_URL"]
        env["OPENAI_API_KEY"] = os.environ["CCX_INFERENCE_API_KEY"]
        env["GRAPHIFY_OPENAI_MODEL"] = os.environ["CCX_INFERENCE_MODEL"]
        # Semantic mode explicitly opts into a configured endpoint; code-only uses no LLM.
        SubprocessRunner().run(args, env=env, timeout=float(os.environ["CCX_INDEX_TIMEOUT"]))
        if "extract" in args:
            # extract writes graph/manifest/cache only; generate report and HTML explicitly.
            SubprocessRunner().run(
                [
                    "graphify",
                    "cluster-only",
                    str(root()),
                    "--graph",
                    str(directory / "graph.json"),
                    "--no-label",
                ],
                env=env,
                timeout=float(os.environ["CCX_INDEX_TIMEOUT"]),
            )
        return graph_status(directory)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true")
    print(json.dumps(build(parser.parse_args().full)))
