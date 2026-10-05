"""用于Blender适配器的Blender工具链传输模块。"""

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from ...config import BlenderClientConfig


@dataclass(frozen=True)
class BlenderCommandResult:
    command: tuple[str, ...]
    cwd: str
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    environment: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": list(self.command),
            "cwd": self.cwd,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
        }


class BlenderToolchain:
    """Run a script inside Blender or a ``bpy`` Python."""

    def __init__(self, config: BlenderClientConfig) -> None:
        self._config = config

    @property
    def blender(self) -> Path | None:
        return self._config.blender_executable

    @staticmethod
    def is_application(binary: Path) -> bool:
        return "blender" in binary.stem.lower()

    def run_script(
        self,
        script_path: Path,
        *,
        cwd: Path,
        extra_args: Sequence[str] = (),
        timeout: float | None = None,
        environment: dict[str, str] | None = None,
        blender: Path | None = None,
    ) -> BlenderCommandResult:
        """Run ``script_path`` with ``extra_args``."""
        binary = blender or self.blender
        if binary is None:
            raise FileNotFoundError(
                "Blender executable was not found; configure blender_root "
                "or add blender to PATH"
            )
        if self.is_application(binary):
            command = [
                str(binary), "--background", "--factory-startup",
                "--python", str(script_path), "--",
            ]
        else:
            command = [str(binary), str(script_path)]
        command.extend(str(item) for item in extra_args)
        return self.run(
            command,
            cwd=cwd,
            timeout=timeout,
            environment=environment,
        )

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        timeout: float | None = None,
        environment: dict[str, str] | None = None,
    ) -> BlenderCommandResult:
        resolved = tuple(str(item) for item in command)
        merged = dict(os.environ)
        merged.update(
            {
                key: str(value)
                for key, value in (environment or {}).items()
            }
        )
        try:
            completed = subprocess.run(
                list(resolved),
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                env=merged,
                errors="replace",
            )
        except subprocess.TimeoutExpired as exc:
            return BlenderCommandResult(
                command=resolved,
                cwd=str(cwd),
                returncode=124,
                stdout=str(exc.stdout or "")[-2000:],
                stderr=str(exc.stderr or "")[-2000:],
                timed_out=True,
                environment=dict(environment or {}),
            )
        return BlenderCommandResult(
            command=resolved,
            cwd=str(cwd),
            returncode=int(completed.returncode),
            stdout=(completed.stdout or "")[-2000:],
            stderr=(completed.stderr or "")[-2000:],
            environment=dict(environment or {}),
        )
