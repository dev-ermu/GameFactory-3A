"""Node toolchain transport for the three.js adapter."""

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from ...config import ThreeClientConfig


@dataclass(frozen=True)
class NodeCommandResult:
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

    @property
    def output(self) -> str:
        return "\n".join(
            item
            for item in (
                self.stdout.strip(),
                self.stderr.strip(),
            )
            if item
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": list(self.command),
            "cwd": self.cwd,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
        }


class NodeToolchain:
    """Resolve and run Node, npm, pnpm, and yarn executables."""

    def __init__(self, config: ThreeClientConfig) -> None:
        self._config = config

    def executable(self, name: str) -> Path | None:
        """Resolve one toolchain executable path."""

        candidates: list[Path] = []
        node_root = self._config.node_root
        if node_root is not None:
            suffixes = (
                ("", ".cmd", ".exe")
                if os.name == "nt"
                else ("",)
            )
            for parent in (node_root, node_root / "bin"):
                for suffix in suffixes:
                    candidates.append(parent / f"{name}{suffix}")
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        found = shutil.which(name)
        return Path(found) if found else None

    @property
    def node(self) -> Path | None:
        return self.executable("node")

    @property
    def package_manager(self) -> Path | None:
        return self.executable(self._config.package_manager)

    def node_version(self, *, timeout: float = 10.0) -> str:
        node = self.node
        if node is None:
            return ""
        try:
            completed = subprocess.run(
                [str(node), "--version"],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except Exception:
            return ""
        return completed.stdout.strip() if completed.returncode == 0 else ""

    def run_script(
        self,
        script: str,
        *,
        cwd: Path,
        extra_args: Sequence[str] = (),
        timeout: float | None = None,
        environment: dict[str, str] | None = None,
    ) -> NodeCommandResult:
        """Run one ``package.json`` script through the package manager."""

        manager = self.package_manager
        if manager is None:
            raise FileNotFoundError(
                "Node package manager was not found: "
                f"{self._config.package_manager}"
            )
        command = [str(manager), "run", str(script)]
        if extra_args:
            if self._config.package_manager == "npm":
                command.append("--")
            command.extend(str(item) for item in extra_args)
        return self.run(
            command,
            cwd=cwd,
            timeout=timeout,
            environment=environment,
        )

    def run_node(
        self,
        script_path: Path,
        *,
        cwd: Path,
        extra_args: Sequence[str] = (),
        timeout: float | None = None,
        environment: dict[str, str] | None = None,
    ) -> NodeCommandResult:
        """Run one Node script file."""

        node = self.node
        if node is None:
            raise FileNotFoundError(
                "Node executable was not found; configure node_root "
                "or add node to PATH"
            )
        command = [str(node), str(script_path)]
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
    ) -> NodeCommandResult:
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
            )
        except subprocess.TimeoutExpired as exc:
            return NodeCommandResult(
                command=resolved,
                cwd=str(cwd),
                returncode=124,
                stdout=str(exc.stdout or ""),
                stderr=str(exc.stderr or ""),
                timed_out=True,
                environment=dict(environment or {}),
            )
        return NodeCommandResult(
            command=resolved,
            cwd=str(cwd),
            returncode=int(completed.returncode),
            stdout=completed.stdout,
            stderr=completed.stderr,
            environment=dict(environment or {}),
        )

    def spawn(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        environment: dict[str, str] | None = None,
    ) -> subprocess.Popen[Any]:
        """Start a long-lived process such as a dev server."""

        merged = dict(os.environ)
        merged.update(
            {
                key: str(value)
                for key, value in (environment or {}).items()
            }
        )
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        return subprocess.Popen(
            [str(item) for item in command],
            cwd=str(cwd),
            env=merged,
            creationflags=creationflags,
            start_new_session=os.name != "nt",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
