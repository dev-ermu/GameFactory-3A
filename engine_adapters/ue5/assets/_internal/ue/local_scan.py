"""Local UE Content directory scan fallback for imported assets."""

import os
import re
from pathlib import Path


TECHNICAL_AVATAR_SUFFIXES = (
    "_skeleton",
    "_physicsasset",
    "_anim",
    "_anim_mixamo_com",
    "_diffuse",
    "_normal",
    "_spec",
    "_specular",
    "_glossiness",
    "_roughness",
    "_metallic",
    "_basecolor",
    "_albedo",
    "_opacity",
    "_emissive",
    "_ao",
    "_mat",
    "_body",
    "mat",
)


def list_local_imported_assets(asset_type: str) -> list[dict]:
    configured_project = (
        os.environ.get("A3GAME_UE_PROJECT", "").strip()
    )
    if not configured_project:
        return []
    project_path = Path(configured_project).expanduser()
    if project_path.suffix.lower() != ".uproject":
        return []
    content_dir = project_path.parent / "Content"
    if asset_type == "avatar":
        root = content_dir / "Imported" / "Avatars"
        class_name = "SkeletalMesh"
    else:
        root = content_dir / "Imported" / "Motions"
        class_name = "AnimSequence"
    if not root.exists():
        return []

    assets: list[dict] = []
    for path in sorted(root.rglob("*.uasset")):
        stem = path.stem
        if asset_type == "avatar" and not looks_like_local_avatar_mesh(stem):
            continue
        package_path = content_package_path(path, content_dir)
        skeleton_path = (
            infer_local_skeleton_path(stem, content_dir)
            if asset_type == "avatar"
            else infer_local_motion_skeleton_path(stem, content_dir)
        )
        assets.append(
            {
                "name": stem,
                "path": package_path,
                "class": class_name,
                "package_path": package_path.rsplit("/", 1)[0],
                "skeleton_path": skeleton_path,
                "skeleton_name": skeleton_path.rsplit("/", 1)[-1] if skeleton_path else "",
                "source": "local_content_scan",
            }
        )
    return assets


def looks_like_local_avatar_mesh(asset_name: str) -> bool:
    normalized = asset_name.strip().lower()
    if not normalized:
        return False
    if re.search(r"(^|_)(body|brows?|eyes?|mouth|face|facialanimmap|hair|skin|teeth|tongue)(_|$)", normalized):
        return False
    if re.search(r"(_mat\d*|_ncl\d+_\d+)$", normalized):
        return False
    return not any(normalized.endswith(suffix) for suffix in TECHNICAL_AVATAR_SUFFIXES)


def dedupe_avatar_assets(assets: list[dict]) -> list[dict]:
    best_by_family: dict[str, dict] = {}
    for asset in assets:
        name = str(asset.get("name") or asset.get("path", "").rsplit("/", 1)[-1])
        if not looks_like_local_avatar_mesh(name):
            continue
        key = avatar_package_key(asset) or avatar_family_key(name)
        if not key:
            continue
        candidate = dict(asset)
        candidate.setdefault("display_name", prettify_avatar_name(name))
        current = best_by_family.get(key)
        if current is None or avatar_choice_score(candidate) > avatar_choice_score(current):
            best_by_family[key] = candidate
    return sorted(best_by_family.values(), key=lambda item: str(item.get("display_name") or item.get("name") or item.get("path") or "").lower())


def avatar_package_key(asset: dict) -> str:
    package_path = str(asset.get("package_path") or asset.get("path", "").rsplit("/", 1)[0]).replace("\\", "/").strip("/")
    parts = package_path.split("/")
    lowered = [part.lower() for part in parts]
    try:
        index = lowered.index("avatars")
    except ValueError:
        return ""
    if index + 1 >= len(parts):
        return ""
    package_id = parts[index + 1].strip().lower()
    return f"package:{package_id}" if package_id else ""


