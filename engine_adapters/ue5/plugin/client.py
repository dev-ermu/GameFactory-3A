"""Stable generated-plugin installation operations for UEClient v1."""

import json
import shutil
from pathlib import Path
from typing import Any, Mapping

from ..assets._internal.source_resolver import (
    GeneratedAssetSourceResolver,
)
from ..config import UEClientConfig
from ..contracts import UEOperationResult


FRAMEWORK_PLUGIN_NAME = "A3GamePlayable"
FRAMEWORK_PLUGIN_ROOT = (
    Path(__file__).resolve().parent
    / FRAMEWORK_PLUGIN_NAME
)


def _plugin_root(path: Path) -> tuple[Path, Path]:
    if path.is_file() and path.suffix.lower() == ".uplugin":
        return path.parent, path
    if not path.is_dir():
        raise ValueError(
            "Generated plugin artifact must be a directory or "
            ".uplugin file"
        )
    descriptors = sorted(path.glob("*.uplugin"))
    if len(descriptors) != 1:
        raise ValueError(
            "Generated plugin directory must contain exactly one "
            "top-level .uplugin file"
        )
    return path, descriptors[0]


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


def _enable_plugin(
    project_file: Path,
    plugin_name: str,
) -> None:
    try:
        payload = json.loads(
            project_file.read_text(encoding="utf-8")
        )
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Unreal project file is invalid JSON: {project_file}"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError(
            f"Unreal project file must be an object: {project_file}"
        )
    plugins = payload.get("Plugins")
    if not isinstance(plugins, list):
        plugins = []
    updated = []
    found = False
    for item in plugins:
        if not isinstance(item, dict):
            continue
        entry = dict(item)
        if str(entry.get("Name") or "") == plugin_name:
            entry["Enabled"] = True
            found = True
        updated.append(entry)
    if not found:
        updated.append(
            {"Name": plugin_name, "Enabled": True}
        )
    payload["Plugins"] = updated
    project_file.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


class UEPluginClient:
    def __init__(self, config: UEClientConfig) -> None:
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
            return UEOperationResult.failure(
                "plugin.install",
                "project_path does not resolve to an existing "
                ".uproject file",
            ).to_dict()
        try:
            resolved = self._sources.resolve(
                source,
                allow_directory=True,
            )
            source_root, descriptor = _plugin_root(
                resolved.path
            )
            plugin_payload = json.loads(
                descriptor.read_text(encoding="utf-8")
            )
            if not isinstance(plugin_payload, dict):
                raise ValueError(
                    ".uplugin descriptor must be a JSON object"
                )
        except Exception as exc:
            return UEOperationResult.failure(
                "plugin.install",
                f"{type(exc).__name__}: {exc}",
                payload={"source": self._descriptor(source)},
            ).to_dict()

        plugin_name = descriptor.stem
        required_plugins = {
            str(item.get("Name") or "")
            for item in plugin_payload.get("Plugins") or []
            if isinstance(item, dict)
        }
        requires_framework = (
            FRAMEWORK_PLUGIN_NAME in required_plugins
        )
        target = (
            project_file.parent
            / "Plugins"
            / plugin_name
        )
        if target.exists() and not replace_existing:
            return UEOperationResult.failure(
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
        }
        if dry_run:
            artifacts = [
                {
                    "type": "unreal_plugin",
                    "path": str(target),
                    "state": "planned",
                }
            ]
            if requires_framework:
                artifacts.insert(
                    0,
                    {
                        "type": "unreal_plugin",
                        "path": str(
                            project_file.parent
                            / "Plugins"
                            / FRAMEWORK_PLUGIN_NAME
                        ),
                        "state": "planned",
                    },
                )
            return UEOperationResult.success(
                "plugin.install",
                artifacts=artifacts,
                payload=payload,
            ).to_dict()

        try:
            framework_result = None
            if requires_framework:
                framework_result = self.install_framework()
                if not framework_result.get("ok"):
                    return UEOperationResult.failure(
                        "plugin.install",
                        *framework_result.get("errors"),
                        payload={
                            **payload,
                            "framework": framework_result,
                        },
                    ).to_dict()
            copied = _sync_tree(source_root, target)
            _enable_plugin(project_file, plugin_name)
        except Exception as exc:
            return UEOperationResult.failure(
                "plugin.install",
                f"{type(exc).__name__}: {exc}",
                payload=payload,
            ).to_dict()
        payload["copied_files"] = copied
        if framework_result is not None:
            payload["framework"] = framework_result
        artifacts = [
            {
                "type": "unreal_plugin",
                "path": str(target),
                "state": "ready",
            }
        ]
        if framework_result is not None:
            artifacts = [
                *framework_result.get("artifacts", []),
                *artifacts,
            ]
        return UEOperationResult.success(
            "plugin.install",
            artifacts=artifacts,
            payload=payload,
        ).to_dict()

    def install_framework(
        self,
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        project_file = self._config.project_file
        if project_file is None or not project_file.is_file():
            return UEOperationResult.failure(
                "plugin.install_framework",
                "project_path does not resolve to an existing "
                ".uproject file",
            ).to_dict()
        descriptor = (
            FRAMEWORK_PLUGIN_ROOT
            / f"{FRAMEWORK_PLUGIN_NAME}.uplugin"
        )
        if not descriptor.is_file():
            return UEOperationResult.failure(
                "plugin.install_framework",
                "A3GamePlayable framework source was not found: "
                f"{descriptor}",
            ).to_dict()
        target = (
            project_file.parent
            / "Plugins"
            / FRAMEWORK_PLUGIN_NAME
        )
        payload = {
            "source": str(FRAMEWORK_PLUGIN_ROOT),
            "target": str(target),
            "dry_run": dry_run,
        }
        if dry_run:
            return UEOperationResult.success(
                "plugin.install_framework",
                artifacts=[
                    {
                        "type": "unreal_plugin",
                        "path": str(target),
                        "state": "planned",
                    }
                ],
                payload=payload,
            ).to_dict()
        try:
            copied = _sync_tree(
                FRAMEWORK_PLUGIN_ROOT,
                target,
            )
            _enable_plugin(
                project_file,
                FRAMEWORK_PLUGIN_NAME,
            )
        except Exception as exc:
            return UEOperationResult.failure(
                "plugin.install_framework",
                f"{type(exc).__name__}: {exc}",
                payload=payload,
            ).to_dict()
        payload["copied_files"] = copied
        return UEOperationResult.success(
            "plugin.install_framework",
            artifacts=[
                {
                    "type": "unreal_plugin",
                    "path": str(target),
                    "state": "ready",
                }
            ],
            payload=payload,
        ).to_dict()

    def list(self) -> dict[str, Any]:
        project_file = self._config.project_file
        if project_file is None:
            return UEOperationResult.failure(
                "plugin.list",
                "project_path is not configured",
            ).to_dict()
        plugins_root = project_file.parent / "Plugins"
        plugins = []
        if plugins_root.is_dir():
            for descriptor in sorted(
                plugins_root.glob("*/*.uplugin")
            ):
                plugins.append(
                    {
                        "name": descriptor.stem,
                        "path": str(descriptor.parent),
                        "descriptor": str(descriptor),
                    }
                )
        return UEOperationResult.success(
            "plugin.list",
            artifacts=[
                {
                    "artifact_id": item["name"],
                    "type": "unreal_plugin",
                    "backend": "ue",
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
