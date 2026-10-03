"""Stable generated-plugin installation operations for UnityClient v1."""

import json
import shutil
from pathlib import Path
from typing import Any, Mapping

from ..assets._internal.source_resolver import (
    GeneratedAssetSourceResolver,
)
from ..config import UnityClientConfig
from ..contracts import UnityOperationResult
from pipeline.common.artifacts import is_relative_to


FRAMEWORK_PLUGIN_NAME = "A3GameRuntime"
FRAMEWORK_PLUGIN_ROOT = (
    Path(__file__).resolve().parents[1]
    / "plugin"
    / FRAMEWORK_PLUGIN_NAME
)


def _assembly_root(path: Path) -> tuple[Path, Path]:
    if path.is_file() and path.suffix.lower() == ".asmdef":
        return path.parent, path
    if not path.is_dir():
        raise ValueError(
            "Generated plugin artifact must be a directory or "
            ".asmdef file"
        )
    descriptors = sorted(path.glob("*.asmdef"))
    if not descriptors:
        descriptors = sorted(path.rglob("*.asmdef"))
    if not descriptors:
        raise ValueError(
            "Generated plugin directory must contain at least one "
            ".asmdef file"
        )
    return descriptors[0].parent, descriptors[0]


def _sync_tree(source: Path, target: Path) -> int:
    copied = 0
    for source_file in sorted(
        item for item in source.rglob("*") if item.is_file()
    ):
        relative = source_file.relative_to(source)
        target_file = target / relative
        target_file.parent.mkdir(parents=True, exist_ok=True)
        if (
            target_file.is_file()
            and target_file.read_bytes()
            == source_file.read_bytes()
        ):
            continue
        shutil.copy2(source_file, target_file)
        copied += 1
    return copied


def _parse_asmdef_dependencies(path: Path) -> set[str]:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8")
        )
    except (json.JSONDecodeError, OSError):
        return set()
    if not isinstance(payload, dict):
        return set()
    return {
        str(name)
        for name in payload.get("references") or []
        if isinstance(name, str) and name
    }


