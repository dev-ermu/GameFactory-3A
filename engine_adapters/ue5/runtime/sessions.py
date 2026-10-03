"""Stable generic runtime session operations for UEClient v1."""

from typing import Any

from ..assets import UEAssetsClient
from ..contracts import UEOperationResult
from ._internal import (
    RuntimeInputState,
    RuntimeSessionService,
)


class UERuntimeSessionsClient:
    def __init__(
        self,
        assets: UEAssetsClient,
        *,
        bridge: Any = None,
        input_host: str = "",
        input_port: int = 0,
    ) -> None:
        self._assets = assets
        self._input_host = input_host
        self._input_port = int(input_port or 0)
        self._service = RuntimeSessionService(
            ue_bridge=bridge,
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
        transform: dict[str, Any] | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            avatar_path = self._artifact_path(
                avatar_artifact_id,
                expected_types={"avatar"},
            )
            idle_path = self._artifact_path(
                idle_motion_artifact_id,
                expected_types={"motion"},
            )
            move_path = self._artifact_path(
                move_motion_artifact_id,
                expected_types={"motion"},
            )
            payload = self._service.join(
                world_id=world_id or None,
                participant_id=participant_id,
                user_id=user_id,
                avatar_asset_path=avatar_path,
                idle_animation_path=idle_path,
                move_animation_path=move_path,
                controller_kind=controller_kind,
                ue_input_host=self._input_host,
                ue_input_port=self._input_port,
                transform=transform,
                parameters=parameters,
            )
        except Exception as exc:
            return UEOperationResult.failure(
                "runtime.sessions.join",
                f"{type(exc).__name__}: {exc}",
            ).to_dict()
        return UEOperationResult.success(
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
                    world_id="",
                    participant_id="",
                    controller_id=controller_id,
                    entity_id="",
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
            return UEOperationResult.failure(
                "runtime.sessions.apply_input",
                f"{type(exc).__name__}: {exc}",
            ).to_dict()
        return UEOperationResult.success(
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
        destroy_actor: bool = True,
    ) -> dict[str, Any]:
        return self._call(
            "runtime.sessions.clear_entity",
            self._service.clear_entity,
            participant_id=participant_id,
            controller_id=controller_id,
            entity_id=entity_id,
            destroy_actor=destroy_actor,
        )

    def _artifact_path(
        self,
        artifact_id: str,
        *,
        expected_types: set[str],
    ) -> str:
        if not str(artifact_id or "").strip():
            return ""
        record = self._assets._service.artifacts.get(
            artifact_id
        )
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
        if record.backend != "ue" or not record.backend_path:
            raise ValueError(
                f"Artifact {artifact_id} is not a resolved UE asset"
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
            return UEOperationResult.failure(
                operation,
                f"{type(exc).__name__}: {exc}",
            ).to_dict()
        return UEOperationResult.success(
            operation,
            payload=payload,
        ).to_dict()
