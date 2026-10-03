"""Import native Unreal and generated A3Game effect packages."""

from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Any

from engine_adapters.ue5._internal.transport import (
    PythonRPCTransport,
    Transport,
)
from engine_adapters.ue5.config import (
    DEFAULT_EFFECT_DEST,
    UEClientConfig,
)

from ..artifacts.models import (
    ArtifactRecord,
    artifact_id_for,
    normalize_backend_path,
)
from ..native_content import (
    content_package_path,
    content_root_path,
    copy_native_content,
    resolve_native_content_source,
)
from ..naming import safe_id
from ..service import AssetService
from ..ue.scripts.effect_scripts import (
    build_effect_content_register_script,
    build_generated_effect_entry_script,
)
from ..ue.utils import (
    normalize_dest_path,
)
from .package import (
    EFFECT_MESH_SUFFIXES,
    EFFECT_PACKAGE_FILENAME,
    EFFECT_PACKAGE_FILENAMES,
    EFFECT_TEXTURE_SUFFIXES,
    EffectPackageInspection,
    inspect_effect_descriptor,
    load_effect_descriptor,
)
from .staging import (
    EffectSourceUploadService,
    StagedEffectSource,
)


PLAYABLE_EFFECT_CLASSES = {
    "NiagaraSystem",
    "ParticleSystem",
}


