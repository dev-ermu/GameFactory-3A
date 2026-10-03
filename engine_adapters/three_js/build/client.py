"""Stable web bundle build operations for ThreeClient v1."""

import re
from pathlib import Path
from typing import Any

from .._internal.transport import NodeToolchain
from ..config import ThreeClientConfig
from ..contracts import ThreeDiagnostic, ThreeOperationResult


_DIAGNOSTIC_PATTERN = re.compile(
    r"^(?P<file>[^\s(]+?)"
    r"(?:[(:](?P<line>\d+)[,:](?P<column>\d+)\)?)?"
    r"[:\s]+(?P<severity>error|warning)"
    r"(?:\s+(?P<code>TS\d+|[A-Z]+\d+))?[:\s]+"
    r"(?P<message>.+)$",
    flags=re.IGNORECASE,
)


def _diagnostics(output: str) -> list[ThreeDiagnostic]:
    results: list[ThreeDiagnostic] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = _DIAGNOSTIC_PATTERN.match(stripped)
        if not match:
            continue
        results.append(
            ThreeDiagnostic(
                severity=match.group("severity").lower(),
                message=match.group("message").strip(),
                code=str(match.group("code") or ""),
                file=str(match.group("file") or "").strip(),
                line=(
                    int(match.group("line"))
                    if match.group("line")
                    else None
                ),
                column=(
                    int(match.group("column"))
                    if match.group("column")
                    else None
                ),
                source="vite",
            )
        )
    return results


def _bundle_artifacts(dist_root: Path) -> list[dict[str, Any]]:
    if not dist_root.is_dir():
        return []
    entries = sorted(
        item for item in dist_root.rglob("*") if item.is_file()
    )
    return [
        {
            "type": "web_bundle",
            "path": str(dist_root),
            "state": "ready",
            "file_count": len(entries),
            "bytes": sum(item.stat().st_size for item in entries),
        }
    ]


class ThreeBuildClient:
    def __init__(self, config: ThreeClientConfig) -> None:
        self._config = config
        self._toolchain = NodeToolchain(config)

    def project(
        self,
        *,
        target: str = "build",
        configuration: str = "production",
        clean: bool = False,
        dry_run: bool = False,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Build the project's web bundle and return build evidence."""

        project_dir = self._config.project_dir
        project_file = self._config.project_file
        if project_dir is None or project_file is None:
            return ThreeOperationResult.failure(
                "build.project",
                "project_path is not configured",
            ).to_dict()
        if not project_file.is_file():
            return ThreeOperationResult.failure(
                "build.project",
                "project_path does not resolve to an existing "
                "package.json file",
            ).to_dict()
        manager = self._toolchain.package_manager
        if manager is None:
            return ThreeOperationResult.failure(
                "build.project",
                "Node package manager was not found: "
                f"{self._config.package_manager}",
            ).to_dict()
        if not (project_dir / "node_modules").is_dir():
            return ThreeOperationResult.failure(
                "build.project",
                "node_modules is missing; call "
                "project.install_dependencies() first",
            ).to_dict()

        resolved_target = str(target).strip() or "build"
        dist_root = self._config.dist_root
        extra_args =["--mode", str(configuration or "production")]
        payload: dict[str, Any] = {
            "script": resolved_target,
            "cwd": str(project_dir),
            "package_manager": self._config.package_manager,
            "configuration": configuration,
            "clean": clean,
            "dry_run": dry_run,
            "dist_root": str(dist_root or ""),
            "engine_version": self._config.engine_version,
            "node_version": self._toolchain.node_version(),
        }
        if dry_run:
            payload["command"] = [
                str(manager),
                "run",
                resolved_target,
                "--",
                *extra_args,
            ]
            return ThreeOperationResult.success(
                "build.project",
                payload=payload,
            ).to_dict()

        if clean and dist_root is not None and dist_root.is_dir():
            for item in sorted(
                dist_root.rglob("*"),
                key=lambda entry: len(entry.parts),
                reverse=True,
            ):
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    item.rmdir()

        try:
            result = self._toolchain.run_script(
                resolved_target,
                cwd=project_dir,
                extra_args=extra_args,
                timeout=timeout,
            )
        except Exception as exc:
            return ThreeOperationResult.failure(
                "build.project",
                f"{type(exc).__name__}: {exc}",
                payload=payload,
            ).to_dict()

        diagnostics = _diagnostics(result.output)
        payload.update(result.to_dict())
        if result.timed_out:
            return ThreeOperationResult.failure(
                "build.project",
                "Web bundle build timed out",
                diagnostics=diagnostics,
                payload=payload,
            ).to_dict()
        if not result.ok:
            return ThreeOperationResult.failure(
                "build.project",
                "Web bundle build failed with exit code "
                f"{result.returncode}",
                diagnostics=diagnostics,
                payload=payload,
            ).to_dict()
        return ThreeOperationResult.success(
            "build.project",
            diagnostics=diagnostics,
            artifacts=(
                _bundle_artifacts(dist_root)
                if dist_root is not None
                else []
            ),
            payload=payload,
        ).to_dict()
