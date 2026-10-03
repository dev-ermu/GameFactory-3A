"""Stable generated-package installation operations for ThreeClient v1."""

import json
import shutil
from pathlib import Path
from typing import Any, Mapping

from ..assets._internal.source_resolver import (
    GeneratedAssetSourceResolver,
)
from ..config import ThreeClientConfig
from ..contracts import ThreeOperationResult


FRAMEWORK_PACKAGE_DIR = "A3GamePlayable"
FRAMEWORK_PACKAGE_NAME = "@a3game/playable"
FRAMEWORK_INSTALL_DIR = "a3game-playable"
FRAMEWORK_PACKAGE_ROOT = (
    Path(__file__).resolve().parent / FRAMEWORK_PACKAGE_DIR
)
PACKAGES_ROOT = "packages"


def _package_root(path: Path) -> tuple[Path, Path]:
    if path.is_file() and path.name == "package.json":
        return path.parent, path
    if not path.is_dir():
        raise ValueError(
            "Generated package artifact must be a directory or a "
            "package.json file"
        )
    descriptor = path / "package.json"
    if not descriptor.is_file():
        raise ValueError(
            "Generated package directory must contain a top-level "
            "package.json file"
        )
    return path, descriptor


def _sync_tree(source: Path, target: Path) -> int:
    copied = 0
    for source_file in sorted(
        item
        for item in source.rglob("*")
        if item.is_file() and "node_modules" not in item.parts
    ):
        relative = source_file.relative_to(source)
        target_file = target / relative
        target_file.parent.mkdir(parents=True, exist_ok=True)
        if (
            target_file.is_file()
            and target_file.read_bytes() == source_file.read_bytes()
        ):
            continue
        shutil.copy2(source_file, target_file)
        copied += 1
    return copied


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"package.json is invalid JSON: {path}"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError(
            f"package.json must be an object: {path}"
        )
    return payload


def _enable_package(
    project_file: Path,
    package_name: str,
    install_dir: str,
) -> None:
    """Register a local package as a project dependency."""

    payload = _read_json(project_file)
    dependencies = payload.get("dependencies")
    if not isinstance(dependencies, dict):
        dependencies = {}
    dependencies[package_name] = f"file:./{PACKAGES_ROOT}/{install_dir}"
    payload["dependencies"] = dict(sorted(dependencies.items()))
    workspaces = payload.get("workspaces")
    entry = f"{PACKAGES_ROOT}/*"
    if isinstance(workspaces, list):
        if entry not in workspaces:
            workspaces.append(entry)
        payload["workspaces"] = workspaces
    else:
        payload["workspaces"] = [entry]
    project_file.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