def merge_asset_lists(primary: list[dict], fallback: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for asset in fallback:
        path = str(asset.get("path") or "").split(".", 1)[0]
        if path:
            merged[path] = dict(asset)
    for asset in primary:
        path = str(asset.get("path") or "").split(".", 1)[0]
        if not path:
            continue
        existing = merged.get(path, {})
        combined = {**existing, **asset}
        if not combined.get("skeleton_path") and existing.get("skeleton_path"):
            combined["skeleton_path"] = existing["skeleton_path"]
            combined["skeleton_name"] = existing.get("skeleton_name", "")
        merged[path] = combined
    return sorted(merged.values(), key=lambda item: str(item.get("name") or item.get("path") or "").lower())


def avatar_family_key(asset_name: str) -> str:
    value = asset_name.strip().lower()
    value = re.sub(r"_(nonpbr|pbr)$", "", value)
    value = re.sub(r"(_body|_body\d+)$", "", value)
    value = re.sub(r"^(sk|sm|bp)_", "", value)
    return value


def prettify_avatar_name(asset_name: str) -> str:
    value = asset_name.strip()
    value = re.sub(r"^(SK|SM|BP)_", "", value, flags=re.IGNORECASE)
    value = re.sub(r"_(nonPBR|PBR)$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"(_body|_body\d+)$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"[_-]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value or asset_name


def avatar_choice_score(asset: dict) -> tuple[int, str]:
    name = str(asset.get("name") or asset.get("path", "").rsplit("/", 1)[-1]).lower()
    package_id = avatar_package_key(asset).split(":", 1)[-1]
    score = 0
    if asset.get("class") == "SkeletalMesh":
        score += 20
    if asset.get("skeleton_path"):
        score += 8
    if package_id and avatar_family_key(name) == package_id:
        score += 100
    if name.endswith("_nonpbr") or name.endswith("_pbr"):
        score += 4
    if not looks_like_local_avatar_mesh(name):
        score -= 100
    return score, str(asset.get("path") or "")


def content_package_path(asset_path: Path, content_dir: Path) -> str:
    relative = asset_path.relative_to(content_dir).with_suffix("")
    return "/Game/" + "/".join(relative.parts)


def infer_local_skeleton_path(asset_name: str, content_dir: Path) -> str:
    avatar_root = content_dir / "Imported" / "Avatars"
    skeleton_candidates = [
        avatar_root / f"{asset_name}_Skeleton.uasset",
        avatar_root / asset_name / f"{asset_name}_Skeleton.uasset",
    ]
    if avatar_root.exists():
        skeleton_candidates.extend(avatar_root.rglob(f"{asset_name}_Skeleton.uasset"))
        skeleton_candidates.extend(avatar_root.rglob("*_Skeleton.uasset"))
    for skeleton_path in skeleton_candidates:
        if skeleton_path.exists():
            return content_package_path(skeleton_path, content_dir)
    motion_root = content_dir / "Imported" / "Motions"
    marker = f"_{asset_name}_Skeleton_Anim.uasset"
    if motion_root.exists() and any(path.name.endswith(marker) for path in motion_root.rglob("*.uasset")):
        return content_package_path(skeleton_candidates[0], content_dir) if skeleton_candidates[0].exists() else f"/Game/Imported/Avatars/{asset_name}_Skeleton"
    return ""


def infer_local_motion_skeleton_path(asset_name: str, content_dir: Path) -> str:
    marker = "_Skeleton_Anim"
    if not asset_name.endswith(marker):
        return ""
    motion_prefix = asset_name[: -len(marker)]
    avatar_root = content_dir / "Imported" / "Avatars"
    if not avatar_root.exists():
        return ""
    avatar_names = [
        path.stem
        for path in avatar_root.rglob("*.uasset")
        if looks_like_local_avatar_mesh(path.stem)
    ]
    for avatar_name in sorted(set(avatar_names), key=len, reverse=True):
        if motion_prefix == avatar_name or motion_prefix.endswith(f"_{avatar_name}"):
            skeleton_path = infer_local_skeleton_path(avatar_name, content_dir)
            return skeleton_path or f"/Game/Imported/Avatars/{avatar_name}_Skeleton"
    return ""
