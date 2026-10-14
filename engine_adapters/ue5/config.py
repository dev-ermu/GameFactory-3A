"""Configuration for the stable UEClient API.

取值一律走 `config.settings`（项目唯一配置源），不再读 `os.environ`；
旧名回退链由 `Settings` 的 `validation_alias` 承担。
"""

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# 仓库根入 sys.path：`config` 是顶层模块，因此适配器不必 import `pipeline/`
# 也能读到项目唯一的配置源（`model_require.md` R1.1）。
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from config import settings


SUPPORTED_API_VERSIONS = ("v1",)
DEFAULT_API_VERSION = "v1"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 30010
DEFAULT_RUNTIME_HOST = "127.0.0.1"
DEFAULT_RUNTIME_PORT = 30020
DEFAULT_PYTHON_TRANSPORT = "remote_execution"
DEFAULT_IMPORT_ROOT = "/Game/Imported"
DEFAULT_AVATAR_DEST = "/Game/Imported/Avatars"
DEFAULT_MOTION_DEST = "/Game/Imported/Motions"
DEFAULT_SCENE_DEST = "/Game/Imported/Scenes"
DEFAULT_ENVIRONMENT_DEST = "/Game/Imported/Environments"
DEFAULT_EFFECT_DEST = "/Game/Imported/Effects"
DEFAULT_MATERIAL_DEST = "/Game/Imported/Materials"
DEFAULT_TEXTURE_DEST = "/Game/Imported/Textures"
DEFAULT_PROP_DEST = "/Game/Imported/Props"
DEFAULT_WEAPON_DEST = "/Game/Imported/Weapons"

UE_ASSET_TYPE_DEFAULT_DESTS = {
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


def _text(value: object) -> str:
    """把 `settings` 字段值转成去空白字符串；`None` 与空值一律返回 `""`。"""
    return "" if value is None else str(value).strip()


def _optional_path(value: str | Path | None) -> Path | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    path = Path(text).expanduser()
    if os.name == "nt" and path.is_absolute():
        # Preserve SUBST and mapped drive roots so Unreal builds can use
        # deliberately short Windows paths instead of expanding them.
        return Path(os.path.abspath(str(path)))
    return path.resolve(strict=False)


def _default_python_plugin_path(
    ue_root: Path | None,
) -> Path | None:
    configured = _text(settings.ue_python_plugin_path)
    if configured:
        return _optional_path(configured)
    if ue_root is None:
        return None
    return (
        ue_root
        / "Engine"
        / "Plugins"
        / "Experimental"
        / "PythonScriptPlugin"
        / "Content"
        / "Python"
    )


@dataclass(frozen=True)
class UEClientConfig:
    """Resolved configuration used by UEClient and private implementations."""

    project_path: Path | None
    ue_root: Path | None
    api_version: str = DEFAULT_API_VERSION
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    runtime_host: str = DEFAULT_RUNTIME_HOST
    runtime_port: int = DEFAULT_RUNTIME_PORT
    python_transport: str = DEFAULT_PYTHON_TRANSPORT
    python_plugin_path: Path | None = None

    @classmethod
    def resolve(
        cls,
        project_path: str | Path | None = None,
        ue_root: str | Path | None = None,
        api_version: str = DEFAULT_API_VERSION,
        *,
        host: str | None = None,
        port: int | None = None,
        runtime_host: str | None = None,
        runtime_port: int | None = None,
        python_transport: str | None = None,
        python_plugin_path: str | Path | None = None,
    ) -> "UEClientConfig":
        version = str(api_version or "").strip()
        if version not in SUPPORTED_API_VERSIONS:
            supported = ", ".join(SUPPORTED_API_VERSIONS)
            raise ValueError(
                f"Unsupported UEClient api_version {version!r}; "
                f"supported versions: {supported}"
            )

        resolved_root = _optional_path(
            ue_root or _text(settings.ue_root)
        )
        resolved_project = _optional_path(
            project_path or _text(settings.ue_project)
        )
        resolved_host = host or _text(settings.ue_host) or DEFAULT_HOST
        resolved_port = port
        if resolved_port is None:
            configured_port = _text(settings.ue_port)
            resolved_port = int(configured_port) if configured_port else DEFAULT_PORT
        if not 1 <= int(resolved_port) <= 65535:
            raise ValueError(
                "UE Remote Control port must be between 1 and 65535"
            )
        resolved_runtime_host = (
            runtime_host or _text(settings.ue_runtime_host) or DEFAULT_RUNTIME_HOST
        )
        resolved_runtime_port = runtime_port
        if resolved_runtime_port is None:
            configured_runtime_port = _text(settings.ue_runtime_port)
            resolved_runtime_port = (
                int(configured_runtime_port)
                if configured_runtime_port
                else DEFAULT_RUNTIME_PORT
            )
        if not 1 <= int(resolved_runtime_port) <= 65535:
            raise ValueError(
                "UE runtime UDP port must be between 1 and 65535"
            )

        resolved_transport = (
            python_transport
            or _text(settings.ue_python_transport)
            or DEFAULT_PYTHON_TRANSPORT
        ).strip().lower()
        if resolved_transport not in {
            "remote_execution",
            "remote_control",
        }:
            raise ValueError(
                "python_transport must be 'remote_execution' "
                "or 'remote_control'"
            )

        resolved_python_path = _optional_path(python_plugin_path)
        if resolved_python_path is None:
            resolved_python_path = _default_python_plugin_path(
                resolved_root
            )

        return cls(
            project_path=resolved_project,
            ue_root=resolved_root,
            api_version=version,
            host=str(resolved_host),
            port=int(resolved_port),
            runtime_host=(
                str(resolved_runtime_host).strip()
                or DEFAULT_RUNTIME_HOST
            ),
            runtime_port=int(resolved_runtime_port),
            python_transport=resolved_transport,
            python_plugin_path=resolved_python_path,
        )

    @property
    def remote_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def project_file(self) -> Path | None:
        path = self.project_path
        if path is None:
            return None
        if path.suffix.lower() == ".uproject":
            return path
        if not path.is_dir():
            return None
        candidates = sorted(path.glob("*.uproject"))
        return candidates[0] if len(candidates) == 1 else None

    @property
    def engine_version(self) -> str:
        if self.ue_root is None:
            return ""
        match = re.search(
            r"(?:UE[_-]?)?(\d+\.\d+(?:\.\d+)?)",
            self.ue_root.name,
            flags=re.IGNORECASE,
        )
        return match.group(1) if match else ""

    @property
    def data_root(self) -> Path:
        configured = _text(settings.ue_data_root)
        if configured:
            return Path(configured).expanduser().resolve(strict=False)
        project_file = self.project_file
        if project_file is not None:
            return (
                project_file.parent
                / "Saved"
                / "A3Game"
            )
        return (
            Path(__file__).resolve().parent
            / "_data"
        )

    @property
    def artifact_registry_path(self) -> Path:
        configured = _text(settings.ue_artifact_registry)
        if configured:
            return Path(configured).expanduser().resolve(strict=False)
        return self.data_root / "artifacts.json"

    @property
    def world_registry_root(self) -> Path:
        configured = _text(settings.ue_world_registry_root)
        if configured:
            return Path(configured).expanduser().resolve(strict=False)
        return self.data_root / "worlds"