class ThreePluginClient:
    """Install generated Gameplay Packages and the runtime framework."""

    def __init__(self, config: ThreeClientConfig) -> None:
        self._config = config
        self._sources = GeneratedAssetSourceResolver()

    def install(
        self,
        source: Mapping[str, Any],
        *,
        replace_existing: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        project_file = self._config.project_file
        if project_file is None or not project_file.is_file():
            return ThreeOperationResult.failure(
                "plugin.install",
                "project_path does not resolve to an existing "
                "package.json file",
            ).to_dict()
        try:
            resolved = self._sources.resolve(
                source,
                allow_directory=True,
            )
            source_root, descriptor = _package_root(resolved.path)
            package_payload = _read_json(descriptor)
        except Exception as exc:
            return ThreeOperationResult.failure(
                "plugin.install",
                f"{type(exc).__name__}: {exc}",
                payload={"source": self._descriptor(source)},
            ).to_dict()

        package_name = str(package_payload.get("name") or "").strip()
        if not package_name:
            return ThreeOperationResult.failure(
                "plugin.install",
                "Generated package.json must declare a name",
                payload={"source": resolved.descriptor()},
            ).to_dict()
        install_dir = package_name.split("/")[-1]
        declared = {
            **dict(package_payload.get("dependencies") or {}),
            **dict(package_payload.get("peerDependencies") or {}),
        }
        requires_framework = FRAMEWORK_PACKAGE_NAME in declared

        target = (
            project_file.parent / PACKAGES_ROOT / install_dir
        )
        if target.exists() and not replace_existing:
            return ThreeOperationResult.failure(
                "plugin.install",
                f"Package target already exists: {target}",
                payload={
                    "source": resolved.descriptor(),
                    "package_name": package_name,
                    "target": str(target),
                },
            ).to_dict()

        payload = {
            "source": resolved.descriptor(),
            "package_name": package_name,
            "install_dir": install_dir,
            "descriptor": str(descriptor),
            "target": str(target),
            "replace_existing": replace_existing,
            "dry_run": dry_run,
            "requires_framework": requires_framework,
        }
        if dry_run:
            artifacts = [
                {
                    "type": "three_gameplay_package",
                    "path": str(target),
                    "state": "planned",
                }
            ]
            if requires_framework:
                artifacts.insert(
                    0,
                    {
                        "type": "three_runtime_framework",
                        "path": str(
                            project_file.parent
                            / PACKAGES_ROOT
                            / FRAMEWORK_INSTALL_DIR
                        ),
                        "state": "planned",
                    },
                )
            return ThreeOperationResult.success(
                "plugin.install",
                artifacts=artifacts,
                payload=payload,
            ).to_dict()

        try:
            framework_result = None
            if requires_framework:
                framework_result = self.install_framework()
                if not framework_result.get("ok"):
                    return ThreeOperationResult.failure(
                        "plugin.install",
                        *framework_result.get("errors") or (),
                        payload={
                            **payload,
                            "framework": framework_result,
                        },
                    ).to_dict()
            copied = _sync_tree(source_root, target)
            _enable_package(project_file, package_name, install_dir)
        except Exception as exc:
            return ThreeOperationResult.failure(
                "plugin.install",
                f"{type(exc).__name__}: {exc}",
                payload=payload,
            ).to_dict()

        payload["copied_files"] = copied
        if framework_result is not None:
            payload["framework"] = framework_result
        artifacts = [
            {
                "type": "three_gameplay_package",
                "path": str(target),
                "state": "ready",
            }
        ]
        if framework_result is not None:
            artifacts = [
                *framework_result.get("artifacts", []),
                *artifacts,
            ]
        return ThreeOperationResult.success(
            "plugin.install",
            artifacts=artifacts,
            warnings=[
                "Run project.install_dependencies() so the package "
                "manager links the newly installed local package"
            ],
            payload=payload,
        ).to_dict()

    def install_framework(
        self,
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        project_file = self._config.project_file
        if project_file is None or not project_file.is_file():
            return ThreeOperationResult.failure(
                "plugin.install_framework",
                "project_path does not resolve to an existing "
                "package.json file",
            ).to_dict()
        descriptor = FRAMEWORK_PACKAGE_ROOT / "package.json"
        if not descriptor.is_file():
            return ThreeOperationResult.failure(
                "plugin.install_framework",
                "A3GamePlayable framework source was not found: "
                f"{descriptor}",
            ).to_dict()
        target = (
            project_file.parent
            / PACKAGES_ROOT
            / FRAMEWORK_INSTALL_DIR
        )
        payload = {
            "source": str(FRAMEWORK_PACKAGE_ROOT),
            "package_name": FRAMEWORK_PACKAGE_NAME,
            "target": str(target),
            "dry_run": dry_run,
        }
        if dry_run:
            return ThreeOperationResult.success(
                "plugin.install_framework",
                artifacts=[
                    {
                        "type": "three_runtime_framework",
                        "path": str(target),
                        "state": "planned",
                    }
                ],
                payload=payload,
            ).to_dict()
        try:
            copied = _sync_tree(FRAMEWORK_PACKAGE_ROOT, target)
            _enable_package(
                project_file,
                FRAMEWORK_PACKAGE_NAME,
                FRAMEWORK_INSTALL_DIR,
            )
        except Exception as exc:
            return ThreeOperationResult.failure(
                "plugin.install_framework",
                f"{type(exc).__name__}: {exc}",
                payload=payload,
            ).to_dict()
        payload["copied_files"] = copied
        return ThreeOperationResult.success(
            "plugin.install_framework",
            artifacts=[
                {
                    "type": "three_runtime_framework",
                    "path": str(target),
                    "state": "ready",
                }
            ],
            payload=payload,
        ).to_dict()

    def list(self) -> dict[str, Any]:
        project_file = self._config.project_file
        if project_file is None:
            return ThreeOperationResult.failure(
                "plugin.list",
                "project_path is not configured",
            ).to_dict()
        packages_root = project_file.parent / PACKAGES_ROOT
        packages = []
        if packages_root.is_dir():
            for descriptor in sorted(
                packages_root.glob("*/package.json")
            ):
                try:
                    payload = _read_json(descriptor)
                except ValueError:
                    continue
                packages.append(
                    {
                        "name": str(payload.get("name") or ""),
                        "version": str(payload.get("version") or ""),
                        "install_dir": descriptor.parent.name,
                        "path": str(descriptor.parent),
                        "descriptor": str(descriptor),
                        "is_framework": (
                            str(payload.get("name") or "")
                            == FRAMEWORK_PACKAGE_NAME
                        ),
                    }
                )
        return ThreeOperationResult.success(
            "plugin.list",
            artifacts=[
                {
                    "artifact_id": item["name"] or item["install_dir"],
                    "type": (
                        "three_runtime_framework"
                        if item["is_framework"]
                        else "three_gameplay_package"
                    ),
                    "backend": "web",
                    "backend_path": item["path"],
                    "metadata": item,
                }
                for item in packages
            ],
            payload={"count": len(packages)},
        ).to_dict()

    @staticmethod
    def _descriptor(source: Any) -> dict[str, Any]:
        return (
            dict(source)
            if isinstance(source, Mapping)
            else {"value": str(source)}
        )
