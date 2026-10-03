"""Validate registered Unreal records against the active project Content."""

import os
from pathlib import Path
from typing import Any


def configured_project_content_dir() -> Path | None:
    project_value = (
        os.environ.get("A3GAME_UE_PROJECT", "").strip()
    )
    if not project_value:
        return None
    project_file = Path(project_value).expanduser()
    if project_file.suffix.lower() != ".uproject":
        return None
    return project_file.resolve().parent / "Content"


def project_package_exists(
    package_path: Any,
    *,
    suffix: str,
    content_dir: Path | None = None,
) -> bool:
    content_dir = content_dir or configured_project_content_dir()
    if content_dir is None:
        return True
    package = str(package_path or "").strip().replace("\\", "/")
    package = package.split(".", 1)[0]
    if not package.startswith("/Game/"):
        return True
    relative = package.removeprefix("/Game/").strip("/")
    if not relative:
        return False
    target = content_dir.joinpath(*relative.split("/")).with_suffix(suffix)
    return target.is_file()


def project_artifact_exists(
    record: Any,
    *,
    content_dir: Path | None = None,
) -> bool:
    if isinstance(record, dict):
        backend_path = (
            record.get("backend_path")
            or record.get("path")
            or (record.get("primary_asset") or {}).get("path")
        )
    else:
        backend_path = getattr(record, "backend_path", "")
    return project_package_exists(
        backend_path,
        suffix=".uasset",
        content_dir=content_dir,
    )


def project_runtime_package_exists(
    package: dict[str, Any],
    *,
    content_dir: Path | None = None,
) -> bool:
    content_dir = content_dir or configured_project_content_dir()
    if content_dir is None:
        return True
    manifest = package.get("manifest")
    if not isinstance(manifest, dict):
        return False
    world = manifest.get("world")
    world = world if isinstance(world, dict) else {}
    metadata = world.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    ue = manifest.get("ue")
    ue = ue if isinstance(ue, dict) else {}
    level_path = ue.get("level_path") or metadata.get("level_path")
    if level_path:
        return project_package_exists(
            level_path,
            suffix=".umap",
            content_dir=content_dir,
        )
    artifacts = [
        item
        for item in manifest.get("artifacts") or []
        if isinstance(item, dict)
    ]
    return bool(artifacts) and all(
        project_artifact_exists(item, content_dir=content_dir)
        for item in artifacts
    )


def project_asset_records(
    asset_service: Any,
    asset_type: str,
) -> list[dict[str, Any]]:
    content_dir = configured_project_content_dir()
    if content_dir is not None:
        registry = getattr(asset_service, "artifacts", None)
        if (
            asset_type not in {"avatar", "motion", "skeleton"}
            and registry is not None
        ):
            registered = [
                record.to_dict()
                for record in registry.list(
                    type=asset_type,
                    backend="ue",
                )
                if (
                    record.state == "ready"
                    and project_artifact_exists(
                        record,
                        content_dir=content_dir,
                    )
                )
            ]
            if registered:
                return registered
        assets = _list_project_imported_assets(
            asset_type,
            content_dir,
        )
    else:
        try:
            assets = asset_service.list_assets(asset_type)
        except Exception:
            return []
    result = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        backend_path = str(asset.get("path") or "").strip()
        if not backend_path:
            continue
        class_name = str(asset.get("class") or "")
        spawnable = asset_type in {
            "avatar",
            "environment",
            "effect",
            "prop",
        }
        playable = asset_type == "motion"
        metadata = {
            key: value
            for key, value in {
                "display_name": asset.get("display_name"),
                "package_path": asset.get("package_path"),
                "skeleton_path": asset.get("skeleton_path"),
                "skeleton_name": asset.get("skeleton_name"),
                "source": asset.get("source"),
            }.items()
            if value not in {None, ""}
        }
        result.append(
            {
                "artifact_id": backend_path,
                "asset_id": str(
                    asset.get("name")
                    or backend_path.rsplit("/", 1)[-1]
                ),
                "package_id": str(
                    asset.get("package_path")
                    or backend_path.rsplit("/", 1)[0]
                ),
                "type": asset_type,
                "category": "",
                "representation": class_name,
                "primary_asset": {
                    "backend": "ue",
                    "class": class_name,
                    "path": backend_path,
                },
                "runtime_capabilities": {
                    "renderable": asset_type != "motion",
                    "spawnable": spawnable,
                    "collidable": False,
                    "playable": playable,
                },
                "backend": "ue",
                "backend_class": class_name,
                "backend_path": backend_path,
                "source_path": "",
                "spawnable": spawnable,
                "state": "ready",
                "metadata": metadata,
            }
        )
    return result


