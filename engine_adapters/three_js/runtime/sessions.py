"""Stable generic runtime session operations for ThreeClient v1."""

from typing import Any

from ..assets import ThreeAssetsClient
from ..contracts import ThreeOperationResult
from ._internal import (
    RuntimeInputState,
    RuntimeSessionService,
)


class ThreeRuntimeSessionsClient:
    def __init__(
        self,
        assets: ThreeAssetsClient,
        *,
        bridge: Any = None,
        default_world_id: str = "world_001",
    ) -> None:
        self._assets = assets
        self._service = RuntimeSessionService(
            bridge=bridge,
            default_world_id=default_world_id,
        )

    def join(
        self,
        *,
        world_id: str = "",
        participant_id: str = "",
        user_id: str = "",
        avatar_artifact_id: str = "",
        idle_motion_artifact_id: str = "",
        move_motion_artifact_id: str = "",
        controller_kind: str = "human",
        control_mode: str = "exclusive",
        priority: int = 0,
        transform: dict[str, Any] | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            avatar_url = self._artifact_url(
                avatar_artifact_id,
                expected_types={"avatar", "prop"},
            )
            idle_url = self._artifact_url(
                idle_motion_artifact_id,
                expected_types={"motion"},
            )
            move_url = self._artifact_url(
                move_motion_artifact_id,
                expected_types={"motion"},
            )
            payload = self._service.join(
                world_id=world_id or None,
                participant_id=participant_id,
                user_id=user_id,
                avatar_url=avatar_url,
                idle_animation=idle_url,
                move_animation=move_url,
                controller_kind=controller_kind,
                control_mode=control_mode,
                priority=priority,
                transform=transform,
                parameters=parameters,
            )
        except Exception as exc:
            return ThreeOperationResult.failure(
                "runtime.sessions.join",
                f"{type(exc).__name__}: {exc}",
            ).to_dict()
        return ThreeOperationResult.success(
            "runtime.sessions.join",
            payload={
                **payload,
                "avatar_artifact_id": avatar_artifact_id,
                "idle_motion_artifact_id": (
                    idle_motion_artifact_id
                ),
                "move_motion_artifact_id": (
                    move_motion_artifact_id
                ),
            },
        ).to_dict()

    def leave(
        self,
        *,
        participant_id: str = "",
        controller_id: str = "",
    ) -> dict[str, Any]:
        return self._call(
            "runtime.sessions.leave",
            self._service.leave,
            participant_id=participant_id,
            controller_id=controller_id,
        )

    def heartbeat(
        self,
        controller_id: str,
    ) -> dict[str, Any]:
        return self._call(
            "runtime.sessions.heartbeat",
            self._service.heartbeat,
            controller_id=controller_id,
        )

    def apply_input(
        self,
        controller_id: str,
        *,
        move_x: float = 0.0,
        move_y: float = 0.0,
        run: bool = False,
        jump: bool = False,
        yaw: float = 0.0,
        pitch: float = 0.0,
        seq: int = 0,
    ) -> dict[str, Any]:
        try:
            payload = self._service.apply_input(
                RuntimeInputState(
                    controller_id=controller_id,
                    move_x=move_x,
                    move_y=move_y,
                    run=run,
                    jump=jump,
                    yaw=yaw,
                    pitch=pitch,
                    seq=seq,
                )
            )
        except Exception as exc:
            return ThreeOperationResult.failure(
                "runtime.sessions.apply_input",
                f"{type(exc).__name__}: {exc}",
            ).to_dict()
        return ThreeOperationResult.success(
            "runtime.sessions.apply_input",
            payload=payload,
        ).to_dict()

    def snapshot(
        self,
        *,
        world_id: str = "",
    ) -> dict[str, Any]:
        return self._call(
            "runtime.sessions.snapshot",
            self._service.world_snapshot,
            world_id=world_id or None,
        )

    def reset_world(
        self,
        *,
        world_id: str = "",
    ) -> dict[str, Any]:
        return self._call(
            "runtime.sessions.reset_world",
            self._service.reset_world,
            world_id=world_id or None,
        )

    def clear_entity(
        self,
        *,
        participant_id: str = "",
        controller_id: str = "",
        entity_id: str = "",
        destroy_object: bool = True,
    ) -> dict[str, Any]:
        return self._call(
            "runtime.sessions.clear_entity",
            self._service.clear_entity,
            participant_id=participant_id,
            controller_id=controller_id,
            entity_id=entity_id,
            destroy_object=destroy_object,
        )

    def _artifact_url(
        self,
        artifact_id: str,
        *,
        expected_types: set[str],
    ) -> str:
        if not str(artifact_id or "").strip():
            return ""
        record = self._assets._service.artifacts.get(artifact_id)
        if record is None:
            raise ValueError(
                f"Unknown artifact_id: {artifact_id}"
            )
        if record.type not in expected_types:
            expected = ", ".join(sorted(expected_types))
            raise ValueError(
                f"Artifact {artifact_id} has type {record.type!r}; "
                f"expected: {expected}"
            )
        if record.backend != "web" or not record.backend_path:
            raise ValueError(
                f"Artifact {artifact_id} is not a resolved web asset"
            )
        return record.backend_path

    @staticmethod
    def _call(
        operation: str,
        function: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        try:
            payload = function(**kwargs)
        except Exception as exc:
            return ThreeOperationResult.failure(
                operation,
                f"{type(exc).__name__}: {exc}",
            ).to_dict()
        return ThreeOperationResult.success(
            operation,
            payload=payload,
        ).to_dict()