class UnityPluginClient:
    def __init__(self, config: UnityClientConfig) -> None:
        self._config = config
        self._sources = GeneratedAssetSourceResolver()

    def install(
        self,
        source: Mapping[str, Any],
        *,
        replace_existing: bool = False,
        include_tests: bool = True,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        project_path = self._config.project_path
        if project_path is None or not project_path.is_dir():
            return UnityOperationResult.failure(
                "plugin.install",
                "project_path is not configured or does not exist",
            ).to_dict()
        try:
            source_descriptor = dict(source)
            task_kind = str(
                source_descriptor.get("task_kind") or ""
            ).strip()
            default_subpaths = {
                "mechanic": "generated_plugin",
                "ui": "generated_ui",
            }
            if task_kind in default_subpaths:
                if not str(
                    source_descriptor.get("artifact_key") or ""
                ).strip():
                    source_descriptor["artifact_key"] = "workspace"
                if not str(
                    source_descriptor.get("assembly_path") or ""
                ).strip():
                    source_descriptor["assembly_path"] = (
                        default_subpaths[task_kind]
                    )
            resolved = self._sources.resolve(
                source_descriptor,
                allow_directory=True,
            )
            assembly_path = str(
                source_descriptor.get("assembly_path") or ""
            ).strip()
            assembly_source = resolved.path
            if assembly_path:
                candidate = (
                    resolved.path / assembly_path
                    if resolved.path.is_dir()
                    else resolved.path.parent / assembly_path
                ).resolve(strict=False)
                artifact_root = (
                    resolved.path
                    if resolved.path.is_dir()
                    else resolved.path.parent
                ).resolve(strict=False)
                if not is_relative_to(candidate, artifact_root):
                    raise ValueError(
                        "assembly_path must stay inside the finalized artifact"
                    )
                assembly_source = candidate
            source_root, descriptor = _assembly_root(
                assembly_source
            )
            plugin_name = descriptor.stem
            test_source = (
                resolved.task_dir / "generated_test_source"
                if task_kind == "mechanic" and include_tests
                else None
            )
            if test_source is not None and not test_source.is_dir():
                test_source = None
        except Exception as exc:
            return UnityOperationResult.failure(
                "plugin.install",
                f"{type(exc).__name__}: {exc}",
                payload={"source": self._descriptor(source)},
            ).to_dict()

        dependencies = _parse_asmdef_dependencies(descriptor)
        requires_framework = (
            FRAMEWORK_PLUGIN_NAME in dependencies
        )
        target = (
            project_path
            / "Assets"
            / plugin_name
        )
        if target.exists() and not replace_existing:
            return UnityOperationResult.failure(
                "plugin.install",
                f"Plugin target already exists: {target}",
                payload={
                    "source": resolved.descriptor(),
                    "plugin_name": plugin_name,
                    "target": str(target),
                },
            ).to_dict()
        payload = {
            "source": resolved.descriptor(),
            "plugin_name": plugin_name,
            "descriptor": str(descriptor),
            "target": str(target),
            "replace_existing": replace_existing,
            "dry_run": dry_run,
            "requires_framework": requires_framework,
            "assembly_path": assembly_path,
            "include_tests": include_tests,
            "test_source": str(test_source or ""),
        }
        if dry_run:
            artifacts = [
                {
                    "type": "unity_plugin",
                    "path": str(target),
                    "state": "planned",
                }
            ]
            if requires_framework:
                artifacts.insert(
                    0,
                    {
                        "type": "unity_plugin",
                        "path": str(
                            project_path
                            / "Assets"
                            / FRAMEWORK_PLUGIN_NAME
                        ),
                        "state": "planned",
                    },
                )
            return UnityOperationResult.success(
                "plugin.install",
                artifacts=artifacts,
                payload=payload,
            ).to_dict()

        try:
            framework_result = None
            if requires_framework:
                framework_result = self.install_framework()
                if not framework_result.get("ok"):
                    return UnityOperationResult.failure(
                        "plugin.install",
                        *framework_result.get("errors"),
                        payload={
                            **payload,
                            "framework": framework_result,
                        },
                    ).to_dict()
            if target.exists() and replace_existing:
                shutil.rmtree(target)
            copied = _sync_tree(source_root, target)
            copied_tests = 0
            if test_source is not None:
                copied_tests = _sync_tree(
                    test_source,
                    target / "Tests",
                )
        except Exception as exc:
            return UnityOperationResult.failure(
                "plugin.install",
                f"{type(exc).__name__}: {exc}",
                payload=payload,
            ).to_dict()
        payload["copied_files"] = copied
        payload["copied_test_files"] = copied_tests
        if framework_result is not None:
            payload["framework"] = framework_result
        artifacts = [
            {
                "type": "unity_plugin",
                "path": str(target),
                "state": "ready",
            }
        ]
        if framework_result is not None:
            artifacts = [
                *framework_result.get("artifacts", []),
                *artifacts,
            ]
        return UnityOperationResult.success(
            "plugin.install",
            artifacts=artifacts,
            payload=payload,
        ).to_dict()

    def install_framework(
        self,
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        project_path = self._config.project_path
        if project_path is None or not project_path.is_dir():
            return UnityOperationResult.failure(
                "plugin.install_framework",
                "project_path is not configured or does not exist",
            ).to_dict()
        framework_root = FRAMEWORK_PLUGIN_ROOT
        if not framework_root.is_dir():
            return UnityOperationResult.failure(
                "plugin.install_framework",
                f"A3GameRuntime framework source was not found: {framework_root}",
            ).to_dict()
        target = (
            project_path
            / "Assets"
            / FRAMEWORK_PLUGIN_NAME
        )
        payload = {
            "source": str(framework_root),
            "target": str(target),
            "dry_run": dry_run,
        }
        if dry_run:
            return UnityOperationResult.success(
                "plugin.install_framework",
                artifacts=[
                    {
                        "type": "unity_plugin",
                        "path": str(target),
                        "state": "planned",
                    }
                ],
                payload=payload,
            ).to_dict()
        try:
            copied = _sync_tree(
                framework_root,
                target,
            )
        except Exception as exc:
            return UnityOperationResult.failure(
                "plugin.install_framework",
                f"{type(exc).__name__}: {exc}",
                payload=payload,
            ).to_dict()
        payload["copied_files"] = copied
        return UnityOperationResult.success(
            "plugin.install_framework",
            artifacts=[
                {
                    "type": "unity_plugin",
                    "path": str(target),
                    "state": "ready",
                }
            ],
            payload=payload,
        ).to_dict()

    def list(self) -> dict[str, Any]:
        project_path = self._config.project_path
        if project_path is None or not project_path.is_dir():
            return UnityOperationResult.failure(
                "plugin.list",
                "project_path is not configured or does not exist",
            ).to_dict()
        assets_root = project_path / "Assets"
        plugins = []
        if assets_root.is_dir():
            for descriptor in sorted(
                assets_root.rglob("*.asmdef")
            ):
                if FRAMEWORK_PLUGIN_ROOT in descriptor.parents:
                    continue
                plugins.append(
                    {
                        "name": descriptor.stem,
                        "path": str(descriptor.parent),
                        "descriptor": str(descriptor),
                    }
                )
        return UnityOperationResult.success(
            "plugin.list",
            artifacts=[
                {
                    "artifact_id": item["name"],
                    "type": "unity_plugin",
                    "backend": "unity",
                    "backend_path": item["path"],
                    "metadata": item,
                }
                for item in plugins
            ],
            payload={"count": len(plugins)},
        ).to_dict()

    @staticmethod
    def _descriptor(source: Any) -> dict[str, Any]:
        return (
            dict(source)
            if isinstance(source, Mapping)
            else {"value": str(source)}
        )