def project_scene_records(
    package_registry: Any,
    *,
    project_id: str = "",
) -> list[dict[str, Any]]:
    """Return imported UE maps, enriched with Runtime Package metadata."""

    content_dir = configured_project_content_dir()
    records_by_level: dict[str, dict[str, Any]] = {}
    packages = package_registry.list_packages(project_id=project_id)
    for package in packages:
        if not isinstance(package, dict):
            continue
        manifest = package.get("manifest")
        manifest = manifest if isinstance(manifest, dict) else {}
        world = manifest.get("world")
        world = world if isinstance(world, dict) else {}
        metadata = world.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        ue = manifest.get("ue")
        ue = ue if isinstance(ue, dict) else {}
        level_path = str(
            ue.get("level_path")
            or metadata.get("level_path")
            or ""
        ).strip()
        if not level_path or not project_runtime_package_exists(
            package,
            content_dir=content_dir,
        ):
            continue
        record = {
            "scene_id": str(
                package.get("world_id")
                or world.get("world_id")
                or level_path.rsplit("/", 1)[-1]
            ),
            "world_id": str(
                package.get("world_id")
                or world.get("world_id")
                or ""
            ),
            "project_id": str(package.get("project_id") or ""),
            "package_id": str(package.get("package_id") or ""),
            "status": str(package.get("status") or ""),
            "created_at": float(package.get("created_at") or 0.0),
            "level_path": level_path,
            "content_root": str(
                ue.get("content_root")
                or metadata.get("native_content_root")
                or ""
            ),
            "source": "runtime_package",
            "runtime_ready": bool(manifest.get("runtime_ready", False)),
            "package": package,
        }
        current = records_by_level.get(level_path)
        if current is None or record["created_at"] > current["created_at"]:
            records_by_level[level_path] = record

    if content_dir is not None:
        imported_scenes = content_dir / "Imported" / "Scenes"
        if imported_scenes.is_dir():
            for map_file in sorted(imported_scenes.rglob("*.umap")):
                level_path = project_file_package_path(
                    map_file,
                    content_dir,
                )
                if level_path in records_by_level:
                    continue
                relative = map_file.relative_to(imported_scenes)
                scene_id = (
                    relative.parts[0]
                    if len(relative.parts) > 1
                    else map_file.stem
                )
                records_by_level[level_path] = {
                    "scene_id": scene_id,
                    "world_id": scene_id,
                    "project_id": "",
                    "package_id": "",
                    "status": "imported",
                    "created_at": map_file.stat().st_mtime,
                    "level_path": level_path,
                    "content_root": (
                        f"/Game/Imported/Scenes/{relative.parts[0]}"
                        if len(relative.parts) > 1
                        else "/Game/Imported/Scenes"
                    ),
                    "source": "project_content_scan",
                    "runtime_ready": False,
                    "package": {},
                }

    return sorted(
        records_by_level.values(),
        key=lambda item: (
            str(item.get("scene_id") or "").lower(),
            str(item.get("level_path") or "").lower(),
        ),
    )


def project_imported_assets(asset_type: str) -> list[dict[str, Any]]:
    content_dir = configured_project_content_dir()
    if content_dir is None:
        return []
    return _list_project_imported_assets(asset_type, content_dir)


def _list_project_imported_assets(
    asset_type: str,
    content_dir: Path,
) -> list[dict[str, Any]]:
    if asset_type in {"avatar", "motion"}:
        from engine_adapters.ue5.assets._internal.ue.local_scan import (
            dedupe_avatar_assets,
            list_local_imported_assets,
        )

        assets = list_local_imported_assets(asset_type)
        return (
            dedupe_avatar_assets(assets)
            if asset_type == "avatar"
            else assets
        )

    imported_root = content_dir / "Imported"
    if asset_type == "skeleton":
        roots = [imported_root / "Avatars"]
        class_name = "Skeleton"
        predicate = lambda path: path.stem.lower().endswith("_skeleton")
    elif asset_type == "environment":
        roots = [imported_root / "Environments"]
        class_name = "StaticMesh"
        predicate = _looks_like_static_mesh_file
    elif asset_type == "prop":
        roots = [imported_root / "Props"]
        class_name = "StaticMesh"
        predicate = _looks_like_static_mesh_file
    elif asset_type == "effect":
        roots = [imported_root / "Effects"]
        class_name = "NiagaraSystem"
        predicate = lambda path: path.stem.lower().startswith(
            ("ns_", "fx_", "p_")
        )
    else:
        return []

    assets = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.uasset")):
            if not predicate(path):
                continue
            package_path = project_file_package_path(path, content_dir)
            assets.append(
                {
                    "name": path.stem,
                    "path": package_path,
                    "class": class_name,
                    "package_path": package_path.rsplit("/", 1)[0],
                    "source": "project_content_scan",
                }
            )
    return assets


def _looks_like_static_mesh_file(path: Path) -> bool:
    stem = path.stem.lower()
    return not stem.startswith(
        (
            "m_",
            "mi_",
            "mf_",
            "t_",
            "sk_",
            "anim_",
            "ns_",
        )
    ) and not stem.endswith(
        (
            "_material",
            "_physicsasset",
            "_skeleton",
        )
    )


def project_file_package_path(path: Path, content_dir: Path) -> str:
    relative = path.resolve().relative_to(
        content_dir.resolve()
    ).with_suffix("")
    return f"/Game/{relative.as_posix()}"


__all__ = [
    "configured_project_content_dir",
    "project_asset_records",
    "project_artifact_exists",
    "project_file_package_path",
    "project_imported_assets",
    "project_package_exists",
    "project_runtime_package_exists",
    "project_scene_records",
]
