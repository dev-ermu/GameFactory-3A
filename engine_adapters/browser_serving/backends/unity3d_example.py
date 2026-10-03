"""Unity3D example backend implemented only through public UnityClient."""

import socket
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from time import time
from typing import Any, Callable, Mapping
from uuid import uuid4

from engine_adapters.unity3d import UnityClient

from ..config import BrowserServingConfig
from ..contracts import (
    AssetImportRequest,
    AssetRecord,
    EngineCapabilities,
    EngineDescriptor,
    WorldRecord,
    serving_result,
)


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
        engine="unity3d",
        state=str(value.get("state") or "ready"),
        capabilities={
            str(key): bool(item)
            for key, item in dict(
                value.get("runtime_capabilities") or {}
            ).items()
        },
        native={
            "backend": "unity",
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
        engine="unity3d",
        state=str(
            package.get("status")
            or value.get("state")
            or "published"
        ),
        manifest=dict(package.get("manifest") or {}),
    ).to_dict()


@dataclass
class Unity3DBrowserSession:
    session_id: str
    participant_id: str
    user_id: str
    state: str
    input_port: int
    webgl_port: int
    stream_url: str
    unity_input_host: str
    preview_scene: str
    client: Any = field(repr=False)
    character: dict[str, Any] = field(default_factory=dict)
    controller_id: str = ""
    entity_id: str = ""
    world_id: str = ""
    project_id: str = ""
    runtime_package_id: str = ""
    world_scene_path: str = ""
    unity_client_pid: int = 0
    webgl_pid: int = 0
    webgl_process: subprocess.Popen | None = field(
        default=None,
        repr=False,
    )
    created_at: float = field(default_factory=time)
    updated_at: float = field(default_factory=time)
    error: str = ""
    last_command: str = ""
    recovered_external: bool = False
    # Unity WebGL is a browser-native player. It has no UDP socket and no
    # native framebuffer stream, so browser input is delivered to the iframe
    # canvas rather than to the Editor UDP bridge.
    runtime_kind: str = "unity_webgl"
    input_transport: str = "browser_canvas"
    last_input: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "participant_id": self.participant_id,
            "user_id": self.user_id,
            "state": self.state,
            "input_port": self.input_port,
            "unity_input_host": self.unity_input_host,
            "unity_input_port": self.input_port,
            "webgl_port": self.webgl_port,
            "stream_url": self.stream_url,
            # Kept as an empty compatibility field. Unity WebGL is not UE
            # Pixel Streaming and does not expose a WebRTC pixel endpoint.
            "pixel_streaming_url": "",
            "streaming_transport": "unity_webgl_http",
            "preview_scene": self.preview_scene,
            "character": dict(self.character),
            "controller_id": self.controller_id,
            "entity_id": self.entity_id,
            "world_id": self.world_id,
            "project_id": self.project_id,
            "runtime_package_id": self.runtime_package_id,
            "world_scene_path": self.world_scene_path,
            "unity_client_pid": self.unity_client_pid,
            "webgl_pid": self.webgl_pid,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
            "last_command": self.last_command,
            "recovered_external": self.recovered_external,
            "runtime_kind": self.runtime_kind,
            "input_transport": self.input_transport,
            "last_input": dict(self.last_input),
        }


