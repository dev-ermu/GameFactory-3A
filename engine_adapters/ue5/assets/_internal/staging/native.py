"""Safe staging for uploaded native Unreal scene content."""

import os
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from engine_adapters.ue5.config import UEClientConfig


SUPPORTED_STAGED_SUFFIXES = {
    ".umap",
    ".uasset",
    ".json",
    ".fbx",
    ".glb",
    ".gltf",
    ".obj",
    ".ply",
    ".usd",
    ".usda",
    ".usdc",
}


@dataclass(frozen=True)
class StagedNativeScene:
    mode: str
    source_dir: str
    staged: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "source_dir": self.source_dir,
            "staged": self.staged,
        }


class NativeSceneUploadService:
    def __init__(self, staging_root: str | Path | None = None) -> None:
        self.staging_root = Path(
            staging_root
            or UEClientConfig.resolve().data_root
            / "uploads"
            / "native_scenes"
        )

    def stage(
        self,
        *,
        archive_path: str = "",
        directory_files: list[Any] | None = None,
    ) -> StagedNativeScene:
        if bool(archive_path) == bool(directory_files):
            raise ValueError(
                "Provide exactly one of archive_path or directory_files"
            )
        stage_root = self.staging_root / uuid4().hex
        stage_root.mkdir(parents=True, exist_ok=False)
        try:
            if archive_path:
                source_dir = self._stage_archive(
                    Path(archive_path).expanduser().resolve(),
                    stage_root,
                )
                mode = "zip"
            else:
                source_dir = self._stage_directory(
                    list(directory_files or []),
                    stage_root,
                )
                mode = "directory"
            self._validate_scene_content(source_dir)
            return StagedNativeScene(
                mode=mode,
                source_dir=str(source_dir),
            )
        except Exception:
            shutil.rmtree(stage_root, ignore_errors=True)
            raise

    @staticmethod
    def _stage_archive(archive: Path, stage_root: Path) -> Path:
        if not archive.is_file():
            raise FileNotFoundError(f"Archive not found: {archive}")
        if archive.suffix.lower() != ".zip":
            raise ValueError(f"Only ZIP scene archives are supported: {archive}")
        with zipfile.ZipFile(archive) as bundle:
            members = [
                info
                for info in bundle.infolist()
                if not info.is_dir()
            ]
            if not members:
                raise ValueError(f"Scene archive is empty: {archive}")
            names = [
                NativeSceneUploadService._safe_archive_path(info.filename)
                for info in members
            ]
            first_parts = {name.parts[0] for name in names if name.parts}
            has_single_root = (
                len(first_parts) == 1
                and all(len(name.parts) > 1 for name in names)
            )
            source_dir = (
                stage_root / next(iter(first_parts))
                if has_single_root
                else stage_root / archive.stem
            )
            source_dir.mkdir(parents=True, exist_ok=True)
            for info, relative in zip(members, names):
                if has_single_root:
                    relative = Path(*relative.parts[1:])
                target = (source_dir / relative).resolve()
                NativeSceneUploadService._ensure_within(
                    target,
                    source_dir.resolve(),
                    info.filename,
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(info) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
        return source_dir

    @staticmethod
    def _stage_directory(files: list[Any], stage_root: Path) -> Path:
        if not files:
            raise ValueError("Directory upload contains no files")
        records = [
            NativeSceneUploadService._directory_file_record(value)
            for value in files
        ]
        paths = [path for path, _relative in records]
        missing = [path for path in paths if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"Uploaded file not found: {missing[0]}")
        relative_paths = [relative for _path, relative in records]
        if all(relative_paths):
            return NativeSceneUploadService._stage_relative_directory(
                records,
                stage_root,
            )
        if any(relative_paths):
            raise ValueError(
                "Directory upload is missing relative paths for some files"
            )
        if NativeSceneUploadService._is_flattened_gradio_upload(paths):
            raise ValueError(
                "Gradio 浏览器目录上传无法保留 UE Content 的相对目录。"
                "请上传包含 Content 层级的 ZIP，或填写服务器本地目录路径。"
            )
        common = Path(os.path.commonpath([str(path) for path in paths]))
        source_root = common if common.is_dir() else common.parent
        source_dir = stage_root / source_root.name
        source_dir.mkdir(parents=True, exist_ok=True)
        for path in paths:
            relative = path.relative_to(source_root)
            target = source_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        return source_dir

    @staticmethod
    def _directory_file_record(value: Any) -> tuple[Path, str]:
        if isinstance(value, dict):
            raw_path = value.get("path") or value.get("name")
            relative_path = (
                value.get("relative_path")
                or value.get("orig_name")
                or ""
            )
        else:
            raw_path = getattr(value, "path", None) or getattr(
                value,
                "name",
                value,
            )
            relative_path = getattr(value, "orig_name", "") or ""
        if not raw_path:
            raise ValueError("Directory upload contains an empty file path")
        return (
            Path(str(raw_path)).expanduser().resolve(),
            str(relative_path).strip(),
        )

    @staticmethod
    def _stage_relative_directory(
        records: list[tuple[Path, str]],
        stage_root: Path,
    ) -> Path:
        relative_paths = [
            NativeSceneUploadService._safe_directory_path(relative)
            for _path, relative in records
        ]
        first_parts = {
            relative.parts[0]
            for relative in relative_paths
            if relative.parts
        }
        has_selected_root = (
            len(first_parts) == 1
            and all(len(relative.parts) > 1 for relative in relative_paths)
        )
        if not has_selected_root:
            raise ValueError(
                "浏览器目录上传没有提供统一的根目录；"
                "请重新选择完整 Scene/Content 文件夹或上传 ZIP"
            )
        source_dir = stage_root / next(iter(first_parts))
        source_dir.mkdir(parents=True, exist_ok=True)
        copied_targets: set[Path] = set()
        for (source, _relative_text), relative in zip(
            records,
            relative_paths,
        ):
            relative = Path(*relative.parts[1:])
            target = (source_dir / relative).resolve()
            NativeSceneUploadService._ensure_within(
                target,
                source_dir.resolve(),
                str(relative),
            )
            if target in copied_targets:
                raise ValueError(
                    f"Directory upload contains duplicate path: {relative}"
                )
            copied_targets.add(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        return source_dir

    @staticmethod
    def _safe_directory_path(value: str) -> Path:
        normalized = value.replace("\\", "/")
        path = Path(normalized)
        if (
            path.is_absolute()
            or not path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValueError(
                f"Directory upload contains an unsafe relative path: {value}"
            )
        return path

    @staticmethod
    def _is_flattened_gradio_upload(files: list[Path]) -> bool:
        if len(files) < 2:
            return False
        hash_pattern = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
        return all(
            hash_pattern.fullmatch(path.parent.name)
            and path.parent.parent.name.lower() == "gradio"
            for path in files
        )

    @staticmethod
    def _safe_archive_path(value: str) -> Path:
        normalized = value.replace("\\", "/")
        path = Path(normalized)
        if (
            path.is_absolute()
            or not path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValueError(f"ZIP 包含不安全路径: {value}")
        return path

    @staticmethod
    def _ensure_within(target: Path, root: Path, source: str) -> None:
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"ZIP 包含不安全路径: {source}") from exc

    @staticmethod
    def _validate_scene_content(source_dir: Path) -> None:
        if not any(
            path.suffix.lower() in SUPPORTED_STAGED_SUFFIXES
            for path in source_dir.rglob("*")
            if path.is_file()
        ):
            raise ValueError(
                f"Staged scene contains no supported files: {source_dir}"
            )
