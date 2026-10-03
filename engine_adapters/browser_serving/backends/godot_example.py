"""Godot example backend implemented only through public GodotClient."""

import json
import logging
import socket
import subprocess
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from time import time
from typing import Any, Callable, Mapping
from uuid import uuid4

from engine_adapters.godot import GodotClient

from ..config import BrowserServingConfig
from ..contracts import (
    AssetImportRequest,
    AssetRecord,
    EngineCapabilities,
    EngineDescriptor,
    WorldRecord,
    serving_result,
)


logger = logging.getLogger(__name__)


def _is_tcp_port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((host, int(port))) != 0


def _is_udp_port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.bind((host, int(port)))
            return True
        except OSError:
            return False


def _http_reachable(url: str, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return int(response.status) < 500
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _payload(result: Mapping[str, Any]) -> dict[str, Any]:
    return dict(result.get("payload") or {})


def _errors(result: Mapping[str, Any]) -> list[str]:
    return [str(item) for item in result.get("errors") or []]


def _normalize_asset(
    item: Mapping[str, Any],
    *,
    asset_type: str = "",
) -> dict[str, Any]:
    value = dict(item)
    if value.get("native"):
        return AssetRecord.from_dict(value).to_dict()
    primary = dict(value.get("primary_asset") or {})
    backend_path = str(
        value.get("backend_path")
        or value.get("path")
        or primary.get("path")
        or ""
    )
    backend_class = str(
        value.get("backend_class")
        or value.get("class")
        or primary.get("class")
        or ""
    )
    metadata = dict(value.get("metadata") or {})
    skeleton_path = str(metadata.get("skeleton_path") or "")
    if not skeleton_path:
        for dependency in metadata.get("dependencies") or []:
            if (
                isinstance(dependency, Mapping)
                and str(dependency.get("type") or "") == "skeleton"
            ):
                assets = dependency.get("assets") or []
                if assets:
                    skeleton_path = str(assets[0])
                    break
    if skeleton_path:
        metadata["skeleton_path"] = skeleton_path
    resolved_type = str(
        value.get("artifact_type")
        or value.get("type")
        or asset_type
        or ""
    )
    return AssetRecord(
        artifact_id=str(
            value.get("artifact_id")
            or backend_path
        ),
        asset_id=str(
            value.get("asset_id")
            or value.get("name")
            or backend_path.rsplit("/", 1)[-1]
        ),
        artifact_type=resolved_type,
        engine="godot",
        state=str(value.get("state") or "ready"),
        capabilities={
            str(key): bool(item)
            for key, item in dict(
                value.get("runtime_capabilities") or {}
            ).items()
        },
        native={
            "backend": "godot",
            "class": backend_class,
            "path": backend_path,
            "primary_asset": primary,
            "editor": dict(value.get("editor_backend") or {}),
            "runtime": dict(value.get("runtime") or {}),
        },
        metadata=metadata,
    ).to_dict()


def _normalize_world(item: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(item)
    metadata = dict(value.get("metadata") or {})
    package = (
        metadata
        if metadata.get("package_id")
        else value
    )
    return WorldRecord(
        package_id=str(
            package.get("package_id")
            or value.get("artifact_id")
            or ""
        ),
        world_id=str(package.get("world_id") or ""),
        project_id=str(package.get("project_id") or ""),
        engine="godot",
        state=str(
            package.get("status")
            or value.get("state")
            or "published"
        ),
        manifest=dict(package.get("manifest") or {}),
    ).to_dict()


@dataclass
class GodotBrowserSession:
    session_id: str
    participant_id: str
    user_id: str
    state: str
    runtime_port: int
    http_port: int
    stream_url: str
    game_url: str
    godot_input_host: str
    preview_scene: str
    client: Any = field(repr=False)
    character: dict[str, Any] = field(default_factory=dict)
    controller_id: str = ""
    entity_id: str = ""
    world_id: str = ""
    project_id: str = ""
    runtime_package_id: str = ""
    world_scene_path: str = ""
    godot_game_pid: int = 0
    http_pid: int = 0
    http_process: subprocess.Popen | None = field(
        default=None,
        repr=False,
    )
    created_at: float = field(default_factory=time)
    updated_at: float = field(default_factory=time)
    error: str = ""
    last_command: str = ""
    recovered_external: bool = False
    # Godot Web export is a browser-native player: the game is served over
    # HTTP and runs inside an iframe wrapper page.
    runtime_kind: str = "godot_web"
    input_transport: str = "browser_canvas"
    streaming_transport: str = "godot_web_http"
    last_input: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "participant_id": self.participant_id,
            "user_id": self.user_id,
            "state": self.state,
            "runtime_port": self.runtime_port,
            "godot_input_host": self.godot_input_host,
            "godot_input_port": self.runtime_port,
            "http_port": self.http_port,
            "stream_url": self.stream_url,
            "game_url": self.game_url,
            "pixel_streaming_url": "",
            "streaming_transport": self.streaming_transport,
            "preview_scene": self.preview_scene,
            "character": dict(self.character),
            "controller_id": self.controller_id,
            "entity_id": self.entity_id,
            "world_id": self.world_id,
            "project_id": self.project_id,
            "runtime_package_id": self.runtime_package_id,
            "world_scene_path": self.world_scene_path,
            "godot_game_pid": self.godot_game_pid,
            "http_pid": self.http_pid,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
            "last_command": self.last_command,
            "recovered_external": self.recovered_external,
            "runtime_kind": self.runtime_kind,
            "input_transport": self.input_transport,
            "last_input": dict(self.last_input),
        }


class GodotExampleBackend:
    """Browser serving backend for Godot 4 via GodotClient."""

    def __init__(
        self,
        config: BrowserServingConfig,
        *,
        client_factory: Callable[..., Any] = GodotClient,
        browser_opener: Callable[[str], bool] | None = None,
    ) -> None:
        self.config = config
        self._client_factory = client_factory
        self._browser_opener = browser_opener or webbrowser.open
        self._sessions: dict[str, GodotBrowserSession] = {}
        self._lock = RLock()
        self._descriptor = EngineDescriptor(
            engine_id="godot",
            display_name="Godot 4 Example",
            backend_kind="example_backend",
            capabilities=EngineCapabilities(
                asset_upload=True,
                asset_import=True,
                asset_inspection=True,
                world_build=True,
                world_catalog=True,
                runtime_sessions=True,
                skeletal_animation=True,
                streaming=True,
                pixel_streaming=False,
                preview_camera=True,
            ),
        )
        self._admin_client = self._new_client(
            runtime_port=config.godot_runtime_port,
        )

    @property
    def descriptor(self) -> EngineDescriptor:
        return self._descriptor

    def _new_client(self, *, runtime_port: int):
        return self._client_factory(
            project_path=self.config.godot_project,
            godot_executable=self.config.godot_executable,
            runtime_host=self.config.godot_host,
            runtime_port=runtime_port,
        )

    # ------------------------------------------------------------------
    # Engine status
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        environment = self._admin_client.get_environment_info()
        observation = self._admin_client.observe.check_status()
        configured = (
            self.config.godot_project is not None
            or self.config.godot_executable is not None
        )
        return serving_result(
            "engine.status",
            engine="godot",
            ok=configured,
            payload={
                "configured": configured,
                "environment": environment,
                "observation": observation,
                "message": (
                    "Godot backend configured"
                    if configured
                    else "Set A3GAME_GODOT_PROJECT or A3GAME_GODOT_EXECUTABLE"
                ),
            },
            warnings=[] if configured else [
                "Godot example backend is not configured"
            ],
        )

    # ------------------------------------------------------------------
    # Asset operations
    # ------------------------------------------------------------------

    def import_asset(
        self,
        request: AssetImportRequest,
    ) -> dict[str, Any]:
        asset_type = request.asset_type
        source = dict(request.descriptor)
        options = dict(request.options)
        if asset_type == "motion":
            skeleton = str(
                options.pop("skeleton", "")
                or options.pop("skeleton_path", "")
                or request.metadata.get("skeleton_path", "")
            )
            avatar_name = str(
                options.pop("avatar_name", "")
                or request.metadata.get("avatar_name", "")
            )
            result = self._admin_client.animation.import_motion(
                source,
                skeleton=skeleton,
                avatar_name=avatar_name,
                destination=request.destination,
                options=options,
            )
        else:
            method_name = {
                "avatar": "import_avatar",
                "effect": "import_effect",
                "material": "import_material",
                "prop": "import_prop",
                "object": "import_prop",
                "static_mesh": "import_prop",
                "texture": "import_texture",
                "weapon": "import_weapon",
                "audio": "import_audio",
                "scene": "import_scene",
            }.get(asset_type, "import_asset")
            method = getattr(self._admin_client.assets, method_name)
            if method_name == "import_asset":
                result = method(
                    source,
                    asset_type,
                    destination=request.destination,
                    options=options,
                )
            else:
                result = method(
                    source,
                    destination=request.destination,
                    options=options,
                )
        return self._translate_godot_result(
            "assets.import",
            result,
            asset_type=asset_type,
        )

    def build_world(
        self,
        request: AssetImportRequest,
    ) -> dict[str, Any]:
        options = dict(request.options)
        result = self._admin_client.world.build(
            request.descriptor,
            options=options,
        )
        translated = self._translate_godot_result(
            "worlds.build",
            result,
            asset_type="scene",
        )
        translated["payload"].setdefault(
            "worlds",
            self.list_worlds(
                project_id=str(options.get("project_id") or "")
            ),
        )
        return translated

    def inspect_asset(self, artifact_id: str) -> dict[str, Any]:
        result = self._admin_client.assets.get_metadata(artifact_id)
        return self._translate_godot_result(
            "assets.inspect",
            result,
        )

    def list_assets(
        self,
        asset_type: str = "",
        *,
        root_uri: str = "",
    ) -> list[dict[str, Any]]:
        result = self._admin_client.assets.list(
            asset_type,
            root=root_uri or "res://assets/imported",
        )
        if not result.get("ok"):
            result = self._admin_client.assets.list_registered(asset_type)
        return [
            _normalize_asset(item, asset_type=asset_type)
            for item in result.get("artifacts") or []
            if isinstance(item, Mapping)
        ]

    def list_worlds(
        self,
        *,
        project_id: str = "",
    ) -> list[dict[str, Any]]:
        result = self._admin_client.world.list_packages(
            project_id=project_id
        )
        return [
            _normalize_world(item)
            for item in result.get("artifacts") or []
            if isinstance(item, Mapping)
        ]

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def create_session(
        self,
        request: Mapping[str, Any],
    ) -> dict[str, Any]:
        slot, ports = self._allocate_ports()
        session_id = f"bs_{uuid4().hex[:10]}"
        user_id = str(request.get("user_id") or "")
        participant_id = str(
            request.get("participant_id")
            or f"participant_{user_id or session_id}"
        )
        stream_url = (
            f"http://{self.config.pixel_host}:{ports['http']}/{self._browser_wrapper_name(session_id)}"
        )
        client = self._new_client(
            runtime_port=ports["runtime"],
        )
        session = GodotBrowserSession(
            session_id=session_id,
            participant_id=participant_id,
            user_id=user_id,
            state="CREATED",
            runtime_port=ports["runtime"],
            http_port=ports["http"],
            stream_url=stream_url,
            game_url="",
            godot_input_host=self.config.godot_host,
            preview_scene=str(request.get("preview_scene") or ""),
            client=client,
            character=dict(request.get("character") or {}),
        )
        with self._lock:
            self._sessions[session_id] = session
        try:
            session.state = "LAUNCHING_GAME"
            launch = self._launch_game(session)
            if not launch.get("ok"):
                raise RuntimeError(
                    "; ".join(_errors(launch))
                    or "Godot game launch failed"
                )
            session.godot_game_pid = int(
                _payload(launch).get("process_id") or 0
            )
            session.state = "PREVIEW_READY"
            if session.character:
                self.configure_session(
                    session.session_id,
                    session.character,
                )
        except Exception as exc:
            session.state = "ERROR"
            session.error = f"{type(exc).__name__}: {exc}"
            self._stop_session_processes(session)
            raise
        return serving_result(
            "sessions.create",
            engine="godot",
            payload={"slot": slot, **session.to_dict()},
        )

    def list_sessions(self) -> dict[str, Any]:
        self._refresh_process_state()
        return serving_result(
            "sessions.list",
            engine="godot",
            payload={
                "sessions": [
                    item.to_dict()
                    for item in self._sessions.values()
                ]
            },
        )

    def get_session(self, session_id: str) -> dict[str, Any]:
        self._refresh_process_state()
        session = self._require_session(session_id)
        return serving_result(
            "sessions.get",
            engine="godot",
            payload=session.to_dict(),
        )

    def recover_session(
        self,
        snapshot: Mapping[str, Any],
    ) -> dict[str, Any]:
        session_id = str(
            snapshot.get("session_id")
            or snapshot.get("sessionId")
            or ""
        ).strip()
        if not session_id:
            raise ValueError("session_id is required")
        if session_id in self._sessions:
            return self.get_session(session_id)
        runtime_port = int(
            snapshot.get("runtime_port")
            or snapshot.get("godot_input_port")
            or self.config.godot_runtime_port
        )
        stream_url = str(
            snapshot.get("stream_url")
            or snapshot.get("pixel_streaming_url")
            or ""
        )
        session = GodotBrowserSession(
            session_id=session_id,
            participant_id=str(
                snapshot.get("participant_id")
                or f"participant_{session_id}"
            ),
            user_id=str(snapshot.get("user_id") or ""),
            state=str(snapshot.get("state") or "PREVIEW_READY"),
            runtime_port=runtime_port,
            http_port=int(snapshot.get("http_port") or 0),
            stream_url=stream_url,
            game_url=str(snapshot.get("game_url") or ""),
            godot_input_host=str(
                snapshot.get("godot_input_host")
                or self.config.godot_host
            ),
            preview_scene=str(
                snapshot.get("preview_scene") or ""
            ),
            client=self._new_client(runtime_port=runtime_port),
            character=dict(snapshot.get("character") or {}),
            controller_id=str(snapshot.get("controller_id") or ""),
            entity_id=str(snapshot.get("entity_id") or ""),
            world_id=str(snapshot.get("world_id") or ""),
            project_id=str(snapshot.get("project_id") or ""),
            runtime_package_id=str(
                snapshot.get("runtime_package_id") or ""
            ),
            world_scene_path=str(
                snapshot.get("world_scene_path") or ""
            ),
            godot_game_pid=int(
                snapshot.get("godot_game_pid") or 0
            ),
            http_pid=int(snapshot.get("http_pid") or 0),
            recovered_external=True,
        )
        self._sessions[session_id] = session
        return serving_result(
            "sessions.recover",
            engine="godot",
            payload={"recovered": True, **session.to_dict()},
        )

    def session_catalog(
        self,
        *,
        project_id: str = "",
    ) -> dict[str, Any]:
        return serving_result(
            "sessions.catalog",
            engine="godot",
            payload={
                "avatars": self.list_assets("avatar"),
                "motions": self.list_assets("motion"),
                "worlds": self.list_worlds(project_id=project_id),
                "runtime_ready": True,
                "project_id": project_id,
            },
        )

    def configure_session(
        self,
        session_id: str,
        character: Mapping[str, Any],
    ) -> dict[str, Any]:
        session = self._require_session(session_id)
        resolved = dict(character)
        avatar_id = self._artifact_reference(
            str(
                resolved.get("avatar_id")
                or resolved.get("avatar_asset_path")
                or ""
            ),
            "avatar",
        )
        idle_id = self._artifact_reference(
            str(
                resolved.get("idle_animation")
                or resolved.get("idle_animation_path")
                or ""
            ),
            "motion",
            required=False,
        )
        move_id = self._artifact_reference(
            str(
                resolved.get("move_animation")
                or resolved.get("move_animation_path")
                or ""
            ),
            "motion",
            required=False,
        )
        if not avatar_id:
            raise ValueError("character.avatar_id is required")
        result = session.client.runtime.sessions.join(
            world_id=session.world_id,
            participant_id=session.participant_id,
            user_id=session.user_id,
            avatar_artifact_id=avatar_id,
            idle_motion_artifact_id=idle_id,
            move_motion_artifact_id=move_id,
            parameters={
                key: value
                for key, value in resolved.items()
                if key not in {
                    "avatar_id",
                    "avatar_asset_path",
                    "idle_animation",
                    "idle_animation_path",
                    "move_animation",
                    "move_animation_path",
                }
            },
        )
        if not result.get("ok"):
            return self._translate_godot_result(
                "sessions.configure",
                result,
            )
        result_payload = _payload(result)
        session.character = {
            **resolved,
            "avatar_id": avatar_id,
            "idle_animation": idle_id,
            "move_animation": move_id,
        }
        session.controller_id = str(
            result_payload.get("controller_id") or ""
        )
        session.entity_id = str(result_payload.get("entity_id") or "")
        session.state = (
            "IN_WORLD"
            if session.state == "IN_WORLD"
            else "PREVIEWING"
        )
        session.updated_at = time()
        session.last_command = "configure_session"
        return serving_result(
            "sessions.configure",
            engine="godot",
            payload={
                "runtime": result,
                **session.to_dict(),
            },
        )

    def play_preview_animation(
        self,
        session_id: str,
        animation: str,
        *,
        loop: bool = True,
        play_rate: float = 1.0,
    ) -> dict[str, Any]:
        session = self._require_session(session_id)
        animation_id = self._artifact_reference(
            animation,
            "motion",
        )
        character = {
            **session.character,
            "idle_animation": animation_id,
            "preview_animation": animation_id,
            "preview_loop": bool(loop),
            "preview_play_rate": float(play_rate),
        }
        result = self.configure_session(session_id, character)
        session.last_command = "play_preview_animation"
        result["payload"]["preview_animation"] = animation_id
        result["payload"]["preview_loop"] = bool(loop)
        result["payload"]["preview_play_rate"] = float(play_rate)
        return result

    def load_world(
        self,
        session_id: str,
        *,
        package_id: str = "",
        world_id: str = "",
        project_id: str = "",
    ) -> dict[str, Any]:
        session = self._require_session(session_id)
        worlds = self.list_worlds(project_id=project_id)
        selected = next(
            (
                item
                for item in worlds
                if (
                    package_id
                    and item.get("package_id") == package_id
                )
                or (
                    world_id
                    and item.get("world_id") == world_id
                )
            ),
            None,
        )
        if selected is None:
            raise FileNotFoundError(
                f"World package was not found: {package_id or world_id}"
            )
        session.runtime_package_id = str(
            selected.get("package_id") or ""
        )
        session.world_id = str(selected.get("world_id") or "")
        session.project_id = str(selected.get("project_id") or "")
        session.world_scene_path = self._world_scene_path(selected)
        session.updated_at = time()
        session.last_command = "load_world"
        return serving_result(
            "sessions.load_world",
            engine="godot",
            payload={
                "loaded": True,
                "package": selected,
                **session.to_dict(),
            },
        )

    def join_world(
        self,
        session_id: str,
        *,
        server_uri: str = "",
    ) -> dict[str, Any]:
        session = self._require_session(session_id)
        del server_uri
        target_scene = session.world_scene_path or session.preview_scene
        if target_scene and target_scene != session.preview_scene:
            relaunch = self._relaunch_game(session, target_scene)
            if not relaunch.get("ok"):
                return relaunch
        session.state = "IN_WORLD"
        if session.character:
            configured = self.configure_session(
                session_id,
                session.character,
            )
            if not configured.get("ok"):
                return configured
        session.state = "IN_WORLD"
        session.updated_at = time()
        session.last_command = "join_world"
        return serving_result(
            "sessions.join_world",
            engine="godot",
            payload={
                "joined": True,
                "server_url": "",
                **session.to_dict(),
            },
        )

    def leave_world(self, session_id: str) -> dict[str, Any]:
        session = self._require_session(session_id)
        runtime = {}
        if session.controller_id:
            runtime = session.client.runtime.sessions.leave(
                participant_id=session.participant_id,
                controller_id=session.controller_id,
            )
        session.state = "PREVIEW_READY"
        session.updated_at = time()
        session.last_command = "leave_world"
        return serving_result(
            "sessions.leave_world",
            engine="godot",
            payload={"runtime": runtime, **session.to_dict()},
        )

    def apply_input(
        self,
        session_id: str,
        input_state: Mapping[str, Any],
    ) -> dict[str, Any]:
        session = self._require_session(session_id)
        if not session.controller_id:
            return serving_result(
                "sessions.apply_input",
                engine="godot",
                payload={
                    "skipped": True,
                    "reason": "session has no configured controller",
                    **session.to_dict(),
                },
            )
        result = session.client.runtime.sessions.apply_input(
            session.controller_id,
            move_x=float(input_state.get("move_x", 0.0)),
            move_y=float(input_state.get("move_y", 0.0)),
            run=bool(input_state.get("run", False)),
            jump=bool(input_state.get("jump", False)),
            yaw=float(input_state.get("yaw", 0.0)),
            pitch=float(input_state.get("pitch", 0.0)),
            seq=int(input_state.get("seq", 0)),
        )
        session.last_input = dict(input_state)
        session.last_command = "apply_input"
        session.updated_at = time()
        warnings = []
        action = str(input_state.get("action") or "").strip()
        if action:
            warnings.append(
                "The GodotClient v1 normalized input contract does not "
                f"define game-specific action {action!r}"
            )
        translated = self._translate_godot_result(
            "sessions.apply_input",
            result,
        )
        translated["warnings"].extend(warnings)
        translated["payload"].update(session.to_dict())
        for key, value in session.to_dict().items():
            translated.setdefault(key, value)
        return translated

    def apply_preview_camera(
        self,
        session_id: str,
        camera_input: Mapping[str, Any],
    ) -> dict[str, Any]:
        session = self._require_session(session_id)
        normalized = {
            "move_x": float(camera_input.get("pan_y_delta", 0.0))
            / 100.0,
            "move_y": float(camera_input.get("zoom_delta", 0.0))
            / 100.0,
            "yaw": float(camera_input.get("yaw_delta", 0.0)),
            "pitch": float(camera_input.get("pitch_delta", 0.0)),
        }
        result = self.apply_input(session_id, normalized)
        result["operation"] = "sessions.apply_preview_camera"
        session.last_command = "apply_preview_camera"
        return result

    def handle_runtime_event(
        self,
        session_id: str,
        event: str,
        *,
        world_name: str = "",
        entity_name: str = "",
    ) -> dict[str, Any]:
        session = self._require_session(session_id)
        normalized = str(event or "").strip().upper()
        if normalized in {"SESSION_READY", "RENDER_READY"}:
            session.state = "IN_WORLD"
        elif normalized == "PREVIEW_READY":
            session.state = "PREVIEW_READY"
        elif normalized == "SESSION_ERROR":
            session.state = "ERROR"
        session.last_command = normalized
        session.updated_at = time()
        return serving_result(
            "sessions.runtime_event",
            engine="godot",
            payload={
                "event": normalized,
                "world_name": world_name,
                "entity_name": entity_name,
                **session.to_dict(),
            },
        )

    def stop_session(self, session_id: str) -> dict[str, Any]:
        session = self._require_session(session_id)
        snapshot = session.to_dict()
        if session.controller_id:
            session.client.runtime.sessions.clear_entity(
                participant_id=session.participant_id,
                controller_id=session.controller_id,
                entity_id=session.entity_id,
            )
        self._stop_session_processes(session)
        session.state = "DESTROYED"
        with self._lock:
            self._sessions.pop(session_id, None)
        return serving_result(
            "sessions.stop",
            engine="godot",
            payload={
                "removed": True,
                "session": snapshot,
                **snapshot,
            },
        )

    # ------------------------------------------------------------------
    # Debug
    # ------------------------------------------------------------------

    def debug(
        self,
        operation: str,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = dict(payload or {})
        normalized = (
            str(operation or "")
            .strip()
            .lower()
            .replace("/", "_")
            .replace("-", "_")
        )
        session = self._first_session()
        if normalized == "viewer_config":
            return serving_result(
                "debug.viewer_config",
                engine="godot",
                payload={
                    "stream_url": (
                        session.stream_url
                        if session is not None
                        else ""
                    ),
                    "streaming_enabled": bool(session),
                    "default_actor_label": "A3Game_BrowserPreview",
                    "playable_actor_label": "A3Game_BrowserPlayer",
                    "playable_blueprint_path": "",
                    "default_walk_speed": 5.0,
                    "default_run_speed": 10.0,
                    "movement_step": 0.5,
                    "rotation_step": 15.0,
                    "viewer_host": self.config.gateway_host,
                    "viewer_port": self.config.gateway_port,
                    "runtime_godot_host": self.config.godot_host,
                    "runtime_godot_port": (
                        session.runtime_port
                        if session is not None
                        else self.config.godot_runtime_port
                    ),
                    "runtime_udp_mode": "godot_web",
                    "streaming_transport": "godot_web_http",
                },
            )
        if normalized == "pixel_status":
            url = (
                session.stream_url
                if session is not None
                else ""
            )
            # Web export has no stream server to probe; any active session
            # URL is treated as reachable.
            reachable = bool(url)
            return serving_result(
                "debug.pixel_status",
                engine="godot",
                payload={
                    "reachable": reachable,
                    "stream_ready": reachable,
                    "url": url,
                    "transport": "godot_web_http",
                    "message": (
                        "godot web export reachable"
                        if reachable
                        else "no active Godot browser session"
                    ),
                },
            )
        if normalized == "runtime_world_state":
            result = self._admin_client.runtime.sessions.snapshot(
                world_id=str(data.get("world_id") or "")
            )
            return self._translate_godot_result(
                "debug.runtime_world_state",
                result,
            )
        if normalized in {
            "runtime_clear_entity",
            "scene_clear",
        }:
            if session is None:
                return serving_result(
                    "debug.clear",
                    engine="godot",
                    payload={"removed": False},
                )
            result = session.client.runtime.sessions.clear_entity(
                participant_id=session.participant_id,
                controller_id=session.controller_id,
                entity_id=session.entity_id,
            )
            return self._translate_godot_result("debug.clear", result)
        if normalized in {
            "scene_present_avatar",
            "scene_preview_runtime_avatar",
        }:
            active = session
            if active is None:
                created = self.create_session(
                    {
                        "user_id": "admin_preview",
                        "participant_id": "admin_preview",
                        "character": {},
                    }
                )
                active = self._require_session(
                    str(created.get("session_id") or "")
                )
            return self.configure_session(
                active.session_id,
                {
                    "avatar_id": (
                        data.get("avatar_asset_path")
                        or data.get("avatar_id")
                        or ""
                    ),
                    "idle_animation": data.get(
                        "idle_animation_path",
                        "",
                    ),
                    "move_animation": data.get(
                        "move_animation_path",
                        "",
                    ),
                },
            )
        if normalized in {
            "scene_play_motion",
            "scene_set_animation",
        }:
            if session is None:
                raise ValueError("No active preview session")
            return self.play_preview_animation(
                session.session_id,
                str(
                    data.get("motion_asset_path")
                    or data.get("animation")
                    or ""
                ),
                loop=bool(data.get("looping", True)),
            )
        if normalized in {
            "scene_move",
            "scene_rotate",
            "editor_camera_input",
            "editor_camera_start",
        }:
            if session is None:
                return serving_result(
                    f"debug.{normalized}",
                    engine="godot",
                    payload={"skipped": True, "reason": "no session"},
                )
            return self.apply_preview_camera(
                session.session_id,
                {
                    "yaw_delta": data.get(
                        "yaw_delta",
                        data.get("yawDelta", 0.0),
                    ),
                    "pitch_delta": data.get(
                        "pitch_delta",
                        data.get("pitchDelta", 0.0),
                    ),
                    "zoom_delta": data.get(
                        "zoom_delta",
                        data.get("move_y", 0.0),
                    ),
                    "pan_y_delta": data.get(
                        "pan_y_delta",
                        data.get("move_x", 0.0),
                    ),
                },
            )
        if normalized == "scene_transform":
            return self.debug(
                "runtime_world_state",
                {"world_id": str(data.get("world_id") or "")},
            )
        return serving_result(
            f"debug.{normalized or 'unknown'}",
            engine="godot",
            ok=False,
            errors=[f"Unsupported Godot example debug operation: {operation}"],
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _allocate_ports(self) -> tuple[int, dict[str, int]]:
        for slot in range(self.config.max_sessions):
            stride = slot * self.config.session_port_stride
            ports = {
                "http": self.config.base_pixel_http_port + stride,
                "runtime": self.config.godot_runtime_port + slot,
            }
            if self.config.dry_run or (
                _is_tcp_port_free(self.config.godot_host, ports["http"])
                and _is_udp_port_free(
                    self.config.godot_host,
                    ports["runtime"],
                )
            ):
                return slot, ports
        raise RuntimeError("No free browser serving session ports")

    def _launch_game(
        self,
        session: GodotBrowserSession,
    ) -> dict[str, Any]:
        if self.config.dry_run:
            return {
                "ok": True,
                "operation": "runtime.launch_game",
                "artifacts": [],
                "warnings": [],
                "errors": [],
                "payload": {
                    "process_id": 0,
                    "dry_run": True,
                },
            }
        # Rebuild the Web export whenever it is missing or older than the
        # project. Generated games can regenerate scenes, scripts, and assets
        # after a previous export, so a stale build would hide those changes
        # from the browser session.
        web_build_dir = self._web_build_dir(session)
        # Godot names the exported HTML after the preset ("web.html");
        # older exports fall back to "index.html".
        web_html = web_build_dir / "web.html"
        if not web_html.is_file():
            web_html = web_build_dir / "index.html"
        if self._web_build_is_stale(web_build_dir, web_html):
            # Godot's export command requires a file destination: passing
            # the build directory would emit the export beside it, where the
            # entry-point lookup below would not find it.
            export_output = web_build_dir / "web.html"
            build_result = session.client.build.project(
                preset="Web",
                output_path=str(export_output),
                debug=True,
            )
            if not build_result.get("ok"):
                return build_result
            web_html = web_build_dir / "web.html"
            if not web_html.is_file():
                web_html = web_build_dir / "index.html"
        if not web_html.is_file():
            raise FileNotFoundError(
                f"Godot Web export is missing an HTML entry point: {web_build_dir}"
            )
        html_name = web_html.name
        session.game_url = (
            f"http://{self.config.pixel_host}:{session.http_port}/{html_name}"
        )
        wrapper = self._write_browser_wrapper(
            web_build_dir,
            session,
            html_name,
        )
        session.stream_url = (
            f"http://{self.config.pixel_host}:{session.http_port}/{wrapper.name}"
        )
        session.http_process = self._start_http_server(
            web_build_dir,
            session.http_port,
        )
        session.http_pid = int(session.http_process.pid) if session.http_process else 0
        self._wait_for_http(session.stream_url)
        if self.config.godot_auto_open_browser:
            self._open_browser(session.stream_url)
        return {
            "ok": True,
            "operation": "runtime.launch_game",
            "artifacts": [],
            "warnings": [],
            "errors": [],
            "payload": {
                "process_id": session.http_pid,
                "stream_url": session.stream_url,
                "game_url": session.game_url,
                "browser_wrapper": wrapper.name,
            },
        }

    def _relaunch_game(
        self,
        session: GodotBrowserSession,
        scene_path: str,
    ) -> dict[str, Any]:
        # A Web-export session has no separate OS process to relaunch; the
        # browser reloads the page for a new scene.
        session.updated_at = time()
        return {
            "ok": True,
            "operation": "sessions.relaunch_game",
            "artifacts": [],
            "warnings": [],
            "errors": [],
            "payload": {"scene_path": scene_path},
        }

    def _stop_session_processes(
        self,
        session: GodotBrowserSession,
    ) -> None:
        process = session.http_process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def _web_build_dir(self, session: GodotBrowserSession) -> Path:
        if self.config.godot_project is None:
            raise ValueError("A3GAME_GODOT_PROJECT is not configured")
        return Path(self.config.godot_project) / "builds"

    def _web_build_is_stale(self, web_build_dir: Path, web_html: Path) -> bool:
        # Older Godot exports use "index.html" with custom companion
        # filenames. Treat those directories as explicit browser builds and
        # do not force a rebuild based on the "web.*" naming convention.
        if web_html.name == "index.html" and web_html.is_file():
            return False
        required = [
            web_html,
            web_build_dir / "web.pck",
            web_build_dir / "web.js",
            web_build_dir / "web.wasm",
        ]
        if any(not path.is_file() for path in required):
            return True
        build_mtime = min(path.stat().st_mtime_ns for path in required)
        if self.config.godot_project is None:
            return False
        project_root = Path(self.config.godot_project)
        # Ignore generated Godot caches and the export directory itself;
        # every authored scene, script, setting, and imported source asset
        # participates in the freshness check.
        for path in project_root.rglob("*"):
            if not path.is_file():
                continue
            try:
                relative = path.relative_to(project_root)
            except ValueError:
                continue
            if relative.parts and relative.parts[0] in {".godot", "builds"}:
                continue
            if path.stat().st_mtime_ns > build_mtime:
                return True
        return False

    def _start_http_server(
        self,
        directory: Path,
        port: int,
    ) -> subprocess.Popen:
        import sys
        return subprocess.Popen(
            [
                sys.executable,
                "-m",
                "http.server",
                str(port),
                "--bind",
                self.config.pixel_host,
            ],
            cwd=str(directory),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def _browser_wrapper_name(self, session_id: str) -> str:
        return f"browser-{session_id}.html"

    def _write_browser_wrapper(
        self,
        directory: Path,
        session: GodotBrowserSession,
        game_html_name: str,
    ) -> Path:
        wrapper = directory / self._browser_wrapper_name(session.session_id)
        wrapper.write_text(
            self._browser_wrapper_html(
                session=session,
                game_html_name=game_html_name,
            ),
            encoding="utf-8",
        )
        return wrapper

    def _browser_wrapper_html(
        self,
        *,
        session: GodotBrowserSession,
        game_html_name: str,
    ) -> str:
        game_url = json.dumps(game_html_name)
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Godot Browser Play — {session.session_id}</title>
  <style>
    :root {{
      color-scheme: dark;
      font-family: Inter, "Segoe UI", system-ui, sans-serif;
      background: #000;
      color: #f4f6f5;
    }}
    html,
    body {{
      width: 100%;
      height: 100%;
      margin: 0;
      overflow: hidden;
      background: #000;
    }}
    body {{
      position: relative;
    }}
    #gameFrame {{
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      border: 0;
      background: #000;
    }}
    .hud {{
      position: absolute;
      top: 12px;
      right: 12px;
      z-index: 2;
      display: flex;
      gap: 8px;
      align-items: center;
      padding: 8px 10px;
      border: 1px solid rgba(255, 255, 255, 0.15);
      border-radius: 12px;
      background: rgba(0, 0, 0, 0.55);
      backdrop-filter: blur(12px);
    }}
    .hud span {{
      color: #c7d0cc;
      font-size: 12px;
      white-space: nowrap;
    }}
    button,
    a.button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 34px;
      border: 1px solid #46504c;
      border-radius: 8px;
      padding: 6px 10px;
      background: #151b19;
      color: #f4f6f5;
      font: inherit;
      text-decoration: none;
      cursor: pointer;
    }}
    button:hover,
    a.button:hover {{
      border-color: #62c7ad;
      background: #202825;
    }}
    .hint {{
      position: absolute;
      left: 12px;
      bottom: 12px;
      z-index: 2;
      max-width: min(480px, calc(100% - 24px));
      border: 1px solid rgba(255, 255, 255, 0.14);
      border-radius: 10px;
      padding: 8px 10px;
      background: rgba(0, 0, 0, 0.6);
      color: #c7d0cc;
      font-size: 12px;
      line-height: 1.45;
    }}
  </style>
