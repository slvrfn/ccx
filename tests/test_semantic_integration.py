"""Optional real Node MCP + Milvus Lite contract test with an offline embedding stub.

This tests interoperability and data flow, not the retrieval quality of real models.
Set CCX_TEST_SEMANTIC=1 and CCX_UPSTREAM_NODE_MODULES to the locked npm install.
Run with pymilvus==2.5.18, milvus-lite==2.5.1, setuptools<81, ccx and pytest.
"""

import asyncio
import hashlib
import json
import os
import shutil
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("CCX_TEST_SEMANTIC") != "1",
    reason="Requires opt-in, Node dependencies and local Milvus Lite.",
)
def test_real_semantic_lifecycle_and_transfer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import grpc
    from milvus_lite.server import Server
    from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility

    from ccx.errors import CcxError
    from ccx.mcp_client import result_text, session
    from ccx.runtime import mcp_server, transfer

    node_modules = Path(os.environ["CCX_UPSTREAM_NODE_MODULES"])
    (tmp_path / "node_modules").symlink_to(node_modules, target_is_directory=True)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    for file in Path(mcp_server.__file__).parent.glob("*.mjs"):
        shutil.copyfile(file, runtime / file.name)
    monkeypatch.setenv("CCX_TEST_JS_DIR", str(runtime))
    fixture = Path(__file__).parent / "fixtures/mcp_integration_server.py"

    def invoke(tool: str, path: Path, **arguments: Any) -> str:
        async def via_stdio() -> str:
            async with session(
                sys.executable, ["-W", "error", str(fixture)], 90, dict(os.environ)
            ) as client:
                return result_text(await client.call_tool(tool, {"path": str(path), **arguments}))

        return asyncio.run(via_stdio())

    class Embeddings(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            items = payload["input"]
            if isinstance(items, str):
                items = [items]
            rows = []
            for index, item in enumerate(items):
                digest = hashlib.sha256(str(item).encode()).digest()
                rows.append(
                    {
                        "object": "embedding",
                        "index": index,
                        "embedding": [(v + 1) / 256 for v in digest[:8]],
                    }
                )
            body = json.dumps(
                {
                    "object": "list",
                    "data": rows,
                    "model": "test-embedding",
                    "usage": {"prompt_tokens": 1, "total_tokens": 1},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    endpoint = ThreadingHTTPServer(("127.0.0.1", 0), Embeddings)
    thread = threading.Thread(target=endpoint.serve_forever, daemon=True)
    thread.start()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = Server(str(tmp_path / "test.db"), address=f"127.0.0.1:{port}")
    assert server.init() and server.start()
    try:
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("Milvus Lite did not become ready")
        repo = tmp_path / "repository"
        repo.mkdir()
        # Reproduce ccx's build-context allowlist: upstream would prune "src"
        # before processing !src/. Keep genuine Git exclusions effective.
        (repo / ".dockerignore").write_text("**\n!Dockerfile\n!src/\n!src/ccx/\n!src/ccx/**\n")
        (repo / ".gitignore").write_text("ignored.py\n")
        (repo / "ignored.py").write_text("def should_never_be_indexed():\n    return 0\n")
        source = repo / "src/ccx/auth.py"
        source.parent.mkdir(parents=True)
        source.write_text('def authenticate(token):\n    return token == "original"\n')
        for key, value in {
            "HOME": str(tmp_path / "home"),
            "CCX_PROJECT_PATH": str(repo),
            "CCX_GRAPH_OUT": "graphify-out",
            "CCX_INDEX_TIMEOUT": "60",
            "OPENAI_BASE_URL": f"http://127.0.0.1:{endpoint.server_port}/v1",
            "OPENAI_API_KEY": "test",
            "EMBEDDING_PROVIDER": "OpenAI",
            "EMBEDDING_MODEL": "test-embedding",
            "MILVUS_ADDRESS": f"127.0.0.1:{port}",
            "HYBRID_MODE": "false",
            "CCX_GRAPH_VERSION": "0.9.83",
            "CCX_CONTEXT_VERSION": "0.1.15",
        }.items():
            monkeypatch.setenv(key, value)
        result = invoke("index_codebase", repo)
        assert "indexed" in result
        assert json.loads(result)["indexedFiles"] == 1
        assert "indexed" in invoke("get_indexing_status", repo)
        assert "authenticate" in invoke("search_code", repo, query="authentication")
        source.write_text('def authenticate(token):\n    return token == "changed"\n')
        result = json.loads(invoke("index_codebase", repo))
        assert result["modified"] == 1
        assert "changed" in invoke("search_code", repo, query="authentication")
        extra = repo / "extra.py"
        extra.write_text("def new_helper():\n    return 12345\n")
        assert json.loads(invoke("index_codebase", repo))["added"] == 1
        extra.unlink()
        assert json.loads(invoke("index_codebase", repo))["removed"] == 1

        # Empty completion must fail quickly instead of leaving the client
        # polling a 100%/indexing snapshot indefinitely.
        with monkeypatch.context() as isolated:
            empty = tmp_path / "empty"
            empty.mkdir()
            (empty / "code.py").write_text("def excluded():\n    return 0\n")
            (empty / ".gitignore").write_text("**\n")
            isolated.setenv("CCX_PROJECT_PATH", str(empty))
            isolated.setenv("HOME", str(tmp_path / "empty-home"))
            started = time.monotonic()
            with pytest.raises(CcxError, match="zero chunks"):
                invoke("index_codebase", empty)
            assert time.monotonic() - started < 30
            info = json.loads(invoke("get_indexing_status", empty))
            assert info["status"] == "indexfailed"
            # Upstream clear_index excludes failed-only snapshots; full reindex
            # is the production recovery path. Remove this test's empty fixture.
            transfer.connect()
            utility.drop_collection(transfer.collection_name(str(empty)))

        # Reproduce an existing custom-model collection with the wrong width.
        with monkeypatch.context() as isolated:
            mismatched = tmp_path / "mismatched"
            mismatched.mkdir()
            (mismatched / "code.py").write_text("def example():\n    return 123\n")
            isolated.setenv("CCX_PROJECT_PATH", str(mismatched))
            isolated.setenv("HOME", str(tmp_path / "mismatch-home"))
            transfer.connect()
            name = transfer.collection_name(str(mismatched))
            Collection(
                name,
                CollectionSchema(
                    [
                        FieldSchema(
                            name="id", dtype=DataType.VARCHAR, max_length=100, is_primary=True
                        ),
                        FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=1536),
                    ],
                    description=f"codebasePath:{mismatched}",
                ),
            )
            with pytest.raises(CcxError, match="dimension mismatch"):
                invoke("index_codebase", mismatched)
            # Explicit full rebuild repairs only this project's vector schema.
            fixed = json.loads(invoke("index_codebase", mismatched, force=True))
            assert fixed["status"] == "indexed"
            dim = next(
                field.params["dim"]
                for field in Collection(name).schema.fields
                if field.name == "vector"
            )
            assert dim == 8
            invoke("clear_index", mismatched)

        bundle = tmp_path / "export.zip"
        transfer.export(bundle)
        copied = tmp_path / "restored"
        shutil.copytree(repo, copied)
        monkeypatch.setenv("CCX_PROJECT_PATH", str(copied))
        monkeypatch.setenv("HOME", str(tmp_path / "restored-home"))
        try:
            transfer.restore(bundle)
        except grpc.RpcError as exc:
            # Milvus Lite 2.5 lacks RenameCollection. Assert production rollback
            # rather than replacing that RPC with a fake and claiming a round trip.
            assert exc.code() == grpc.StatusCode.UNIMPLEMENTED
            assert not utility.has_collection(transfer.collection_name(str(copied)))
            assert not any("_import_" in name for name in utility.list_collections())
            monkeypatch.setenv("CCX_PROJECT_PATH", str(repo))
            monkeypatch.setenv("HOME", str(tmp_path / "home"))
            invoke("clear_index", repo)
            assert not utility.has_collection(transfer.collection_name(str(repo)))
            return
        assert "authenticate" in invoke("search_code", copied, query="authentication")
        collection = Collection(transfer.collection_name(str(copied)))
        assert collection.num_entities > 0
        assert "indexed" in invoke("index_codebase", copied)
        invoke("clear_index", copied)
        assert not utility.has_collection(transfer.collection_name(str(copied)))
    finally:
        connections.disconnect("default")
        server.stop()
        endpoint.shutdown()
        endpoint.server_close()
        thread.join(timeout=2)
