"""Stable project inspection operations for UnityClient v1."""

import json
import os
import re
from pathlib import Path
from typing import Any

from ..config import UnityClientConfig
from ..contracts import UnityOperationResult


def _validate_project_name(project_name: str) -> None:
    if not re.fullmatch(
        r"[A-Za-z][A-Za-z0-9_]*",
        project_name,
    ):
        raise ValueError(
            "Unity project name must start with a letter "
            "and contain only letters, digits, and underscores: "
            f"{project_name!r}"
        )


_CONTENT_ROOTS = (
    "Avatars",
    "Motions",
    "Scenes",
    "Environments",
    "Props",
    "Weapons",
    "Materials",
    "Textures",
    "Effects",
    "Audio",
    "Prefabs",
)

_PACKAGES_MANIFEST = {
    "dependencies": {
        "com.unity.test-framework": "1.1.33",
        "com.unity.ugui": "1.0.0",
        "com.unity.cloud.gltfast": "6.16.0",
        "com.unity.render-pipelines.universal": "14.0.11",
        "com.unity.modules.animation": "1.0.0",
        "com.unity.modules.audio": "1.0.0",
        "com.unity.modules.jsonserialize": "1.0.0",
        "com.unity.modules.physics": "1.0.0",
        "com.unity.modules.terrain": "1.0.0",
        "com.unity.modules.terrainphysics": "1.0.0",
    },
}

_DEFAULT_EDITOR_VERSION = "2022.3.62f3c1"


_A3GAME_BOOTSTRAP_CS = """\
using UnityEngine;
using A3GameRuntime;

namespace A3Game
{
    /// <summary>
    /// Bootstraps the A3Game runtime: initialises the runtime subsystem,
    /// entity factory, session, input receiver, and generated gameplay.
    /// </summary>
    public class A3GameBootstrap : MonoBehaviour
    {
        [SerializeField] private string worldId = "world_001";

        private void Awake()
        {
            var runtime = A3GameRuntimeSubsystem.Instance
                ?? FindObjectOfType<A3GameRuntimeSubsystem>();
            if (runtime == null)
            {
                var runtimeObject = new GameObject("A3GameRuntimeSubsystem");
                runtime = runtimeObject.AddComponent<A3GameRuntimeSubsystem>();
            }
            runtime.Initialize(worldId);
            var session = A3GameWorldSessionSubsystem.Instance;
            if (session != null)
            {
                session.Initialize(worldId);
            }
            var inputReceiver = FindObjectOfType<A3GameRuntimeInputReceiver>();
            if (inputReceiver == null)
            {
                var receiverObj = new GameObject("A3GameRuntimeInputReceiver");
                receiverObj.AddComponent<A3GameRuntimeInputReceiver>();
            }
            Debug.Log($"[A3GameBootstrap] Runtime initialised for world '{worldId}'");
        }
    }
}
"""


