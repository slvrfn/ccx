"""One opt-in watcher. Native notifications feed a queue; refresh work never drops events."""

import contextlib
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from filelock import FileLock, Timeout
from watchfiles import watch

from ccx.errors import CcxError
from ccx.io import read_json, write_json
from ccx.project import Project

IGNORED = {
    ".git",
    ".opencode",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "dist",
    "build",
}


def relevant(project: Project, path: str) -> bool:
    try:
        relative = Path(path).absolute().relative_to(project.path)
    except ValueError:
        return False
    graph = Path(project.graph_out)
    return (
        not any(part in IGNORED for part in relative.parts)
        and not relative.is_relative_to(graph)
        and not relative.name.startswith(".env")
        and relative.suffix not in (".pem", ".key", ".swp", ".tmp", ".pyc")
    )


class Debouncer:
    def __init__(self, seconds: float) -> None:
        self.seconds, self.changed_at = seconds, float("inf")
        self.dirty = False

    def touch(self, now: float) -> None:
        self.dirty, self.changed_at = True, now

    def due(self, now: float) -> bool:
        return self.dirty and now - self.changed_at >= self.seconds

    def consume(self) -> None:
        self.dirty = False


def is_running(state: Path) -> bool:
    try:
        with FileLock(state / "watch.lock", timeout=0):
            return False
    except Timeout:
        return True


def start(home: Path, state: Path, project: Project, interval: float) -> None:
    if is_running(state):
        raise CcxError("Watcher is already running.")
    token = uuid.uuid4().hex
    with (state / "watch.log").open("ab") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "ccx",
                "--home",
                str(home),
                "_watch-run",
                project.slug,
                "--interval",
                str(interval),
                "--token",
                token,
            ],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise CcxError(f"Watcher failed to start. See {state / 'watch.log'}")
        status = state / "watch.json"
        if status.exists() and read_json(status).get("token") == token:
            return
        time.sleep(0.05)
    # Signal only this launch, not an arbitrary PID or another watcher.
    (state / f"watch-stop-{token}").touch()
    raise CcxError(f"Watcher startup timed out. See {state / 'watch.log'}")


def stop(state: Path) -> None:
    if not is_running(state):
        return
    data = read_json(state / "watch.json")
    (state / f"watch-stop-{data['token']}").touch()
    deadline = time.monotonic() + 10
    while is_running(state) and time.monotonic() < deadline:
        time.sleep(0.05)
    if is_running(state):
        raise CcxError("Stop requested; active index update will finish before watcher exits.")


def run_loop(
    project: Project, state: Path, interval: float, token: str, refresh: Callable[[], object]
) -> None:
    events: queue.Queue[float] = queue.Queue()
    stopping = threading.Event()
    stop_file = state / f"watch-stop-{token}"
    debouncer = Debouncer(interval)

    def observe() -> None:
        try:
            for changes in watch(
                project.path,
                stop_event=stopping,
                debounce=100,
                step=50,
                watch_filter=lambda _change, path: relevant(project, path),
            ):
                if changes:
                    events.put(time.monotonic())
        except Exception as exc:
            print(f"Watch backend failed: {exc}", flush=True)
            stopping.set()

    with FileLock(state / "watch.lock", timeout=0):
        thread = threading.Thread(target=observe, daemon=True)
        thread.start()
        write_json(
            state / "watch.json",
            {"pid": os.getpid(), "token": token, "interval": interval, "running": True},
        )
        try:
            while not stopping.is_set() and not stop_file.exists():
                try:
                    debouncer.touch(events.get(timeout=0.1))
                    while True:
                        debouncer.touch(events.get_nowait())
                except queue.Empty:
                    pass
                if debouncer.due(time.monotonic()):
                    debouncer.consume()
                    try:
                        refresh()
                    except Exception as exc:
                        print(f"Refresh failed: {exc}", flush=True)
                        # Avoid hot-loop retry; retry after a quiet interval.
                        debouncer.touch(time.monotonic())
        finally:
            stopping.set()
            thread.join(timeout=2)
            stop_file.unlink(missing_ok=True)
            with contextlib.suppress(OSError):
                (state / "watch.json").unlink()
