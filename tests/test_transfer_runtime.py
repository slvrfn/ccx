"""Import success/rollback logic without a Milvus service; live RPC tested separately."""

import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import Mock

import pytest

from ccx.errors import CcxError
from ccx.io import write_json
from ccx.runtime import transfer
from ccx.transfer import create_bundle


@pytest.fixture
def import_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    staging = tmp_path / "source"
    write_json(
        staging / "vectors/schema.json",
        {
            "description": "codebasePath:/old/path",
            "fields": [{"name": "vector", "params": {"dim": 8}}],
        },
    )
    (staging / "vectors/rows.jsonl").write_text(
        json.dumps(
            {
                "id": "one",
                "content": "literal /old/path must stay",
                "metadata": '{"path":"/old/path/code.py"}',
                "vector": [0.1] * 8,
            }
        )
        + "\n"
    )
    write_json(staging / "graph/graph.json", {"nodes": [{"file": "/old/path/code.py"}]})
    bundle = tmp_path / "bundle.zip"
    metadata = {
        "source_mount": "/old/path",
        "row_count": 1,
        "embedding": {"model": "embedder"},
        "claude_context_version": "0.1.15",
    }
    create_bundle(staging, bundle, metadata)
    root = tmp_path / "repo"
    root.mkdir()
    for key, value in {
        "HOME": str(tmp_path / "home"),
        "CCX_PROJECT_PATH": str(root),
        "CCX_GRAPH_OUT": "graph",
        "CCX_CONTEXT_VERSION": "0.1.15",
        "OPENAI_BASE_URL": "http://embedding/v1",
        "OPENAI_API_KEY": "test",
        "EMBEDDING_MODEL": "embedder",
        "EMBEDDING_PROVIDER": "OpenAI",
    }.items():
        monkeypatch.setenv(key, value)
    collection = Mock()
    collection.num_entities = 1
    fake = ModuleType("pymilvus")
    fake.Collection = Mock(return_value=collection)
    fake.CollectionSchema = Mock()
    fake.CollectionSchema.construct_from_dict.side_effect = lambda value: value
    fake.utility = Mock()
    fake.utility.has_collection.return_value = False
    monkeypatch.setitem(sys.modules, "pymilvus", fake)
    monkeypatch.setattr(transfer, "connect", lambda: None)
    monkeypatch.setattr(transfer, "probe_dimension", lambda: 8)
    return {
        "bundle": bundle,
        "root": root,
        "fake": fake,
        "collection": collection,
        "staging": staging,
        "metadata": metadata,
    }


def test_import_promotes_verified_collection_and_remaps_paths(import_case: dict[str, Any]) -> None:
    transfer.restore(import_case["bundle"])
    fake = import_case["fake"]
    fake.utility.rename_collection.assert_called_once()
    schema = fake.CollectionSchema.construct_from_dict.call_args.args[0]
    assert schema["description"] == f"codebasePath:{import_case['root']}"
    # Graph artifacts are remapped, but code chunks are not.
    assert str(import_case["root"]) in (import_case["root"] / "graph/graph.json").read_text()
    row = import_case["collection"].insert.call_args.args[0][0]
    assert row["content"] == "literal /old/path must stay"
    assert str(import_case["root"]) in row["metadata"]
    assert (import_case["root"] / "graph/.ccx-generated.json").exists()


def test_import_dimension_mismatch_has_no_writes(
    import_case: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(transfer, "probe_dimension", lambda: 32)
    with pytest.raises(CcxError, match="dimension"):
        transfer.restore(import_case["bundle"])
    import_case["fake"].Collection.assert_not_called()


def test_import_refuses_existing_collection(import_case: dict[str, Any]) -> None:
    import_case["fake"].utility.has_collection.return_value = True
    with pytest.raises(CcxError, match="exists"):
        transfer.restore(import_case["bundle"])
    import_case["fake"].Collection.assert_not_called()


def test_import_rolls_back_graph_and_collection(import_case: dict[str, Any]) -> None:
    fake = import_case["fake"]
    fake.utility.has_collection.side_effect = [False, True]
    fake.utility.rename_collection.side_effect = RuntimeError("rename failed")
    with pytest.raises(RuntimeError, match="rename failed"):
        transfer.restore(import_case["bundle"])
    fake.utility.drop_collection.assert_called_once()
    assert not (import_case["root"] / "graph").exists()


def test_import_count_mismatch_prevents_promotion(import_case: dict[str, Any]) -> None:
    import_case["collection"].num_entities = 0
    with pytest.raises(CcxError, match="row count mismatch"):
        transfer.restore(import_case["bundle"])
    import_case["fake"].utility.rename_collection.assert_not_called()
