"""Stable asset operations for UnityClient v1."""

from typing import Any, Mapping, Sequence

from .._internal.transport.unity_editor import UnityEditorTransport
from ..config import DEFAULT_IMPORT_ROOT, UnityClientConfig
from ..contracts import UnityOperationResult
from ._internal.artifacts import ArtifactRegistry, build_artifact_records
from ._internal.artifacts.models import normalize_artifact_type, normalize_backend_path
from ._internal.service import AssetService
from ._internal.source_resolver import (
    GeneratedAssetSourceResolver,
    ResolvedAssetSource,
)
from ._internal.unity.dispatcher import UnityImportDispatcher


class UnityAssetsClient:
    def __init__(
        self,
        config: UnityClientConfig,
        transport: UnityEditorTransport,
    ) -> None:
        self._config = config
        self._sources = GeneratedAssetSourceResolver()
        dispatcher = UnityImportDispatcher(transport, config)
        self._service = AssetService(
            dispatcher=dispatcher,
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
        try:
            resolved = self._resolve_source(source, asset_type)
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
            return UnityOperationResult.failure(
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

    def import_batch(
        self,
        sources: Sequence[Mapping[str, Any]],
        *,
        options: Mapping[str, Any] | None = None,
        timeout: int | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Import a dependency-ordered asset set in one Unity Editor job.

        Each source is still a canonical generated-output descriptor.  The
        Editor receives absolute materialized paths only after this client has
        resolved and validated every descriptor, so this operation cannot
        silently import files directly from ``test_samples`` or ``asset``.
        """
        if isinstance(sources, (str, bytes)) or not sources:
            return UnityOperationResult.failure(
                "assets.import_batch",
                "sources must be a non-empty sequence of descriptors",
            ).to_dict()
        entries: list[dict[str, Any]] = []
        resolved_sources: list[ResolvedAssetSource] = []
        common_options = dict(options or {})
        try:
            for source in sources:
                if not isinstance(source, Mapping):
                    raise TypeError("each batch source must be a descriptor object")
                descriptor = dict(source)
                asset_type = str(
                    descriptor.get("asset_type")
                    or descriptor.get("type")
                    or ""
                ).strip().lower()
                if asset_type == "environment":
                    resolve_type = "scene"
                else:
                    resolve_type = asset_type
                if not resolve_type:
                    raise ValueError("batch source is missing asset_type")
                resolved = self._resolve_source(
                    descriptor,
                    resolve_type,
                    allow_directory=resolve_type == "scene",
                )
                validation = self._service.validate_asset(
                    str(resolved.path),
                    resolve_type,
                    **common_options,
                )
                # Unity packages are valid scene inputs even when the generic
                # validation path only sees a directory after pre-extraction.
                if not validation.get("ok"):
                    raise ValueError(
                        "; ".join(str(item) for item in validation.get("errors") or [])
                    )
                src_path = resolved.path
                package_root = ""
                pre_extracted = False
                package_warnings: list[str] = []
                if src_path.suffix.lower() == ".unitypackage":
                    (
                        prepared,
                        package_warnings,
                        pre_extracted,
                    ) = self._service.dispatcher._prepare_unitypackage(src_path)
                    src_path = prepared
                    from ._internal.unity.dispatcher import discover_unitypackage_root
                    package_root = discover_unitypackage_root(resolved.path)
                name = str(
                    descriptor.get("name")
                    or descriptor.get("task_id")
                    or resolved.path.stem
                ).strip()
                destination = str(
                    descriptor.get("destination")
                    or common_options.get("destination")
                    or self._service.default_destination(resolve_type)
                )
                entry = {
                    "asset_type": "scene" if asset_type == "environment" else asset_type,
                    "src": str(src_path),
                    "dest": destination,
                    "name": name,
                    "skeleton_asset_path": str(
                        descriptor.get("skeleton")
                        or descriptor.get("skeleton_asset_path")
                        or common_options.get("skeleton")
                        or ""
                    ),
                    "package_root": package_root,
                    "pre_extracted": pre_extracted,
                    "world_id": str(descriptor.get("world_id") or common_options.get("world_id") or ""),
                    "project_id": str(descriptor.get("project_id") or common_options.get("project_id") or ""),
                    "publish": str(bool(descriptor.get("publish", common_options.get("publish", False)))).lower(),
                    "replace_existing": str(bool(descriptor.get("replace_existing", common_options.get("replace_existing", True)))).lower(),
                    "usage": str(descriptor.get("usage") or common_options.get("usage") or "Asset"),
                    "category": str(descriptor.get("category") or common_options.get("category") or ""),
                }
                entries.append(entry)
                resolved_sources.append(resolved)
                if package_warnings:
                    entry["client_warnings"] = package_warnings
        except Exception as exc:
            return UnityOperationResult.failure(
                "assets.import_batch",
                f"{type(exc).__name__}: {exc}",
            ).to_dict()

        # Keep the dependency contract deterministic even if callers pass an
        # arbitrary order: avatars/meshes first, then motions, then scenes.
        order = {"avatar": 0, "weapon": 0, "prop": 0, "static_mesh": 0,
                 "motion": 1, "scene": 2, "environment": 2}
        paired = sorted(
            zip(entries, resolved_sources),
            key=lambda item: order.get(item[0]["asset_type"], 0),
        )
        entries = [item[0] for item in paired]
        resolved_sources = [item[1] for item in paired]
        avatar_prefab = next(
            (
                f"Assets/Generated/Prefabs/{entry['name']}.prefab"
                for entry in entries
                if entry["asset_type"] == "avatar"
            ),
            "",
        )
        if avatar_prefab:
            for entry in entries:
                if entry["asset_type"] == "motion" and not entry.get("skeleton_asset_path"):
                    entry["skeleton_asset_path"] = avatar_prefab
        report = self._service.dispatcher._transport.execute_method(
            "ImportBatch.RunFromCLI",
            args={"entries": entries},
            timeout=timeout or self._config.editor_batchmode_timeout,
            dry_run=dry_run,
        )
        if dry_run:
            return UnityOperationResult.success(
                "assets.import_batch",
                artifacts=[
                    {"type": "unity_asset_batch", "path": "ImportBatch.RunFromCLI", "state": "planned"}
                ],
                payload={"entries": entries, "source_count": len(entries)},
            ).to_dict()
        if not isinstance(report, dict):
            return UnityOperationResult.failure(
                "assets.import_batch",
                "Unity batch import returned an invalid report",
            ).to_dict()
        raw_items = report.get("items") or []
        artifacts: list[dict[str, Any]] = []
        item_results: list[dict[str, Any]] = []
        errors = [str(item) for item in report.get("errors") or []]
        warnings = [str(item) for item in report.get("warnings") or []]
        for index, (entry, resolved) in enumerate(zip(entries, resolved_sources)):
            item = dict(raw_items[index]) if index < len(raw_items) and isinstance(raw_items[index], dict) else {"ok": False, "error": "Unity omitted batch item report"}
            if entry.get("client_warnings"):
                warnings.extend(str(value) for value in entry["client_warnings"])
            imported_paths = [str(value) for value in item.get("importedPaths") or [] if str(value)]
            result_payload = {
                "ok": bool(item.get("ok")),
                "src_path": str(resolved.path),
                "asset_type": str(entry["asset_type"]),
                "asset_id": str(resolved.task_id),
                "dest_path": str(entry["dest"]),
                "imported_paths": imported_paths,
                "metadata": {
                    "batch": True,
                    "task_id": resolved.task_id,
                    "task_kind": resolved.task_kind,
                    "report": item,
                },
            }
            if item.get("runtimePrefabPath"):
                result_payload["runtimePrefabPath"] = item["runtimePrefabPath"]
            if item.get("runtimeAnimationClipPath"):
                result_payload["runtimeAnimationClipPath"] = item["runtimeAnimationClipPath"]
            records = build_artifact_records(
                result_payload,
                backend="unity",
                category=str(entry.get("category") or ""),
            ) if item.get("ok") else []
            if records:
                self._service.artifacts.upsert_many(records)
                artifacts.extend(record.to_dict() for record in records)
            if not item.get("ok"):
                errors.append(
                    f"{resolved.task_id}: {item.get('error') or 'batch import failed'}"
                )
            item_results.append({
                "task_id": resolved.task_id,
                "task_kind": resolved.task_kind,
                "asset_type": entry["asset_type"],
                "ok": bool(item.get("ok")),
                "report": item,
                "artifacts": [record.to_dict() for record in records],
            })
        ok = bool(report.get("ok")) and not errors
        return UnityOperationResult(
            operation="assets.import_batch",
            ok=ok,
            artifacts=tuple(artifacts),
            warnings=tuple(dict.fromkeys(warnings)),
            errors=tuple(dict.fromkeys(errors)),
            payload={
                "source_count": len(entries),
                "succeeded": int(report.get("succeeded") or 0),
                "failed": int(report.get("failed") or 0),
                "items": item_results,
                "entries": entries,
            },
        ).to_dict()

    def import_avatar(
        self,
        source: Mapping[str, Any],
        *,
        destination: str = "",
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.import_asset(
            source,
            "avatar",
            destination=destination,
            options=options,
        )

    def import_motion(
        self,
        source: Mapping[str, Any],
        *,
        skeleton: str,
        destination: str = "",
        avatar_name: str = "",
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not str(skeleton or "").strip():
            descriptor = (
                dict(source)
                if isinstance(source, Mapping)
                else {"value": str(source)}
            )
            return UnityOperationResult.failure(
                "assets.import_motion",
                "skeleton is required for Motion import",
                payload={"source": descriptor},
            ).to_dict()
        resolved_options = dict(options or {})
        resolved_options["skeleton_asset_path"] = skeleton
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

    def validate(
        self,
        source: Mapping[str, Any],
        asset_type: str,
        *,
        destination: str = "",
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            resolved = self._resolve_source(source, asset_type)
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
            return UnityOperationResult.failure(
                "assets.validate",
                f"{type(exc).__name__}: {exc}",
                payload={
                    "asset_type": asset_type,
                    "source": resolved.descriptor(),
                },
            ).to_dict()
        result = UnityOperationResult(
            operation="assets.validate",
            ok=validation.get("ok", not validation.get("errors")),
            warnings=tuple(validation.get("warnings") or []),
            errors=tuple(validation.get("errors") or []),
            payload={
                "asset_type": asset_type,
                "source": resolved.descriptor(),
            },
        )
        return result.to_dict()

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
        return UnityOperationResult.success(
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
            return UnityOperationResult.failure(
                "assets.list",
                f"{type(exc).__name__}: {exc}",
                payload={
                    "asset_type": asset_type,
                    "root": root,
                },
            ).to_dict()
        return UnityOperationResult.success(
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
            backend="unity",
        )
        return UnityOperationResult.success(
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
            return UnityOperationResult.failure(
                "assets.get_metadata",
                f"Unknown artifact_id: {artifact_id}",
            ).to_dict()
        return UnityOperationResult.success(
            "assets.get_metadata",
            artifacts=[record.to_dict()],
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
        return UnityOperationResult.failure(
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
        error = str(payload.get("error") or "").strip()
        if error and error not in errors:
            errors.insert(0, error)
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
        return UnityOperationResult(
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
            "backend": "unity",
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
