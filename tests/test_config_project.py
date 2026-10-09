import json
import stat
from pathlib import Path

import pytest

from ccx.config import Settings, asset_root
from ccx.errors import CcxError
from ccx.io import atomic_write, read_json, safe_child, write_json
from ccx.project import Project, ProjectStore


def test_configuration_defaults(settings: Settings) -> None:
    assert settings.boolean("GRAPHIFY_ENABLED")
    assert not settings.boolean("GRAPHIFY_SEMANTIC_EXTRACTION")
    assert settings.url("INFERENCE") != settings.url("EMBEDDING")
    assert settings.number("WATCH_DEBOUNCE_SECONDS") == 5


def test_environment_precedence(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    settings.home.mkdir()
    (settings.home / ".env").write_text("INFERENCE_MODEL=file\n")
    monkeypatch.setenv("INFERENCE_MODEL", "environment")
    assert Settings.load(settings.home).get("INFERENCE_MODEL") == "environment"


@pytest.mark.parametrize(
    "key,value",
    [
        ("GRAPHIFY_ENABLED", "maybe"),
        ("MILVUS_PORT", "0"),
        ("ATTU_PORT", "not-a-port"),
        ("GRAPHIFY_OUT_DIR", "../escape"),
        ("GRAPHIFY_OUT_DIR", "."),
        ("WATCH_DEBOUNCE_SECONDS", "zero"),
        ("WATCH_DEBOUNCE_SECONDS", "-1"),
        ("GRAPHIFY_VERSION", "latest"),
        ("INFERENCE_API_HOST", "host;cmd"),
        ("INFERENCE_API_BASE_URL", "ftp://server"),
        ("INFERENCE_API_BASE_URL", "http://key@host"),
    ],
)
def test_bad_settings(
    key: str, value: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(key, value)
    with pytest.raises(CcxError):
        Settings.load(tmp_path)


def test_base_url_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("INFERENCE_API_BASE_URL", "https://gateway.example/v1/")
    assert Settings.load(tmp_path).url("INFERENCE") == "https://gateway.example/v1"


def test_init_idempotent_preserves_secret(settings: Settings) -> None:
    settings.initialize()
    content = (settings.home / ".env").read_text()
    assert "CHANGE_ME_GENERATED_ON_INIT" not in content
    assert stat.S_IMODE((settings.home / ".env").stat().st_mode) == 0o600
    settings.initialize(force=True)
    assert (settings.home / ".env").read_text() == content
    assert settings.check() == {"missing": [], "unknown_or_stale": []}
    assert (settings.home / "src/ccx/runtime/upstream.mjs").exists()


def test_env_check_reports_drift(settings: Settings) -> None:
    settings.home.mkdir()
    (settings.home / ".env").write_text("OLD_SETTING=true\n")
    result = settings.check()
    assert result["unknown_or_stale"] == ["OLD_SETTING"]
    assert "GRAPHIFY_ENABLED" in result["missing"]


def test_project_identity_and_alias(project: Project, tmp_path: Path) -> None:
    alias = tmp_path / "alias"
    alias.symlink_to(project.path, target_is_directory=True)
    assert Project.from_path(alias) == project
    assert Project.from_path(project.path).slug == project.slug
    other = tmp_path / "other" / project.path.name
    other.mkdir(parents=True)
    assert Project.from_path(other).slug != project.slug
    assert project.mount == f"/workspace/{project.slug}"
    assert project.container == f"ccx-{project.slug}"


def test_store_roundtrip(settings: Settings, project: Project) -> None:
    store = ProjectStore(settings.home)
    store.save(project)
    assert store.resolve(project.slug) == project
    assert store.resolve(str(project.path)) == project
    with pytest.raises(CcxError, match="not registered"):
        store.resolve("missing-12345678")


@pytest.mark.parametrize("relative", ["/tmp", "../x", ".", ".git", ".opencode/x", "a/../../x"])
def test_safe_child_rejects_escape(tmp_path: Path, relative: str) -> None:
    with pytest.raises(CcxError):
        safe_child(tmp_path, relative)


def test_safe_child_rejects_symlink(tmp_path: Path) -> None:
    (tmp_path / "graph").symlink_to(tmp_path / "real", target_is_directory=True)
    with pytest.raises(CcxError, match="symlink"):
        safe_child(tmp_path, "graph/output")


def test_atomic_io(tmp_path: Path) -> None:
    path = tmp_path / "nested/state.json"
    write_json(path, {"ok": True})
    assert read_json(path) == {"ok": True}
    atomic_write(path, '{"other": 2}')
    assert json.loads(path.read_text()) == {"other": 2}
    assert not list(path.parent.glob(".state.json.*"))
    path.write_text("broken")
    with pytest.raises(CcxError):
        read_json(path)


def test_packaged_templates_match_top_level() -> None:
    root = Path(__file__).parents[1]
    for name in ("Dockerfile", "compose.yaml", ".env.example", ".dockerignore"):
        assert (root / name).read_bytes() == (asset_root() / name).read_bytes()