class EffectImportService:
    """Import UE-native Content Packs or generated effect source bundles.

    Native packages install their existing Unreal assets and register every
    playable effect. Generated packages import source dependencies first and
    optionally resolve a playable entry through an explicit build mode.
    Binding effects to animation or sockets is intentionally out of scope.
    """

    def __init__(
        self,
        asset_service: AssetService | Any,
        transport: Transport | None = None,
        upload_service: EffectSourceUploadService | None = None,
        config: UEClientConfig | None = None,
    ) -> None:
        self.config = config or UEClientConfig.resolve()
        self.assets = asset_service
        self.transport = transport or PythonRPCTransport(self.config)
        self.uploads = upload_service or EffectSourceUploadService(
            self.config.data_root / "uploads" / "effects"
        )

    def import_effect(
        self,
        source_path: str,
        *,
        effect_id: str = "",
        destination_root: str = "",
        entry_id: str = "",
        entry_asset: str = "",
        replace_existing: bool = False,
    ) -> dict[str, Any]:
        source = Path(source_path).expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(f"找不到特效源: {source}")

        staged = self._stage_source(source)
        staged_payload = staged.to_dict()
        resolved_source = Path(staged.source_path).expanduser().resolve()
        if staged.effect_kind == "native_ue":
            result = self._import_native_ue_content(
                resolved_source,
                effect_id=effect_id,
                entry_asset=entry_asset,
                replace_existing=replace_existing,
            )
        else:
            selected = self._select_generated_entry(
                staged,
                entry_id=entry_id,
            )
            if selected.suffix.lower() == ".uasset":
                raise ValueError(
                    "不能单独导入 .uasset；请上传保留 Content 相对目录的 "
                    "UE Content Pack ZIP 或目录"
                )
            if selected.suffix.lower() == ".json":
                result = self._import_generated_package(
                    selected,
                    effect_id=effect_id,
                    destination_root=destination_root,
                    replace_existing=replace_existing,
                )
            else:
                result = self._import_generated_file(
                    selected,
                    effect_id=effect_id,
                    destination_root=destination_root,
                )

        result["staged_source"] = staged_payload
        return result

    def _stage_source(self, source: Path) -> StagedEffectSource:
        if source.is_dir():
            return self.uploads.inspect_local_directory(str(source))
        if not source.is_file():
            raise ValueError(
                f"特效源既不是文件也不是目录: {source}"
            )
        if source.suffix.lower() == ".zip":
            return self.uploads.stage_effect(
                archive_path=str(source)
            )
        return self.uploads.stage_effect(file_path=str(source))

    @staticmethod
    def _select_generated_entry(
        staged: StagedEffectSource,
        *,
        entry_id: str,
    ) -> Path:
        requested = str(
            entry_id or staged.recommended_entry_id or ""
        ).strip()
        entries = {
            entry.entry_id: entry
            for entry in staged.entries
        }
        if requested:
            selected = entries.get(requested)
            if selected is None:
                available = ", ".join(sorted(entries))
                raise KeyError(
                    f"Effect source entry not found: {requested}; "
                    f"available: {available}"
                )
            return Path(selected.source_path).expanduser().resolve()
        source = Path(staged.source_path).expanduser().resolve()
        if source.is_file():
            return source
        raise ValueError("生成式特效包没有可导入入口")

    def _import_native_ue_content(
        self,
        source_dir: Path,
        *,
        effect_id: str,
        entry_asset: str,
        replace_existing: bool,
    ) -> dict[str, Any]:
        package_inspection = self._native_package_inspection(
            source_dir
        )
        if package_inspection is not None:
            effect_id = effect_id or package_inspection.effect_id
            entry_asset = (
                entry_asset
                or str(
                    package_inspection.build.get("entry_asset")
                    or ""
                )
            )
        content_source_dir, target_relative_root, source_layout = (
            resolve_native_content_source(source_dir)
        )
        source_assets = sorted(content_source_dir.rglob("*.uasset"))
        if not source_assets:
            raise ValueError(
                f"UE 原生 Effect 目录没有 .uasset: "
                f"{content_source_dir}"
            )

        project_file = self._configured_project_file()
        content_dir = project_file.parent / "Content"
        content_dir.mkdir(parents=True, exist_ok=True)
        target_dir = content_dir / target_relative_root
        copy_result = copy_native_content(
            content_source_dir,
            target_dir,
            replace_existing=replace_existing,
        )

        target_assets = [
            target_dir / path.relative_to(content_source_dir)
            for path in source_assets
        ]
        package_paths = [
            content_package_path(path, content_dir)
            for path in target_assets
        ]
        registry_scan_path = self._registry_scan_root(
            package_paths,
            fallback=content_root_path(target_dir, content_dir),
        )
        inspection = self.transport.execute_json(
            build_effect_content_register_script(
                registry_scan_path
            ),
            timeout=240,
        )
        if not isinstance(inspection, dict):
            raise RuntimeError(
                f"UE Effect Content 扫描返回无效结果: {inspection!r}"
            )
        playable_effects = [
            dict(item)
            for item in inspection.get("playable_effects") or []
            if isinstance(item, dict)
            and str(item.get("class") or "")
            in PLAYABLE_EFFECT_CLASSES
        ]
        if not playable_effects:
            raise ValueError(
                "UE 原生 Effect Content Pack 中没有可播放的 "
                "NiagaraSystem 或 ParticleSystem"
            )

        selected = self._select_entry_asset(
            playable_effects,
            entry_asset=entry_asset,
        )
        package_id = safe_id(
            effect_id or source_dir.name,
            fallback="effect",
        )
        all_assets = [
            dict(item)
            for item in inspection.get("assets") or []
            if isinstance(item, dict)
        ]
        records = self._build_effect_records(
            playable_effects,
            source_path=source_dir,
            package_id=package_id,
            package_kind="native_ue",
            entry_path=str(selected.get("path") or ""),
            metadata={
                "content_root_path": registry_scan_path,
                "source_layout": source_layout,
                "package_assets": all_assets,
                "copy": copy_result,
                "effect_package": (
                    package_inspection.to_dict()
                    if package_inspection is not None
                    else {}
                ),
                "binding": (
                    package_inspection.binding
                    if package_inspection is not None
                    else None
                ),
            },
        )
        self.assets.artifacts.upsert_many(records)

        warnings = (
            list(package_inspection.warnings)
            if package_inspection is not None
            else []
        )
        if copy_result.get("preserved_modified"):
            warnings.append(
                "目标 Content 中存在不同大小的同名文件，"
                "replace_existing=false，因此保留了现有文件"
            )
        return {
            "ok": True,
            "source_path": str(source_dir),
            "import_mode": "native_ue",
            "effect_id": package_id,
            "runtime_ready": True,
            "entry_asset_path": str(selected.get("path") or ""),
            "artifacts": [record.to_dict() for record in records],
            "warnings": warnings,
            "native_content": {
                "content_source_dir": str(content_source_dir),
                "source_layout": source_layout,
                "target_dir": str(target_dir),
                "content_root_path": registry_scan_path,
                "package_paths": package_paths,
                "copy": copy_result,
                "inspection": inspection,
                "package": (
                    package_inspection.to_dict()
                    if package_inspection is not None
                    else {}
                ),
            },
        }

    def _import_generated_package(
        self,
        descriptor_path: Path,
        *,
        effect_id: str,
        destination_root: str,
        replace_existing: bool,
    ) -> dict[str, Any]:
        descriptor = load_effect_descriptor(descriptor_path)
        inspection = inspect_effect_descriptor(
            descriptor_path,
            descriptor,
        )
        if not inspection.canonical:
            raise ValueError(
                f"生成式特效包必须使用 {EFFECT_PACKAGE_FILENAME}"
            )

        package_id = safe_id(
            effect_id or inspection.effect_id,
            fallback="effect",
        )
        content_root = self._generated_content_root(
            destination_root,
            package_id,
        )
        dependency_artifacts: list[dict[str, Any]] = []
        imported_assets: list[dict[str, Any]] = []
        skipped_assets: list[dict[str, Any]] = []
        warnings = list(inspection.warnings)

        for asset in inspection.assets.values():
            import_as = str(asset.get("import_as") or "").strip()
            if not import_as:
                skipped_assets.append(
                    {
                        "id": asset["id"],
                        "role": asset["role"],
                        "source_path": asset["source_path"],
                        "reason": "auxiliary_source",
                    }
                )
                continue
            destination = self._generated_asset_destination(
                content_root,
                asset["role"],
                asset["id"],
            )
            options: dict[str, Any] = {
                "category": "effect_dependency",
                "metadata": {
                    "effect_package_id": package_id,
                    "effect_role": asset["role"],
                    "effect_source_id": asset["id"],
                },
            }
            if import_as == "prop":
                options.update(
                    {
                        "generate_collision": False,
                        "combine_meshes": True,
                        "include_all_static_meshes": True,
                    }
                )
            imported = self.assets.import_asset(
                asset["source_path"],
                import_as,
                dst_path=destination,
                **options,
            )
            artifacts = [
                item
                for item in imported.get("artifacts") or []
                if isinstance(item, dict)
            ]
            tagged = self._tag_dependency_artifacts(
                artifacts,
                package_id=package_id,
                source_id=asset["id"],
                role=asset["role"],
            )
            dependency_artifacts.extend(tagged)
            imported_assets.append(
                {
                    "id": asset["id"],
                    "role": asset["role"],
                    "import_as": import_as,
                    "source_path": asset["source_path"],
                    "destination": destination,
                    "artifacts": tagged,
                }
            )

        build_result = self._build_generated_entry(
            inspection,
            content_root=content_root,
            package_id=package_id,
            replace_existing=replace_existing,
        )
        effect_records: list[ArtifactRecord] = []
        entry_effect = build_result.get("effect")
        if isinstance(entry_effect, dict) and entry_effect.get("path"):
            effect_records = self._build_effect_records(
                [entry_effect],
                source_path=descriptor_path,
                package_id=package_id,
                package_kind="generated",
                entry_path=str(entry_effect.get("path") or ""),
                metadata={
                    "effect_package": inspection.to_dict(),
                    "build": build_result,
                    "binding": inspection.binding,
                    "dependencies": [
                        {
                            "artifact_id": artifact.get("artifact_id"),
                            "backend_path": artifact.get("backend_path"),
                            "type": artifact.get("type"),
                        }
                        for artifact in dependency_artifacts
                    ],
                    "skipped_assets": skipped_assets,
                    **dict(inspection.metadata),
                },
            )
            self.assets.artifacts.upsert_many(effect_records)
        else:
            warnings.append(
                "生成式特效源资源已导入，但 manifest 没有生成或解析出"
                "可播放的 NiagaraSystem；runtime_ready=false"
            )

        return {
            "ok": True,
            "source_path": str(descriptor_path),
            "import_mode": "generated",
            "effect_id": package_id,
            "runtime_ready": bool(effect_records),
            "entry_asset_path": (
                effect_records[0].backend_path
                if effect_records
                else ""
            ),
            "artifacts": [
                *[record.to_dict() for record in effect_records],
                *dependency_artifacts,
            ],
            "warnings": warnings,
            "generated_content": {
                "content_root_path": content_root,
                "package": inspection.to_dict(),
                "imported_assets": imported_assets,
                "skipped_assets": skipped_assets,
                "build": build_result,
                "binding": inspection.binding,
            },
        }

    def _import_generated_file(
        self,
        source: Path,
        *,
        effect_id: str,
        destination_root: str,
    ) -> dict[str, Any]:
        suffix = source.suffix.lower()
        if suffix in EFFECT_TEXTURE_SUFFIXES:
            import_as = "texture"
            role = "texture"
        elif suffix in EFFECT_MESH_SUFFIXES:
            import_as = "prop"
            role = "mesh"
        else:
            raise ValueError(
                f"当前不能直接导入生成式特效文件: {suffix}；"
                f"请使用 {EFFECT_PACKAGE_FILENAME} 声明其角色和构建方式"
            )
        package_id = safe_id(
            effect_id or source.stem,
            fallback="effect",
        )
        content_root = self._generated_content_root(
            destination_root,
            package_id,
        )
        destination = self._generated_asset_destination(
            content_root,
            role,
            source.stem,
        )
        options: dict[str, Any] = {
            "category": "effect_dependency",
            "metadata": {
                "effect_package_id": package_id,
                "effect_role": role,
            },
        }
        if import_as == "prop":
            options["generate_collision"] = False
        imported = self.assets.import_asset(
            str(source),
            import_as,
            dst_path=destination,
            **options,
        )
        artifacts = self._tag_dependency_artifacts(
            [
                item
                for item in imported.get("artifacts") or []
                if isinstance(item, dict)
            ],
            package_id=package_id,
            source_id=source.stem,
            role=role,
        )
        return {
            "ok": True,
            "source_path": str(source),
            "import_mode": "generated_single_asset",
            "effect_id": package_id,
            "runtime_ready": False,
            "entry_asset_path": "",
            "artifacts": artifacts,
            "warnings": [
                "源资源已导入，但单个纹理或 Mesh 不是可播放的 "
                "NiagaraSystem"
            ],
            "generated_content": {
                "content_root_path": content_root,
                "source_role": role,
                "destination": destination,
            },
        }

    def _build_generated_entry(
        self,
        inspection: EffectPackageInspection,
        *,
        content_root: str,
        package_id: str,
        replace_existing: bool,
    ) -> dict[str, Any]:
        mode = str(inspection.build.get("mode") or "none")
        if mode == "none":
            return {
                "ok": True,
                "mode": "none",
                "effect": None,
            }
        result = self.transport.execute_json(
            build_generated_effect_entry_script(
                inspection.build,
                content_root,
                effect_id=package_id,
                replace_existing=replace_existing,
            ),
            timeout=180,
        )
        if not isinstance(result, dict) or not result.get("ok"):
            raise RuntimeError(
                f"UE 生成式 Effect 入口构建失败: {result!r}"
            )
        return result

    def _tag_dependency_artifacts(
        self,
        artifacts: list[dict[str, Any]],
        *,
        package_id: str,
        source_id: str,
        role: str,
    ) -> list[dict[str, Any]]:
        records = []
        for artifact in artifacts:
            record = ArtifactRecord.from_dict(artifact)
            record = replace(
                record,
                metadata={
                    **dict(record.metadata or {}),
                    "effect_package_id": package_id,
                    "effect_source_id": source_id,
                    "effect_role": role,
                    "effect_dependency": True,
                },
            )
            records.append(record)
        if records:
            self.assets.artifacts.upsert_many(records)
        return [record.to_dict() for record in records]

    @staticmethod
    def _build_effect_records(
        effects: list[dict[str, Any]],
        *,
        source_path: Path,
        package_id: str,
        package_kind: str,
        entry_path: str,
        metadata: dict[str, Any],
    ) -> list[ArtifactRecord]:
        records = []
        multiple = len(effects) > 1
        normalized_entry = normalize_backend_path(entry_path)
        for effect in effects:
            backend_path = normalize_backend_path(
                str(effect.get("path") or "")
            )
            backend_class = str(effect.get("class") or "")
            if (
                not backend_path
                or backend_class not in PLAYABLE_EFFECT_CLASSES
            ):
                continue
            name = str(
                effect.get("name")
                or backend_path.rsplit("/", 1)[-1]
            )
            asset_id = (
                f"{package_id}_{safe_id(name, fallback='effect')}"
                if multiple
                else package_id
            )
            record_metadata = {
                "effect_package_id": package_id,
                "effect_package_kind": package_kind,
                "entry_asset": backend_path == normalized_entry,
                **dict(metadata),
            }
            records.append(
                ArtifactRecord(
                    artifact_id=artifact_id_for(
                        "ue",
                        backend_class,
                        asset_id,
                        backend_path,
                    ),
                    asset_id=asset_id,
                    package_id=package_id,
                    type="effect",
                    category="",
                    backend="ue",
                    backend_class=backend_class,
                    backend_path=backend_path,
                    source_path=str(source_path),
                    spawnable=False,
                    state="ready",
                    runtime_capabilities={
                        "renderable": True,
                        "spawnable": False,
                        "collidable": False,
                        "playable": False,
                    },
                    metadata=record_metadata,
                )
            )
        return records

    @staticmethod
    def _select_entry_asset(
        effects: list[dict[str, Any]],
        *,
        entry_asset: str,
    ) -> dict[str, Any]:
        requested = normalize_backend_path(entry_asset)
        if requested:
            requested_name = requested.rsplit("/", 1)[-1].lower()
            for effect in effects:
                path = normalize_backend_path(
                    str(effect.get("path") or "")
                )
                name = str(
                    effect.get("name")
                    or path.rsplit("/", 1)[-1]
                ).lower()
                if (
                    path == requested
                    or name == requested_name
                    or path.lower().endswith(
                        "/" + requested_name
                    )
                ):
                    return effect
            available = ", ".join(
                str(effect.get("path") or "")
                for effect in effects
            )
            raise ValueError(
                f"找不到指定 Effect entry asset: {entry_asset}；"
                f"可选: {available}"
            )
        return sorted(
            effects,
            key=lambda item: (
                not str(item.get("name") or "")
                .lower()
                .startswith("ns_"),
                str(item.get("path") or "").lower(),
            ),
        )[0]

    @staticmethod
    def _registry_scan_root(
        package_paths: list[str],
        *,
        fallback: str,
    ) -> str:
        parent_parts = [
            PurePosixPath(path).parent.parts
            for path in package_paths
            if path.startswith("/Game/")
        ]
        if parent_parts:
            common = list(parent_parts[0])
            for parts in parent_parts[1:]:
                prefix_length = 0
                for left, right in zip(common, parts):
                    if left != right:
                        break
                    prefix_length += 1
                common = common[:prefix_length]
                if not common:
                    break
            if common and common[0] == "/":
                common = common[1:]
            if common:
                return "/" + "/".join(common)
        return fallback or "/Game"

    @staticmethod
    def _generated_content_root(
        destination_root: str,
        package_id: str,
    ) -> str:
        base = normalize_dest_path(
            destination_root or DEFAULT_EFFECT_DEST,
            DEFAULT_EFFECT_DEST,
        ).rstrip("/")
        if base.rsplit("/", 1)[-1].lower() == package_id.lower():
            return base
        return f"{base}/{package_id}"

    @staticmethod
    def _generated_asset_destination(
        content_root: str,
        role: str,
        asset_id: str,
    ) -> str:
        folder = {
            "texture": "Textures",
            "mesh": "Meshes",
            "material": "Materials",
        }.get(role, "Sources")
        return (
            f"{content_root.rstrip('/')}/{folder}/"
            f"{safe_id(asset_id, fallback='asset')}"
        )

    def _configured_project_file(self) -> Path:
        project_file = self.config.project_file
        if project_file is None:
            raise ValueError(
                "导入 UE Content Pack 需要配置 project_path"
            )
        if (
            not project_file.is_file()
            or project_file.suffix.lower() != ".uproject"
        ):
            raise FileNotFoundError(
                f"UE project_path 无效: {project_file}"
            )
        return project_file

    @staticmethod
    def _native_package_inspection(
        source_dir: Path,
    ) -> EffectPackageInspection | None:
        manifests = sorted(
            path
            for path in source_dir.rglob("*.json")
            if path.is_file()
            and path.name.lower() in EFFECT_PACKAGE_FILENAMES
        )
        if not manifests:
            return None
        if len(manifests) > 1:
            raise ValueError(
                "UE 原生 Effect Content Pack 包含多个 "
                f"{EFFECT_PACKAGE_FILENAME}"
            )
        inspection = inspect_effect_descriptor(manifests[0])
        if inspection.representation != "native_ue_content":
            raise ValueError(
                "含 UE 原生 .uasset 的包如提供 "
                f"{EFFECT_PACKAGE_FILENAME}，representation 必须是 "
                "native_ue_content"
            )
        return inspection


__all__ = ["EffectImportService"]
