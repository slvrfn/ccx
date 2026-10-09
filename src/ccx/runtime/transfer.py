"""Milvus logical snapshots. Import stages a new collection and never overwrites one."""

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ccx.errors import CcxError
from ccx.graph.output import IDENTITY, MARKER, require_owned
from ccx.io import read_json, safe_child, write_json
from ccx.runtime.state import embedding_identity, lock, root, state_dir
from ccx.transfer import create_bundle, extract_bundle


def collection_name(path: str) -> str:
    return "code_chunks_" + hashlib.md5(path.encode(), usedforsecurity=False).hexdigest()[:8]


def connect() -> None:
    from pymilvus import connections

    connections.connect(alias="default", uri="http://" + os.environ["MILVUS_ADDRESS"])


def export(destination: Path) -> None:
    from pymilvus import Collection, utility

    connect()
    with lock(), tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        name = collection_name(str(root()))
        if not utility.has_collection(name):
            raise CcxError("No semantic collection to export. Run ccx reindex first.")
        collection = Collection(name)
        collection.flush()
        collection.load()
        vectors = directory / "vectors"
        vectors.mkdir()
        write_json(vectors / "schema.json", collection.schema.to_dict())
        iterator = collection.query_iterator(
            batch_size=500, expr="", output_fields=["*"], consistency_level="Strong"
        )
        rows = 0
        try:
            with (vectors / "rows.jsonl").open("w") as stream:
                while batch := iterator.next():
                    for row in batch:
                        stream.write(json.dumps(row) + "\n")
                    rows += len(batch)
        finally:
            iterator.close()
        graph = safe_child(root(), os.environ["CCX_GRAPH_OUT"])
        if graph.exists():
            require_owned(graph)
            for path in graph.rglob("*"):
                if path.is_file() and path.suffix in (".json", ".md", ".html"):
                    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
                        raise CcxError("Symlink graph files cannot be exported.")
                    dest = directory / "graph" / path.relative_to(graph)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, dest)
        snapshot = Path.home() / ".context" / "mcp-codebase-snapshot.json"
        if snapshot.exists():
            shutil.copyfile(snapshot, directory / "snapshot.json")
        create_bundle(
            directory,
            destination,
            {
                "created_at": datetime.now(UTC).isoformat(),
                "source_mount": str(root()),
                "collection": name,
                "row_count": rows,
                "embedding": embedding_identity(),
                "graphify_version": os.environ["CCX_GRAPH_VERSION"],
                "claude_context_version": os.environ["CCX_CONTEXT_VERSION"],
            },
        )


def probe_dimension() -> int:
    """Reject vector-dimension mismatch before changing Milvus."""
    from urllib.request import Request, urlopen

    request = Request(
        os.environ["OPENAI_BASE_URL"].rstrip("/") + "/embeddings",
        data=json.dumps(
            {"model": os.environ["EMBEDDING_MODEL"], "input": ["dimension probe"]}
        ).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + os.environ["OPENAI_API_KEY"],
        },
    )
    with urlopen(request, timeout=30) as response:  # noqa: S310
        return len(json.load(response)["data"][0]["embedding"])


def restore(source: Path) -> None:
    from pymilvus import Collection, CollectionSchema, utility

    connect()
    with lock(), tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        manifest = extract_bundle(source, directory)
        if manifest["claude_context_version"] != os.environ["CCX_CONTEXT_VERSION"]:
            raise CcxError("Claude Context version mismatch; reindex instead of importing.")
        if manifest["embedding"]["model"] != os.environ["EMBEDDING_MODEL"]:
            raise CcxError("Embedding model mismatch. Use the same model or rebuild.")
        schema_data = read_json(directory / "vectors/schema.json")
        schema_data["description"] = f"codebasePath:{root()}"
        vector_fields = [f for f in schema_data["fields"] if f["name"] == "vector"]
        if len(vector_fields) != 1 or int(vector_fields[0]["params"]["dim"]) != probe_dimension():
            raise CcxError("Embedding dimension mismatch.")
        name = collection_name(str(root()))
        if utility.has_collection(name):
            raise CcxError("Target collection exists. Explicitly clear-index before importing.")
        graph = safe_child(root(), os.environ["CCX_GRAPH_OUT"])
        if graph.exists():
            raise CcxError("Target graph output exists. Explicitly clear-graph before importing.")
        staging = f"{name}_import_{uuid.uuid4().hex[:8]}"
        imported = False
        graph_installed = False
        try:
            collection = Collection(staging, CollectionSchema.construct_from_dict(schema_data))
            batch: list[dict[str, Any]] = []
            count = 0
            with (directory / "vectors/rows.jsonl").open() as stream:
                for line in stream:
                    row = json.loads(line)
                    # Source chunks remain byte-for-byte unchanged; only metadata paths are remapped.
                    for key in ("relativePath", "metadata"):
                        if isinstance(row.get(key), str):
                            row[key] = row[key].replace(manifest["source_mount"], str(root()))
                    batch.append(row)
                    count += 1
                    if len(batch) == 500:
                        collection.insert(batch)
                        batch.clear()
                if batch:
                    collection.insert(batch)
            if count != manifest["row_count"]:
                raise CcxError("Exported row count does not match the manifest.")
            collection.flush()
            collection.create_index("vector", {"index_type": "AUTOINDEX", "metric_type": "COSINE"})
            collection.load()
            if collection.num_entities != count:
                raise CcxError("Imported collection row count mismatch.")
            graph_source = directory / "graph"
            if graph_source.exists():
                # Remap only graph artifacts; no code source, credentials, or executable files.
                for path in graph_source.rglob("*"):
                    if path.is_file():
                        path.write_text(
                            path.read_text().replace(manifest["source_mount"], str(root()))
                        )
                graph.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(graph_source, graph)
                graph_installed = True
                write_json(graph / MARKER, IDENTITY)
            utility.rename_collection(staging, name)
            imported = True
            stamp = datetime.now(UTC).isoformat()
            write_json(
                Path.home() / ".context/mcp-codebase-snapshot.json",
                {
                    "formatVersion": "v2",
                    "codebases": {
                        str(root()): {
                            "status": "indexed",
                            "indexedFiles": 0,
                            "totalChunks": count,
                            "lastUpdated": stamp,
                            "indexStatus": "completed",
                        }
                    },
                    "lastUpdated": stamp,
                },
            )
            write_json(state_dir() / "embedding.json", embedding_identity())
            write_json(state_dir() / "imported.json", {"first_refresh_requires_full": True})
        except BaseException:
            if utility.has_collection(name if imported else staging):
                utility.drop_collection(name if imported else staging)
            if graph_installed:
                shutil.rmtree(graph)
            raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["export", "import"])
    parser.add_argument("path", type=Path)
    arguments = parser.parse_args()
    (export if arguments.operation == "export" else restore)(arguments.path)
