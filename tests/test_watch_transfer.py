import json
import stat
import threading
import time
import zipfile
from pathlib import Path

import pytest
from filelock import FileLock

from ccx.errors import CcxError
from ccx.graph.output import claim_output, require_owned
from ccx.graph.status import graph_status
from ccx.io import write_json
from ccx.project import Project
from ccx.transfer import create_bundle, extract_bundle
from ccx.watch import Debouncer, is_running, relevant, run_loop, stop


def test_debounce_quiet_period() -> None:
    debounce = Debouncer(5)
    assert not debounce.due(100)
    debounce.touch(1)
    assert not debounce.due(5)
    debounce.touch(4)
    assert not debounce.due(8.9)
    assert debounce.due(9)
    debounce.consume()
    assert not debounce.due(10)


@pytest.mark.parametrize(
    "path",
    [
        ".git/index",
        ".opencode/a.json",
        "node_modules/module.js",
        ".venv/a.py",
        "graphify-out/graph.json",
        "graphify-out/cache/1.json",
        ".env",
        "nested/.env.local",
        "private.key",
        "__pycache__/a.pyc",
    ],
)
def test_watch_ignores_generated(project: Project, path: str) -> None:
    assert not relevant(project, str(project.path / path))


@pytest.mark.parametrize("path", ["src/auth.py", "README.md", "a.py", "nested/deleted.py"])
def test_watch_accepts_source(project: Project, path: str) -> None:
    assert relevant(project, str(project.path / path))


def test_watch_custom_graph_folder(project: Project) -> None:
    project = Project(project.path, project.slug, True, "artifacts/context")
    assert not relevant(project, str(project.path / "artifacts/context/graph.json"))
    assert relevant(project, str(project.path / "artifacts/other.py"))
    assert not relevant(project, "/somewhere/else")


def test_watch_lock_not_pid(tmp_path: Path) -> None:
    assert not is_running(tmp_path)
    with FileLock(tmp_path / "watch.lock"):
        assert is_running(tmp_path)
    assert not is_running(tmp_path)
    stop(tmp_path)  # idempotent; no process is killed


def test_real_watcher_retains_changes_during_refresh(project: Project, tmp_path: Path) -> None:
    state = tmp_path / "watch-state"
    state.mkdir()
    entered = threading.Event()
    release = threading.Event()
    completed = threading.Event()
    calls: list[int] = []

    def refresh() -> None:
        calls.append(1)
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
        else:
            completed.set()

    worker = threading.Thread(
        target=run_loop, args=(project, state, 0.1, "test-token", refresh), daemon=True
    )
    worker.start()
    try:
        deadline = time.monotonic() + 5
        while not (state / "watch.json").exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        time.sleep(0.2)  # Let native notification registration complete.
        (project.path / "first.py").write_text("first = 1")
        assert entered.wait(5)
        (project.path / "second.py").write_text("second = 2")
        time.sleep(0.2)
        release.set()
        assert completed.wait(5)
    finally:
        release.set()
        (state / "watch-stop-test-token").touch()
        worker.join(5)
    assert not worker.is_alive()
    assert not is_running(state)
    assert len(calls) >= 2


def test_graph_counts(tmp_path: Path) -> None:
    assert graph_status(tmp_path) == {"exists": False}
    write_json(tmp_path / "graph.json", {"nodes": [{}, {}], "links": [{}]})
    assert graph_status(tmp_path)["nodes"] == 2
    assert graph_status(tmp_path)["edges"] == 1


def test_graph_ownership_refuses_source_directory(tmp_path: Path) -> None:
    (tmp_path / "important.py").write_text("important = True")
    with pytest.raises(CcxError, match="unmanaged"):
        claim_output(tmp_path)
    with pytest.raises(CcxError, match="unmanaged"):
        require_owned(tmp_path)
    assert (tmp_path / "important.py").exists()


def test_graph_ownership_idempotent(tmp_path: Path) -> None:
    output = tmp_path / "graph"
    claim_output(output)
    (output / "graph.json").write_text("{}")
    claim_output(output)
    require_owned(output)


def fixture_bundle(tmp_path: Path) -> Path:
    staging = tmp_path / "stage"
    staging.mkdir()
    write_json(staging / "vectors/schema.json", {"fields": []})
    (staging / "vectors/rows.jsonl").write_text("")
    write_json(staging / "graph/graph.json", {"nodes": []})
    bundle = tmp_path / "bundle.zip"
    create_bundle(staging, bundle, {"embedding": {"model": "test"}})
    return bundle


def test_bundle_roundtrip(tmp_path: Path) -> None:
    source = fixture_bundle(tmp_path)
    output = tmp_path / "out"
    manifest = extract_bundle(source, output)
    assert manifest["format_version"] == 1
    assert (output / "graph/graph.json").exists()
    assert ".env" not in manifest["files"]


@pytest.mark.parametrize("name", ["../escape", "/absolute", "nested/../../escape", "C:\\evil"])
def test_bundle_rejects_traversal(tmp_path: Path, name: str) -> None:
    bundle = tmp_path / "evil.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr(name, "bad")
    with pytest.raises(CcxError):
        extract_bundle(bundle, tmp_path / "out")


def test_bundle_rejects_symlink(tmp_path: Path) -> None:
    bundle = tmp_path / "evil.zip"
    member = zipfile.ZipInfo("link")
    member.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr(member, "/etc/passwd")
    with pytest.raises(CcxError, match="Unsafe"):
        extract_bundle(bundle, tmp_path / "out")


def test_bundle_detects_corruption(tmp_path: Path) -> None:
    bundle = fixture_bundle(tmp_path)
    damaged = tmp_path / "damaged.zip"
    with zipfile.ZipFile(bundle) as src, zipfile.ZipFile(damaged, "w") as dst:
        for name in src.namelist():
            data = b"modified" if name == "graph/graph.json" else src.read(name)
            dst.writestr(name, data)
    with pytest.raises(CcxError, match="Checksum"):
        extract_bundle(damaged, tmp_path / "out")


def test_bundle_rejects_extra_and_future_versions(tmp_path: Path) -> None:
    bundle = tmp_path / "future.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"format_version": 500}))
    with pytest.raises(CcxError, match="Unsupported"):
        extract_bundle(bundle, tmp_path / "out")