def _write_project_files(
    project_dir: Path,
    project_name: str,
    api_version: str,
    unity_root: Path | None,
    editor_version: str,
) -> None:
    _validate_project_name(project_name)
    project_dir.mkdir(parents=True, exist_ok=True)

    for name in _CONTENT_ROOTS:
        (project_dir / "Assets" / "Imported" / name).mkdir(
            parents=True, exist_ok=True
        )
    (project_dir / "Assets" / "Generated" / "Meshes").mkdir(
        parents=True, exist_ok=True
    )
    (project_dir / "Assets" / "Generated" / "Prefabs").mkdir(
        parents=True, exist_ok=True
    )
    (project_dir / "Assets" / "Editor").mkdir(
        parents=True, exist_ok=True
    )
    (project_dir / "Assets" / "Scenes").mkdir(
        parents=True, exist_ok=True
    )
    (project_dir / "Assets" / "A3Game").mkdir(
        parents=True, exist_ok=True
    )

    settings_dir = project_dir / "ProjectSettings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "ProjectVersion.txt").write_text(
        f"m_EditorVersion: {editor_version or _DEFAULT_EDITOR_VERSION}\n",
        encoding="utf-8",
    )
    (settings_dir / "ProjectSettings.asset").write_text(
        "%YAML 1.1\n%TAG !u! tag:unity3d.com,2011:\n",
        encoding="utf-8",
    )

    packages_dir = project_dir / "Packages"
    packages_dir.mkdir(parents=True, exist_ok=True)
    (packages_dir / "manifest.json").write_text(
        json.dumps(_PACKAGES_MANIFEST, indent=2) + "\n",
        encoding="utf-8",
    )

    asmdef = {
        "name": f"{project_name}.A3Game",
        "rootNamespace": "A3Game",
        "references": ["A3GameRuntime"],
        "includePlatforms": [],
        "excludePlatforms": [],
        "allowUnsafeCode": False,
        "autoReferenced": True,
        "defineConstraints": [],
    }
    (project_dir / "Assets" / "A3Game" / f"{project_name}.A3Game.asmdef").write_text(
        json.dumps(asmdef, indent=2) + "\n",
        encoding="utf-8",
    )

    bootstrap_dir = project_dir / "Assets" / "A3Game"
    (bootstrap_dir / "A3GameBootstrap.cs").write_text(
        _A3GAME_BOOTSTRAP_CS,
        encoding="utf-8",
    )

    (project_dir / ".a3game-unity.json").write_text(
        json.dumps(
            {
                "engine": "unity3d",
                "api_version": api_version,
                "engine_root": str(unity_root or ""),
                "project_path": str(project_dir),
                "project_name": project_name,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


class UnityProjectClient:
    def __init__(self, config: UnityClientConfig) -> None:
        self._config = config

    def get_info(self) -> dict[str, Any]:
        project_path = self._config.project_path
        unity_root = self._config.unity_root
        return UnityOperationResult.success(
            "project.get_info",
            payload={
                "api_version": self._config.api_version,
                "engine_version": self._config.engine_version,
                "unity_root": str(unity_root) if unity_root else "",
                "unity_root_exists": bool(
                    unity_root and unity_root.exists()
                ),
                "project_path": str(
                    project_path or ""
                ),
                "project_exists": bool(
                    project_path and project_path.is_dir()
                ),
            },
        ).to_dict()

    def create(
        self,
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        project_path = self._config.project_path
        if project_path is None:
            return UnityOperationResult.failure(
                "project.create",
                "project_path is not configured",
            ).to_dict()

        project_name = project_path.name
        try:
            _validate_project_name(project_name)
        except ValueError as exc:
            return UnityOperationResult.failure(
                "project.create",
                str(exc),
            ).to_dict()
        if project_path.exists() and any(project_path.iterdir()):
            return UnityOperationResult.failure(
                "project.create",
                f"Project directory already exists and is not empty: {project_path}",
            ).to_dict()

        payload = {
            "api_version": self._config.api_version,
            "dry_run": dry_run,
            "unity_root": str(self._config.unity_root or ""),
            "project_dir": str(project_path),
            "project_name": project_name,
            "content_roots": list(_CONTENT_ROOTS),
            "packages": _PACKAGES_MANIFEST,
        }
        if dry_run:
            return UnityOperationResult.success(
                "project.create",
                artifacts=[
                    {
                        "type": "unity_project",
                        "path": str(project_path),
                        "state": "planned",
                    },
                    {
                        "type": "unity_plugin",
                        "path": str(
                            project_path
                            / "Assets"
                            / "A3GameRuntime"
                        ),
                        "state": "planned",
                    },
                ],
                payload=payload,
            ).to_dict()

        try:
            _write_project_files(
                project_path,
                project_name,
                self._config.api_version,
                self._config.unity_root,
                self._config.engine_version,
            )
            # A generated host references A3GameRuntime immediately, so the
            # framework is part of project creation rather than an optional
            # follow-up step.
            from ..plugin import UnityPluginClient

            framework = UnityPluginClient(
                self._config
            ).install_framework()
            if not framework.get("ok"):
                return UnityOperationResult.failure(
                    "project.create",
                    *framework.get("errors", []),
                    payload={
                        **payload,
                        "framework": framework,
                    },
                ).to_dict()
        except Exception as exc:
            return UnityOperationResult.failure(
                "project.create",
                f"{type(exc).__name__}: {exc}",
                payload=payload,
            ).to_dict()

        payload["framework"] = framework
        return UnityOperationResult.success(
            "project.create",
            artifacts=[
                {
                    "type": "unity_project",
                    "path": str(project_path),
                    "state": "ready",
                },
                *framework.get("artifacts", []),
            ],
            payload=payload,
        ).to_dict()

    def validate(self) -> dict[str, Any]:
        errors: list[str] = []
        project_path = self._config.project_path
        if project_path is None:
            errors.append("project_path is not configured")
        elif not project_path.is_dir():
            errors.append(f"project_path does not exist: {project_path}")
        else:
            settings = project_path / "ProjectSettings"
            if not settings.is_dir():
                errors.append("ProjectSettings directory is missing")
            else:
                version_file = settings / "ProjectVersion.txt"
                if not version_file.is_file():
                    errors.append("ProjectSettings/ProjectVersion.txt is missing")
            packages = project_path / "Packages" / "manifest.json"
            if not packages.is_file():
                errors.append("Packages/manifest.json is missing")
            assets = project_path / "Assets"
            if not assets.is_dir():
                errors.append("Assets directory is missing")
            framework = (
                assets
                / "A3GameRuntime"
                / "Runtime"
                / "A3GameRuntime.asmdef"
            )
            if not framework.is_file():
                errors.append(
                    "A3GameRuntime framework assembly is missing"
                )

        if errors:
            return UnityOperationResult.failure(
                "project.validate",
                *errors,
                payload={
                    "api_version": self._config.api_version,
                },
            ).to_dict()
        return UnityOperationResult.success(
            "project.validate",
            payload={
                "api_version": self._config.api_version,
                "project_path": str(project_path),
            },
        ).to_dict()

    def synchronize_packages(self) -> dict[str, Any]:
        """Merge adapter-required packages into an existing project manifest."""
        project_path = self._config.project_path
        if project_path is None or not project_path.is_dir():
            return UnityOperationResult.failure(
                "project.synchronize_packages",
                "project_path is not configured or does not exist",
            ).to_dict()
        manifest_path = project_path / "Packages" / "manifest.json"
        if not manifest_path.is_file():
            return UnityOperationResult.failure(
                "project.synchronize_packages",
                f"Packages/manifest.json is missing: {manifest_path}",
            ).to_dict()
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict):
                raise ValueError("manifest root must be an object")
            dependencies = manifest.setdefault("dependencies", {})
            if not isinstance(dependencies, dict):
                raise ValueError("manifest dependencies must be an object")
            required = dict(_PACKAGES_MANIFEST["dependencies"])
            changed = {
                name: version
                for name, version in required.items()
                if dependencies.get(name) != version
            }
            dependencies.update(required)
            if changed:
                manifest_path.write_text(
                    json.dumps(manifest, indent=2) + "\n",
                    encoding="utf-8",
                )
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            return UnityOperationResult.failure(
                "project.synchronize_packages",
                f"{type(exc).__name__}: {exc}",
                payload={"manifest_path": str(manifest_path)},
            ).to_dict()
        return UnityOperationResult.success(
            "project.synchronize_packages",
            artifacts=[
                {
                    "type": "unity_package_manifest",
                    "path": str(manifest_path),
                    "state": "ready",
                }
            ],
            payload={
                "manifest_path": str(manifest_path),
                "required_packages": required,
                "updated_packages": changed,
                "changed": bool(changed),
            },
        ).to_dict()