</head>
<body>
  <iframe
    id="gameFrame"
    title="Godot game"
    src={game_url}
    allow="autoplay; fullscreen; clipboard-read; clipboard-write; pointer-lock"
  ></iframe>
  <div class="hud">
    <span>{json.dumps(f'Godot {session.session_id}')}</span>
    <button id="fullscreenButton" type="button">Fullscreen</button>
    <a class="button" href={game_url} target="_blank" rel="noreferrer">Open direct</a>
  </div>
  <div class="hint">
    Click <strong>Fullscreen</strong> for a larger view, or open the raw Web export directly.
  </div>
  <script>
    // The admin page and the raw Web export live on different ports, so
    // browser-play input is forwarded through this wrapper iframe. Keep the
    // latest message queued until the game finishes loading; input sent
    // earlier would be dropped by the not-yet-ready player.
    const gameFrame = document.getElementById("gameFrame");
    let pendingGameMessage = null;
    function forwardGameMessage(data) {{
      pendingGameMessage = data;
      if (gameFrame && gameFrame.contentWindow) {{
        gameFrame.contentWindow.postMessage(data, "*");
      }}
    }}
    window.addEventListener("message", (event) => {{
      if (typeof event.data === "string") forwardGameMessage(event.data);
    }});
    gameFrame.addEventListener("load", () => {{
      if (pendingGameMessage !== null) {{
        gameFrame.contentWindow.postMessage(pendingGameMessage, "*");
      }}
    }});

    const fullscreenButton = document.getElementById("fullscreenButton");
    fullscreenButton.addEventListener("click", async () => {{
      try {{
        await document.documentElement.requestFullscreen();
      }} catch {{
        try {{
          await document.body.requestFullscreen();
        }} catch {{
          // Ignored: the user can still play in the browser window.
        }}
      }}
    }});
    window.addEventListener("keydown", (event) => {{
      if (event.key === "F11") {{
        event.preventDefault();
        fullscreenButton.click();
      }}
    }});
  </script>
