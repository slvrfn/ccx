"""Offline uv contract: dedicated persistent environment, host .venv untouched."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv executable required")
def test_uv_sync_and_no_sync_reuse_isolated_environment(tmp_path: Path) -> None:
    executable = os.environ.get("CCX_TEST_UV_EXECUTABLE") or shutil.which("uv")
    assert executable
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "fixture"\nversion = "0.0.1"\n'
        'requires-python = ">=3.12"\ndependencies = []\n'
    )
    host_environment = repo / ".venv"
    host_environment.mkdir()
    (host_environment / "host-only.txt").write_text("leave host environment untouched")
    home = tmp_path / "persistent-home"
    environment = home / ".venvs/project"
    cache = home / ".cache/uv"
    values = {
        **os.environ,
        "UV_PROJECT_ENVIRONMENT": str(environment),
        "UV_CACHE_DIR": str(cache),
        "UV_HTTP_TIMEOUT": "300",
        "UV_CONCURRENT_DOWNLOADS": "2",
        "UV_LINK_MODE": "copy",
    }
    values.pop("VIRTUAL_ENV", None)
    values.pop("UV_NO_SYNC", None)

    def invoke(*args: str) -> str:
        completed = subprocess.run(
            [executable, *args],
            cwd=repo,
            env=values,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert completed.returncode == 0, completed.stderr
        return completed.stdout

    invoke("sync", "--offline", "--python", sys.executable)
    sentinel = environment / "environment-was-synced.txt"
    sentinel.write_text("persistent")
    invoke("sync", "--locked", "--offline", "--python", sys.executable)
    prefix = json.loads(
        invoke(
            "run",
            "--offline",
            "--no-sync",
            "python",
            "-c",
            "import json,sys; print(json.dumps(sys.prefix))",
        )
    )
    assert Path(prefix).resolve() == environment.resolve()
    assert sentinel.read_text() == "persistent"
    assert (host_environment / "host-only.txt").read_text() == "leave host environment untouched"
    assert not (host_environment / "pyvenv.cfg").exists()
    assert cache.is_dir()
