"""Only boundary allowed to launch shell commands; never uses shell=True."""

import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from ccx.errors import CcxError


@dataclass(frozen=True)
class Result:
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0


class Runner(Protocol):
    def run(
        self,
        args: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        capture: bool = True,
        timeout: float | None = 120,
    ) -> Result: ...


class SubprocessRunner:
    def run(
        self,
        args: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        capture: bool = True,
        timeout: float | None = 120,
    ) -> Result:
        try:
            result = subprocess.run(
                list(args),
                env={**os.environ, **(env or {})},
                capture_output=capture,
                text=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise CcxError(
                f"Executable not found: {args[0]}. Install Docker with Compose v2."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise CcxError(f"{args[0]} timed out after {timeout}s.") from exc
        if result.returncode:
            # Never print full argv/environment: these may contain secrets.
            raise CcxError(
                f"{args[0]} failed (exit {result.returncode}): {(result.stderr or '')[-2000:]}"
            )
        return Result(result.stdout or "", result.stderr or "", result.returncode)
