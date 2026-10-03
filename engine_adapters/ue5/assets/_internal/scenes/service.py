"""Import generated scene sources into an A3Game world package."""

import shutil
from pathlib import Path
from typing import Any

from engine_adapters.ue5._internal.transport import (
    PythonRPCTransport,
    Transport,
)
from engine_adapters.ue5.assets._internal.artifacts import (
    ArtifactRecord,
)
from engine_adapters.ue5.assets._internal.artifacts.models import (
    artifact_id_for,
)
from engine_adapters.ue5.assets._internal.preprocessors import (
    estimate_ply_ground_alignment,
    is_gaussian_splat_ply,
    prepare_gaussian_splat_source,
)
from engine_adapters.ue5.assets._internal.service import (
    AssetService,
)
from engine_adapters.ue5.assets._internal.ue.scripts.native_scene_scripts import (
    build_native_scene_register_script,
)
from engine_adapters.ue5.assets._internal.ue.scripts.gaussian_splat_scripts import (
    build_gaussian_splat_import_script,
)
from engine_adapters.ue5.assets._internal.ue.scripts.generated_scene_scripts import (
    build_generated_scene_map_script,
    build_generated_scene_prepare_script,
)
from engine_adapters.ue5.bindings._internal.materials import (
    PBRMaterialBindingService,
)
from engine_adapters.ue5.config import UEClientConfig
from engine_adapters.ue5.world._internal.service import (
    WorldService,
)
from engine_adapters.ue5.world._internal.specs import (
    CameraSpec,
    TransformSpec,
    WorldEntitySpec,
    WorldSpec,
    safe_id,
)

from .package import (
    ScenePackageInspection,
    inspect_scene_descriptor,
    load_scene_descriptor,
)


