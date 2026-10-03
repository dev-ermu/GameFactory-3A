"""Configuration for the stable ThreeClient API."""

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path


SUPPORTED_API_VERSIONS = ("v1",)
DEFAULT_API_VERSION = "v1"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5173
DEFAULT_RUNTIME_HOST = "127.0.0.1"
DEFAULT_RUNTIME_PORT = 30040
DEFAULT_PACKAGE_MANAGER = "npm"
DEFAULT_RUNTIME_TRANSPORT = "http"
DEFAULT_IMPORT_ROOT = "assets/imported"
DEFAULT_AVATAR_DEST = "assets/imported/avatars"
DEFAULT_MOTION_DEST = "assets/imported/motions"
DEFAULT_SCENE_DEST = "assets/imported/scenes"
DEFAULT_ENVIRONMENT_DEST = "assets/imported/environments"
DEFAULT_EFFECT_DEST = "assets/imported/effects"
DEFAULT_MATERIAL_DEST = "assets/imported/materials"
DEFAULT_TEXTURE_DEST = "assets/imported/textures"
DEFAULT_PROP_DEST = "assets/imported/props"
DEFAULT_WEAPON_DEST = "assets/imported/weapons"
DEFAULT_AUDIO_DEST = "assets/imported/audio"

THREE_ASSET_TYPE_DEFAULT_DESTS = {
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
    "audio": DEFAULT_AUDIO_DEST,
}

SUPPORTED_PACKAGE_MANAGERS = ("npm", "pnpm", "yarn")
SUPPORTED_RUNTIME_TRANSPORTS = ("http", "websocket")


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
        # Preserve SUBST and mapped drive roots so Node toolchains can
        # use deliberately short Windows paths.
        return Path(os.path.abspath(str(path)))
    return path.resolve(strict=False)


def _package_version(package_json: Path | None) -> str:
    if package_json is None or not package_json.is_file():
        return ""
    try:
        payload = json.loads(
            package_json.read_text(encoding="utf-8")
        )
    except (json.JSONDecodeError, OSError):
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("version") or "").strip()


