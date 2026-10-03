"""Unified staging and inspection for native and generated effect sources."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine_adapters.ue5.config import UEClientConfig

from ..staging import NativeSceneUploadService
from .package import (
    EFFECT_PACKAGE_FILENAME,
    EFFECT_PACKAGE_FILENAMES,
    EFFECT_PACKAGE_SOURCE_SUFFIXES,
    inspect_effect_descriptor,
)


@dataclass(frozen=True)
class EffectSourceEntry:
    entry_id: str
    source_path: str
    kind: str

    def to_dict(self) -> dict[str, str]:
        return {
            "entry_id": self.entry_id,
            "source_path": self.source_path,
            "kind": self.kind,
        }


@dataclass(frozen=True)
class StagedEffectSource:
    mode: str
    effect_kind: str
    source_path: str
    recommended_entry_id: str
    entries: tuple[EffectSourceEntry, ...]
    staged: bool
    package_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "effect_kind": self.effect_kind,
            "source_path": self.source_path,
            "recommended_entry_id": self.recommended_entry_id,
            "entries": [entry.to_dict() for entry in self.entries],
            "staged": self.staged,
            "package_summary": dict(self.package_summary),
        }


class EffectSourceUploadService:
    def __init__(self, staging_root: str | Path | None = None) -> None:
        self.native = NativeSceneUploadService(
            staging_root
            or UEClientConfig.resolve().data_root
            / "uploads"
            / "effects"
        )

    def stage_effect(
        self,
        *,
        archive_path: str = "",
        directory_files: list[Any] | None = None,
        file_path: str = "",
    ) -> StagedEffectSource:
        selected = sum(
            bool(value)
            for value in (archive_path, directory_files, file_path)
        )
        if selected != 1:
            raise ValueError(
                "Provide exactly one effect archive, directory, or file"
            )
        if file_path:
            source = Path(file_path).expanduser().resolve()
            if not source.is_file():
                raise FileNotFoundError(
                    f"Effect source not found: {source}"
                )
            entry = self._entry_for_file(source.name, source)
            package_summary: dict[str, Any] = {}
            if source.name.lower() in EFFECT_PACKAGE_FILENAMES:
                package_summary = inspect_effect_descriptor(
                    source
                ).to_dict()
            return StagedEffectSource(
                mode="file",
                effect_kind="generated",
                source_path=str(source),
                recommended_entry_id=entry.entry_id,
                entries=(entry,),
                staged=False,
                package_summary=package_summary,
            )

        staged = self.native.stage(
            archive_path=archive_path,
            directory_files=directory_files,
        )
        return self._inspect_staged(
            Path(staged.source_dir),
            mode=staged.mode,
        )

    def inspect_local_directory(
        self,
        directory_path: str,
    ) -> StagedEffectSource:
        source_root = Path(directory_path).expanduser().resolve()
        if not source_root.is_dir():
            raise NotADirectoryError(
                f"Effect directory not found: {source_root}"
            )
        return self._inspect_staged(
            source_root,
            mode="local_directory",
            staged=False,
        )

    def resolve_entry(
        self,
        staged: dict[str, Any],
        entry_id: str,
    ) -> EffectSourceEntry:
        for raw_entry in staged.get("entries") or []:
            if str(raw_entry.get("entry_id") or "") == entry_id:
                return EffectSourceEntry(
                    entry_id=entry_id,
                    source_path=str(
                        raw_entry.get("source_path") or ""
                    ),
                    kind=str(raw_entry.get("kind") or ""),
                )
        raise KeyError(f"Effect source entry not found: {entry_id}")

    def _inspect_staged(
        self,
        source_root: Path,
        *,
        mode: str,
        staged: bool = True,
    ) -> StagedEffectSource:
        files = sorted(
            path for path in source_root.rglob("*") if path.is_file()
        )
        native_assets = sorted(source_root.rglob("*.uasset"))
        canonical = next(
            (
                path
                for path in files
                if path.name.lower() in EFFECT_PACKAGE_FILENAMES
            ),
            None,
        )
        package_summary: dict[str, Any] = {}
        if canonical is not None:
            package_summary = inspect_effect_descriptor(
                canonical
            ).to_dict()
            if (
                native_assets
                and package_summary.get("representation")
                == "native_ue_content"
            ):
                entries = tuple(
                    EffectSourceEntry(
                        entry_id=path.relative_to(
                            source_root
                        ).as_posix(),
                        source_path=str(path),
                        kind="native_asset",
                    )
                    for path in native_assets
                )
                recommended = next(
                    (
                        entry.entry_id
                        for entry in entries
                        if Path(entry.entry_id).stem.lower().startswith(
                            ("ns_", "fx_", "p_")
                        )
                    ),
                    entries[0].entry_id,
                )
                return StagedEffectSource(
                    mode=mode,
                    effect_kind="native_ue",
                    source_path=str(source_root),
                    recommended_entry_id=recommended,
                    entries=entries,
                    staged=staged,
                    package_summary=package_summary,
                )
            entries = tuple(
                self._entry_for_file(
                    path.relative_to(source_root).as_posix(),
                    path,
                )
                for path in files
                if self._is_generated_entry(path)
            )
            return StagedEffectSource(
                mode=mode,
                effect_kind="generated",
                source_path=str(source_root),
                recommended_entry_id=canonical.relative_to(
                    source_root
                ).as_posix(),
                entries=entries,
                staged=staged,
                package_summary=package_summary,
            )

        if native_assets:
            entries = tuple(
                EffectSourceEntry(
                    entry_id=path.relative_to(
                        source_root
                    ).as_posix(),
                    source_path=str(path),
                    kind="native_asset",
                )
                for path in native_assets
            )
            recommended = next(
                (
                    entry.entry_id
                    for entry in entries
                    if Path(entry.entry_id).stem.lower().startswith(
                        ("ns_", "fx_", "p_")
                    )
                ),
                entries[0].entry_id,
            )
            return StagedEffectSource(
                mode=mode,
                effect_kind="native_ue",
                source_path=str(source_root),
                recommended_entry_id=recommended,
                entries=entries,
                staged=staged,
            )

        entries = tuple(
            self._entry_for_file(
                path.relative_to(source_root).as_posix(),
                path,
            )
            for path in files
            if self._is_generated_entry(path)
        )
        if not entries:
            raise ValueError(
                f"Generated effect contains no importable entry: "
                f"{source_root}"
            )
        recommended = next(
            (
                entry.entry_id
                for entry in entries
                if Path(entry.entry_id).suffix.lower() == ".json"
            ),
            entries[0].entry_id,
        )
        return StagedEffectSource(
            mode=mode,
            effect_kind="generated",
            source_path=str(source_root),
            recommended_entry_id=recommended,
            entries=entries,
            staged=staged,
        )

    @staticmethod
    def _is_generated_entry(path: Path) -> bool:
        if path.name.lower() in EFFECT_PACKAGE_FILENAMES:
            return True
        suffix = path.suffix.lower()
        if suffix in EFFECT_PACKAGE_SOURCE_SUFFIXES:
            if suffix != ".json":
                return True
            try:
                with path.open("r", encoding="utf-8") as handle:
                    descriptor = json.load(handle)
            except (OSError, UnicodeError, json.JSONDecodeError):
                return False
            if not isinstance(descriptor, dict):
                return False
            if isinstance(descriptor.get("effect"), dict):
                descriptor = {
                    **descriptor,
                    **descriptor["effect"],
                }
            effect_keys = {
                "effect_id",
                "representation",
                "assets",
                "build",
                "entry_asset",
                "emitters",
                "bindings",
            }
            return bool(effect_keys.intersection(descriptor))
        return False

    @staticmethod
    def _entry_for_file(
        entry_id: str,
        source: Path,
    ) -> EffectSourceEntry:
        kind = (
            "effect_descriptor"
            if source.suffix.lower() == ".json"
            else "generated_asset"
        )
        return EffectSourceEntry(
            entry_id=entry_id,
            source_path=str(source),
            kind=kind,
        )


__all__ = [
    "EffectSourceEntry",
    "EffectSourceUploadService",
    "StagedEffectSource",
]
