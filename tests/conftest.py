from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from ccx.config import Settings
from ccx.process import Result
from ccx.project import Project


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.environments: list[Mapping[str, str] | None] = []
        self.response = Result()

    def run(
        self,
        args: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        capture: bool = True,
        timeout: float | None = 120,
    ) -> Result:
        self.calls.append(list(args))
        self.environments.append(env)
        return self.response


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings.load(tmp_path / "home")


@pytest.fixture
def project(tmp_path: Path) -> Project:
    repo = tmp_path / "sample repo"
    repo.mkdir()
    return Project.from_path(repo)


@pytest.fixture
def runner() -> FakeRunner:
    return FakeRunner()