@dataclass(frozen=True)
class ThreeClientConfig:
    """Resolved configuration used by ThreeClient and private code."""

    project_path: Path | None
    three_root: Path | None
    api_version: str = DEFAULT_API_VERSION
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    runtime_host: str = DEFAULT_RUNTIME_HOST
    runtime_port: int = DEFAULT_RUNTIME_PORT
    package_manager: str = DEFAULT_PACKAGE_MANAGER
    runtime_transport: str = DEFAULT_RUNTIME_TRANSPORT
    node_root: Path | None = None

    @classmethod
    def resolve(
        cls,
        project_path: str | Path | None = None,
        three_root: str | Path | None = None,
        api_version: str = DEFAULT_API_VERSION,
        *,
        host: str | None = None,
        port: int | None = None,
        runtime_host: str | None = None,
        runtime_port: int | None = None,
        package_manager: str | None = None,
        runtime_transport: str | None = None,
        node_root: str | Path | None = None,
    ) -> "ThreeClientConfig":
        version = str(api_version or "").strip()
        if version not in SUPPORTED_API_VERSIONS:
            supported = ", ".join(SUPPORTED_API_VERSIONS)
            raise ValueError(
                f"Unsupported ThreeClient api_version {version!r}; "
                f"supported versions: {supported}"
            )

        resolved_root = _optional_path(
            three_root
            or _first_environment_value(
                "A3GAME_THREE_ROOT",
            )
        )
        resolved_project = _optional_path(
            project_path
            or _first_environment_value(
                "A3GAME_THREE_PROJECT",
            )
        )
        resolved_node_root = _optional_path(
            node_root
            or _first_environment_value(
                "A3GAME_NODE_ROOT",
            )
        )
        resolved_host = (
            host
            or _first_environment_value(
                "A3GAME_THREE_HOST",
                "THREE_HOST",
            )
            or DEFAULT_HOST
        )
        resolved_port = port
        if resolved_port is None:
            configured_port = _first_environment_value(
                "A3GAME_THREE_PORT",
                "THREE_PORT",
            )
            resolved_port = (
                int(configured_port)
                if configured_port
                else DEFAULT_PORT
            )
        if not 1 <= int(resolved_port) <= 65535:
            raise ValueError(
                "three.js dev server port must be between 1 and 65535"
            )
        resolved_runtime_host = (
            runtime_host
            or _first_environment_value(
                "A3GAME_THREE_RUNTIME_HOST",
            )
            or DEFAULT_RUNTIME_HOST
        )
        resolved_runtime_port = runtime_port
        if resolved_runtime_port is None:
            configured_runtime_port = _first_environment_value(
                "A3GAME_THREE_RUNTIME_PORT",
            )
            resolved_runtime_port = (
                int(configured_runtime_port)
                if configured_runtime_port
                else DEFAULT_RUNTIME_PORT
            )
        if not 1 <= int(resolved_runtime_port) <= 65535:
            raise ValueError(
                "three.js runtime control port must be between 1 "
                "and 65535"
            )

        resolved_manager = (
            package_manager
            or _first_environment_value(
                "A3GAME_THREE_PACKAGE_MANAGER",
            )
            or DEFAULT_PACKAGE_MANAGER
        ).strip().lower()
        if resolved_manager not in SUPPORTED_PACKAGE_MANAGERS:
            supported = ", ".join(SUPPORTED_PACKAGE_MANAGERS)
            raise ValueError(
                f"package_manager must be one of: {supported}"
            )

        resolved_transport = (
            runtime_transport
            or _first_environment_value(
                "A3GAME_THREE_RUNTIME_TRANSPORT",
            )
            or DEFAULT_RUNTIME_TRANSPORT
        ).strip().lower()
        if resolved_transport not in SUPPORTED_RUNTIME_TRANSPORTS:
            supported = ", ".join(SUPPORTED_RUNTIME_TRANSPORTS)
            raise ValueError(
                f"runtime_transport must be one of: {supported}"
            )

        return cls(
            project_path=resolved_project,
            three_root=resolved_root,
            api_version=version,
            host=str(resolved_host),
            port=int(resolved_port),
            runtime_host=(
                str(resolved_runtime_host).strip()
                or DEFAULT_RUNTIME_HOST
            ),
            runtime_port=int(resolved_runtime_port),
            package_manager=resolved_manager,
            runtime_transport=resolved_transport,
            node_root=resolved_node_root,
        )

    @property
    def dev_server_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def runtime_url(self) -> str:
        return f"http://{self.runtime_host}:{self.runtime_port}"

    @property
    def project_dir(self) -> Path | None:
        path = self.project_path
        if path is None:
            return None
        if path.name == "package.json":
            return path.parent
        return path

    @property
    def project_file(self) -> Path | None:
        """Resolve the project's ``package.json`` descriptor."""

        project_dir = self.project_dir
        if project_dir is None:
            return None
        candidate = project_dir / "package.json"
        return candidate if candidate.name else None

    @property
    def project_name(self) -> str:
        project_dir = self.project_dir
        return project_dir.name if project_dir else ""

    @property
    def public_root(self) -> Path | None:
        project_dir = self.project_dir
        return None if project_dir is None else project_dir / "public"

    @property
    def dist_root(self) -> Path | None:
        project_dir = self.project_dir
        return None if project_dir is None else project_dir / "dist"

    @property
    def engine_version(self) -> str:
        """Report the active three.js baseline version."""

        if self.three_root is not None:
            version = _package_version(
                self.three_root / "package.json"
            )
            if version:
                return version
            match = re.search(
                r"(\d+\.\d+(?:\.\d+)?)",
                self.three_root.name,
            )
            if match:
                return match.group(1)
        project_dir = self.project_dir
        if project_dir is not None:
            return _package_version(
                project_dir
                / "node_modules"
                / "three"
                / "package.json"
            )
        return ""

    @property
    def data_root(self) -> Path:
        configured = _first_environment_value(
            "A3GAME_THREE_DATA_ROOT",
            "A3GAME_DATA_ROOT",
        )
        if configured:
            return Path(configured).expanduser().resolve(
                strict=False
            )
        project_dir = self.project_dir
        if project_dir is not None:
            return project_dir / ".a3game"
        return (
            Path(__file__).resolve().parent
            / "_data"
        )

    @property
    def artifact_registry_path(self) -> Path:
        configured = _first_environment_value(
            "A3GAME_THREE_ARTIFACT_REGISTRY",
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
            "A3GAME_THREE_WORLD_REGISTRY_ROOT",
            "A3GAME_WORLD_REGISTRY_ROOT",
        )
        if configured:
            return Path(configured).expanduser().resolve(
                strict=False
            )
        return self.data_root / "worlds"

    @property
    def preview_root(self) -> Path:
        """Where review renders land.

        Deliberately *not* under ``public/``: an orientation sheet is
        evidence for a reviewer, not content for the bundle, and staging
        it would ship megabytes of PNG to every player.
        """

        configured = _first_environment_value(
            "A3GAME_THREE_PREVIEW_ROOT",
        )
        if configured:
            return Path(configured).expanduser().resolve(
                strict=False
            )
        return self.data_root / "previews"