</body>
</html>
"""

    def _open_browser(self, url: str) -> None:
        try:
            self._browser_opener(url)
        except Exception as exc:
            logger.warning("Godot browser auto-open failed: %s", exc)

    def _wait_for_http(self, url: str) -> None:
        deadline = time() + self.config.pixel_start_timeout
        while time() < deadline:
            if _http_reachable(url, 1.0):
                return
            import time as _time
            _time.sleep(0.5)
        raise TimeoutError(
            f"Timed out waiting for Godot Web export: {url}"
        )

    def _refresh_process_state(self) -> None:
        for session in self._sessions.values():
            if (
                session.http_process is not None
                and session.http_process.poll() is not None
                and session.state not in {"DESTROYED", "ERROR"}
            ):
                session.state = "ERROR"
                session.error = (
                    f"Godot Web HTTP server exited with code "
                    f"{session.http_process.returncode}"
                )

    def _require_session(self, session_id: str) -> GodotBrowserSession:
        try:
            return self._sessions[str(session_id)]
        except KeyError as exc:
            raise KeyError(f"Unknown browser session: {session_id}") from exc

    def _first_session(self) -> GodotBrowserSession | None:
        return next(iter(self._sessions.values()), None)

    def _artifact_reference(
        self,
        reference: str,
        asset_type: str,
        *,
        required: bool = True,
    ) -> str:
        value = str(reference or "").strip()
        if not value:
            if required:
                raise ValueError(f"{asset_type} asset is required")
            return ""
        for asset in self.list_assets(asset_type):
            if value in {
                str(asset.get("artifact_id") or ""),
                str((asset.get("native") or {}).get("path") or ""),
            }:
                return str(asset.get("artifact_id") or value)
        if required:
            raise KeyError(f"Unknown {asset_type} asset: {value}")
        return ""

    @staticmethod
    def _world_scene_path(world: Mapping[str, Any]) -> str:
        manifest = dict(world.get("manifest") or {})
        engine_data = dict(manifest.get("godot") or {})
        if engine_data.get("scene_path"):
            return str(engine_data["scene_path"])
        world_data = dict(manifest.get("world") or {})
        metadata = dict(world_data.get("metadata") or {})
        return str(
            metadata.get("scene_path")
            or world_data.get("scene_path")
            or ""
        )

    @staticmethod
    def _translate_godot_result(
        operation: str,
        result: Mapping[str, Any],
        *,
        asset_type: str = "",
    ) -> dict[str, Any]:
        value = dict(result)
        godot_payload = dict(value.get("payload") or {})
        artifacts = [
            _normalize_asset(item, asset_type=asset_type)
            for item in value.get("artifacts") or []
            if isinstance(item, Mapping)
        ]
        return serving_result(
            operation,
            engine="godot",
            ok=bool(value.get("ok", False)),
            payload={
                "godot_operation": value.get("operation", ""),
                "godot_payload": godot_payload,
                **godot_payload,
            },
            artifacts=artifacts,
            warnings=[
                str(item)
                for item in value.get("warnings") or []
            ],
            errors=_errors(value),
        )


def create_godot_example_backend(
    config: BrowserServingConfig | None = None,
) -> GodotExampleBackend:
    return GodotExampleBackend(
        config or BrowserServingConfig.from_environment()
    )
