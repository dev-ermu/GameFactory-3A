"""Stable asset operations for ThreeClient v1."""

from pathlib import Path
from typing import Any, Mapping

from ..config import DEFAULT_IMPORT_ROOT, ThreeClientConfig
from ..contracts import ThreeOperationResult
from ._internal import (
    ArtifactRegistry,
    AssetService,
    GeneratedAssetSourceResolver,
    ResolvedAssetSource,
)
from ._internal.inspectors import inspect_source
from ._internal.orientation import (
    RUNTIME_FORWARD_AXIS,
    RUNTIME_UP_AXIS,
    ORIENTATION_OPTION_KEYS,
    OrientationError,
    analyze_geometry,
    summarize,
)


class ThreeAssetsClient:
    def __init__(self, config: ThreeClientConfig) -> None:
        self._config = config
        self._sources = GeneratedAssetSourceResolver()
        self._service = AssetService(
            config,
            artifact_registry=ArtifactRegistry(
                config.artifact_registry_path
            ),
        )

    def import_asset(
        self,
        source: Mapping[str, Any],
        asset_type: str,
        *,
        destination: str = "",
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        allow_directory = str(asset_type or "").strip().lower() in {
            "scene",
            "effect",
            "environment",
        }
        try:
            resolved = self._resolve_source(
                source,
                asset_type,
                allow_directory=allow_directory,
            )
        except Exception as exc:
            return self._source_failure(
                "assets.import_asset",
                source,
                exc,
            )
        try:
            payload = self._service.import_asset(
                str(resolved.path),
                asset_type,
                dst_path=destination,
                **dict(options or {}),
            )
        except Exception as exc:
            return ThreeOperationResult.failure(
                "assets.import_asset",
                f"{type(exc).__name__}: {exc}",
                payload={
                    "asset_type": asset_type,
                    "source": resolved.descriptor(),
                },
            ).to_dict()
        result = self._import_result(
            "assets.import_asset",
            payload,
        )
        result["payload"]["source"] = resolved.descriptor()
        return result

    def import_avatar(
        self,
        source: Mapping[str, Any],
        *,
        destination: str = "",
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = self.import_asset(
            source,
            "avatar",
            destination=destination,
            options=options,
        )
        result["operation"] = "assets.import_avatar"
        return result

    def import_motion(
        self,
        source: Mapping[str, Any],
        *,
        skeleton: str = "",
        destination: str = "",
        avatar_name: str = "",
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        resolved_options = dict(options or {})
        if skeleton:
            resolved_options["skeleton_artifact_id"] = skeleton
        if avatar_name:
            resolved_options["avatar_name"] = avatar_name
        result = self.import_asset(
            source,
            "motion",
            destination=destination,
            options=resolved_options,
        )
        result["operation"] = "assets.import_motion"
        return result

    def import_scene(
        self,
        source: Mapping[str, Any],
        *,
        destination: str = "",
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = self.import_asset(
            source,
            "scene",
            destination=destination,
            options=options,
        )
        result["operation"] = "assets.import_scene"
        return result

    def import_prop(
        self,
        source: Mapping[str, Any],
        *,
        destination: str = "",
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = self.import_asset(
            source,
            "prop",
            destination=destination,
            options=options,
        )
        result["operation"] = "assets.import_prop"
        return result

    def import_weapon(
        self,
        source: Mapping[str, Any],
        *,
        destination: str = "",
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = self.import_asset(
            source,
            "weapon",
            destination=destination,
            options=options,
        )
        result["operation"] = "assets.import_weapon"
        return result

    def import_material(
        self,
        source: Mapping[str, Any],
        *,
        destination: str = "",
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = self.import_asset(
            source,
            "material",
            destination=destination,
            options=options,
        )
        result["operation"] = "assets.import_material"
        return result

    def import_texture(
        self,
        source: Mapping[str, Any],
        *,
        destination: str = "",
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = self.import_asset(
            source,
            "texture",
            destination=destination,
            options=options,
        )
        result["operation"] = "assets.import_texture"
        return result

    def import_effect(
        self,
        source: Mapping[str, Any],
        *,
        destination: str = "",
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = self.import_asset(
            source,
            "effect",
            destination=destination,
            options=options,
        )
        result["operation"] = "assets.import_effect"
        return result

    def import_audio(
        self,
        source: Mapping[str, Any],
        *,
        destination: str = "",
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = self.import_asset(
            source,
            "audio",
            destination=destination,
            options=options,
        )
        result["operation"] = "assets.import_audio"
        return result

    def validate(
        self,
        source: Mapping[str, Any],
        asset_type: str,
        *,
        destination: str = "",
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        allow_directory = str(asset_type or "").strip().lower() in {
            "scene",
            "effect",
            "environment",
        }
        try:
            resolved = self._resolve_source(
                source,
                asset_type,
                allow_directory=allow_directory,
            )
        except Exception as exc:
            return self._source_failure(
                "assets.validate",
                source,
                exc,
            )
        try:
            validation = self._service.validate_asset(
                str(resolved.path),
                asset_type,
                dst_path=destination,
                **dict(options or {}),
            )
        except Exception as exc:
            return ThreeOperationResult.failure(
                "assets.validate",
                f"{type(exc).__name__}: {exc}",
                payload={
                    "asset_type": asset_type,
                    "source": resolved.descriptor(),
                },
            ).to_dict()
        return ThreeOperationResult(
            operation="assets.validate",
            ok=validation.ok,
            warnings=tuple(validation.warnings),
            errors=tuple(validation.errors),
            payload={
                **dict(validation.payload),
                "asset_type": asset_type,
                "source": resolved.descriptor(),
            },
        ).to_dict()

    def resolve_source(
        self,
        source: Mapping[str, Any],
        *,
        asset_type: str = "",
    ) -> dict[str, Any]:
        try:
            resolved = self._resolve_source(
                source,
                asset_type,
                allow_directory=(
                    str(asset_type or "").strip().lower() == "scene"
                    or str(source.get("task_kind") or "").strip()
                    == "3d_scene"
                ),
            )
        except Exception as exc:
            return self._source_failure(
                "assets.resolve_source",
                source,
                exc,
            )
        return ThreeOperationResult.success(
            "assets.resolve_source",
            payload={
                "source": resolved.descriptor(),
                "path": str(resolved.path),
                "meta_path": str(resolved.meta_path),
                "metadata": dict(resolved.metadata),
            },
        ).to_dict()

    def list(
        self,
        asset_type: str = "",
        *,
        root: str = DEFAULT_IMPORT_ROOT,
    ) -> dict[str, Any]:
        try:
            assets = self._service.list_assets(
                asset_type=asset_type or None,
                root_path=root,
            )
        except Exception as exc:
            return ThreeOperationResult.failure(
                "assets.list",
                f"{type(exc).__name__}: {exc}",
                payload={
                    "asset_type": asset_type,
                    "root": root,
                },
            ).to_dict()
        return ThreeOperationResult.success(
            "assets.list",
            artifacts=[
                self._query_artifact(asset)
                for asset in assets
            ],
            payload={
                "asset_type": asset_type,
                "root": root,
                "count": len(assets),
            },
        ).to_dict()

    def list_registered(
        self,
        asset_type: str = "",
    ) -> dict[str, Any]:
        records = self._service.artifacts.list(
            type=asset_type or None,
        )
        return ThreeOperationResult.success(
            "assets.list_registered",
            artifacts=[
                record.to_dict()
                for record in records
            ],
            payload={
                "asset_type": asset_type,
                "count": len(records),
                "registry_path": str(
                    self._config.artifact_registry_path
                ),
            },
        ).to_dict()

    def get_metadata(
        self,
        artifact_id: str,
    ) -> dict[str, Any]:
        record = self._service.artifacts.get(artifact_id)
        if record is None:
            return ThreeOperationResult.failure(
                "assets.get_metadata",
                f"Unknown artifact_id: {artifact_id}",
            ).to_dict()
        return ThreeOperationResult.success(
            "assets.get_metadata",
            artifacts=[record.to_dict()],
        ).to_dict()

    # ── Orientation ──────────────────────────────────────────────────────
    #
    # glTF records which way is up and nothing about which way is front.
    # These three operations make the missing fact explicit: analyze it,
    # record it, read it back. The runtime applies whatever is recorded
    # and leaves an unrecorded model untouched, so annotating an asset can
    # never make an already-correct game worse.

    def set_orientation(
        self,
        reference: str,
        *,
        forward_axis: str = "",
        up_axis: str = "",
        yaw_offset_degrees: float | None = None,
        pitch_offset_degrees: float | None = None,
        roll_offset_degrees: float | None = None,
        scale_hint_metres: float | None = None,
        pivot: str = "",
        verified_by: str = "",
        notes: str = "",
    ) -> dict[str, Any]:
        """Record which way a staged model faces.

        ``forward_axis`` names the axis the model *currently* faces in its
        own space; the runtime derives the yaw that turns it to face the
        runtime forward axis, so a caller never computes an angle.
        ``yaw_offset_degrees`` remains available for the models that face
        no cardinal axis at all.

        Set ``verified_by='agent_vision'`` when the answer came from
        looking at rendered views, so a later pass can tell a checked
        asset from a guessed one.
        """

        operation = "assets.set_orientation"
        artifact_id = self._resolve_artifact_id(reference)
        if artifact_id is None:
            return ThreeOperationResult.failure(
                operation,
                f"Unknown asset reference: {reference}",
            ).to_dict()
        updates = {
            "forward_axis": forward_axis,
            "up_axis": up_axis,
            "yaw_offset_degrees": yaw_offset_degrees,
            "pitch_offset_degrees": pitch_offset_degrees,
            "roll_offset_degrees": roll_offset_degrees,
            "scale_hint_metres": scale_hint_metres,
            "pivot": pivot,
            "verified_by": verified_by,
            "notes": notes,
        }
        updates = {
            key: value
            for key, value in updates.items()
            if value not in (None, "")
        }
        if not updates:
            return ThreeOperationResult.failure(
                operation,
                "Nothing to record; pass at least one of "
                f"{list(ORIENTATION_OPTION_KEYS)}",
            ).to_dict()
        try:
            payload = self._service.set_orientation(artifact_id, updates)
        except OrientationError as exc:
            return ThreeOperationResult.failure(
                operation,
                str(exc),
                payload={"reference": reference},
            ).to_dict()
        except Exception as exc:
            return ThreeOperationResult.failure(
                operation,
                f"{type(exc).__name__}: {exc}",
                payload={"reference": reference},
            ).to_dict()
        record = self._service.artifacts.get(artifact_id)
        return ThreeOperationResult.success(
            operation,
            artifacts=[record.to_dict()] if record else [],
            payload={
                **payload,
                "reference": reference,
                "summary": summarize(payload.get("orientation")),
            },
        ).to_dict()

    def get_orientation(self, reference: str) -> dict[str, Any]:
        """Read the recorded orientation of one staged artifact."""

        operation = "assets.get_orientation"
        artifact_id = self._resolve_artifact_id(reference)
        if artifact_id is None:
            return ThreeOperationResult.failure(
                operation,
                f"Unknown asset reference: {reference}",
            ).to_dict()
        payload = self._service.get_orientation(artifact_id)
        return ThreeOperationResult.success(
            operation,
            payload={
                **payload,
                "reference": reference,
                "summary": summarize(payload.get("orientation")),
            },
        ).to_dict()

    def analyze_orientation(
        self,
        reference: str | Mapping[str, Any],
        *,
        asset_type: str = "",
    ) -> dict[str, Any]:
        """Report what geometry alone says about a model's facing.

        Accepts a staged reference or an unstaged repository task
        identity. The result narrows the answer and never states it: a
        bounding box cannot tell a chest from a back. Pair it with
        ``three.preview.orientation_report`` when a decision is needed.
        """

        operation = "assets.analyze_orientation"
        resolved_type = asset_type
        if isinstance(reference, Mapping):
            resolved = self.resolve_source(
                reference,
                asset_type=asset_type,
            )
            if not resolved.get("ok"):
                resolved["operation"] = operation
                return resolved
            path = Path(
                str((resolved.get("payload") or {}).get("path") or "")
            )
            source_descriptor: Any = dict(reference)
        else:
            artifact_id = self._resolve_artifact_id(reference)
            record = (
                self._service.artifacts.get(artifact_id)
                if artifact_id
                else None
            )
            if record is None:
                return ThreeOperationResult.failure(
                    operation,
                    f"Unknown asset reference: {reference}",
                ).to_dict()
            public_root = self._config.public_root
            if public_root is None:
                return ThreeOperationResult.failure(
                    operation,
                    "project_path is not configured",
                ).to_dict()
            path = public_root / record.backend_path.lstrip("/")
            resolved_type = asset_type or record.type
            source_descriptor = {"reference": reference}

        try:
            inspection = inspect_source(path, asset_type=resolved_type)
        except Exception as exc:
            return ThreeOperationResult.failure(
                operation,
                f"{type(exc).__name__}: {exc}",
                payload={"source_path": str(path)},
            ).to_dict()
        evidence = analyze_geometry(inspection, asset_type=resolved_type)
        return ThreeOperationResult.success(
            operation,
            payload={
                "source": source_descriptor,
                "source_path": str(path),
                "asset_type": resolved_type,
                "evidence": evidence,
                "runtime_forward_axis": RUNTIME_FORWARD_AXIS,
                "runtime_up_axis": RUNTIME_UP_AXIS,
            },
        ).to_dict()

    def _resolve_artifact_id(self, reference: str) -> str | None:
        """Accept an ``artifact_id`` or an ``asset_id``, as the runtime does."""

        key = str(reference or "")
        if not key:
            return None
        if self._service.artifacts.get(key) is not None:
            return key
        for record in self._service.artifacts.list():
            if record.asset_id == key:
                return record.artifact_id
        return None

    def write_manifest(self) -> dict[str, Any]:
        try:
            manifest_path = self._service.write_manifest()
        except Exception as exc:
            return ThreeOperationResult.failure(
                "assets.write_manifest",
                f"{type(exc).__name__}: {exc}",
            ).to_dict()
        if manifest_path is None:
            return ThreeOperationResult.failure(
                "assets.write_manifest",
                "project_path is not configured",
            ).to_dict()
        records = self._service.artifacts.list()
        return ThreeOperationResult.success(
            "assets.write_manifest",
            artifacts=[
                {
                    "type": "web_asset_manifest",
                    "path": str(manifest_path),
                    "state": "ready",
                }
            ],
            payload={
                "manifest_path": str(manifest_path),
                "asset_count": len(records),
            },
        ).to_dict()

    def _resolve_source(
        self,
        source: Mapping[str, Any],
        asset_type: str,
        *,
        allow_directory: bool = False,
    ) -> ResolvedAssetSource:
        return self._sources.resolve(
            source,
            asset_type=asset_type,
            allow_directory=allow_directory,
        )

    @staticmethod
    def _source_failure(
        operation: str,
        source: Any,
        exc: Exception,
    ) -> dict[str, Any]:
        descriptor = (
            dict(source)
            if isinstance(source, Mapping)
            else {"value": str(source)}
        )
        return ThreeOperationResult.failure(
            operation,
            f"{type(exc).__name__}: {exc}",
            payload={"source": descriptor},
        ).to_dict()

    @staticmethod
    def _import_result(
        operation: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        artifacts = [
            dict(item)
            for item in payload.get("artifacts") or []
            if isinstance(item, dict)
        ]
        warnings = [
            str(item)
            for item in payload.get("warnings") or []
        ]
        errors = [
            str(item)
            for item in payload.get("errors") or []
        ]
        extra = {
            key: value
            for key, value in payload.items()
            if key not in {
                "ok",
                "artifacts",
                "warnings",
                "errors",
            }
        }
        return ThreeOperationResult(
            operation=operation,
            ok=bool(payload.get("ok", not errors)),
            artifacts=tuple(artifacts),
            warnings=tuple(warnings),
            errors=tuple(errors),
            payload=extra,
        ).to_dict()

    @staticmethod
    def _query_artifact(asset: dict[str, Any]) -> dict[str, Any]:
        path = str(asset.get("path") or "")
        return {
            "artifact_id": path,
            "asset_id": str(
                asset.get("name")
                or path.rsplit("/", 1)[-1]
            ),
            "type": str(asset.get("type") or ""),
            "backend": "web",
            "backend_class": str(asset.get("class") or ""),
            "backend_path": path,
            "metadata": {
                key: value
                for key, value in asset.items()
                if key
                not in {
                    "name",
                    "path",
                    "type",
                    "class",
                }
            },
        }