class Unity3DExampleBackend:
    """Unity3D browser serving backend."""

    def __init__(
        self,
        config: BrowserServingConfig,
        *,
        client_factory: Callable[..., Any] = UnityClient,
    ) -> None:
        self.config = config
        self._client_factory = client_factory
        self._sessions: dict[str, Unity3DBrowserSession] = {}
        self._lock = RLock()
        self._descriptor = EngineDescriptor(
            engine_id="unity3d",
            display_name="Unity3D Example",
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
                # Unity's supported browser path is a WebGL player served by
                # HTTP. It is not UE Pixel Streaming/WebRTC.
                pixel_streaming=False,
                preview_camera=True,
            ),
        )
        self._admin_client = self._new_client(
            runtime_port=config.base_runtime_port,
        )

    @property
    def descriptor(self) -> EngineDescriptor:
        return self._descriptor

    def _new_client(self, *, runtime_port: int):
        return self._client_factory(
            project_path=self.config.unity_project,
            unity_root=self.config.unity_root,
            host=self.config.unity_host,
            port=self.config.unity_port,
            runtime_host=self.config.runtime_host,
            runtime_port=runtime_port,
        )

    def status(self) -> dict[str, Any]:
        environment = self._admin_client.get_environment_info()
        configured = (
            self.config.unity_project is not None
            and self.config.unity_root is not None
        )
        return serving_result(
            "engine.status",
            engine="unity3d",
            ok=configured,
            payload={
                "configured": configured,
                "environment": environment,
                "message": (
                    "Unity3D backend configured"
                    if configured
                    else "Set A3GAME_UNITY_PROJECT and A3GAME_UNITY_ROOT"
                ),
            },
            warnings=[] if configured else [
                "Unity3D example backend is not configured"
            ],
        )

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
            result = self._admin_client.assets.import_motion(
                source,
                skeleton=skeleton,
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
        return self._translate_unity_result(
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
        translated = self._translate_unity_result(
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
        return self._translate_unity_result(
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
            root=root_uri or "Assets/Imported",
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

    def create_session(
        self,
        request: Mapping[str, Any],
    ) -> dict[str, Any]:
        session_id = f"bs_{uuid4().hex[:10]}"
        user_id = str(request.get("user_id") or "")
        participant_id = str(
            request.get("participant_id")
            or f"participant_{user_id or session_id}"
        )
        with self._lock:
            slot, input_port, webgl_port = self._allocate_session_ports()
            stream_url = (
                f"http://{self.config.pixel_host}:{webgl_port}/index.html"
            )
            client = self._new_client(
                runtime_port=input_port,
            )
            session = Unity3DBrowserSession(
                session_id=session_id,
                participant_id=participant_id,
                user_id=user_id,
                state="CREATED",
                input_port=input_port,
                webgl_port=webgl_port,
                stream_url=stream_url,
                unity_input_host=self.config.runtime_host,
                preview_scene=self.config.preview_map,
                client=client,
                character=dict(request.get("character") or {}),
            )
            self._sessions[session_id] = session
        try:
            session.state = "BOOTING_WEBGL"
            if not self.config.dry_run:
                build = self._ensure_webgl_build(client)
                if not build.get("ok"):
                    raise RuntimeError(
                        "; ".join(_errors(build))
                        or "Unity WebGL build failed"
                    )
                webgl_root = Path(str(_payload(build).get("output_path") or ""))
                session.webgl_process = self._start_webgl_server(
                    webgl_root,
                    session.webgl_port,
                )
                session.webgl_pid = session.webgl_process.pid
            # The WebGL player is the runtime. There is intentionally no
            # second Editor/Player process to launch for this browser session.
            session.state = "IN_WORLD"
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
            engine="unity3d",
            payload={"slot": slot, **session.to_dict()},
        )

    def _ensure_webgl_build(self, client: Any) -> dict[str, Any]:
        output = self.config.unity_webgl_build or (
            self.config.unity_project / "Builds" / "WebGL"
            if self.config.unity_project is not None
            else None
        )
        if output is None:
            return {"ok": False, "errors": [
                "A3GAME_UNITY_WEBGL_BUILD or A3GAME_UNITY_PROJECT is required"
            ]}
        output = output.expanduser().resolve(strict=False)
        if (output / "index.html").is_file():
            return {"ok": True, "payload": {"output_path": str(output), "reused": True}}
        return client.build.project(
            target="WebGL",
            output_path=str(output),
            clean=False,
        )

    def _start_webgl_server(self, root: Path, port: int) -> subprocess.Popen[Any]:
        if not root.is_dir() or not (root / "index.html").is_file():
            raise FileNotFoundError(
                f"Unity WebGL build directory is missing index.html: {root}"
            )
        if not _is_tcp_port_free(self.config.pixel_host, port):
            raise OSError(
                f"Unity WebGL port is already in use: {self.config.pixel_host}:{port}"
            )
        return subprocess.Popen(
            [sys.executable, "-m", "http.server", str(port), "--bind", self.config.pixel_host],
            cwd=str(root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def _allocate_session_ports(self) -> tuple[int, int, int]:
        used_webgl_ports = {
            session.webgl_port for session in self._sessions.values()
        }
        used_input_ports = {
            session.input_port for session in self._sessions.values()
        }
        for slot in range(self.config.max_sessions):
            input_port = self.config.base_runtime_port + slot
            webgl_port = (
                self.config.base_pixel_http_port
                + slot * self.config.session_port_stride
            )
            if webgl_port in used_webgl_ports or input_port in used_input_ports:
                continue
            if self.config.dry_run or (
                _is_tcp_port_free(self.config.pixel_host, webgl_port)
                and _is_udp_port_free(self.config.runtime_host, input_port)
            ):
                return slot, input_port, webgl_port
        raise RuntimeError("No free Unity browser serving session ports")

    def list_sessions(self) -> dict[str, Any]:
        return serving_result(
            "sessions.list",
            engine="unity3d",
            payload={
                "sessions": [
                    item.to_dict()
                    for item in self._sessions.values()
                ]
            },
        )

    def get_session(self, session_id: str) -> dict[str, Any]:
        session = self._require_session(session_id)
        return serving_result(
            "sessions.get",
            engine="unity3d",
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
        stream_url = str(
            snapshot.get("stream_url")
            or snapshot.get("pixel_streaming_url")
            or ""
        )
        input_port = int(
            snapshot.get("input_port")
            or snapshot.get("unity_input_port")
            or 0
        )
        session = Unity3DBrowserSession(
            session_id=session_id,
            participant_id=str(
                snapshot.get("participant_id")
                or f"participant_{session_id}"
            ),
            user_id=str(snapshot.get("user_id") or ""),
            state=str(snapshot.get("state") or "PREVIEW_READY"),
            input_port=input_port,
            webgl_port=int(snapshot.get("webgl_port") or 0),
            stream_url=stream_url,
            unity_input_host=str(
                snapshot.get("unity_input_host")
                or self.config.runtime_host
            ),
            preview_scene=str(
                snapshot.get("preview_scene")
                or self.config.preview_map
            ),
            client=self._new_client(
                runtime_port=input_port,
            ),
            character=dict(snapshot.get("character") or {}),
            controller_id=str(snapshot.get("controller_id") or ""),
            entity_id=str(snapshot.get("entity_id") or ""),
            world_id=str(snapshot.get("world_id") or ""),
            project_id=str(snapshot.get("project_id") or ""),
            runtime_package_id=str(
                snapshot.get("runtime_package_id") or ""
            ),
            unity_client_pid=int(snapshot.get("unity_client_pid") or 0),
            recovered_external=True,
        )
        self._sessions[session_id] = session
        return serving_result(
            "sessions.recover",
            engine="unity3d",
            payload={"recovered": True, **session.to_dict()},
        )

    def session_catalog(
        self,
        *,
        project_id: str = "",
    ) -> dict[str, Any]:
        return serving_result(
            "sessions.catalog",
            engine="unity3d",
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
        # A WebGL build cannot receive the adapter's native UDP datagrams.
        # The generated game owns its local Unity Input API and receives
        # keyboard/mouse events directly from the iframe canvas. Keep the
        # session metadata here without creating a misleading UDP binding.
        result = {
            "ok": True,
            "operation": "runtime.sessions.join",
            "payload": {
                "world_id": session.world_id,
                "participant_id": session.participant_id,
                "controller_id": f"webgl_ctrl_{session.session_id}",
                "entity_id": f"webgl_entity_{session.session_id}",
                "view_mode": "browser_canvas",
                "unity_bridge": {
                    "enabled": False,
                    "status": "browser_canvas",
                },
            },
        }
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
            engine="unity3d",
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
        session.updated_at = time()
        session.last_command = "load_world"
        return serving_result(
            "sessions.load_world",
            engine="unity3d",
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
            engine="unity3d",
            payload={
                "joined": True,
                "server_url": "",
                **session.to_dict(),
            },
        )

    def leave_world(self, session_id: str) -> dict[str, Any]:
        session = self._require_session(session_id)
        runtime = {}
        if session.controller_id and session.runtime_kind != "unity_webgl":
            runtime = session.client.runtime.sessions.leave(
                participant_id=session.participant_id,
                controller_id=session.controller_id,
            )
        session.state = "PREVIEW_READY"
        session.updated_at = time()
        session.last_command = "leave_world"
        return serving_result(
            "sessions.leave_world",
            engine="unity3d",
            payload={"runtime": runtime, **session.to_dict()},
        )

    def apply_input(
        self,
        session_id: str,
        input_state: Mapping[str, Any],
    ) -> dict[str, Any]:
        session = self._require_session(session_id)
        if session.runtime_kind == "unity_webgl":
            session.last_input = dict(input_state)
            session.last_command = "apply_input"
            session.updated_at = time()
            return serving_result(
                "sessions.apply_input",
                engine="unity3d",
                payload={
                    "accepted": True,
                    "recorded": True,
                    "applied": False,
                    "delivery": "native iframe input is handled by the Unity canvas",
                    "input_transport": session.input_transport,
                    **session.to_dict(),
                },
            )
        if not session.controller_id:
            return serving_result(
                "sessions.apply_input",
                engine="unity3d",
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
        session.last_command = "apply_input"
        session.updated_at = time()
        translated = self._translate_unity_result(
            "sessions.apply_input",
            result,
        )
        translated["payload"].update(session.to_dict())
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
            engine="unity3d",
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
        if session.controller_id and session.runtime_kind != "unity_webgl":
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
            engine="unity3d",
            payload={
                "removed": True,
                "session": snapshot,
                **snapshot,
            },
        )

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
                engine="unity3d",
                payload={
                    "stream_url": (
                        session.stream_url
                        if session is not None
                        else ""
                    ),
                    "default_actor_label": "A3Game_BrowserPreview",
                    "playable_actor_label": "A3Game_BrowserPlayer",
                    "default_walk_speed": 5.0,
                    "default_run_speed": 10.0,
                    "movement_step": 0.5,
                    "rotation_step": 15.0,
                    "viewer_host": self.config.gateway_host,
                    "viewer_port": self.config.gateway_port,
                    "runtime_unity_port": (
                        session.input_port
                        if session is not None
                        else self.config.base_runtime_port
                    ),
                    "runtime_unity_host": self.config.runtime_host,
                    "runtime_udp_mode": "unityclient",
                    "streaming_transport": "unity_webgl_http",
                },
            )
        if normalized == "pixel_status":
            url = (
                session.stream_url
                if session is not None
                else ""
            )
            reachable = False
            if url:
                try:
                    with urllib.request.urlopen(url, timeout=2.0) as response:
                        reachable = int(response.status) < 500
                except (urllib.error.URLError, TimeoutError, OSError):
                    reachable = False
            return serving_result(
                "debug.pixel_status",
                engine="unity3d",
                payload={
                    "reachable": reachable,
                    "stream_ready": reachable,
                    "url": url,
                    "message": (
                        "reachable" if reachable else "no active Unity3D WebGL page"
                    ),
                    "transport": "unity_webgl_http",
                },
            )
        if normalized == "runtime_world_state":
            result = self._admin_client.runtime.sessions.snapshot(
                world_id=str(data.get("world_id") or "")
            )
            return self._translate_unity_result(
                "debug.runtime_world_state",
                result,
            )
        return serving_result(
            f"debug.{normalized or 'unknown'}",
            engine="unity3d",
            ok=False,
            errors=[f"Unsupported Unity3D debug operation: {operation}"],
        )

    def _launch_runtime(
        self,
        session: Unity3DBrowserSession,
        scene_path: str,
    ) -> dict[str, Any]:
        if self.config.dry_run:
            return {
                "ok": True,
                "operation": "runtime.launch_editor",
                "artifacts": [],
                "warnings": [],
                "errors": [],
                "payload": {
                    "process_id": 0,
                    "scene_path": scene_path,
                    "dry_run": True,
                },
            }
        return session.client.runtime.launch_editor(
            scene_path=scene_path,
            dry_run=self.config.dry_run,
        )

    def _stop_session_processes(
        self,
        session: Unity3DBrowserSession,
    ) -> None:
        if session.unity_client_pid and not session.recovered_external:
            session.client.runtime.stop_editor(session.unity_client_pid)
        process = session.webgl_process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def _require_session(self, session_id: str) -> Unity3DBrowserSession:
        try:
            return self._sessions[str(session_id)]
        except KeyError as exc:
            raise KeyError(f"Unknown browser session: {session_id}") from exc

    def _first_session(self) -> Unity3DBrowserSession | None:
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
    def _translate_unity_result(
        operation: str,
        result: Mapping[str, Any],
        *,
        asset_type: str = "",
    ) -> dict[str, Any]:
        value = dict(result)
        unity_payload = dict(value.get("payload") or {})
        artifacts = [
            _normalize_asset(item, asset_type=asset_type)
            for item in value.get("artifacts") or []
            if isinstance(item, Mapping)
        ]
        return serving_result(
            operation,
            engine="unity3d",
            ok=bool(value.get("ok", False)),
            payload={
                "unity_operation": value.get("operation", ""),
                "unity_payload": unity_payload,
                **unity_payload,
            },
            artifacts=artifacts,
            warnings=[
                str(item)
                for item in value.get("warnings") or []
            ],
            errors=_errors(value),
        )


def create_unity3d_example_backend(
    config: BrowserServingConfig | None = None,
) -> Unity3DExampleBackend:
    return Unity3DExampleBackend(
        config or BrowserServingConfig.from_environment()
    )
