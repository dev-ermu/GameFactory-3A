"""Unity-specific asset import dispatcher."""

import shutil
import tarfile
from pathlib import Path
from typing import Any

from ...._internal.transport.unity_editor import UnityEditorTransport
from ....config import UnityClientConfig, UNITY_ASSET_TYPE_DEFAULT_DESTS


def discover_unitypackage_root(source: Path) -> str:
    """Return the common ``Assets/...`` root declared by a unitypackage.

    Unity packages are tar records rather than ordinary folders.  Reading the
    pathname records here lets the public client pass the actual package root
    to the Editor importer instead of assuming a vendor-specific directory.
    """
    if not source.is_file() or source.suffix.lower() != ".unitypackage":
        return ""
    paths: list[str] = []
    try:
        with tarfile.open(source, "r:gz") as archive:
            for member in archive.getmembers():
                if not member.isfile() or not member.name.endswith("/pathname"):
                    continue
                stream = archive.extractfile(member)
                if stream is None:
                    continue
                raw = stream.read().decode("utf-8", "replace").replace("\x00", "")
                normalized = "\n".join(raw.splitlines()).strip()
                while normalized.endswith("\n00"):
                    normalized = normalized[:-3].rstrip()
                if normalized.startswith("Assets/"):
                    paths.append(normalized.replace("\\", "/"))
    except (OSError, tarfile.TarError, UnicodeError):
        return ""
    if not paths:
        return ""
    parts = [Path(item).parts for item in paths]
    common: list[str] = []
    for values in zip(*parts):
        if len({value for value in values}) != 1:
            break
        common.append(values[0])
    if common and Path(common[-1]).suffix:
        common.pop()
    # A package can contain files directly below Assets.  In that case the
    # package root is Assets itself, which is still a valid import scope.
    if not common:
        return "Assets"
    return "/".join(common)


