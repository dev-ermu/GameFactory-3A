"""Shared helpers for installing native Unreal Content directories."""

import shutil
from pathlib import Path
from typing import Any


UE_CONTENT_FOLDERS = {
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


def resolve_native_content_source(
    source_dir: Path,
) -> tuple[Path, Path, str]:
    current = source_dir.resolve()
    unwrapped = False
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
                first_part.lower() not in UE_CONTENT_FOLDERS
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


def copy_native_content(
    source_dir: Path,
    target_dir: Path,
    *,
    replace_existing: bool,
) -> dict[str, Any]:
    source_dir = source_dir.resolve()
    target_dir = target_dir.resolve()
    if source_dir == target_dir:
        files = [
            path for path in source_dir.rglob("*") if path.is_file()
        ]
        return {
            "copied": 0,
            "reused": len(files),
            "preserved_modified": 0,
            "mismatches": [],
            "total": len(files),
            "bytes": sum(path.stat().st_size for path in files),
        }

    copied = 0
    reused = 0
    preserved_modified = 0
    total_bytes = 0
    mismatches: list[str] = []
    for source_file in sorted(
        path for path in source_dir.rglob("*") if path.is_file()
    ):
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


def content_package_path(
    asset_file: Path,
    content_dir: Path,
) -> str:
    relative = asset_file.resolve().relative_to(content_dir.resolve())
    return f"/Game/{relative.with_suffix('').as_posix()}"


def content_root_path(
    target_dir: Path,
    content_dir: Path,
) -> str:
    relative = target_dir.resolve().relative_to(content_dir.resolve())
    return f"/Game/{relative.as_posix()}" if relative.parts else "/Game"


__all__ = [
    "content_package_path",
    "content_root_path",
    "copy_native_content",
    "resolve_native_content_source",
]
