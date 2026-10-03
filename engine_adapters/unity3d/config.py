"""Configuration for the stable UnityClient API."""

import os
import re
from dataclasses import dataclass
from pathlib import Path


SUPPORTED_API_VERSIONS = ("v1",)
DEFAULT_API_VERSION = "v1"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 30010
DEFAULT_RUNTIME_HOST = "127.0.0.1"
DEFAULT_RUNTIME_PORT = 30030
DEFAULT_EDITOR_BATCHMODE_TIMEOUT = 1800
DEFAULT_IMPORT_ROOT = "Assets/Imported"
DEFAULT_AVATAR_DEST = "Assets/Imported/Avatars"
DEFAULT_MOTION_DEST = "Assets/Imported/Motions"
DEFAULT_SCENE_DEST = "Assets/Imported/Scenes"
DEFAULT_ENVIRONMENT_DEST = "Assets/Imported/Environments"
DEFAULT_EFFECT_DEST = "Assets/Imported/Effects"
DEFAULT_MATERIAL_DEST = "Assets/Imported/Materials"
DEFAULT_TEXTURE_DEST = "Assets/Imported/Textures"
DEFAULT_PROP_DEST = "Assets/Imported/Props"
DEFAULT_WEAPON_DEST = "Assets/Imported/Weapons"

UNITY_ASSET_TYPE_DEFAULT_DESTS = {
    "avatar": DEFAULT_AVATAR_DEST,
    "motion": DEFAULT_MOTION_DEST,
    "scene": DEFAULT_SCENE_DEST,
    "environment": DEFAULT_ENVIRONMENT_DEST,
    "effect": DEFAULT_EFFECT_DEST,
    "material": DEFAULT_MATERIAL_DEST,
    "texture": DEFAULT_TEXTURE_DEST,
    "prop": DEFAULT_PROP_DEST,
    "weapon": DEFAULT_WEAPON_DEST,
    "static_mesh": DEFAULT_PROP_DEST,
}


def _first_environment_value(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def _optional_path(value: str | Path | None) -> Path | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    path = Path(text).expanduser()
    if os.name == "nt" and path.is_absolute():
        return Path(os.path.abspath(str(path)))
    return path.resolve(strict=False)


@dataclass(frozen=True)
class UnityClientConfig:
    """Resolved configuration used by UnityClient and private implementations."""

    project_path: Path | None
    unity_root: Path | None
    api_version: str = DEFAULT_API_VERSION
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    runtime_host: str = DEFAULT_RUNTIME_HOST
    runtime_port: int = DEFAULT_RUNTIME_PORT
    editor_batchmode_timeout: int = DEFAULT_EDITOR_BATCHMODE_TIMEOUT

    @classmethod
    def resolve(
        cls,
        project_path: str | Path | None = None,
        unity_root: str | Path | None = None,
        api_version: str = DEFAULT_API_VERSION,
        *,
        host: str | None = None,
        port: int | None = None,
        runtime_host: str | None = None,
        runtime_port: int | None = None,
        editor_batchmode_timeout: int | None = None,
    ) -> "UnityClientConfig":
        version = str(api_version or "").strip()
        if version not in SUPPORTED_API_VERSIONS:
            supported = ", ".join(SUPPORTED_API_VERSIONS)
            raise ValueError(
                f"Unsupported UnityClient api_version {version!r}; "
                f"supported versions: {supported}"
            )

        resolved_root = _optional_path(
            unity_root
            or _first_environment_value(
                "A3GAME_UNITY_ROOT",
                "AAAGF_UNITY",
            )
        )
        resolved_project = _optional_path(
            project_path
            or _first_environment_value(
                "A3GAME_UNITY_PROJECT",
                "AAAGF_UNITY_PROJECT",
            )
        )
        resolved_host = (
            host
            or _first_environment_value(
                "A3GAME_UNITY_HOST",
            )
            or DEFAULT_HOST
        )
        resolved_port = port
        if resolved_port is None:
            configured_port = _first_environment_value(
                "A3GAME_UNITY_PORT",
            )
            resolved_port = (
                int(configured_port)
                if configured_port
                else DEFAULT_PORT
            )
        if not 1 <= int(resolved_port) <= 65535:
            raise ValueError(
                "Unity Remote Control port must be between 1 and 65535"
            )
        resolved_runtime_host = (
            runtime_host
            or _first_environment_value(
                "A3GAME_UNITY_RUNTIME_HOST",
            )
            or DEFAULT_RUNTIME_HOST
        )
        resolved_runtime_port = runtime_port
        if resolved_runtime_port is None:
            configured_runtime_port = _first_environment_value(
                "A3GAME_UNITY_RUNTIME_PORT",
            )
            resolved_runtime_port = (
                int(configured_runtime_port)
                if configured_runtime_port
                else DEFAULT_RUNTIME_PORT
            )
        if not 1 <= int(resolved_runtime_port) <= 65535:
            raise ValueError(
                "Unity runtime UDP port must be between 1 and 65535"
            )

        resolved_timeout = editor_batchmode_timeout
        if resolved_timeout is None:
            configured_timeout = _first_environment_value(
                "A3GAME_UNITY_EDITOR_TIMEOUT",
            )
            resolved_timeout = (
                int(configured_timeout)
                if configured_timeout
                else DEFAULT_EDITOR_BATCHMODE_TIMEOUT
            )
        if int(resolved_timeout) <= 0:
            raise ValueError(
                "editor_batchmode_timeout must be greater than zero"
            )

        return cls(
            project_path=resolved_project,
            unity_root=resolved_root,
            api_version=version,
            host=str(resolved_host),
            port=int(resolved_port),
            runtime_host=(
                str(resolved_runtime_host).strip()
                or DEFAULT_RUNTIME_HOST
            ),
            runtime_port=int(resolved_runtime_port),
            editor_batchmode_timeout=int(resolved_timeout),
        )

    @property
    def remote_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def project_file(self) -> Path | None:
        path = self.project_path
        if path is None:
            return None
        if path.is_file():
            return path
        if not path.is_dir():
            return None
        return path

    @property
    def engine_version(self) -> str:
        if self.unity_root is None:
            return ""
        pattern = re.compile(
            r"(\d+\.\d+(?:\.\d+)?[a-z]\d+(?:[a-z]\d+)?)",
            flags=re.IGNORECASE,
        )
        for part in reversed(self.unity_root.parts):
            match = pattern.search(part)
            if match:
                return match.group(1)
        return ""

    @property
    def data_root(self) -> Path:
        configured = _first_environment_value(
            "A3GAME_UNITY_DATA_ROOT",
            "A3GAME_DATA_ROOT",
        )
        if configured:
            return Path(configured).expanduser().resolve(
                strict=False
            )
        project = self.project_path
        if project is not None:
            return project / "Saved" / "A3Game"
        return (
            Path(__file__).resolve().parent
            / "_data"
        )

    @property
    def artifact_registry_path(self) -> Path:
        configured = _first_environment_value(
            "A3GAME_UNITY_ARTIFACT_REGISTRY",
            "A3GAME_ARTIFACT_REGISTRY",
        )
        if configured:
            return Path(configured).expanduser().resolve(
                strict=False
            )
        return self.data_root / "artifacts.json"

    @property
    def world_registry_root(self) -> Path:
        configured = _first_environment_value(
            "A3GAME_UNITY_WORLD_REGISTRY_ROOT",
            "A3GAME_WORLD_REGISTRY_ROOT",
        )
        if configured:
            return Path(configured).expanduser().resolve(
                strict=False
            )
        return self.data_root / "worlds"