class UnityImportDispatcher:
    """Selects and runs the correct C# import script for each asset type."""

    SCRIPT_MAP = {
        "avatar": "ImportGeneratedAvatar",
        "motion": "ImportGeneratedMotion",
        "scene": "ImportGeneratedScene",
        "prop": "ImportGeneratedMesh",
        "weapon": "ImportGeneratedMesh",
        "material": "ImportGeneratedMaterial",
        "texture": "ImportGeneratedTexture",
        "effect": "ImportGeneratedMesh",
        "environment": "ImportGeneratedScene",
        "static_mesh": "ImportGeneratedMesh",
    }

    # When the source is a .unity file or a directory containing .unity files,
    # route to ImportNativeScene instead of the default scene script.
    NATIVE_SCENE_SCRIPT = "ImportNativeScene"

    def __init__(
        self,
        transport: UnityEditorTransport,
        config: UnityClientConfig,
    ) -> None:
        self._transport = transport
        self._config = config

    def import_asset(
        self,
        src_path: str,
        asset_type: str,
        dst_path: str = "",
        **options: Any,
    ) -> dict[str, Any]:
        normalized_type = (asset_type or "").strip().lower().replace("-", "_").replace(" ", "_")
        validation = self.validate_asset(
            src_path,
            normalized_type,
            dst_path=dst_path,
            **options,
        )
        if not validation.get("ok"):
            return {
                "ok": False,
                "error": "; ".join(validation.get("errors") or []),
                "errors": list(validation.get("errors") or []),
                "warnings": list(validation.get("warnings") or []),
                "src_path": src_path,
                "asset_type": normalized_type,
                "dest_path": dst_path,
            }
        default_dest = UNITY_ASSET_TYPE_DEFAULT_DESTS.get(
            normalized_type,
            "Assets/Imported/Props",
        )
        destination = str(dst_path or default_dest)
        script_class = self.SCRIPT_MAP.get(
            normalized_type,
            "ImportGeneratedMesh",
        )

        # Native Unity scene: .unity file or directory with .unity files
        src_path_obj = Path(src_path)
        if src_path_obj.suffix.lower() == ".unitypackage":
            script_class = "ImportUnityPackage"
        if normalized_type in {"scene", "environment"} and src_path_obj.exists():
            if src_path_obj.suffix.lower() == ".unitypackage":
                script_class = "ImportUnityPackage"
            elif src_path_obj.is_file() and src_path_obj.suffix.lower() == ".unity":
                script_class = self.NATIVE_SCENE_SCRIPT
            elif src_path_obj.is_dir() and any(src_path_obj.rglob("*.unity")):
                script_class = self.NATIVE_SCENE_SCRIPT

        method = f"{script_class}.RunFromCLI"
        transport_source = src_path
        package_warnings: list[str] = []
        package_pre_extracted = False
        if src_path_obj.suffix.lower() == ".unitypackage":
            (
                transport_source,
                package_warnings,
                package_pre_extracted,
            ) = self._prepare_unitypackage(src_path_obj)
        args: dict[str, Any] = {
            "src": str(transport_source),
            "dest": destination,
            "asset_type": normalized_type,
        }
        if package_pre_extracted:
            args["pre_extracted"] = True
        if src_path_obj.suffix.lower() == ".unitypackage":
            package_root = discover_unitypackage_root(src_path_obj)
            if package_root:
                args["package_root"] = package_root
        for key, value in options.items():
            if value is not None and value != "":
                args[key] = value
        if (
            normalized_type == "material"
            and src_path_obj.suffix.lower()
            in {".png", ".jpg", ".jpeg", ".tga", ".tif", ".tiff"}
            and not args.get("albedo")
        ):
            args["albedo"] = str(src_path_obj)

        report = self._transport.execute_method(
            method,
            args=args,
            timeout=self._config.editor_batchmode_timeout,
        )
        if not isinstance(report, dict):
            report = {"ok": False, "error": "Invalid report from Unity"}
        if normalized_type == "motion" and report.get("ok"):
            clip_count = int(report.get("clipCount") or 0)
            clip_path = str(report.get("animationClipPath") or "").strip()
            if clip_count < 1 or not clip_path:
                report["ok"] = False
                report["error"] = (
                    "Unity motion import produced no playable AnimationClip"
                )
        if package_warnings:
            report.setdefault("warnings", [])
            report["warnings"] = [
                *[str(item) for item in report.get("warnings") or []],
                *package_warnings,
            ]
            report["normalized_package_path"] = str(transport_source)
            report["pre_extracted"] = package_pre_extracted
        report.setdefault("src_path", src_path)
        report.setdefault("asset_type", normalized_type)
        report.setdefault("dest_path", destination)
        if report.get("ok") and "assetPath" in report:
            report.setdefault("imported_paths", [report["assetPath"]])
        if report.get("ok") and "prefabPath" in report:
            report.setdefault("imported_paths", [])
            if report["prefabPath"] not in report.get("imported_paths", []):
                report["imported_paths"].append(report["prefabPath"])
        if report.get("ok") and report.get("avatarPath"):
            report.setdefault("imported_paths", [])
            if report["avatarPath"] not in report["imported_paths"]:
                report["imported_paths"].append(report["avatarPath"])
            metadata = report.setdefault("metadata", {})
            if isinstance(metadata, dict):
                metadata.setdefault("skeleton_path", report["avatarPath"])
        if report.get("ok") and report.get("runtimePrefabPath"):
            report.setdefault("imported_paths", [])
            if report["runtimePrefabPath"] not in report["imported_paths"]:
                report["imported_paths"].append(report["runtimePrefabPath"])
        if report.get("ok") and report.get("animationClipPath"):
            report.setdefault("imported_paths", [])
            if report["animationClipPath"] not in report["imported_paths"]:
                report["imported_paths"].append(report["animationClipPath"])
        if report.get("ok") and report.get("runtimeAnimationClipPath"):
            report.setdefault("imported_paths", [])
            if report["runtimeAnimationClipPath"] not in report["imported_paths"]:
                report["imported_paths"].append(report["runtimeAnimationClipPath"])
            if report.get("sourceAvatarPath"):
                metadata = report.setdefault("metadata", {})
                if isinstance(metadata, dict):
                    metadata.setdefault(
                        "source_avatar_path",
                        report["sourceAvatarPath"],
                    )
        if report.get("ok") and report.get("materialPath"):
            report.setdefault("imported_paths", [])
            if report["materialPath"] not in report["imported_paths"]:
                report["imported_paths"].append(report["materialPath"])
        backend_classes = {
            "texture": "Texture2D",
            "material": "Material",
        }
        if report.get("ok") and normalized_type in backend_classes:
            metadata = report.setdefault("metadata", {})
            if isinstance(metadata, dict):
                metadata.setdefault(
                    "backend_class",
                    backend_classes[normalized_type],
                )
        report.setdefault("warnings", [])
        report.setdefault("errors", [])
        return report

    def _prepare_unitypackage(
        self,
        source: Path,
    ) -> tuple[Path, list[str], bool]:
        """Pre-extract malformed package records for Unity AssetDatabase import."""
        if self._config.project_path is None or not source.is_file():
            return source, [], False

        pathnames: dict[str, str] = {}
        malformed_count = 0
        try:
            with tarfile.open(source, "r:gz") as archive:
                for member in archive.getmembers():
                    if not member.isfile() or not member.name.endswith("/pathname"):
                        continue
                    extracted = archive.extractfile(member)
                    raw = extracted.read() if extracted is not None else b""
                    text = raw.decode("utf-8", "replace").replace("\x00", "")
                    lines = text.splitlines()
                    while lines and lines[-1].strip() == "00":
                        lines.pop()
                    normalized = "\n".join(lines).strip()
                    if normalized.encode("utf-8") != raw:
                        malformed_count += 1
                    pathnames[member.name.split("/", 1)[0]] = normalized
        except (tarfile.TarError, OSError, UnicodeError):
            return source, [], False

        if malformed_count == 0:
            return source, [], False

        project_root = self._config.project_path.resolve(strict=False)
        extracted_count = 0
        with tarfile.open(source, "r:gz") as archive:
            members = {member.name: member for member in archive.getmembers()}
            for guid, pathname in pathnames.items():
                relative = Path(pathname)
                if (
                    relative.is_absolute()
                    or not relative.parts
                    or relative.parts[0] != "Assets"
                    or ".." in relative.parts
                ):
                    raise ValueError(
                        f"Unsafe unitypackage pathname: {pathname!r}"
                    )
                destination = (project_root / relative).resolve(strict=False)
                try:
                    destination.relative_to(project_root)
                except ValueError as exc:
                    raise ValueError(
                        f"Unitypackage pathname escapes project: {pathname!r}"
                    ) from exc

                asset_member = members.get(f"{guid}/asset")
                meta_member = members.get(f"{guid}/asset.meta")
                if asset_member is not None and asset_member.isfile():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    source_file = archive.extractfile(asset_member)
                    if source_file is None:
                        raise OSError(f"Could not read package asset: {pathname}")
                    with destination.open("wb") as output:
                        shutil.copyfileobj(source_file, output)
                else:
                    destination.mkdir(parents=True, exist_ok=True)

                if meta_member is not None and meta_member.isfile():
                    meta_destination = Path(str(destination) + ".meta")
                    meta_destination.parent.mkdir(parents=True, exist_ok=True)
                    meta_file = archive.extractfile(meta_member)
                    if meta_file is None:
                        raise OSError(f"Could not read package metadata: {pathname}")
                    with meta_destination.open("wb") as output:
                        shutil.copyfileobj(meta_file, output)
                extracted_count += 1

        return source, [
            "Pre-extracted malformed unitypackage records into the generated "
            f"project ({extracted_count} assets, {malformed_count} repaired "
            "pathnames); canonical source remains unchanged"
        ], True

    def validate_asset(
        self,
        src_path: str,
        asset_type: str,
        dst_path: str = "",
        **options: Any,
    ) -> dict[str, Any]:
        source = Path(src_path)
        errors: list[str] = []
        warnings: list[str] = []
        normalized_type = (
            str(asset_type or "")
            .strip()
            .lower()
            .replace("-", "_")
            .replace(" ", "_")
        )
        if not source.is_file():
            errors.append(f"Source file does not exist: {src_path}")
        else:
            ext = source.suffix.lower()
            mesh_extensions = {".glb", ".gltf", ".fbx", ".obj"}
            image_extensions = {
                ".png",
                ".jpg",
                ".jpeg",
                ".tga",
                ".tif",
                ".tiff",
                ".psd",
                ".exr",
                ".hdr",
            }
            supported_by_type = {
                "avatar": mesh_extensions,
                "motion": mesh_extensions,
                "prop": mesh_extensions,
                "weapon": mesh_extensions,
                "static_mesh": mesh_extensions,
                "texture": image_extensions,
                "material": image_extensions,
                "effect": mesh_extensions | {".unitypackage"},
                "scene": mesh_extensions | {".unity", ".unitypackage"},
                "environment": mesh_extensions | {".unity", ".unitypackage"},
            }
            supported = supported_by_type.get(normalized_type)
            if supported is not None and ext not in supported:
                errors.append(
                    f"Unsupported {normalized_type} source extension: {ext}; "
                    f"supported: {', '.join(sorted(supported))}"
                )
        return {
            "ok": not errors,
            "errors": errors,
            "warnings": warnings,
        }

    def list_assets(
        self,
        asset_type: str = "",
        root_path: str = "Assets/Imported",
    ) -> list[dict[str, Any]]:
        report = self._transport.execute_method(
            "ListAssets.RunFromCLI",
            args={
                "root": root_path,
                "asset_type": asset_type or "",
            },
            timeout=120,
        )
        if not isinstance(report, dict) or not report.get("ok"):
            return []
        assets = report.get("assets") or []
        if not isinstance(assets, list):
            return []
        return [item for item in assets if isinstance(item, dict)]
