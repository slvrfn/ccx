"""Configuration with explicit precedence: environment > .env > shipped defaults."""

import math
import os
import re
import secrets
import shutil
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from dotenv import dotenv_values

from ccx.errors import CcxError
from ccx.io import atomic_write, safe_child


def asset_root() -> Path:
    return Path(str(files("ccx").joinpath("assets")))


def default_home() -> Path:
    return Path(os.environ.get("CCX_HOME", "~/.claude-context-cli")).expanduser().resolve()


@dataclass(frozen=True)
class Settings:
    home: Path
    values: dict[str, str]

    @classmethod
    def load(cls, home: Path | None = None) -> "Settings":
        home = (home or default_home()).resolve()
        defaults = dotenv_values(asset_root() / ".env.example", interpolate=False)
        active = dotenv_values(home / ".env", interpolate=False)
        values = {k: str(v or "") for k, v in defaults.items()}
        values.update({k: str(v or "") for k, v in active.items()})
        values.update({k: os.environ[k] for k in values if k in os.environ})
        result = cls(home, values)
        for key in ("GRAPHIFY_ENABLED", "GRAPHIFY_SEMANTIC_EXTRACTION", "GRAPHIFY_COMMIT_OUTPUT"):
            result.boolean(key)
        for key in ("WATCH_DEBOUNCE_SECONDS", "INDEX_TIMEOUT_SECONDS", "COMMAND_TIMEOUT_SECONDS"):
            if result.number(key) <= 0:
                raise CcxError(f"{key} must be positive.")
        for key in (
            "MILVUS_PORT",
            "MINIO_CONSOLE_PORT",
            "ATTU_PORT",
            "INFERENCE_API_PORT",
            "EMBEDDING_API_PORT",
        ):
            if not result.get(key).isdigit() or not 1 <= int(result.get(key)) <= 65535:
                raise CcxError(f"{key} must be a port in 1..65535.")
        safe_child(Path("/workspace/repository"), result.get("GRAPHIFY_OUT_DIR"))
        for key in ("GRAPHIFY_VERSION", "CLAUDE_CONTEXT_VERSION"):
            if not re.fullmatch(r"\d+\.\d+\.\d+(?:[a-zA-Z0-9.+-]*)?", result.get(key)):
                raise CcxError(f"{key} must be an exact package version.")
        for prefix in ("INFERENCE", "EMBEDDING"):
            result.url(prefix)
        return result

    def get(self, key: str) -> str:
        return self.values[key]

    def boolean(self, key: str) -> bool:
        value = self.get(key).lower()
        if value not in ("true", "false"):
            raise CcxError(f"{key} must be true or false.")
        return value == "true"

    def number(self, key: str) -> float:
        try:
            value = float(self.get(key))
            if not math.isfinite(value):
                raise ValueError("not finite")
            return value
        except ValueError as exc:
            raise CcxError(f"{key} must be numeric.") from exc

    def url(self, prefix: str) -> str:
        from urllib.parse import urlsplit

        override = self.get(f"{prefix}_API_BASE_URL")
        if override:
            parsed = urlsplit(override)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username:
                raise CcxError(f"Invalid {prefix}_API_BASE_URL (HTTP(S), no embedded credentials).")
            return override.rstrip("/")
        host = self.get(f"{prefix}_API_HOST")
        if not re.fullmatch(r"[a-zA-Z0-9._-]+", host):
            raise CcxError(f"Invalid {prefix}_API_HOST; use *_API_BASE_URL for IPv6 or HTTPS.")
        return f"http://{host}:{self.get(f'{prefix}_API_PORT')}/v1"

    def initialize(self, force: bool = False) -> None:
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name in ("compose.yaml", "Dockerfile", ".dockerignore"):
            dest = self.home / name
            if force or not dest.exists():
                shutil.copyfile(asset_root() / name, dest)
        shutil.copyfile(asset_root() / ".env.example", self.home / ".env.example")
        if not (self.home / ".env").exists():
            template = (asset_root() / ".env.example").read_text()
            template = template.replace("CHANGE_ME_GENERATED_ON_INIT", secrets.token_urlsafe(32))
            atomic_write(self.home / ".env", template)
        # Build context contains only the installed distribution, never target repositories.
        package = Path(__file__).parent
        shutil.copytree(
            package,
            self.home / "src" / "ccx",
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        for name in ("package.json", "package-lock.json", "requirements-container.txt"):
            shutil.copyfile(asset_root() / name, self.home / name)

    def check(self) -> dict[str, list[str]]:
        defaults = set(dotenv_values(asset_root() / ".env.example"))
        active = set(dotenv_values(self.home / ".env"))
        return {"missing": sorted(defaults - active), "unknown_or_stale": sorted(active - defaults)}