class SceneImportService:
    """Bridge scene generators to the existing Artifact/World pipeline.

    A scene source may be a mesh file (FBX/GLB/GLTF/USD/Collider PLY) or a JSON
    layout descriptor. JSON keeps logical IDs and transforms separate from UE
    paths, which makes it suitable for generated scene layouts.
    """

    def __init__(
        self,
        asset_service: AssetService,
        world_service: WorldService,
        transport: Transport | None = None,
        material_service: PBRMaterialBindingService | None = None,
        config: UEClientConfig | None = None,
    ) -> None:
        self.config = config or UEClientConfig.resolve()
        self.assets = asset_service
        self.worlds = world_service
        self.transport = transport or PythonRPCTransport(self.config)
        self.materials = material_service or PBRMaterialBindingService(
            transport=self.transport
        )

    def import_scene(
        self,
        source_path: str,
        *,
        world_id: str = "",
        project_id: str = "",
        publish: bool = True,
        default_spawn_point: dict[str, Any] | list[float] | None = None,
        native_map: str = "",
        replace_existing: bool = False,
        preview_in_editor: bool = True,
        repair_missing_collision: bool = False,
    ) -> dict[str, Any]:
        source = Path(source_path).expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(f"找不到场景源: {source}")

        if source.is_dir():
            return self._import_native_ue_content(
                source,
                world_id=world_id,
                project_id=project_id,
                publish=publish,
                default_spawn_point=default_spawn_point,
                native_map=native_map,
                replace_existing=replace_existing,
                preview_in_editor=preview_in_editor,
                repair_missing_collision=repair_missing_collision,
            )
        if not source.is_file():
            raise ValueError(f"场景源既不是文件也不是目录: {source}")

        if source.suffix.lower() == ".json":
            descriptor = load_scene_descriptor(source)
            package_inspection = inspect_scene_descriptor(source, descriptor)
            return self._import_descriptor(
                source,
                descriptor,
                world_id=world_id,
                project_id=project_id,
                publish=publish,
                default_spawn_point=default_spawn_point,
                package_inspection=package_inspection,
                replace_existing=replace_existing,
                preview_in_editor=preview_in_editor,
            )

        resolved_world_id = safe_id(world_id or source.stem, fallback="world")
        resolved_project_id = safe_id(project_id, fallback="")
        content_root = self._generated_content_root(resolved_world_id)
        prepare_result = self._prepare_generated_content(
            content_root,
            replace_existing=replace_existing,
        )
        environment_artifacts = self._import_assets(
            source,
            "environment",
            dest_path=self._generated_asset_destination(
                content_root,
                source.stem,
            ),
        )
        material_bindings = [
            self.materials.bind(
                asset_id=source.stem,
                source_path=source,
                mesh_asset_paths=[
                    str(artifact.get("backend_path") or "")
                    for artifact in environment_artifacts
                    if artifact.get("backend_path")
                ],
                destination_root=content_root,
            )
        ]
        return self._create_generated_native_map(
            source_path=source,
            world_id=resolved_world_id,
            project_id=resolved_project_id,
            entities=self._environment_entities(environment_artifacts),
            metadata={"source_representation": "mesh"},
            spawn_point=self._spawn_transform(default_spawn_point),
            camera=dict_to_camera(None),
            content_root=content_root,
            publish=publish,
            replace_existing=replace_existing,
            preview_in_editor=preview_in_editor,
            add_default_lighting=True,
            add_default_ground=False,
            material_bindings=material_bindings,
            prepare_result=prepare_result,
        )

    def _import_native_ue_content(
        self,
        source_dir: Path,
        *,
        world_id: str,
        project_id: str,
        publish: bool,
        default_spawn_point: dict[str, Any] | list[float] | None,
        native_map: str,
        replace_existing: bool,
        preview_in_editor: bool,
        repair_missing_collision: bool,
    ) -> dict[str, Any]:
        content_source_dir, target_relative_root, source_layout = (
            self._resolve_native_content_source(source_dir)
        )
        source_maps = sorted(content_source_dir.rglob("*.umap"))
        source_assets = sorted(content_source_dir.rglob("*.uasset"))
        if not source_maps:
            raise ValueError(f"UE 原生 Scene 目录没有 .umap: {content_source_dir}")
        if not source_assets:
            raise ValueError(f"UE 原生 Scene 目录没有 .uasset: {content_source_dir}")

        project_file = self.config.project_file
        if project_file is None:
            raise ValueError(
                "导入 UE Content Pack 需要配置 project_path"
            )
        if (
            not project_file.exists()
            or project_file.suffix.lower() != ".uproject"
        ):
            raise FileNotFoundError(
                f"UE project_path 无效: {project_file}"
            )

        content_dir = project_file.parent / "Content"
        content_dir.mkdir(parents=True, exist_ok=True)
        target_dir = content_dir / target_relative_root
        copy_result = self._copy_native_content(
            content_source_dir,
            target_dir,
            replace_existing=replace_existing,
        )

        target_maps = [
            target_dir / path.relative_to(content_source_dir)
            for path in source_maps
        ]
        map_paths = [
            self._content_package_path(path, content_dir)
            for path in target_maps
        ]
        selected_map_path = self._select_native_map(
            source_maps,
            map_paths,
            native_map=native_map,
        )
        content_root_path = self._native_content_root(
            target_dir,
            content_dir,
            selected_map_path,
        )
        registry_scan_path = (
            content_root_path
            if target_relative_root.parts
            else "/Game"
        )
        inspection = self.transport.execute_json(
            build_native_scene_register_script(
                registry_scan_path,
                map_paths,
                selected_map_path,
                load_map=preview_in_editor,
                repair_missing_collision=repair_missing_collision,
            ),
            timeout=240,
        )

        inspected_spawn = None
        if isinstance(inspection, dict):
            inspected_spawn = inspection.get("player_start") or inspection.get("suggested_spawn")
        spawn_transform = (
            self._spawn_transform(default_spawn_point)
            if default_spawn_point is not None
            else TransformSpec.from_dict(inspected_spawn if isinstance(inspected_spawn, dict) else {})
        )
        resolved_world_id = safe_id(
            world_id or Path(selected_map_path).name or source_dir.name,
            fallback="world",
        )
        resolved_project_id = safe_id(project_id, fallback="")
        metadata = {
            "representation": "native_ue_level",
            "source_path": str(source_dir),
            "native_content_root": content_root_path,
            "level_path": selected_map_path,
            "maps": map_paths,
            "spawn_point": spawn_transform.to_dict(),
            "spawn_point_mode": "actor" if default_spawn_point is None and inspected_spawn else "ground",
            "spawn_point_source": (
                str(inspection.get("spawn_source") or "")
                if isinstance(inspection, dict)
                else ""
            ),
            "collidable": self._native_scene_collidable(inspection),
            "navigable": True,
            "interactive": True,
            "collision_audit": (
                inspection.get("collision")
                if isinstance(inspection, dict)
                else {}
            ),
        }
        spec = WorldSpec(
            world_id=resolved_world_id,
            project_id=resolved_project_id,
            entities=[],
            metadata=metadata,
        )
        result = self._save_world(spec, publish=publish, source_path=source_dir)
        result["native_content"] = {
            "source_dir": str(source_dir),
            "content_source_dir": str(content_source_dir),
            "source_layout": source_layout,
            "target_dir": str(target_dir),
            "content_root_path": content_root_path,
            "registry_scan_path": registry_scan_path,
            "map_paths": map_paths,
            "selected_map_path": selected_map_path,
            "repair_missing_collision": repair_missing_collision,
            "copy": copy_result,
            "inspection": inspection,
        }
        return result

    @staticmethod
    def _resolve_native_content_source(source_dir: Path) -> tuple[Path, Path, str]:
        current = source_dir.resolve()
        unwrapped = False
        ue_content_folders = {
            "animations",
            "assets",
            "blueprints",
            "effects",
            "environment",
            "maps",
            "map",
            "materials",
            "meshes",
            "textures",
        }
        while True:
            project_content = current / "Content"
            project_files = list(current.glob("*.uproject"))
            if project_content.is_dir() and (
                project_files
                or any(project_content.rglob("*.umap"))
                or any(project_content.rglob("*.uasset"))
            ):
                return project_content, Path(), "uproject"
            if current.name.lower() == "content":
                return current, Path(), "content"

            native_files = sorted(
                [
                    *current.rglob("*.umap"),
                    *current.rglob("*.uasset"),
                ]
            )
            first_parts = {
                path.relative_to(current).parts[0]
                for path in native_files
                if len(path.relative_to(current).parts) > 1
            }
            has_direct_native_files = any(
                len(path.relative_to(current).parts) == 1
                for path in native_files
            )
            if (
                native_files
                and not has_direct_native_files
                and len(first_parts) == 1
            ):
                first_part = next(iter(first_parts))
                child = current / first_part
                if (
                    first_part.lower() not in ue_content_folders
                    and child.is_dir()
                ):
                    current = child
                    unwrapped = True
                    continue
            return (
                current,
                Path(current.name),
                "wrapped_content_pack" if unwrapped else "content_pack",
            )

    @staticmethod
    def _native_content_root(
        target_dir: Path,
        content_dir: Path,
        selected_map_path: str,
    ) -> str:
        relative_target = target_dir.resolve().relative_to(content_dir.resolve())
        if relative_target.parts:
            return f"/Game/{relative_target.as_posix()}"
        map_relative = selected_map_path.removeprefix("/Game/").strip("/")
        if not map_relative:
            return "/Game"
        return f"/Game/{map_relative.split('/', 1)[0]}"

    @staticmethod
    def _native_scene_collidable(inspection: Any) -> bool:
        if not isinstance(inspection, dict):
            return False
        collision = inspection.get("collision")
        if not isinstance(collision, dict):
            return bool(inspection.get("actor_count"))
        return bool(collision.get("collidable"))

    @staticmethod
    def _copy_native_content(
        source_dir: Path,
        target_dir: Path,
        *,
        replace_existing: bool,
    ) -> dict[str, Any]:
        source_dir = source_dir.resolve()
        target_dir = target_dir.resolve()
        if source_dir == target_dir:
            files = [path for path in source_dir.rglob("*") if path.is_file()]
            return {
                "copied": 0,
                "reused": len(files),
                "total": len(files),
                "bytes": sum(path.stat().st_size for path in files),
            }

        copied = 0
        reused = 0
        preserved_modified = 0
        total_bytes = 0
        mismatches: list[str] = []
        for source_file in sorted(path for path in source_dir.rglob("*") if path.is_file()):
            relative = source_file.relative_to(source_dir)
            target_file = target_dir / relative
            source_size = source_file.stat().st_size
            total_bytes += source_size
            if target_file.exists() and not replace_existing:
                if target_file.stat().st_size == source_size:
                    reused += 1
                else:
                    preserved_modified += 1
                    mismatches.append(str(relative))
                continue
            target_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target_file)
            copied += 1
        return {
            "copied": copied,
            "reused": reused,
            "preserved_modified": preserved_modified,
            "mismatches": mismatches,
            "total": copied + reused + preserved_modified,
            "bytes": total_bytes,
        }

    @staticmethod
    def _content_package_path(asset_file: Path, content_dir: Path) -> str:
        relative = asset_file.resolve().relative_to(content_dir.resolve())
        return f"/Game/{relative.with_suffix('').as_posix()}"

    @staticmethod
    def _select_native_map(
        source_maps: list[Path],
        map_paths: list[str],
        *,
        native_map: str,
    ) -> str:
        requested = str(native_map or "").strip().replace("\\", "/")
        if requested:
            requested_name = requested.rsplit("/", 1)[-1].lower()
            for source_map, package_path in zip(source_maps, map_paths):
                candidates = {
                    source_map.stem.lower(),
                    source_map.name.lower(),
                    source_map.as_posix().lower(),
                    package_path.lower(),
                }
                if (
                    requested.lower() in candidates
                    or requested_name in candidates
                    or package_path.lower().endswith(requested.lower())
                ):
                    return package_path
            raise ValueError(f"找不到指定 Map: {native_map}；可选: {', '.join(map_paths)}")

        ranked = sorted(
            zip(source_maps, map_paths),
            key=lambda item: (
                item[0].stem.lower() == "demo",
                -item[0].stat().st_size,
                item[1].lower(),
            ),
        )
        return ranked[0][1]

    def _import_descriptor(
        self,
        descriptor_path: Path,
        descriptor: dict[str, Any],
        *,
        world_id: str,
        project_id: str,
        publish: bool,
        default_spawn_point: dict[str, Any] | list[float] | None,
        package_inspection: ScenePackageInspection | None = None,
        replace_existing: bool = False,
        preview_in_editor: bool = True,
    ) -> dict[str, Any]:
        representation = str(descriptor.get("representation") or "mesh_layout").strip().lower()
        if representation not in {"mesh", "mesh_layout", "hybrid"}:
            raise ValueError(
                f"当前 UE Play Runtime 需要碰撞网格，暂不支持 scene representation={representation}；"
                "请从生成器导出 mesh/collision proxy 后再导入"
            )
        descriptor, ground_alignment, safety_floor = (
            self._apply_descriptor_ground_alignment(
                descriptor_path,
                descriptor,
                default_spawn_point=default_spawn_point,
            )
        )

        resolved_world_id = safe_id(
            world_id
            or descriptor.get("world_id")
            or descriptor.get("scene_id")
            or descriptor_path.stem,
            fallback="world",
        )
        resolved_project_id = safe_id(
            project_id or descriptor.get("project_id") or "",
            fallback="",
        )
        content_root = self._generated_content_root(resolved_world_id)
        prepare_result = self._prepare_generated_content(
            content_root,
            replace_existing=replace_existing,
        )
        base_dir = descriptor_path.parent
        entities: list[WorldEntitySpec] = []
        import_cache: dict[
            tuple[str, str, bool, bool, str],
            list[dict[str, Any]],
        ] = {}
        material_bindings: list[dict[str, Any]] = []
        special_imports: list[dict[str, Any]] = []
        package_assets = (
            package_inspection.assets
            if package_inspection is not None and package_inspection.canonical
            else {}
        )

        environment = (
            descriptor.get("environment")
            or descriptor.get("scene")
            or descriptor.get("environment_source")
            or descriptor.get("source_path")
            or descriptor.get("model")
        )
        if environment:
            environment_ref = self._resolve_entry(
                environment,
                base_dir=base_dir,
                default_role="environment",
                import_cache=import_cache,
                destination_path=self._generated_asset_destination(
                    content_root,
                    self._entry_asset_key(environment, "environment"),
                ),
                material_destination_root=content_root,
                asset_key=self._entry_asset_key(
                    environment,
                    "environment",
                ),
                material_results=material_bindings,
            )
            entities.extend(
                self._environment_entities(
                    environment_ref["artifacts"],
                    transform=environment_ref.get("transform"),
                    collision=bool(environment_ref.get("collision", True)),
                )
            )

        raw_entities = (
            descriptor.get("entities")
            or descriptor.get("objects")
            or descriptor.get("nodes")
            or []
        )
        if not isinstance(raw_entities, list):
            raise ValueError("场景 JSON 的 entities/objects/nodes 必须是数组")

        for index, raw_entry in enumerate(raw_entities):
            if not isinstance(raw_entry, dict):
                continue
            entry = dict(raw_entry)
            package_asset = None
            package_asset_ref = str(entry.get("asset_ref") or "").strip()
            if package_asset_ref:
                package_asset = package_assets.get(package_asset_ref)
                if package_asset is None:
                    raise ValueError(
                        f"场景实体 {index} 引用了未声明的 asset_ref: {package_asset_ref}"
                    )
            role = str(
                entry.get("role")
                or entry.get("kind")
                or (package_asset or {}).get("role")
                or "prop"
            ).strip().lower()
            if role in {"mesh", "object", "static_mesh", "decoration"}:
                role = "prop"
            if role not in {"environment", "prop", "avatar"}:
                role = "prop"
            reference = (
                (package_asset or {}).get("source_path")
                or entry.get("artifact_id")
                or entry.get("asset_id")
                or entry.get("source_path")
                or entry.get("model")
                or entry.get("mesh")
                or entry.get("asset")
            )
            if not reference:
                raise ValueError(f"场景实体 {index} 缺少 artifact_id 或 source_path")
            category = str(
                entry.get("category")
                or (package_asset or {}).get("category")
                or ""
            ).strip()
            category_key = (
                category.lower()
                .replace("-", "_")
                .replace(" ", "_")
            )
            collision_mode = (
                str(entry.get("collision_mode") or "")
                .strip()
                .lower()
                .replace("-", "_")
                .replace(" ", "_")
            )
            force_complex_collision = (
                collision_mode in {
                    "complex",
                    "complex_as_simple",
                    "use_complex_as_simple",
                }
                or category_key in {
                    "collider",
                    "collider_visible",
                    "collision",
                    "collision_mesh",
                }
            )
            gaussian_source = self._gaussian_splat_source(
                reference,
                base_dir=base_dir,
                category=category,
            )
            entity_id = str(
                entry.get("id")
                or entry.get("entity_id")
                or entry.get("node_id")
                or f"{role}_{index}"
            ).strip()
            if gaussian_source is not None:
                asset_key = (
                    package_asset_ref
                    or self._entry_asset_key(
                        reference,
                        f"gaussian_splat_{index}",
                    )
                )
                gaussian_import = self._import_gaussian_splat(
                    gaussian_source,
                    content_root=content_root,
                    asset_key=asset_key,
                )
                special_imports.append(
                    dict(gaussian_import["import"])
                )
                entities.append(
                    WorldEntitySpec(
                        entity_id=entity_id,
                        role=role,
                        artifact_id=str(
                            gaussian_import["artifact"][
                                "artifact_id"
                            ]
                        ),
                        category=category or "gaussian_splat",
                        collision=False,
                        transform=TransformSpec.from_dict(
                            entry.get("transform")
                        ),
                    )
                )
                continue

            entry_collision = (
                bool(entry.get("collision"))
                if "collision" in entry
                else (
                    bool(package_asset.get("collision"))
                    if package_asset is not None
                    else None
                )
            )
            resolved = self._resolve_entry(
                {**entry, "reference": reference},
                base_dir=base_dir,
                default_role=role,
                import_cache=import_cache,
                generate_collision=entry_collision,
                force_complex_collision=force_complex_collision,
                destination_path=self._generated_asset_destination(
                    content_root,
                    package_asset_ref
                    or self._entry_asset_key(reference, f"asset_{index}"),
                ),
                material_destination_root=content_root,
                asset_key=package_asset_ref
                or self._entry_asset_key(reference, f"asset_{index}"),
                material_config=(
                    dict(package_asset.get("material") or {})
                    if package_asset is not None
                    else (
                        dict(entry.get("material") or {})
                        if isinstance(entry.get("material"), dict)
                        else None
                    )
                ),
                material_results=material_bindings,
            )
            for part_index, artifact in enumerate(resolved["artifacts"]):
                part_entity_id = entity_id if part_index == 0 else f"{entity_id}_part_{part_index}"
                entities.append(
                    WorldEntitySpec(
                        entity_id=part_entity_id,
                        role=role,
                        artifact_id=artifact["artifact_id"],
                        category=category,
                        collision=bool(resolved.get("collision", role != "avatar")),
                        transform=TransformSpec.from_dict(entry.get("transform")),
                    )
                )

        if not entities:
            raise ValueError("场景 JSON 没有可加载的 environment 或 entities")

        metadata = dict(descriptor.get("metadata") or {})
        if ground_alignment is not None:
            metadata["ground_alignment"] = ground_alignment
        spawn_point = (
            default_spawn_point
            or descriptor.get("spawn_point")
            or descriptor.get("player_start")
            or self._first_spawn_point(descriptor.get("spawn_points"))
            or {}
        )
        spawn_transform = TransformSpec.from_dict(
            {"location": spawn_point}
            if isinstance(spawn_point, (list, tuple))
            else spawn_point
        )
        if (
            ground_alignment is not None
            and int(ground_alignment.get("grounded_sample_count", 0)) > 0
        ):
            grounded_spawn = spawn_transform.to_dict()
            grounded_spawn["location"]["z"] = (
                float(ground_alignment["target_ground_z_cm"])
                + float(ground_alignment.get("spawn_height_cm", 93.0))
            )
            spawn_transform = TransformSpec.from_dict(grounded_spawn)
        metadata["source_representation"] = representation
        if package_inspection is not None and package_inspection.canonical:
            metadata["scene_package"] = package_inspection.to_dict()
        return self._create_generated_native_map(
            source_path=descriptor_path,
            world_id=resolved_world_id,
            project_id=resolved_project_id,
            entities=entities,
            camera=dict_to_camera(descriptor.get("camera")),
            metadata=metadata,
            spawn_point=spawn_transform,
            content_root=content_root,
            publish=publish,
            replace_existing=replace_existing,
            preview_in_editor=preview_in_editor,
            add_default_lighting=bool(
                descriptor.get("add_default_lighting", True)
            ),
            add_default_ground=bool(
                descriptor.get("add_default_ground", False)
            ),
            material_bindings=material_bindings,
            special_imports=special_imports,
            safety_floor=safety_floor,
            prepare_result=prepare_result,
        )

    @staticmethod
    def _scene_entity_id(entry: dict[str, Any], index: int) -> str:
        role = str(
            entry.get("role")
            or entry.get("kind")
            or "prop"
        ).strip().lower()
        return str(
            entry.get("id")
            or entry.get("entity_id")
            or entry.get("node_id")
            or f"{role}_{index}"
        ).strip()

    @classmethod
    def _apply_descriptor_ground_alignment(
        cls,
        descriptor_path: Path,
        descriptor: dict[str, Any],
        *,
        default_spawn_point: dict[str, Any] | list[float] | None,
    ) -> tuple[
        dict[str, Any],
        dict[str, Any] | None,
        dict[str, Any] | None,
    ]:
        raw_config = descriptor.get(
            "ground_alignment",
            descriptor.get("auto_align_ground"),
        )
        if raw_config in (None, False):
            return descriptor, None, None
        if raw_config is True:
            config: dict[str, Any] = {}
        elif isinstance(raw_config, dict):
            config = dict(raw_config)
        else:
            raise ValueError("ground_alignment 必须是 bool 或 object")
        mode = str(config.get("mode") or "auto").strip().lower()
        if mode in {"off", "disabled", "none"}:
            return descriptor, None, None
        if mode != "auto":
            raise ValueError("ground_alignment.mode 当前只支持 auto")

        raw_entities = descriptor.get("entities") or []
        if not isinstance(raw_entities, list):
            raise ValueError("ground_alignment 需要 entities 数组")
        entries = [
            dict(entry)
            for entry in raw_entities
            if isinstance(entry, dict)
        ]
        source_id = str(config.get("source_entity") or "").strip()
        source_entry = None
        source_index = -1
        for index, entry in enumerate(entries):
            entity_id = cls._scene_entity_id(entry, index)
            category = (
                str(entry.get("category") or "")
                .strip()
                .lower()
                .replace("-", "_")
                .replace(" ", "_")
            )
            if source_id and entity_id == source_id:
                source_entry = entry
                source_index = index
                break
            if not source_id and category in {
                "collider",
                "collision",
                "collision_mesh",
            }:
                source_entry = entry
                source_index = index
                source_id = entity_id
                break
        if source_entry is None:
            raise ValueError(
                "ground_alignment 找不到 source_entity 或 collider entity"
            )
        source_value = (
            config.get("source_path")
            or source_entry.get("source_path")
            or source_entry.get("model")
            or source_entry.get("mesh")
            or source_entry.get("asset")
        )
        source = Path(str(source_value or "")).expanduser()
        if not source.is_absolute():
            source = descriptor_path.parent / source
        source = source.resolve()
        if source.suffix.lower() != ".ply":
            raise ValueError(
                "ground_alignment.source_entity 当前必须引用 polygon mesh PLY"
            )

        sample_points: list[Any] = []
        configured_samples = config.get("sample_points")
        if isinstance(configured_samples, list):
            sample_points.extend(configured_samples)
        if bool(config.get("include_spawn_points", True)):
            for candidate in (
                default_spawn_point,
                descriptor.get("spawn_point"),
                descriptor.get("player_start"),
            ):
                if candidate is not None:
                    sample_points.append(candidate)
            spawn_points = descriptor.get("spawn_points")
            if isinstance(spawn_points, list):
                sample_points.extend(spawn_points)

        source_transform = (
            source_entry.get("transform")
            if isinstance(source_entry.get("transform"), dict)
            else {}
        )
        source_location = (
            source_transform.get("location")
            if isinstance(source_transform.get("location"), dict)
            else {}
        )
        actor_location_xy = (
            float(source_location.get("x", 0.0)),
            float(source_location.get("y", 0.0)),
        )
        alignment = estimate_ply_ground_alignment(
            source,
            sample_points=sample_points,
            target_ground_z_cm=float(
                config.get("target_ground_z_cm", 0.0)
            ),
            actor_location_xy_cm=actor_location_xy,
            source_up_axis=str(config.get("source_up_axis") or "y"),
            unit_scale_cm=float(config.get("unit_scale_cm", 100.0)),
            max_tilt_degrees=float(
                config.get("max_tilt_degrees", 70.0)
            ),
            refinement_radius_cm=float(
                config.get("refinement_radius_cm", 1000.0)
            ),
        )
        alignment_data = alignment.to_dict()
        alignment_data["source_entity"] = source_id
        alignment_data["spawn_height_cm"] = float(
            config.get("spawn_height_cm", 93.0)
        )
        alignment_data["include_spawn_points"] = bool(
            config.get("include_spawn_points", True)
        )

        apply_to_raw = config.get("apply_to")
        apply_to = (
            {
                str(value).strip()
                for value in apply_to_raw
                if str(value).strip()
            }
            if isinstance(apply_to_raw, list)
            else set()
        )
        z_offset = float(config.get("z_offset_cm", 0.0))
        pitch_offset = float(config.get("pitch_offset_degrees", 0.0))
        roll_offset = float(config.get("roll_offset_degrees", 0.0))
        aligned_entries: list[dict[str, Any]] = []
        aligned_ids: list[str] = []
        for index, entry in enumerate(entries):
            entity_id = cls._scene_entity_id(entry, index)
            role = str(entry.get("role") or "prop").strip().lower()
            should_align = (
                entity_id in apply_to
                if apply_to
                else role in {"environment", "prop"}
            )
            if not should_align:
                aligned_entries.append(entry)
                continue
            transform = (
                dict(entry.get("transform"))
                if isinstance(entry.get("transform"), dict)
                else {}
            )
            location = (
                dict(transform.get("location"))
                if isinstance(transform.get("location"), dict)
                else {}
            )
            rotation = (
                dict(transform.get("rotation"))
                if isinstance(transform.get("rotation"), dict)
                else {}
            )
            location["z"] = alignment.location_z_cm + z_offset
            rotation["pitch"] = (
                float(alignment.rotation["pitch"]) + pitch_offset
            )
            rotation["roll"] = (
                float(alignment.rotation["roll"]) + roll_offset
            )
            rotation.setdefault("yaw", 0.0)
            transform["location"] = location
            transform["rotation"] = rotation
            entry["transform"] = transform
            aligned_entries.append(entry)
            aligned_ids.append(entity_id)
        alignment_data["applied_to"] = aligned_ids

        result = dict(descriptor)
        result["entities"] = aligned_entries
        metadata = dict(result.get("metadata") or {})
        metadata["ground_alignment"] = alignment_data
        result["metadata"] = metadata

        safety_floor = cls._safety_floor_from_alignment(
            config.get("safety_floor"),
            alignment_data,
        )
        return result, alignment_data, safety_floor

    @staticmethod
    def _safety_floor_from_alignment(
        raw_config: Any,
        alignment: dict[str, Any],
    ) -> dict[str, Any] | None:
        if raw_config in (None, False):
            return None
        if raw_config is True:
            config: dict[str, Any] = {}
        elif isinstance(raw_config, dict):
            config = dict(raw_config)
        else:
            raise ValueError("ground_alignment.safety_floor 必须是 bool 或 object")
        if not bool(config.get("enabled", True)):
            return None
        bounds_min = alignment["ground_bounds_min_cm"]
        bounds_max = alignment["ground_bounds_max_cm"]
        padding = max(0.0, float(config.get("padding_cm", 50.0)))
        thickness = max(1.0, float(config.get("thickness_cm", 20.0)))
        drop = max(0.0, float(config.get("drop_cm", 10.0)))
        min_x = float(bounds_min[0]) - padding
        min_y = float(bounds_min[1]) - padding
        max_x = float(bounds_max[0]) + padding
        max_y = float(bounds_max[1]) + padding
        size_x = max(
            float(config.get("size_x_cm", max_x - min_x)),
            100.0,
        )
        size_y = max(
            float(config.get("size_y_cm", max_y - min_y)),
            100.0,
        )
        center_x = float(
            config.get("center_x_cm", (min_x + max_x) * 0.5)
        )
        center_y = float(
            config.get("center_y_cm", (min_y + max_y) * 0.5)
        )
        top_z = float(
            config.get(
                "top_z_cm",
                float(alignment["target_ground_z_cm"]) - drop,
            )
        )
        return {
            "enabled": True,
            "location": {
                "x": center_x,
                "y": center_y,
                "z": top_z - thickness * 0.5,
            },
            "size": {
                "x": size_x,
                "y": size_y,
                "z": thickness,
            },
        }

    @staticmethod
    def _gaussian_splat_source(
        reference: Any,
        *,
        base_dir: Path,
        category: str,
    ) -> Path | None:
        value = str(reference or "").strip()
        if not value or value.startswith("/Game/"):
            return None
        source = Path(value).expanduser()
        if not source.is_absolute():
            source = base_dir / source
        source = source.resolve()
        category_key = (
            str(category or "")
            .strip()
            .lower()
            .replace("-", "_")
            .replace(" ", "_")
        )
        explicit = category_key in {
            "3dgs",
            "gaussian",
            "gaussian_splat",
            "splat",
        }
        if source.suffix.lower() == ".spz" and explicit:
            raise ValueError(
                "当前 XV3dGS 1.1.5.1 只注册 PLY 导入工厂；"
                "请使用 Hunyuan 同时导出的 Gaussian PLY"
            )
        if source.suffix.lower() != ".ply":
            return None
        if is_gaussian_splat_ply(source):
            return source
        if explicit:
            raise ValueError(
                f"Gaussian Splat PLY 格式无效或属性不完整: {source}"
            )
        return None

    def _import_gaussian_splat(
        self,
        source: Path,
        *,
        content_root: str,
        asset_key: str,
    ) -> dict[str, Any]:
        destination_path = f"{content_root.rstrip('/')}/Splats"
        resolved_asset_key = safe_id(
            asset_key,
            fallback="gaussian_splat",
        )
        with prepare_gaussian_splat_source(source) as prepared:
            import_result = self.transport.execute_json(
                build_gaussian_splat_import_script(
                    prepared.import_path.as_posix(),
                    destination_path,
                    resolved_asset_key,
                ),
                timeout=300,
            )
            if (
                not isinstance(import_result, dict)
                or not import_result.get("ok")
            ):
                raise RuntimeError(
                    f"XV3dGS Gaussian Splat 导入失败: {import_result!r}"
                )

            actor_path = str(
                import_result.get("actor_path") or ""
            ).strip()
            buffer_path = str(
                import_result.get("buffer_path") or ""
            ).strip()
            if not actor_path or not buffer_path:
                raise RuntimeError(
                    "XV3dGS 导入结果缺少 actor_path 或 buffer_path"
                )
            artifact = ArtifactRecord(
                artifact_id=artifact_id_for(
                    "ue",
                    "Blueprint",
                    resolved_asset_key,
                    actor_path,
                ),
                asset_id=resolved_asset_key,
                package_id=resolved_asset_key,
                type="environment",
                category="gaussian_splat",
                representation="gaussian_splat",
                primary_asset={
                    "backend": "ue",
                    "class": "Blueprint",
                    "path": actor_path,
                },
                runtime_capabilities={
                    "renderable": True,
                    "spawnable": True,
                    "collidable": False,
                    "playable": False,
                },
                backend="ue",
                backend_class="Blueprint",
                backend_path=actor_path,
                source_path=str(prepared.original_path),
                spawnable=True,
                state="ready",
                editor_backend={
                    "backend": "ue",
                    "path": actor_path,
                    "package_path": destination_path,
                },
                runtime={
                    "spawnable": True,
                    "class": "Blueprint",
                },
                metadata={
                    "dest_path": destination_path,
                    "package_path": destination_path,
                    "buffer_path": buffer_path,
                    "actor_blueprint_path": actor_path,
                    "source_preprocessing": (
                        prepared.summary.to_dict()
                    ),
                },
            )
            self.assets.artifacts.upsert(artifact)
            preprocessing = prepared.summary.to_dict()
            preprocessing.pop("output_path", None)
            return {
                "artifact": artifact.to_dict(),
                "import": {
                    **dict(import_result),
                    "source_path": str(prepared.original_path),
                    "source_preprocessing": preprocessing,
                },
            }

    def _resolve_entry(
        self,
        entry: Any,
        *,
        base_dir: Path,
        default_role: str,
        import_cache: dict[
            tuple[str, str, bool, bool, str],
            list[dict[str, Any]],
        ] | None = None,
        generate_collision: bool | None = None,
        force_complex_collision: bool = False,
        destination_path: str = "",
        material_destination_root: str = "",
        asset_key: str = "",
        material_config: dict[str, Any] | None = None,
        material_results: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if isinstance(entry, str):
            value = entry
            transform = {}
        elif isinstance(entry, dict):
            value = entry.get("reference") or entry.get("artifact_id") or entry.get("source_path")
            transform = entry.get("transform") or {}
        else:
            raise ValueError(f"无效的场景资源引用: {entry!r}")

        value = str(value or "").strip()
        if not value:
            raise ValueError("场景资源引用不能为空")
        collision = (
            default_role in {"environment", "prop"}
            if generate_collision is None
            else bool(generate_collision)
        )
        existing = self.assets.artifacts.get(value)
        if existing is not None:
            return {
                "artifacts": [existing.to_dict()],
                "transform": transform,
                "collision": collision,
            }
        if value.startswith("/Game/"):
            raise ValueError(
                f"场景 JSON 不能直接使用未注册的 UE 路径: {value}；"
                "请先导入资产，或将 artifact_id 写入场景描述"
            )

        source = Path(value).expanduser()
        if not source.is_absolute():
            source = base_dir / source
        source = source.resolve()
        cache_key = (
            default_role,
            str(source),
            collision,
            bool(force_complex_collision),
            destination_path,
        )
        if import_cache is not None and cache_key in import_cache:
            return {
                "artifacts": list(import_cache[cache_key]),
                "transform": transform,
                "collision": collision,
            }
        imported = self._import_assets(
            source,
            "environment" if default_role == "environment" else "prop",
            generate_collision=collision,
            force_complex_collision=force_complex_collision,
            dest_path=destination_path,
        )
        if destination_path:
            material_result = self.materials.bind(
                asset_id=asset_key or source.stem,
                source_path=source,
                mesh_asset_paths=[
                    str(artifact.get("backend_path") or "")
                    for artifact in imported
                    if artifact.get("backend_path")
                ],
                destination_root=(
                    material_destination_root
                    or destination_path
                ),
                material_config=material_config,
            )
            if material_results is not None:
                material_results.append(material_result)
        if import_cache is not None:
            import_cache[cache_key] = list(imported)
        return {
            "artifacts": imported,
            "transform": transform,
            "collision": collision,
        }

    def _import_assets(
        self,
        source: Path,
        asset_type: str,
        *,
        generate_collision: bool | None = None,
        force_complex_collision: bool = False,
        dest_path: str = "",
    ) -> list[dict[str, Any]]:
        collision = (
            asset_type in {"environment", "prop"}
            if generate_collision is None
            else bool(generate_collision)
        )
        result = self.assets.import_asset(
            str(source),
            asset_type,
            dst_path=dest_path,
            generate_collision=collision,
            force_complex_collision=bool(force_complex_collision),
            category=asset_type,
            combine_meshes=True,
            include_all_static_meshes=True,
        )
        artifacts = result.get("artifacts") or []
        if not artifacts:
            raise RuntimeError(f"场景资源导入没有生成 Artifact: {source}")
        return list(artifacts)

    @staticmethod
    def _environment_entities(
        artifacts: list[dict[str, Any]],
        *,
        transform: dict[str, Any] | None = None,
        collision: bool = True,
    ) -> list[WorldEntitySpec]:
        result = []
        for index, artifact in enumerate(artifacts):
            entity_id = "environment_root" if index == 0 else f"environment_part_{index}"
            result.append(
                WorldEntitySpec(
                    entity_id=entity_id,
                    role="environment",
                    artifact_id=str(artifact.get("artifact_id") or ""),
                    collision=collision,
                    transform=TransformSpec.from_dict(transform),
                )
            )
        return result

    def _create_generated_native_map(
        self,
        *,
        source_path: Path,
        world_id: str,
        project_id: str,
        entities: list[WorldEntitySpec],
        metadata: dict[str, Any],
        spawn_point: TransformSpec,
        camera,
        content_root: str,
        publish: bool,
        replace_existing: bool,
        preview_in_editor: bool,
        add_default_lighting: bool,
        add_default_ground: bool,
        material_bindings: list[dict[str, Any]],
        prepare_result: dict[str, Any],
        special_imports: list[dict[str, Any]] | None = None,
        safety_floor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        layout_spec = WorldSpec(
            world_id=world_id,
            project_id=project_id,
            entities=entities,
            camera=camera,
            metadata=dict(metadata),
        )
        plans = self.worlds.build_spawn_plan(layout_spec)
        entities_by_id = {
            entity.entity_id: entity
            for entity in entities
        }
        actor_specs = [
            {
                "entity_id": plan.entity_id,
                "actor_label": f"A3Game_{plan.entity_id}",
                "asset_path": plan.backend_path,
                "backend_class": plan.backend_class,
                "collision": plan.collision,
                "force_complex_collision": (
                    entities_by_id[plan.entity_id]
                    .category.strip()
                    .lower()
                    .replace("-", "_")
                    .replace(" ", "_")
                    in {
                        "collider",
                        "collider_visible",
                        "collision",
                        "collision_mesh",
                    }
                ),
                "visible": (
                    entities_by_id[plan.entity_id]
                    .category.strip()
                    .lower()
                    .replace("-", "_")
                    not in {
                        "collider",
                        "collision",
                        "collision_mesh",
                    }
                ),
                "transform": plan.transform.to_dict(),
            }
            for plan in plans
        ]
        map_path = f"{content_root}/Map/{world_id}"
        map_build = self.transport.execute_json(
            build_generated_scene_map_script(
                map_path,
                actor_specs,
                spawn_point=spawn_point.to_dict(),
                replace_existing=replace_existing,
                add_default_lighting=add_default_lighting,
                add_default_ground=add_default_ground,
                safety_floor=safety_floor,
                preview_in_editor=preview_in_editor,
            ),
            timeout=240,
        )
        if not isinstance(map_build, dict) or not map_build.get("ok"):
            raise RuntimeError(f"UE 生成场景地图失败: {map_build!r}")

        resolved_spawn_point = TransformSpec.from_dict(
            map_build.get("player_start")
            if isinstance(map_build.get("player_start"), dict)
            else spawn_point.to_dict()
        )
        native_metadata = dict(metadata)
        native_metadata.update(
            {
                "representation": "native_ue_level",
                "source_path": str(source_path),
                "native_content_root": content_root,
                "level_path": map_path,
                "maps": [map_path],
                "spawn_point": resolved_spawn_point.to_dict(),
                "spawn_point_mode": "actor",
                "spawn_point_source": (
                    "generated_ground_trace"
                    if map_build.get("player_start_grounded")
                    else "a3game_scene_package"
                ),
                "collidable": bool(
                    (map_build.get("collision") or {}).get("collidable")
                ),
                "collision_audit": dict(map_build.get("collision") or {}),
                "navigable": True,
                "interactive": True,
                "generated_scene": True,
                "layout_entity_count": len(entities),
            }
        )
        spec = WorldSpec(
            world_id=world_id,
            project_id=project_id,
            entities=[],
            camera=camera,
            metadata=native_metadata,
        )
        result = self._save_world(
            spec,
            publish=publish,
            source_path=source_path,
        )
        result["generated_content"] = {
            "content_root_path": content_root,
            "map_path": map_path,
            "asset_count": len(
                {
                    actor["asset_path"]
                    for actor in actor_specs
                }
            ),
            "layout_entity_count": len(entities),
            "map_build": map_build,
            "material_bindings": list(material_bindings),
            "special_imports": list(special_imports or []),
            "prepare": dict(prepare_result),
        }
        return result

    def _prepare_generated_content(
        self,
        content_root: str,
        *,
        replace_existing: bool,
    ) -> dict[str, Any]:
        result = self.transport.execute_json(
            build_generated_scene_prepare_script(
                content_root,
                replace_existing=replace_existing,
            ),
            timeout=120,
        )
        if not isinstance(result, dict) or not result.get("ok"):
            raise RuntimeError(f"UE Scene Content 预处理失败: {result!r}")
        return result

    @staticmethod
    def _generated_content_root(world_id: str) -> str:
        return (
            "/Game/Imported/Scenes/"
            f"{safe_id(world_id, fallback='scene')}"
        )

    @staticmethod
    def _generated_asset_destination(content_root: str, asset_key: str) -> str:
        return (
            f"{content_root.rstrip('/')}/Meshes/"
            f"{safe_id(asset_key, fallback='asset')}"
        )

    @staticmethod
    def _entry_asset_key(entry: Any, fallback: str) -> str:
        value = entry
        if isinstance(entry, dict):
            value = (
                entry.get("source")
                or entry.get("source_path")
                or entry.get("reference")
                or entry.get("asset_id")
                or ""
            )
        text = str(value or "").strip()
        if not text or text.startswith("/Game/"):
            return safe_id(fallback, fallback="asset")
        return safe_id(Path(text).stem, fallback=safe_id(fallback, fallback="asset"))

    @staticmethod
    def _spawn_transform(value: Any) -> TransformSpec:
        if isinstance(value, dict) and any(
            key in value
            for key in ("location", "rotation", "scale")
        ):
            return TransformSpec.from_dict(value)
        if value is None:
            return TransformSpec()
        return TransformSpec.from_dict({"location": value})

    def _save_world(self, spec: WorldSpec, *, publish: bool, source_path: Path) -> dict[str, Any]:
        draft = self.worlds.create_draft(
            spec,
            project_id=spec.project_id,
            metadata={"source_path": str(source_path), "import_mode": "scene"},
        )
        validation = self.worlds.validate_draft(draft.draft_id)
        if not validation.get("ok"):
            raise ValueError("; ".join(validation.get("errors") or ["场景 World 校验失败"]))
        result: dict[str, Any] = {
            "ok": True,
            "source_path": str(source_path),
            "world": spec.to_dict(),
            "draft": draft.to_dict(),
            "validation": validation,
        }
        if publish:
            package = self.worlds.publish_draft(draft.draft_id)
            result["package"] = package.to_dict()
        return result

    @staticmethod
    def _load_descriptor(path: Path) -> dict[str, Any]:
        return load_scene_descriptor(path)

    @staticmethod
    def _first_spawn_point(value: Any) -> Any:
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, dict):
                return first.get("transform") or first
        return {}


def dict_to_camera(value: Any):
    return CameraSpec.from_dict(value if isinstance(value, dict) else {})


__all__ = ["SceneImportService"]
